"""
Tests for contract upload: document loading, storage, and the upload routes.

PDF fixtures are generated in-process rather than committed, so the suite stays
dependency-light and the "scanned PDF" case is unambiguous - a page with no text
operators at all is exactly what a scan produces.
"""

from __future__ import annotations

import re
import threading
import time

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


# Uploaded .txt is held to the same minimum-content floor as a PDF (see
# config.SCANNED_PDF_MIN_CHARS), so a fixture body has to read like an actual
# contract rather than a single line. This boilerplate is the padding: it states
# nothing the offline extractor looks for, so it changes no assertion about the
# terms a fixture is meant to exercise.
BOILERPLATE = (
    "This Agreement is made between the parties identified above and governs the "
    "provision of the services described in the attached schedules. Each party "
    "represents that the individual signing has authority to bind it. Notices are "
    "effective on receipt. Neither party may assign this Agreement without the "
    "prior written consent of the other party, which shall not be unreasonably "
    "withheld.\n"
)


def _txt(*lines: str) -> bytes:
    """A .txt upload fixture: the lines under test, padded past the floor."""
    return ("\n".join(lines) + "\n" + BOILERPLATE).encode("utf-8")


def test_txt_upload_produces_text():
    text = document_loader.load_document("contract.txt", _txt("VENDOR: Acme Corp"))
    assert "Acme Corp" in text


def test_txt_falls_back_to_latin1_on_bad_utf8():
    latin1 = ("VENDOR: Caf\xe9 Ltd\n" + BOILERPLATE).encode("latin-1")
    text = document_loader.load_document("contract.txt", latin1)
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
    first, _, _ = uploads.store("one.txt", _txt("VENDOR: One Corp"))
    second, _, _ = uploads.store("two.txt", _txt("VENDOR: Two Corp"))
    assert first == "U-0001"
    assert second == "U-0002"


def test_duplicate_filenames_both_persist(clean_uploads):
    _, first_path, _ = uploads.store("same.txt", _txt("VENDOR: First"))
    _, second_path, _ = uploads.store("same.txt", _txt("VENDOR: Second"))
    assert first_path != second_path
    assert second_path.name == "same-2.txt"
    assert first_path.exists() and second_path.exists()


def test_store_records_manifest_entry(clean_uploads):
    contract_id, path, text = uploads.store("deal.txt", _txt("VENDOR: Acme"))
    manifest = uploads.read_manifest()
    assert contract_id in manifest["entries"]
    assert manifest["entries"][contract_id]["original_filename"] == "deal.txt"
    assert manifest["entries"][contract_id]["stored_filename"] == path.name
    assert "Acme" in text


def test_remove_deletes_file_and_manifest_entry(clean_uploads):
    contract_id, path, _ = uploads.store("gone.txt", _txt("VENDOR: Acme"))
    assert uploads.remove(contract_id) is True
    assert not path.exists()
    assert contract_id not in uploads.read_manifest()["entries"]


def test_remove_unknown_id_returns_false(clean_uploads):
    assert uploads.remove("U-9999") is False


# --- Coverage added after review: manifest durability, monotonic ids,
# defensive parsing, null-byte filenames, and an end-to-end traversal check.


def test_id_not_reused_after_removing_highest(clean_uploads):
    first, _, _ = uploads.store("one.txt", _txt("VENDOR: One"))
    second, _, _ = uploads.store("two.txt", _txt("VENDOR: Two"))
    assert uploads.remove(second) is True
    third, _, _ = uploads.store("three.txt", _txt("VENDOR: Three"))
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
    uploads.store("one.txt", _txt("VENDOR: Acme"))
    assert list(clean_uploads.glob(".manifest-*")) == []
    assert config.UPLOAD_MANIFEST_PATH.exists()


def test_write_manifest_is_atomic_on_failure(clean_uploads, monkeypatch):
    uploads.store("one.txt", _txt("VENDOR: Acme"))
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
    contract_id, _, _ = uploads.store("weird.txt", _txt("VENDOR: Acme"))
    manifest = uploads.read_manifest()
    del manifest["entries"][contract_id]["stored_filename"]
    uploads.write_manifest(manifest)

    assert uploads.remove(contract_id) is True
    assert contract_id not in uploads.read_manifest()["entries"]


def test_null_byte_in_filename_is_stripped(clean_uploads):
    assert uploads.safe_basename("evil.txt\x00.pdf") == "evil.txt.pdf"


def test_null_byte_in_filename_does_not_crash_store(clean_uploads):
    contract_id, path, text = uploads.store("evil\x00.txt", _txt("VENDOR: Acme"))
    assert path.exists()
    assert "Acme" in text


def test_path_traversal_cannot_escape_upload_dir_end_to_end(clean_uploads):
    """The unit-level safe_basename test proves the string is sanitized; this
    proves the file that store() actually writes lands inside UPLOAD_DIR, not
    just that the intermediate basename looks clean."""
    contract_id, path, _ = uploads.store(
        "../../etc/passwd.txt", _txt("VENDOR: Acme")
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


from app.data import seed_db
from app.tools import dataset_tools


def _sample_record(contract_id: str = "U-0001") -> ExtractedContract:
    return ExtractedContract(
        contract_id=contract_id,
        vendor="Acme Corp",
        category="Network Circuit Services",
        renewal_date="2026-12-31",
        notice_period_days=60,
        auto_renew=True,
        monthly_cost=1000.0,
        annual_cost=12000.0,
        minimum_commitment="10 circuits",
    )


def test_upsert_creates_a_row_marked_as_upload():
    dataset_tools.upsert_upload_row(_sample_record("U-0101"))
    row = dataset_tools.fetch_contract("U-0101")
    assert row is not None
    assert row["source"] == "upload"
    assert row["vendor"] == "Acme Corp"
    assert row["annual_cost"] == 12000.0
    dataset_tools.delete_upload_row("U-0101")


def test_seed_rows_are_marked_as_seed():
    dataset_tools.ensure_source_column()
    assert dataset_tools.fetch_contract("C-0001")["source"] == "seed"


def test_upsert_is_idempotent():
    """Re-uploading the same id must replace the row, not accumulate duplicates."""
    dataset_tools.upsert_upload_row(_sample_record("U-0102"))
    dataset_tools.upsert_upload_row(_sample_record("U-0102"))
    rows = dataset_tools._rows(
        "SELECT contract_id FROM contracts WHERE contract_id = ?", ("U-0102",)
    )
    assert len(rows) == 1
    dataset_tools.delete_upload_row("U-0102")


def test_delete_removes_the_row():
    dataset_tools.upsert_upload_row(_sample_record("U-0103"))
    dataset_tools.delete_upload_row("U-0103")
    assert dataset_tools.fetch_contract("U-0103") is None


def test_reseed_rehydrates_uploads_from_the_manifest(clean_uploads):
    (clean_uploads / "U-0201.txt").write_text("VENDOR: Rehydrated Corp\n", encoding="utf-8")
    uploads.write_manifest({
        "next_id": 202,
        "entries": {
            "U-0201": {
                "contract_id": "U-0201",
                "original_filename": "deal.txt",
                "stored_filename": "U-0201.txt",
                "terms": _sample_record("U-0201").model_dump(mode="json"),
            },
        },
    })

    seed_db.build_database()

    row = dataset_tools.fetch_contract("U-0201")
    assert row is not None, "a reseed must not lose uploaded contracts"
    assert row["source"] == "upload"


def test_corrupt_manifest_does_not_break_a_reseed(clean_uploads, capsys):
    """Rehydration reads the manifest but never writes it, so a corrupt manifest
    at startup/reseed time must degrade (skip rehydration, warn loudly) rather
    than crash build_database() - which would take down the whole app/test
    suite over a problem that store()/remove() would still report loudly the
    moment someone actually tries to upload."""
    clean_uploads.joinpath("manifest.json").write_text("{not valid json", encoding="utf-8")

    counts = seed_db.build_database()

    assert counts, "build_database() must still complete and return table counts"
    captured = capsys.readouterr()
    assert "[PACT]" in captured.out
    assert "manifest" in captured.out.lower()


def test_delete_upload_row_self_heals_a_pre_source_column_table():
    """ensure_source_column, upsert_upload_row, and fetch_upload_ids all guard
    against a contracts table that predates the source column (e.g. right
    after a reseed builds it straight from CSV). delete_upload_row must too,
    instead of raising OperationalError: no such column: source."""
    with dataset_tools.connection() as conn:
        conn.execute("ALTER TABLE contracts DROP COLUMN source")
        conn.commit()

    dataset_tools.delete_upload_row("U-9999")  # must not raise

    with dataset_tools.connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(contracts)")}
    assert "source" in columns


from fastapi.testclient import TestClient


@pytest.fixture
def client(clean_uploads, monkeypatch):
    monkeypatch.setenv("PACT_LLM_MODE", "offline")
    from app.main import app
    return TestClient(app)


def test_upload_txt_returns_a_contract_id(client):
    body = _txt("VENDOR: Acme Corp", "CATEGORY: Network Circuit Services",
                "This Agreement continues through 2026-12-31 and will automatically renew.")
    response = client.post("/api/upload", files={"file": ("deal.txt", body, "text/plain")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_id"] == "U-0001"
    assert payload["vendor"] == "Acme Corp"


def test_upload_creates_a_contracts_row(client):
    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    contract_id = client.post(
        "/api/upload", files={"file": ("deal.txt", body, "text/plain")}
    ).json()["contract_id"]
    from app.tools import dataset_tools
    assert dataset_tools.fetch_contract(contract_id)["source"] == "upload"


def test_unsupported_extension_returns_415(client):
    response = client.post("/api/upload", files={"file": ("deal.docx", b"x", "application/msword")})
    assert response.status_code == 415
    assert ".pdf" in response.json()["detail"]


def test_oversized_upload_returns_413(client):
    oversized = b"x" * (config.MAX_UPLOAD_BYTES + 1)
    response = client.post("/api/upload", files={"file": ("big.txt", oversized, "text/plain")})
    assert response.status_code == 413


def test_scanned_pdf_upload_returns_422(client):
    response = client.post("/api/upload", files={"file": ("scan.pdf", _scanned_pdf(), "application/pdf")})
    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


def test_remove_deletes_row_and_file(client):
    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    contract_id = client.post(
        "/api/upload", files={"file": ("deal.txt", body, "text/plain")}
    ).json()["contract_id"]

    response = client.post(f"/api/uploads/{contract_id}/remove")
    assert response.status_code == 200

    from app.tools import dataset_tools
    assert dataset_tools.fetch_contract(contract_id) is None
    assert contract_id not in uploads.read_manifest()["entries"]


def test_remove_unknown_id_returns_404(client):
    assert client.post("/api/uploads/U-9999/remove").status_code == 404


def test_corrupt_pdf_upload_returns_422(client):
    """The brief only exercised the corrupt-PDF case through document_loader
    directly (test_corrupt_pdf_is_rejected); this proves the route wires the
    same UnsupportedDocument reason through to a 422 response."""
    response = client.post(
        "/api/upload",
        files={"file": ("broken.pdf", b"%PDF-1.4\nnot actually a pdf", "application/pdf")},
    )
    assert response.status_code == 422
    assert "parsed" in response.json()["detail"]


def test_upload_with_corrupt_manifest_returns_500(client):
    """uploads.store() calls read_manifest() internally, which raises
    ManifestError on a corrupt manifest file. Before this fix nothing in the
    route caught it, so the user got an unhandled 500 traceback instead of an
    error naming the actual problem."""
    config.UPLOAD_MANIFEST_PATH.write_text("{not valid json", encoding="utf-8")
    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    response = client.post("/api/upload", files={"file": ("deal.txt", body, "text/plain")})
    assert response.status_code == 500
    detail = response.json()["detail"].lower()
    assert "manifest" in detail


def test_oversized_upload_never_reaches_the_multipart_parser(client, monkeypatch):
    """The 10 MB cap must be enforced before Starlette's multipart parser ever
    touches the body. A check inside the route (or a spy on UploadFile.read)
    runs too late to prove this: FastAPI resolves the `UploadFile` parameter
    by calling request.form(), which parses the ENTIRE body through
    MultiPartParser BEFORE the endpoint function is entered - and the parser
    writes file bytes via `part.file.write()`, a path a read()-spy never
    observes at all. This only proves real protection by patching the parser
    itself and asserting it never receives file body bytes - i.e. that
    middleware short-circuited the request before call_next reached routing."""
    from starlette.formparsers import MultiPartParser

    parsed_chunk_sizes = []
    original_on_part_data = MultiPartParser.on_part_data

    def spy_on_part_data(self, data, start, end):
        parsed_chunk_sizes.append(end - start)
        return original_on_part_data(self, data, start, end)

    monkeypatch.setattr(MultiPartParser, "on_part_data", spy_on_part_data)

    oversized = b"x" * (config.MAX_UPLOAD_BYTES + 1)
    response = client.post("/api/upload", files={"file": ("big.txt", oversized, "text/plain")})

    assert response.status_code == 413
    assert response.json() == {
        "detail": f"File exceeds the {config.MAX_UPLOAD_BYTES // 1_048_576} MB limit."
    }
    assert parsed_chunk_sizes == [], (
        "the multipart parser must never see file body bytes once Content-Length "
        "already exceeds the cap - if this fails, the guard ran too late to help"
    )


def test_upload_failure_during_extraction_leaves_no_trace(client, monkeypatch):
    """A genuine exception during extraction (not a poor-but-successful offline
    fallback, which extract_one already handles internally) must roll the
    whole upload back: no orphaned file, no stale manifest entry, no contracts
    row left behind for an id nothing can reach."""
    from app.agents import extraction
    from app.tools import dataset_tools

    def boom(contract_id, text):
        raise RuntimeError("simulated extraction crash")

    monkeypatch.setattr(extraction, "extract_one", boom)

    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    response = client.post("/api/upload", files={"file": ("deal.txt", body, "text/plain")})

    assert response.status_code == 500
    assert "discarded" in response.json()["detail"].lower()

    assert uploads.read_manifest()["entries"] == {}
    assert not (config.UPLOAD_DIR / "U-0001.txt").exists()
    assert dataset_tools.fetch_contract("U-0001") is None


def test_write_manifest_failure_after_rename_rolls_back_completely(client, monkeypatch):
    """The write_manifest() call immediately after the rename used to run
    unguarded. If it failed, the file would already be sitting at
    <contract_id>.txt on disk while the manifest still named the pre-rename
    file - the original orphaned-file bug, just in a narrower window. This
    proves that failure now triggers the same full rollback as any other
    exception during upload processing: neither the pre- nor post-rename
    filename is left behind, the manifest entry is gone, and no DB row
    remains."""
    from app.tools import dataset_tools, uploads

    original_write_manifest = uploads.write_manifest
    calls = {"count": 0}

    def flaky_write_manifest(manifest):
        calls["count"] += 1
        # Call 1 is uploads.store()'s own internal write (the initial
        # manifest entry); call 2 is the route's post-rename write - the one
        # this test targets.
        if calls["count"] == 2:
            raise OSError("simulated disk failure writing the manifest")
        return original_write_manifest(manifest)

    monkeypatch.setattr(uploads, "write_manifest", flaky_write_manifest)

    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    response = client.post("/api/upload", files={"file": ("deal.txt", body, "text/plain")})

    assert response.status_code == 500
    assert "discarded" in response.json()["detail"].lower()

    assert uploads.read_manifest()["entries"] == {}
    assert not (config.UPLOAD_DIR / "U-0001.txt").exists()
    assert not (config.UPLOAD_DIR / "deal.txt").exists()
    assert dataset_tools.fetch_contract("U-0001") is None


def test_rollback_failure_does_not_mask_the_original_error(client, monkeypatch):
    """If the cleanup after a genuine extraction failure itself fails (e.g. a
    disk error while unlinking or writing the manifest during rollback), the
    user must still see the original 'upload was discarded' error - not an
    unrelated exception raised while trying to clean up. Cleanup failures are
    swallowed; the original cause is what gets reported."""
    from app.agents import extraction
    from app.tools import uploads

    def boom_extract(contract_id, text):
        raise RuntimeError("simulated extraction crash")

    def boom_remove(contract_id):
        raise OSError("simulated failure while cleaning up")

    monkeypatch.setattr(extraction, "extract_one", boom_extract)
    monkeypatch.setattr(uploads, "remove", boom_remove)

    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    response = client.post("/api/upload", files={"file": ("deal.txt", body, "text/plain")})

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "discarded" in detail.lower()
    assert "simulated extraction crash" in detail


def test_waste_produces_no_findings_for_an_uploaded_contract(client):
    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    contract_id = client.post(
        "/api/upload", files={"file": ("deal.txt", body, "text/plain")}
    ).json()["contract_id"]

    from app.agents import waste
    findings = waste.run()
    assert not [f for f in findings if f.contract_id == contract_id], (
        "waste findings require utilization telemetry, which a contract document "
        "does not contain - inventing one would be a fabricated number"
    )


def test_waste_ignores_uploads_even_with_an_empty_owner(client):
    """The 'no waste findings for uploads' guarantee must not rest on
    upsert_upload_row's incidental choice of owner="Uploaded" as a placeholder
    string. If a future edit blanks that placeholder out, the upload-id guard
    in waste.py - not the string's truthiness - must still be what keeps
    contract_owner_gap (or any other waste finding) from firing."""
    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    contract_id = client.post(
        "/api/upload", files={"file": ("deal.txt", body, "text/plain")}
    ).json()["contract_id"]

    from app.tools import dataset_tools
    with dataset_tools.connection() as conn:
        conn.execute("UPDATE contracts SET owner = '' WHERE contract_id = ?", (contract_id,))
        conn.commit()

    from app.agents import waste
    findings = waste.run()
    assert not [f for f in findings if f.contract_id == contract_id], (
        "an uploaded contract must produce zero waste findings regardless of its "
        "owner field - the guard is contract_id in fetch_upload_ids(), not "
        "whether some other column happens to be non-empty"
    )


def test_mission_control_renders_upload_card(client):
    """The dashboard's upload card must render even with nothing uploaded yet
    - the drop zone and browse control are always present."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="upload-drop"' in response.text
    assert 'id="upload-input"' in response.text
    assert "Choose a file" in response.text


def test_mission_control_lists_uploaded_contract(client):
    """After a real upload, the dashboard's upload list must show the new
    contract id and the vendor extracted from it."""
    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    contract_id = client.post(
        "/api/upload", files={"file": ("deal.txt", body, "text/plain")}
    ).json()["contract_id"]

    response = client.get("/")
    assert response.status_code == 200
    assert contract_id in response.text
    assert "Acme Corp" in response.text


def test_mission_control_handles_entry_without_terms(client):
    """The manifest is written before extraction runs, so an entry may not
    have a "terms" key yet. The template must fall back to the original
    filename rather than raising a Jinja UndefinedError."""
    (uploads_dir := config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    uploads.write_manifest({
        "next_id": 2,
        "entries": {
            "U-0001": {
                "contract_id": "U-0001",
                "original_filename": "pending-extraction.txt",
                "stored_filename": "pending-extraction.txt",
            },
        },
    })
    (uploads_dir / "pending-extraction.txt").write_text("VENDOR: Acme\n", encoding="utf-8")

    response = client.get("/")
    assert response.status_code == 200
    assert "pending-extraction.txt" in response.text


def test_mission_control_with_no_uploads_does_not_break(client):
    """A fresh install with no manifest file at all must still render the
    dashboard normally rather than raising."""
    assert not config.UPLOAD_MANIFEST_PATH.exists()
    response = client.get("/")
    assert response.status_code == 200


def test_mission_control_degrades_on_corrupt_manifest(client):
    """A corrupt manifest must not take down the whole dashboard - every
    other figure on the page (KPIs, pipeline, etc.) is still valid, so this
    should degrade to an empty upload list rather than 500."""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_MANIFEST_PATH.write_text("{not valid json", encoding="utf-8")

    response = client.get("/")
    assert response.status_code == 200


def test_upload_status_message_is_never_built_via_innerhtml():
    """Regression test for an XSS found in code review: the post-upload status
    message used to be built with

        status.innerHTML = `Added <strong>${payload.contract_id}</strong>` +
            `${payload.vendor ? ` - ${payload.vendor}` : ""}. ...`

    payload.vendor is a raw regex capture off the uploaded document's own
    text (extraction.py's "VENDOR:" search) with no sanitization anywhere
    between there and this line. A .txt file containing
    "VENDOR: <img src=x onerror=alert(1)>" would execute script in the
    uploader's page the instant the upload succeeded.

    This can't be exercised through a real browser here (no DOM/JS engine
    available to this suite), so it's pinned at the source level instead:
    a crude but effective regex over app.js asserting no `.innerHTML`
    assignment interpolates `${payload...}`. The fixed code builds the
    message with createElement/textContent/Node.append (a string passed to
    append() becomes a Text node, never parsed as markup), which this
    pattern does not flag.
    """
    js = (config.STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    dangerous = re.search(r"innerHTML\s*=[^;]*\$\{\s*payload", js, re.DOTALL)
    assert dangerous is None, (
        "found an innerHTML assignment interpolating payload-derived data - "
        "user-supplied upload content (vendor, filename, API error detail) "
        "must only ever be set via textContent/createElement/append, never "
        "written into innerHTML unescaped"
    )


def test_renewal_risk_includes_an_uploaded_contract(client):
    body = _txt("VENDOR: Acme Corp",
                "This Agreement continues through 2026-09-30 and will automatically renew "
                "unless either party gives notice of non-renewal at least 30 days before "
                "expiration.")
    contract_id = client.post(
        "/api/upload", files={"file": ("soon.txt", body, "text/plain")}
    ).json()["contract_id"]

    # renewal.run() returns (risks, narrative) - unpack it, do not iterate the tuple.
    from app.agents import renewal
    risks, _ = renewal.run()
    assert any(r.contract_id == contract_id for r in risks), (
        "end date, notice days and auto-renew are all stated in the document, so "
        "renewal risk must cover uploads"
    )


# ---------------------------------------------------------------------------
# The manifest is the source of truth; the contracts table is derived state
# ---------------------------------------------------------------------------


def test_the_suite_never_writes_to_the_real_database():
    """Route tests upsert contracts rows. Before this guard, clean_uploads
    redirected UPLOAD_DIR but not DB_PATH, so every one of those rows landed in
    the developer's runtime/pact.db - where it had no manifest entry, no file,
    no Remove button, and still counted in totals and renewal risk."""
    assert config.DB_PATH != config.RUNTIME_DIR / "pact.db", (
        "tests must run against a temporary database, not runtime/pact.db"
    )
    assert not str(config.DB_PATH).startswith(str(config.RUNTIME_DIR))


def test_rehydrate_deletes_upload_rows_with_no_manifest_entry(clean_uploads):
    """An upload row whose manifest entry is gone is unreachable: the dashboard
    card is manifest-driven so it has no Remove button, and the remove route
    404s. The manifest is the source of truth, so rehydration must reconcile
    the table down to it rather than only inserting."""
    dataset_tools.upsert_upload_row(_sample_record("U-0301"))
    assert dataset_tools.fetch_contract("U-0301") is not None

    seed_db.rehydrate_uploads()

    assert dataset_tools.fetch_contract("U-0301") is None


def test_rehydrate_keeps_upload_rows_that_are_in_the_manifest(clean_uploads):
    (clean_uploads / "U-0302.txt").write_text("VENDOR: Kept Corp\n", encoding="utf-8")
    uploads.write_manifest({
        "next_id": 303,
        "entries": {
            "U-0302": {
                "contract_id": "U-0302",
                "original_filename": "kept.txt",
                "stored_filename": "U-0302.txt",
                "terms": _sample_record("U-0302").model_dump(mode="json"),
            },
        },
    })

    seed_db.rehydrate_uploads()

    assert dataset_tools.fetch_contract("U-0302") is not None


def test_a_corrupt_manifest_never_deletes_upload_rows(clean_uploads):
    """Reconciliation trusts the manifest. If the manifest cannot be read, the
    honest response is to leave the table alone - deleting every upload row
    because a file failed to parse would turn one recoverable problem into
    permanent data loss."""
    dataset_tools.upsert_upload_row(_sample_record("U-0303"))
    clean_uploads.joinpath("manifest.json").write_text("{not valid json", encoding="utf-8")

    seed_db.rehydrate_uploads()

    assert dataset_tools.fetch_contract("U-0303") is not None
    dataset_tools.delete_upload_row("U-0303")


# ---------------------------------------------------------------------------
# An uploaded contract must actually reach the retriever
# ---------------------------------------------------------------------------

from app.tools import vector_store  # noqa: E402

# "any hit at all for this contract", rather than the backend-specific relevance
# floor: these tests ask whether the document is in the index, not how well a
# particular query happens to score against a hashed embedding.
ANY_DISTANCE = float("inf")

# Deliberately NOT the seed generator's phrasing. The offline regex is tuned to
# that generator, so a document worded like a real contract is the only fixture
# that can tell "the LLM read it" apart from "the regex happened to match".
REALISTIC_CONTRACT = """MASTER SUBSCRIPTION AGREEMENT

1. TERM AND RENEWAL. The initial subscription term commences on the Effective
Date and expires on 30 June 2027. Thereafter this Agreement shall renew for
successive periods of one (1) year unless a party delivers written notice of
its intention not to renew no fewer than ninety (90) days prior to the end of
the then-current period.

2. FEES. Customer shall remit subscription charges of USD 14,250 each calendar
month, invoiced quarterly in advance and payable within thirty days of receipt.

3. TERMINATION FOR CONVENIENCE. Either party may exit this Agreement early on
payment of an exit charge amounting to twenty percent of the charges that would
otherwise have fallen due across the unexpired balance of the period.
"""


def _upload(client, name: str = "realistic.txt", body: str = REALISTIC_CONTRACT) -> str:
    response = client.post(
        "/api/upload", files={"file": (name, body.encode("utf-8"), "text/plain")}
    )
    assert response.status_code == 200, response.text
    return response.json()["contract_id"]


def test_uploaded_contract_chunks_are_retrievable(client):
    """The regression: nothing rebuilt or extended the vector index after an
    upload, so _extract_agentic retrieved zero chunks, broke out of its loop,
    and silently degraded to the offline regex - which is tuned to the seed
    generator's exact wording and reads almost nothing off a real contract.

    Asserted at the vector-store level because the suite is pinned to offline
    mode, where extraction never queries the index at all."""
    contract_id = _upload(client)

    hits = vector_store.search(
        "term expiration renewal notice", n_results=5,
        contract_id=contract_id, max_distance=ANY_DISTANCE,
    )
    assert hits, "an uploaded contract must be searchable immediately after upload"
    assert {h["contract_id"] for h in hits} == {contract_id}


def test_removing_an_upload_drops_its_chunks(client):
    """Otherwise the index accumulates chunks for documents that no longer
    exist, and /api/ask cites contracts the user has deleted."""
    contract_id = _upload(client)
    assert vector_store.search("renewal", 5, contract_id=contract_id, max_distance=ANY_DISTANCE)

    assert client.post(f"/api/uploads/{contract_id}/remove").status_code == 200

    assert vector_store.search("renewal", 5, contract_id=contract_id, max_distance=ANY_DISTANCE) == []


def test_index_document_chunks_exactly_as_build_index_does(client):
    """index_document and build_index must share one chunking/embedding path,
    or the incremental route and the full rebuild drift into indexing the same
    document two different ways."""
    expected = len(vector_store.chunk_document(REALISTIC_CONTRACT))
    assert vector_store.index_document("U-9001", REALISTIC_CONTRACT) == expected

    hits = vector_store.search("fees charges", n_results=expected,
                               contract_id="U-9001", max_distance=ANY_DISTANCE)
    assert len(hits) == expected
    vector_store.remove_document("U-9001")


def test_reindexing_the_same_id_replaces_its_chunks(client):
    """A re-index must not leave the previous version's chunks behind next to
    the new ones - stale clause text would still be retrievable and citable."""
    vector_store.index_document("U-9002", REALISTIC_CONTRACT)
    vector_store.index_document("U-9002", "1. TERM. This one expires 2028-01-01.")

    hits = vector_store.search("term", 20, contract_id="U-9002", max_distance=ANY_DISTANCE)
    assert len(hits) == 1
    assert "2028-01-01" in hits[0]["text"]
    vector_store.remove_document("U-9002")


# ---------------------------------------------------------------------------
# A .txt upload gets the same minimum-content floor as a PDF
# ---------------------------------------------------------------------------


def test_empty_txt_is_rejected():
    """An empty file produced a 200 and a contract row with no terms - exactly
    the outcome SCANNED_PDF_MIN_CHARS exists to prevent for PDFs. The floor is
    a property of "is this a readable contract document", not of the format."""
    with pytest.raises(UnsupportedDocument) as excinfo:
        document_loader.load_document("empty.txt", b"")
    assert "text" in excinfo.value.reason.lower()


def test_whitespace_only_txt_is_rejected():
    with pytest.raises(UnsupportedDocument) as excinfo:
        document_loader.load_document("blank.txt", b"   \n\t\n   ")
    assert str(config.SCANNED_PDF_MIN_CHARS) in excinfo.value.reason


def test_empty_txt_upload_returns_422(client):
    response = client.post("/api/upload", files={"file": ("empty.txt", b"  \n ", "text/plain")})
    assert response.status_code == 422
    assert response.json()["detail"]


# ---------------------------------------------------------------------------
# Low confidence has to mean something, and has to be visible
# ---------------------------------------------------------------------------

READABLE_CONTRACT = ("VENDOR: Acme Corp", "CATEGORY: Network Circuit Services",
                     "This Agreement continues through 2026-12-31 and will "
                     "automatically renew.")


def test_low_confidence_is_false_when_the_load_bearing_fields_were_read(client):
    """The old rule - offline source plus any unresolved field - was true for
    virtually every upload, because a False boolean counts as unresolved. A
    flag that is always on tells the user nothing."""
    payload = client.post(
        "/api/upload", files={"file": ("deal.txt", _txt(*READABLE_CONTRACT), "text/plain")}
    ).json()
    assert payload["vendor"] == "Acme Corp"
    assert payload["renewal_date"] == "2026-12-31"
    assert payload["low_confidence"] is False


def test_low_confidence_is_true_when_the_document_could_not_be_read(client):
    """Vendor and renewal date are the load-bearing fields: without them there
    is no contract to show and no renewal risk to compute, so the reading has
    to be flagged rather than presented as a result."""
    payload = client.post(
        "/api/upload",
        files={"file": ("realistic.txt", REALISTIC_CONTRACT.encode("utf-8"), "text/plain")},
    ).json()
    assert payload["low_confidence"] is True


def test_low_confidence_is_true_when_only_the_vendor_was_read(client):
    payload = client.post(
        "/api/upload", files={"file": ("half.txt", _txt("VENDOR: Acme Corp"), "text/plain")}
    ).json()
    assert payload["vendor"] == "Acme Corp"
    assert not payload["renewal_date"]
    assert payload["low_confidence"] is True


def test_mission_control_flags_a_low_confidence_upload(client):
    """The spec requires a degraded extraction to be flagged, so a user can tell
    "we read your contract" from "we read nothing". It was computed and returned
    but rendered nowhere."""
    client.post("/api/upload",
                files={"file": ("realistic.txt", REALISTIC_CONTRACT.encode("utf-8"), "text/plain")})
    body = client.get("/").text
    assert "could read very little" in body
    assert "may be incomplete" in body


def test_mission_control_does_not_flag_a_readable_upload(client):
    client.post("/api/upload", files={"file": ("deal.txt", _txt(*READABLE_CONTRACT), "text/plain")})
    assert "could read very little" not in client.get("/").text


def test_upload_status_message_surfaces_low_confidence():
    """The status line the user sees right after uploading is the only place
    that reports the outcome of an extraction they just triggered."""
    source = (config.STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    assert "low_confidence" in source, (
        "app.js never reads payload.low_confidence, so a failed extraction is "
        "reported to the user as an ordinary success"
    )
    assert "could read very little" in source


def test_remove_with_corrupt_manifest_returns_500(client):
    """uploads.remove() calls read_manifest() too. The upload route already
    turns ManifestError into a 500 that names the manifest; this one let it
    escape as a raw traceback, so the same fault reported itself two different
    ways depending on which button the user pressed."""
    config.UPLOAD_MANIFEST_PATH.write_text("{not valid json", encoding="utf-8")

    response = client.post("/api/uploads/U-0001/remove")

    assert response.status_code == 500
    assert "manifest" in response.json()["detail"].lower()


def test_unique_path_docstring_matches_what_the_route_does():
    """The -2 suffix is transient: api_upload renames the stored file to
    <contract_id>.txt immediately, so no -2 file ever persists. Duplicates are
    still both kept - by the rename, not by the suffix."""
    doc = uploads.unique_path.__doc__
    assert "rename" in doc.lower()


# ---------------------------------------------------------------------------
# A date the model read in prose still has to reach renewal risk
# ---------------------------------------------------------------------------


def test_normalize_date_passes_iso_through():
    assert extraction.normalize_date("2026-09-30") == "2026-09-30"


def test_normalize_date_reads_a_day_first_prose_date():
    """Found end-to-end against a live model: a real contract says "expires on
    30 September 2026", the model faithfully reports that string, and every
    downstream consumer parses dates with %Y-%m-%d - so renewal.run() dropped
    the contract on a ValueError and it vanished from renewal risk behind a
    200 response."""
    assert extraction.normalize_date("30 September 2026") == "2026-09-30"


def test_normalize_date_reads_a_month_first_prose_date():
    assert extraction.normalize_date("September 30, 2026") == "2026-09-30"


def test_normalize_date_leaves_an_unparseable_string_alone():
    """Never guess. An ambiguous or unreadable date is reported as the model
    read it, not converted into a confident-looking wrong one."""
    assert extraction.normalize_date("some time next autumn") == "some time next autumn"
    assert extraction.normalize_date("09/30/2026") == "09/30/2026"
    assert extraction.normalize_date("") == ""


def test_extract_one_normalizes_a_prose_renewal_date(monkeypatch):
    chunk = {"contract_id": "U-0001", "chunk_index": 0, "heading": "1. TERM",
             "text": "The period expires on 30 September 2026.", "distance": 0.1}
    monkeypatch.setattr(extraction, "chat_structured",
                        lambda system, user, schema, agent="unknown":
                        ContractTerms(renewal_date="30 September 2026"))
    monkeypatch.setattr(extraction, "get_mode", lambda: "ollama")
    monkeypatch.setattr(extraction, "_retrieve", lambda cid, queries: [chunk])
    monkeypatch.setattr(config, "EXTRACTION_CACHE_ENABLED", False)

    record = extraction.extract_one("U-0001", "contract text")

    assert record.renewal_date == "2026-09-30"


def test_an_uploaded_contract_with_a_prose_date_reaches_renewal_risk(monkeypatch, clean_uploads):
    """The whole point of normalizing: renewal risk is one of only two things
    an uploaded contract can produce, and it is keyed off a parseable date."""
    monkeypatch.setattr(config, "REFERENCE_DATE", "2026-08-03")
    monkeypatch.setattr(extraction, "chat_structured",
                        lambda system, user, schema, agent="unknown":
                        ContractTerms(vendor="Helioscope Networks", auto_renew=True,
                                      renewal_date="30 September 2026",
                                      notice_period_days=60))
    monkeypatch.setattr(extraction, "get_mode", lambda: "ollama")
    monkeypatch.setattr(extraction, "_retrieve",
                        lambda cid, queries: [{"contract_id": cid, "chunk_index": 0,
                                               "heading": "1. TERM",
                                               "text": "Expires on 30 September 2026.",
                                               "distance": 0.1}])
    monkeypatch.setattr(config, "EXTRACTION_CACHE_ENABLED", False)

    record = extraction.extract_one("U-0401", "contract text")
    dataset_tools.upsert_upload_row(record)
    try:
        from app.agents import renewal
        risks, _ = renewal.run()
        assert any(r.contract_id == "U-0401" for r in risks)
    finally:
        dataset_tools.delete_upload_row("U-0401")


def test_upload_does_not_block_the_event_loop(clean_uploads, monkeypatch):
    """api_upload is declared `async def` (it needs `await file.read()`), which
    means FastAPI runs its body directly on uvicorn's single event loop unless
    the blocking work inside is explicitly offloaded. Two calls in the route -
    vector_store.index_document (an embedding HTTP call) and
    extraction.extract_one (up to 3 agentic LLM iterations, ~16-27s each in
    real use against Ollama) - are synchronous and, before this fix, ran
    straight on that loop. Measured live, a single upload froze the whole
    server for 61s: a concurrent GET / did not even get a socket-level
    response until the upload finished.

    Route tests elsewhere all use PACT_LLM_MODE=offline, where extract_one
    returns in ~0.03s, so the blocking never manifests there - this is the
    only test that would catch a regression.

    What this test proves: with extract_one patched to sleep, a concurrent
    request issued while the upload is mid-flight is served (and the upload
    is confirmed still running) rather than queueing behind it. It proves
    this via TestClient used as a context manager (`with TestClient(app) as
    client:`), which is required here - see starlette.testclient: a TestClient
    used WITHOUT `with` spins up a brand-new anyio event-loop thread for every
    individual request, which would silently give each concurrent call its own
    loop and never exercise the shared-loop contention a real server has.
    Entering the context manager makes the client reuse one persistent portal
    (one event-loop thread) across both concurrent calls, mirroring uvicorn's
    single worker.

    What this test does NOT prove: real wall-clock timing against a live
    Ollama, or behavior across multiple uvicorn worker processes (this app
    runs the uvicorn default of one)."""
    from app.agents import extraction as extraction_module

    original_extract_one = extraction_module.extract_one
    SLEEP_SECONDS = 1.5

    def slow_extract_one(contract_id, text):
        time.sleep(SLEEP_SECONDS)
        return original_extract_one(contract_id, text)

    monkeypatch.setattr(extraction_module, "extract_one", slow_extract_one)
    monkeypatch.setenv("PACT_LLM_MODE", "offline")

    from fastapi.testclient import TestClient
    from app.main import app

    body = _txt("VENDOR: Acme Corp", "This Agreement continues through 2026-12-31.")
    upload_result: dict = {}

    with TestClient(app) as client:

        def do_upload():
            resp = client.post("/api/upload", files={"file": ("deal.txt", body, "text/plain")})
            upload_result["status"] = resp.status_code

        upload_thread = threading.Thread(target=do_upload)
        upload_thread.start()
        time.sleep(SLEEP_SECONDS / 3)  # let the upload reach the patched sleep

        t0 = time.monotonic()
        status_resp = client.get("/api/status")
        get_elapsed = time.monotonic() - t0
        upload_still_running = upload_thread.is_alive()

        upload_thread.join(timeout=SLEEP_SECONDS + 10)

    assert status_resp.status_code == 200
    assert upload_still_running, (
        "the concurrent GET /api/status only completed after the upload "
        "finished - the event loop is still blocked for the duration of "
        "extraction, i.e. the upload route is not offloading its blocking work"
    )
    assert get_elapsed < SLEEP_SECONDS, (
        f"GET /api/status took {get_elapsed:.2f}s while an upload was in flight "
        f"(patched to sleep for {SLEEP_SECONDS}s); it should return almost "
        "immediately if the upload's blocking work is off the event loop"
    )
    assert upload_result.get("status") == 200
