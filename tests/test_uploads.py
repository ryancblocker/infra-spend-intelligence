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
