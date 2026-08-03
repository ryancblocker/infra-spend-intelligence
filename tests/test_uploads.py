"""
Tests for contract upload: document loading, storage, and the upload routes.

PDF fixtures are generated in-process rather than committed, so the suite stays
dependency-light and the "scanned PDF" case is unambiguous - a page with no text
operators at all is exactly what a scan produces.
"""

from __future__ import annotations

import pytest

from app import config
from app.tools import document_loader
from app.tools.document_loader import UnsupportedDocument


def _digital_pdf(text: str) -> bytes:
    """A minimal one-page PDF with a real text object.

    Hand-built because pypdf can create pages but cannot author text content,
    and this fixture's whole purpose is having extractable text."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


def _scanned_pdf() -> bytes:
    """A one-page PDF with no text operators - what a scanner produces."""
    from pypdf import PdfWriter
    import io

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# Must exceed SCANNED_PDF_MIN_CHARS, or the fixture meant to represent a real
# digital contract trips the image-only guard. No parentheses: they delimit
# strings in PDF syntax and would need escaping.
DIGITAL_PDF_TEXT = (
    "MASTER SERVICES AGREEMENT between ACME CORP and the Customer. "
    "This Agreement continues through 2026-12-31 and will automatically renew "
    "for successive twelve month terms unless either party gives written notice "
    "of non-renewal at least 60 days before expiration of the then-current term."
)


def test_txt_upload_produces_text():
    text = document_loader.load_document("contract.txt", b"VENDOR: Acme Corp\n")
    assert "Acme Corp" in text


def test_txt_falls_back_to_latin1_on_bad_utf8():
    text = document_loader.load_document("contract.txt", b"VENDOR: Caf\xe9 Ltd\n")
    assert "Caf" in text


def test_digital_pdf_produces_text():
    text = document_loader.load_document("contract.pdf", _digital_pdf(DIGITAL_PDF_TEXT))
    assert "ACME" in text.upper()


def test_digital_pdf_fixture_clears_the_scanned_threshold():
    """Guards the fixture itself: if it ever drops below the floor, the test above
    would fail for a reason that has nothing to do with the loader."""
    assert len(DIGITAL_PDF_TEXT) > config.SCANNED_PDF_MIN_CHARS


def test_scanned_pdf_is_rejected():
    with pytest.raises(UnsupportedDocument) as excinfo:
        document_loader.load_document("scan.pdf", _scanned_pdf())
    assert "OCR" in excinfo.value.reason


def test_corrupt_pdf_is_rejected():
    with pytest.raises(UnsupportedDocument) as excinfo:
        document_loader.load_document("broken.pdf", b"%PDF-1.4\nnot actually a pdf")
    # Must name the actual cause, not just be non-empty - the underlying pypdf
    # error text should come through rather than be swallowed into a generic
    # message like "error".
    assert "parsed" in excinfo.value.reason
    assert "Stream has ended unexpectedly" in excinfo.value.reason


def test_unsupported_extension_is_rejected():
    with pytest.raises(UnsupportedDocument) as excinfo:
        document_loader.load_document("contract.docx", b"anything")
    assert ".pdf" in excinfo.value.reason and ".txt" in excinfo.value.reason


from pathlib import Path

from app import config
from app.tools import uploads
from app.tools.uploads import UploadTooLarge


@pytest.fixture
def clean_uploads(tmp_path, monkeypatch):
    """Point upload storage at a temp dir so tests never touch runtime/uploads/."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(config, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(config, "UPLOAD_MANIFEST_PATH", upload_dir / "manifest.json")
    return upload_dir


def test_path_traversal_filename_is_sanitized(clean_uploads):
    assert uploads.safe_basename("../../etc/passwd") == "passwd"
    assert uploads.safe_basename("/absolute/path/contract.txt") == "contract.txt"
    assert uploads.safe_basename("a/b/c/deal.pdf") == "deal.pdf"


def test_empty_filename_gets_a_fallback(clean_uploads):
    assert uploads.safe_basename("../..") == "upload"
    assert uploads.safe_basename("") == "upload"


def test_oversized_file_is_rejected(clean_uploads):
    oversized = b"x" * (config.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(UploadTooLarge):
        uploads.store("big.txt", oversized)


def test_store_allocates_sequential_upload_ids(clean_uploads):
    first, _, _ = uploads.store("one.txt", b"VENDOR: One Corp\n")
    second, _, _ = uploads.store("two.txt", b"VENDOR: Two Corp\n")
    assert first == "U-0001"
    assert second == "U-0002"


def test_duplicate_filenames_both_persist(clean_uploads):
    _, first_path, _ = uploads.store("same.txt", b"VENDOR: First\n")
    _, second_path, _ = uploads.store("same.txt", b"VENDOR: Second\n")
    assert first_path != second_path
    assert second_path.name == "same-2.txt"
    assert first_path.exists() and second_path.exists()


def test_store_records_manifest_entry(clean_uploads):
    contract_id, path, text = uploads.store("deal.txt", b"VENDOR: Acme\n")
    manifest = uploads.read_manifest()
    assert contract_id in manifest
    assert manifest[contract_id]["original_filename"] == "deal.txt"
    assert manifest[contract_id]["stored_filename"] == path.name
    assert "Acme" in text


def test_remove_deletes_file_and_manifest_entry(clean_uploads):
    contract_id, path, _ = uploads.store("gone.txt", b"VENDOR: Acme\n")
    assert uploads.remove(contract_id) is True
    assert not path.exists()
    assert contract_id not in uploads.read_manifest()


def test_remove_unknown_id_returns_false(clean_uploads):
    assert uploads.remove("U-9999") is False
