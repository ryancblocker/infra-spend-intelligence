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
    assert contract_id in manifest["entries"]
    assert manifest["entries"][contract_id]["original_filename"] == "deal.txt"
    assert manifest["entries"][contract_id]["stored_filename"] == path.name
    assert "Acme" in text


def test_remove_deletes_file_and_manifest_entry(clean_uploads):
    contract_id, path, _ = uploads.store("gone.txt", b"VENDOR: Acme\n")
    assert uploads.remove(contract_id) is True
    assert not path.exists()
    assert contract_id not in uploads.read_manifest()["entries"]


def test_remove_unknown_id_returns_false(clean_uploads):
    assert uploads.remove("U-9999") is False


# --- Coverage added after review: manifest durability, monotonic ids,
# defensive parsing, null-byte filenames, and an end-to-end traversal check.


def test_id_not_reused_after_removing_highest(clean_uploads):
    first, _, _ = uploads.store("one.txt", b"VENDOR: One\n")
    second, _, _ = uploads.store("two.txt", b"VENDOR: Two\n")
    assert uploads.remove(second) is True
    third, _, _ = uploads.store("three.txt", b"VENDOR: Three\n")
    assert first == "U-0001"
    assert second == "U-0002"
    assert third == "U-0003"  # not U-0002 reissued


def test_corrupt_manifest_raises_manifest_error(clean_uploads):
    config.UPLOAD_MANIFEST_PATH.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(uploads.ManifestError):
        uploads.read_manifest()


def test_missing_manifest_file_is_not_an_error(clean_uploads):
    assert not config.UPLOAD_MANIFEST_PATH.exists()
    assert uploads.read_manifest() == {"next_id": 1, "entries": {}}


def test_write_manifest_leaves_no_temp_file_behind(clean_uploads):
    uploads.store("one.txt", b"VENDOR: Acme\n")
    assert list(clean_uploads.glob(".manifest-*")) == []
    assert config.UPLOAD_MANIFEST_PATH.exists()


def test_write_manifest_is_atomic_on_failure(clean_uploads, monkeypatch):
    uploads.store("one.txt", b"VENDOR: Acme\n")
    original = uploads.read_manifest()

    def boom(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(uploads.os, "replace", boom)
    with pytest.raises(OSError):
        uploads.write_manifest({"next_id": 999, "entries": {}})

    # os.replace() never ran, so the on-disk manifest must be exactly what
    # it was before the failed write - not truncated, not the new content.
    assert uploads.read_manifest() == original
    assert list(clean_uploads.glob(".manifest-*")) == []


def test_remove_tolerates_entry_missing_stored_filename(clean_uploads):
    contract_id, _, _ = uploads.store("weird.txt", b"VENDOR: Acme\n")
    manifest = uploads.read_manifest()
    del manifest["entries"][contract_id]["stored_filename"]
    uploads.write_manifest(manifest)

    assert uploads.remove(contract_id) is True
    assert contract_id not in uploads.read_manifest()["entries"]


def test_null_byte_in_filename_is_stripped(clean_uploads):
    assert uploads.safe_basename("evil.txt\x00.pdf") == "evil.txt.pdf"


def test_null_byte_in_filename_does_not_crash_store(clean_uploads):
    contract_id, path, text = uploads.store("evil\x00.txt", b"VENDOR: Acme\n")
    assert path.exists()
    assert "Acme" in text


def test_path_traversal_cannot_escape_upload_dir_end_to_end(clean_uploads):
    """The unit-level safe_basename test proves the string is sanitized; this
    proves the file that store() actually writes lands inside UPLOAD_DIR, not
    just that the intermediate basename looks clean."""
    contract_id, path, _ = uploads.store(
        "../../etc/passwd.txt", b"VENDOR: Acme\n"
    )
    assert path.parent == config.UPLOAD_DIR
    assert path.exists()
    assert not (config.UPLOAD_DIR.parent / "etc" / "passwd.txt").exists()


from app.agents import extraction
from app.agents.schemas import ContractTerms, ExtractedContract


def test_contract_terms_has_cost_fields():
    terms = ContractTerms(monthly_cost=1000.0, annual_cost=12000.0)
    assert terms.monthly_cost == 1000.0
    assert terms.annual_cost == 12000.0


def test_cost_fields_default_to_none():
    assert ContractTerms().monthly_cost is None
    assert ExtractedContract(contract_id="U-0001").annual_cost is None


def test_reconcile_costs_derives_annual_from_monthly():
    assert extraction.reconcile_costs(1000.0, None) == (1000.0, 12000.0)


def test_reconcile_costs_derives_monthly_from_annual():
    assert extraction.reconcile_costs(None, 12000.0) == (1000.0, 12000.0)


def test_reconcile_costs_keeps_both_when_stated():
    assert extraction.reconcile_costs(1000.0, 11000.0) == (1000.0, 11000.0)


def test_reconcile_costs_passes_through_nones():
    assert extraction.reconcile_costs(None, None) == (None, None)


def test_offline_extraction_reads_a_stated_monthly_fee():
    text = "VENDOR: Acme Corp\nCustomer shall pay recurring fees of $9,936.97 per month.\n"
    record = extraction._extract_offline("U-0001", text)
    assert record.monthly_cost == 9936.97
    assert record.annual_cost == pytest.approx(119243.64)


def test_offline_extraction_reads_a_stated_annual_fee():
    text = "VENDOR: Acme Corp\nTotal annual fees of $120,000.00 are due.\n"
    record = extraction._extract_offline("U-0001", text)
    assert record.annual_cost == 120000.0
    assert record.monthly_cost == pytest.approx(10000.0)


def test_offline_extraction_reads_a_stated_annualized_parenthetical():
    """Phrasing modeled on app/data/contract_docs/C-0007.txt (verbatim there:
    "recurring fees of $9,936.97 per month ($119,243.64 annualized), subject
    to an Annual Escalator of 2% ..."), but with the monthly and annualized
    figures deliberately NOT a clean *12 multiple of each other. If the
    annual regex still doesn't match "annualized", reconcile_costs silently
    derives 1000 * 12 = 12000.0 - which would make this test pass for the
    wrong reason. Choosing a stated annual figure that a *12 derivation
    could never produce (11000.0 != 12000.0) proves the value was actually
    read from the parenthetical, not computed."""
    text = (
        "VENDOR: Acme Corp\n"
        "2. FEES. Customer shall pay Vendor recurring fees of $1,000.00 per "
        "month ($11,000.00 annualized), subject to an Annual Escalator of "
        "2% applied on each anniversary of the Effective Date.\n"
    )
    record = extraction._extract_offline("U-0001", text)
    assert record.monthly_cost == 1000.0
    # Stated verbatim in the contract - must be read, not 1000.0 * 12.
    assert record.annual_cost == 11000.0


def test_money_does_not_cross_an_intervening_dollar_figure():
    """[^.$]* used to stop only at a literal '.' or '$', so it could cross a
    semicolon and an unrelated fee to grab the first $ downstream of the
    keyword instead of the one actually associated with it."""
    text = (
        "VENDOR: Acme Corp\n"
        "Recurring fees exclude a one-time setup fee of $500; the standard "
        "monthly fee is $9,936.97 per month.\n"
    )
    record = extraction._extract_offline("U-0001", text)
    assert record.monthly_cost == 9936.97


def test_agentic_path_also_derives_the_missing_cost_figure(monkeypatch):
    """reconcile_costs was wired into _extract_offline only. The agentic path
    (extract_one -> _extract_agentic, what runs against a live model) must
    get the same treatment so it doesn't ship a record with one cost field
    set and the other left None."""
    chunk = {"contract_id": "C-0007", "chunk_index": 0, "heading": "2. FEES",
              "text": "Customer shall pay recurring fees of $1,000.00 per month.",
              "distance": 0.1}
    monkeypatch.setattr(extraction, "chat_structured",
                         lambda system, user, schema, agent="unknown":
                         ContractTerms(monthly_cost=1000.0))
    monkeypatch.setattr(extraction, "get_mode", lambda: "ollama")
    monkeypatch.setattr(extraction, "_retrieve", lambda cid, queries: [chunk])
    monkeypatch.setattr(config, "EXTRACTION_CACHE_ENABLED", False)

    record = extraction.extract_one("C-0007", "contract text")

    assert record.monthly_cost == 1000.0
    assert record.annual_cost == pytest.approx(12000.0)


def test_document_paths_includes_seed_and_upload_dirs(clean_uploads):
    (clean_uploads / "U-0001.txt").write_text("VENDOR: Acme\n", encoding="utf-8")
    paths = config.document_paths()
    names = {p.name for p in paths}
    assert "U-0001.txt" in names
    assert any(p.parent == config.CONTRACT_DOCS_DIR for p in paths)


def test_document_path_resolves_an_upload(clean_uploads):
    (clean_uploads / "U-0001.txt").write_text("VENDOR: Acme\n", encoding="utf-8")
    resolved = config.document_path("U-0001")
    assert resolved is not None and resolved.name == "U-0001.txt"


def test_document_path_returns_none_for_unknown_id(clean_uploads):
    assert config.document_path("U-9999") is None


def test_manifest_json_is_not_treated_as_a_document(clean_uploads):
    uploads.write_manifest({})
    assert all(p.suffix == ".txt" for p in config.document_paths())
