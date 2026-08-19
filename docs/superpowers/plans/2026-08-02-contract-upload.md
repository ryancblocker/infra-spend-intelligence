# Contract Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a viewer upload their own `.pdf`/`.txt` contract and get clause extraction and renewal risk on it, with waste and benchmark honestly reported as unavailable.

**Architecture:** Uploaded files land in `runtime/uploads/`, never in the git-tracked seed corpus. A JSON manifest beside them is the durable record of what was uploaded; the `contracts` table row is derived from that manifest and rebuilt whenever the database is reseeded. Document reading moves behind two `config` helpers so extraction, the vector index, and the detail view all see both directories through one code path.

**Tech Stack:** FastAPI, Pydantic v2, SQLite, ChromaDB, pypdf, pytest.

## Global Constraints

- Uploaded files are written to `runtime/uploads/` only. `app/data/contract_docs/` stays clean and git-tracked.
- Upload contract IDs are `U-0001`, `U-0002`, … — visually distinct from seed `C-00xx`.
- Extension allow-list: `.pdf`, `.txt` only. Anything else → HTTP 415.
- Size cap: 10 MB (10 * 1024 * 1024 bytes). Over → HTTP 413.
- Scanned-PDF threshold: extracted text under 200 characters → HTTP 422, OCR named as the reason.
- Filenames are reduced to a basename; path separators stripped so `../` cannot escape the upload directory.
- Duplicate filenames are suffixed `-2`, `-3`; both files are kept.
- The model never produces a computed dollar figure. Extracting a price the contract *states* is allowed; deriving monthly↔annual is done in Python (`* 12` / `/ 12`), never by the model.
- Uploads produce extraction + renewal risk only. Waste and benchmark report unavailability with the reason stated — never a fabricated finding.
- `Reset` clears the run, not uploads. Removal is explicit and per-contract.
- Python 3.13, `from __future__ import annotations` at the top of every new module (matches existing files).

## Design decision not in the spec: surviving a reseed

The spec says the `source` column is added by `ALTER TABLE ... ADD COLUMN source TEXT DEFAULT 'seed'` "so existing databases migrate without a reseed." That handles the upgrade path but not the reseed path, and the reseed path is destructive:

`app/data/seed_db.py:31-34` does `config.DB_PATH.unlink()` and then `df.to_sql(table, conn, if_exists="replace")` for every table. Any reseed deletes the whole database file — uploaded rows and the `source` column with it. Two things trigger this today:

- `tests/conftest.py:17` calls `build_database()` as a session-autouse fixture, so **running the test suite wipes `runtime/pact.db`**.
- `python -m app.data.seed_db` reseeds manually.

App startup is safe (`app/main.py:64` only seeds when the DB is absent), but "your uploads vanished because you ran pytest" is not acceptable behavior.

**Resolution:** `runtime/uploads/manifest.json` is the source of truth for what has been uploaded. The `contracts` row is derived state. `build_database()` gains a final rehydration step that re-applies the `source` column and re-inserts a row per manifest entry. The manifest stores the extracted terms, so rehydration needs no LLM call and no re-parse of the PDF.

This is an addition to the approved spec. It changes no user-visible behavior described there — it only makes Component 1 actually hold.

**Amended during Task 2** after review found the manifest code below did not
actually deliver the durability it claimed. Two rulings, both from Sofia:

1. **Fail loud, write atomically.** As originally drafted, `read_manifest`
   swallowed a corrupt file and returned `{}`, and the next `store()` wrote that
   empty dict back over it — turning one transient corruption into permanent loss
   of every upload record, with the `.txt` files left orphaned on disk. Writes now
   go through a temp file plus `os.replace()`, and unparseable JSON raises
   `ManifestError` instead of degrading to "nothing was ever uploaded." A missing
   file still returns `{}`; that is the real "nothing uploaded yet" case.
2. **Monotonic IDs.** `max(existing) + 1` reissued an id after the highest upload
   was removed, so `U-0002` could name two different documents over time. The
   manifest now carries a `next_id` counter that only increases.

The Task 2 code blocks below predate both rulings; the committed implementation
is the authority where they differ.

## File Structure

| File | Responsibility |
|---|---|
| `app/tools/document_loader.py` | **new** — bytes + filename → plain text. Knows about PDF/txt and nothing else. |
| `app/tools/uploads.py` | **new** — upload storage: sanitization, size cap, ID allocation, duplicate suffixing, manifest read/write, contracts-row sync. |
| `tests/test_uploads.py` | **new** — all upload tests. |
| `app/config.py` | `UPLOAD_DIR`, `MAX_UPLOAD_BYTES`, `ALLOWED_UPLOAD_SUFFIXES`, `SCANNED_PDF_MIN_CHARS`, plus `document_paths()` / `document_path()` helpers. |
| `app/agents/schemas.py` | `monthly_cost` / `annual_cost` on `ContractTerms` and `ExtractedContract`. |
| `app/agents/extraction.py` | `run()` reads both directories; offline regex learns the two cost patterns. |
| `app/tools/vector_store.py` | `build_index()` indexes both directories. |
| `app/views.py` | detail page reads through the config helper; exposes `is_upload`. |
| `app/tools/dataset_tools.py` | `source` column migration, upload row insert/delete, `fetch_upload_ids()`. |
| `app/data/seed_db.py` | rehydrate uploads after a reseed. |
| `app/main.py` | `POST /api/upload`, `POST /api/uploads/{contract_id}/remove`. |
| `app/templates/mission_control.html` | upload card above the pipeline. |
| `app/templates/contract_detail.html` | unavailable-findings note for uploads. |
| `app/static/css/theme.css`, `app/static/js/app.js` | upload card styling and behavior. |
| `requirements.txt` | `pypdf>=5.1`. |

---

### Task 1: Document loader

**Files:**
- Create: `app/tools/document_loader.py`
- Create: `tests/test_uploads.py`
- Modify: `app/config.py` (after line 22, the `TEMPLATES_DIR` block)
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `load_document(filename: str, data: bytes) -> str` and `class UnsupportedDocument(Exception)` with a `.reason: str` attribute. Task 2 and Task 6 both call `load_document`.

- [ ] **Step 1: Add the dependency and config constants**

Append to `requirements.txt`:

```
pypdf>=5.1
```

Install it: `.venv/bin/pip install "pypdf>=5.1"`

In `app/config.py`, after the `TEMPLATES_DIR = APP_DIR / "templates"` line, add:

```python
# --- Uploads ---
# Uploaded contracts live in runtime/, never in the git-tracked seed corpus.
UPLOAD_DIR = RUNTIME_DIR / "uploads"
UPLOAD_MANIFEST_PATH = UPLOAD_DIR / "manifest.json"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_SUFFIXES = (".pdf", ".txt")
# A digital PDF of a contract yields thousands of characters. Under this, the
# file is image-only and needs OCR, which is out of scope - so say so plainly
# rather than creating a contract with no terms and no explanation.
SCANNED_PDF_MIN_CHARS = 200
```

Extend `ensure_runtime_dirs()` at the bottom of the same file:

```python
def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_uploads.py`:

```python
"""
Tests for contract upload: document loading, storage, and the upload routes.

PDF fixtures are generated in-process rather than committed, so the suite stays
dependency-light and the "scanned PDF" case is unambiguous - a page with no text
operators at all is exactly what a scan produces.
"""

from __future__ import annotations

import pytest

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


def test_txt_upload_produces_text():
    text = document_loader.load_document("contract.txt", b"VENDOR: Acme Corp\n")
    assert "Acme Corp" in text


def test_txt_falls_back_to_latin1_on_bad_utf8():
    text = document_loader.load_document("contract.txt", b"VENDOR: Caf\xe9 Ltd\n")
    assert "Caf" in text


# Must exceed SCANNED_PDF_MIN_CHARS, or the fixture meant to represent a real
# digital contract trips the image-only guard. No parentheses: they delimit
# strings in PDF syntax and would need escaping.
DIGITAL_PDF_TEXT = (
    "MASTER SERVICES AGREEMENT between ACME CORP and the Customer. "
    "This Agreement continues through 2026-12-31 and will automatically renew "
    "for successive twelve month terms unless either party gives written notice "
    "of non-renewal at least 60 days before expiration of the then-current term."
)


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
    assert excinfo.value.reason


def test_unsupported_extension_is_rejected():
    with pytest.raises(UnsupportedDocument) as excinfo:
        document_loader.load_document("contract.docx", b"anything")
    assert ".pdf" in excinfo.value.reason and ".txt" in excinfo.value.reason
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_uploads.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tools.document_loader'`

- [ ] **Step 4: Write the implementation**

Create `app/tools/document_loader.py`:

```python
"""
Purpose: Turn an uploaded file into plain text. Bytes plus filename in, text out.

Single responsibility on purpose - the upload route should not know anything
about PDF internals, and this module should not know anything about HTTP.
"""

from __future__ import annotations

import io
from pathlib import Path

from app import config


class UnsupportedDocument(Exception):
    """Raised when a file cannot be read. Carries a reason meant for the user."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def load_document(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in config.ALLOWED_UPLOAD_SUFFIXES:
        permitted = ", ".join(config.ALLOWED_UPLOAD_SUFFIXES)
        raise UnsupportedDocument(f"Unsupported file type '{suffix or filename}'. Permitted types: {permitted}.")
    if suffix == ".txt":
        return _load_txt(data)
    return _load_pdf(data)


def _load_txt(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _load_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except (PdfReadError, ValueError, KeyError, AttributeError) as exc:
        raise UnsupportedDocument(f"This PDF could not be parsed: {exc}") from exc

    if len(text.strip()) < config.SCANNED_PDF_MIN_CHARS:
        raise UnsupportedDocument(
            "This looks like a scanned or image-only PDF - almost no selectable text was "
            "found. OCR is not supported; please upload a text-based PDF or a .txt file."
        )
    return text
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_uploads.py -v`
Expected: PASS, 6 passed

- [ ] **Step 6: Commit**

```bash
git add app/tools/document_loader.py tests/test_uploads.py app/config.py requirements.txt
git commit -m "Add document loader for uploaded contracts"
```

---

### Task 2: Upload storage and manifest

**Files:**
- Create: `app/tools/uploads.py`
- Modify: `tests/test_uploads.py` (append)

**Interfaces:**
- Consumes: `document_loader.load_document`, `config.UPLOAD_DIR`, `config.MAX_UPLOAD_BYTES`, `config.UPLOAD_MANIFEST_PATH`.
- Produces:
  - `class UploadTooLarge(Exception)`
  - `safe_basename(filename: str) -> str`
  - `next_contract_id(manifest: dict) -> str`
  - `unique_path(basename: str) -> Path`
  - `read_manifest() -> dict[str, dict]` — keyed by contract_id
  - `write_manifest(manifest: dict[str, dict]) -> None`
  - `store(filename: str, data: bytes) -> tuple[str, Path, str]` — returns `(contract_id, path, text)`
  - `remove(contract_id: str) -> bool`
  Tasks 5 and 6 call `read_manifest`, `store`, and `remove`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_uploads.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_uploads.py -v -k "sanitiz or oversized or sequential or duplicate or manifest or remove or fallback"`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tools.uploads'`

- [ ] **Step 3: Write the implementation**

Create `app/tools/uploads.py`:

```python
"""
Purpose: Storage for uploaded contracts - where the bytes go, what they are
called, and what we remember about them.

The manifest, not the database, is the durable record of an upload. A reseed
drops and recreates every table (see app/data/seed_db.py), so a contracts row
cannot be the source of truth; it is rebuilt from this manifest instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.tools.document_loader import load_document


class UploadTooLarge(Exception):
    """Raised when a file exceeds config.MAX_UPLOAD_BYTES."""


def safe_basename(filename: str) -> str:
    """Reduce an arbitrary client-supplied name to a bare filename.

    PurePath handles the separator cases; the leading-dot guard is what stops
    '../..' from surviving as a name that still means 'parent directory'."""
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name or set(name) <= {"."}:
        return "upload"
    return name


def read_manifest() -> dict[str, dict]:
    if not config.UPLOAD_MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(config.UPLOAD_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_manifest(manifest: dict[str, dict]) -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )


def next_contract_id(manifest: dict) -> str:
    used = [int(cid.split("-")[1]) for cid in manifest if cid.startswith("U-")]
    return f"U-{max(used, default=0) + 1:04d}"


def unique_path(basename: str) -> Path:
    """Suffix -2, -3, ... rather than overwriting. Two contracts genuinely can
    share a filename, and silently replacing one would lose a user's document."""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    candidate = config.UPLOAD_DIR / basename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(basename).stem, Path(basename).suffix
    counter = 2
    while True:
        candidate = config.UPLOAD_DIR / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def store(filename: str, data: bytes) -> tuple[str, Path, str]:
    """Validate, read, and persist an upload. Returns (contract_id, path, text).

    Raises UploadTooLarge or document_loader.UnsupportedDocument."""
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise UploadTooLarge(
            f"File is {len(data) / 1_048_576:.1f} MB; the limit is "
            f"{config.MAX_UPLOAD_BYTES // 1_048_576} MB."
        )

    basename = safe_basename(filename)
    text = load_document(basename, data)

    manifest = read_manifest()
    contract_id = next_contract_id(manifest)
    # Store the extracted text, not the original bytes: every downstream reader
    # (extraction, the vector index, the detail page) wants .txt, and this keeps
    # PDF parsing to exactly once per upload.
    path = unique_path(f"{Path(basename).stem}.txt")
    path.write_text(text, encoding="utf-8")

    manifest[contract_id] = {
        "contract_id": contract_id,
        "original_filename": basename,
        "stored_filename": path.name,
    }
    write_manifest(manifest)
    return contract_id, path, text


def remove(contract_id: str) -> bool:
    manifest = read_manifest()
    entry = manifest.pop(contract_id, None)
    if entry is None:
        return False
    path = config.UPLOAD_DIR / entry["stored_filename"]
    path.unlink(missing_ok=True)
    write_manifest(manifest)
    return True
```

Note on `store`: the file is saved as `<stem>.txt` regardless of input type, so `unique_path` dedupes on the stored name. A `deal.pdf` and a `deal.txt` therefore become `deal.txt` and `deal-2.txt` — both kept, as the spec requires.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_uploads.py -v`
Expected: PASS, 14 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/uploads.py tests/test_uploads.py
git commit -m "Add upload storage with manifest and filename sanitization"
```

---

### Task 3: Cost fields on the extraction schema

**Files:**
- Modify: `app/agents/schemas.py:29-48` (`ContractTerms`), `:57-79` (`ExtractedContract`)
- Modify: `app/agents/extraction.py:299-335` (`_extract_offline`)
- Modify: `tests/test_uploads.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ContractTerms.monthly_cost: float | None`, `ContractTerms.annual_cost: float | None`, the same two fields on `ExtractedContract`, and `extraction.reconcile_costs(monthly, annual) -> tuple[float | None, float | None]`. Task 6 calls `reconcile_costs`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_uploads.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_uploads.py -v -k "cost or reconcile"`
Expected: FAIL — `AttributeError: module 'app.agents.extraction' has no attribute 'reconcile_costs'` and pydantic rejecting `monthly_cost`

- [ ] **Step 3: Add the schema fields**

In `app/agents/schemas.py`, inside `ContractTerms`, after the `minimum_commitment: str = ""` line (line 42):

```python
    # The contract states its price; reading a written-down number is extraction,
    # not calculation. Every *derived* figure stays in Python - see
    # extraction.reconcile_costs.
    monthly_cost: float | None = None
    annual_cost: float | None = None
```

In the same file, inside `ExtractedContract`, after its `minimum_commitment: str = ""` line (line 66), add the identical two lines:

```python
    monthly_cost: float | None = None
    annual_cost: float | None = None
```

- [ ] **Step 4: Add cost reconciliation and offline patterns**

In `app/agents/extraction.py`, add above `_extract_offline` (before line 299):

```python
def reconcile_costs(monthly: float | None, annual: float | None) -> tuple[float | None, float | None]:
    """Fill in whichever figure the contract did not state. Arithmetic only -
    the model is never asked to compute a number, just to read one."""
    if monthly is not None and annual is None:
        return monthly, round(monthly * 12, 2)
    if annual is not None and monthly is None:
        return round(annual / 12, 2), annual
    return monthly, annual
```

Inside `_extract_offline`, after the `minimum_commitment = _search(...)` line, add:

```python
    monthly_cost = _money(text, r"(?:recurring fees|monthly (?:fee|charge)s?)[^.$]*\$\s*([\d,]+(?:\.\d{2})?)")
    annual_cost = _money(text, r"(?:annual|yearly)\s+(?:fees|cost|charges)[^.$]*\$\s*([\d,]+(?:\.\d{2})?)")
    monthly_cost, annual_cost = reconcile_costs(monthly_cost, annual_cost)
```

Add the two extracted fields to the `ExtractedContract(...)` constructor in the same function, after `minimum_commitment=minimum_commitment,`:

```python
        monthly_cost=monthly_cost,
        annual_cost=annual_cost,
```

And add this helper next to `_search` (after line 341):

```python
def _money(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_uploads.py -v`
Expected: PASS, 22 passed

- [ ] **Step 6: Run the full suite to confirm nothing regressed**

Run: `.venv/bin/pytest -q`
Expected: PASS — the two new optional fields must not disturb `tests/test_agents.py` or `tests/test_llm_agents.py`

- [ ] **Step 7: Commit**

```bash
git add app/agents/schemas.py app/agents/extraction.py tests/test_uploads.py
git commit -m "Extract stated contract costs, deriving the missing figure in code"
```

---

### Task 4: Read documents from both directories

**Files:**
- Modify: `app/config.py` (add helpers below `ensure_runtime_dirs`)
- Modify: `app/agents/extraction.py:69-73` (`run`)
- Modify: `app/tools/vector_store.py:74`
- Modify: `app/views.py:55-57`
- Modify: `tests/test_uploads.py` (append)

**Interfaces:**
- Consumes: `config.UPLOAD_DIR` (Task 1).
- Produces: `config.document_paths() -> list[Path]` and `config.document_path(contract_id: str) -> Path | None`. Tasks 6 and 7 rely on uploaded contracts being visible to `extraction.run()` and `vector_store.build_index()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_uploads.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_uploads.py -v -k "document_path or manifest_json"`
Expected: FAIL — `AttributeError: module 'app.config' has no attribute 'document_paths'`

- [ ] **Step 3: Add the config helpers**

In `app/config.py`, below `ensure_runtime_dirs()`:

```python
def document_paths() -> list[Path]:
    """Every contract document the agents can read: the git-tracked seed corpus
    plus anything the user uploaded. One helper so extraction, the vector index,
    and the detail view can never drift out of sync about where documents live."""
    seed = sorted(CONTRACT_DOCS_DIR.glob("*.txt"))
    uploaded = sorted(UPLOAD_DIR.glob("*.txt")) if UPLOAD_DIR.exists() else []
    return seed + uploaded


def document_path(contract_id: str) -> Path | None:
    for directory in (CONTRACT_DOCS_DIR, UPLOAD_DIR):
        candidate = directory / f"{contract_id}.txt"
        if candidate.exists():
            return candidate
    return None
```

The manifest is `manifest.json`, so the `*.txt` glob already excludes it.

- [ ] **Step 4: Route the three call sites through the helpers**

`app/agents/extraction.py`, replace lines 69-73:

```python
def run() -> list[ExtractedContract]:
    results = []
    for path in config.document_paths():
        results.append(extract_one(path.stem, path.read_text(encoding="utf-8")))
    return results
```

`app/tools/vector_store.py`, replace line 74:

```python
    doc_paths = config.document_paths()
```

and update that function's docstring (line 67) to:

```python
    """(Re)build the contract-document vector index from the seed corpus and uploads."""
```

`app/views.py`, replace lines 55-57:

```python
    from app import config
    candidate = config.document_path(contract_id)
    source_text = candidate.read_text(encoding="utf-8") if candidate else None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_uploads.py -v && .venv/bin/pytest -q`
Expected: PASS on both

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/agents/extraction.py app/tools/vector_store.py app/views.py tests/test_uploads.py
git commit -m "Read contract documents from the seed corpus and uploads through one helper"
```

---

### Task 5: Database rows for uploads

**Files:**
- Modify: `app/tools/dataset_tools.py` (append functions)
- Modify: `app/data/seed_db.py:31-47` (`build_database`)
- Modify: `tests/test_uploads.py` (append)

**Interfaces:**
- Consumes: `uploads.read_manifest` (Task 2), `ExtractedContract` cost fields (Task 3).
- Produces:
  - `ensure_source_column() -> None`
  - `upsert_upload_row(record: ExtractedContract) -> None`
  - `delete_upload_row(contract_id: str) -> None`
  - `fetch_upload_ids() -> set[str]`
  Tasks 6, 7 and 8 call these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_uploads.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_uploads.py -v -k "upsert or seed_rows or delete_removes or rehydrates"`
Expected: FAIL — `AttributeError: module 'app.tools.dataset_tools' has no attribute 'upsert_upload_row'`

- [ ] **Step 3: Write the dataset_tools functions**

Append to `app/tools/dataset_tools.py`:

```python
# ---------------------------------------------------------------------------
# Uploaded contracts
# ---------------------------------------------------------------------------


def ensure_source_column() -> None:
    """Add contracts.source to databases created before uploads existed, so an
    existing runtime/pact.db upgrades in place rather than needing a reseed."""
    with connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(contracts)")}
        if "source" not in columns:
            conn.execute("ALTER TABLE contracts ADD COLUMN source TEXT DEFAULT 'seed'")
            conn.execute("UPDATE contracts SET source = 'seed' WHERE source IS NULL")
            conn.commit()


def upsert_upload_row(record) -> None:
    """Insert or replace the contracts row derived from an uploaded document.

    Only the columns an actual contract document can support are populated.
    Utilization-derived columns stay NULL - see the waste agent, which reports
    uploads as unavailable rather than inventing numbers for them."""
    ensure_source_column()
    with connection() as conn:
        conn.execute("DELETE FROM contracts WHERE contract_id = ?", (record.contract_id,))
        conn.execute(
            """INSERT INTO contracts
               (contract_id, vendor, service_type, start_date, end_date, annual_cost,
                monthly_cost, auto_renew, notice_days, termination_fee_pct,
                escalation_pct, owner, status, region, minimum_commitment, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'upload')""",
            (
                record.contract_id,
                record.vendor or "Unknown vendor",
                record.category or "Uploaded contract",
                "",
                record.renewal_date or "",
                record.annual_cost,
                record.monthly_cost,
                "Yes" if record.auto_renew else "No",
                record.notice_period_days,
                record.termination_fee_pct,
                record.annual_escalator_pct,
                "Uploaded",
                "Active",
                "",
                record.minimum_commitment or "",
            ),
        )
        conn.commit()


def delete_upload_row(contract_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "DELETE FROM contracts WHERE contract_id = ? AND source = 'upload'",
            (contract_id,),
        )
        conn.commit()


def fetch_upload_ids() -> set[str]:
    ensure_source_column()
    return {row["contract_id"] for row in _rows("SELECT contract_id FROM contracts WHERE source = 'upload'")}
```

If `connection()` is not a context manager in this codebase, check `app/tools/dataset_tools.py:16` and match whatever pattern `fetch_contracts` uses.

- [ ] **Step 4: Rehydrate uploads after a reseed**

In `app/data/seed_db.py`, inside `build_database()`, replace the `conn.commit()` / `finally` tail (lines 43-47) so rehydration runs after the tables are rebuilt:

```python
        conn.commit()
    finally:
        conn.close()

    _rehydrate_uploads()
    return counts


def _rehydrate_uploads() -> int:
    """Re-create contracts rows for uploaded documents.

    build_database() deletes the database file outright, so uploaded rows cannot
    survive a reseed on their own. runtime/uploads/manifest.json is the durable
    record; this replays it. Returns the number of rows restored."""
    from app.agents.schemas import ExtractedContract
    from app.tools import dataset_tools, uploads

    dataset_tools.ensure_source_column()
    restored = 0
    for entry in uploads.read_manifest()["entries"].values():
        terms = entry.get("terms")
        if not terms:
            continue
        dataset_tools.upsert_upload_row(ExtractedContract(**terms))
        restored += 1
    return restored
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_uploads.py -v && .venv/bin/pytest -q`
Expected: PASS on both

- [ ] **Step 6: Commit**

```bash
git add app/tools/dataset_tools.py app/data/seed_db.py tests/test_uploads.py
git commit -m "Persist uploaded contracts and rebuild them after a reseed"
```

---

### Task 6: Upload and remove routes

**Files:**
- Modify: `app/main.py` (add routes after `api_reset`, around line 165)
- Modify: `tests/test_uploads.py` (append)

**Interfaces:**
- Consumes: `uploads.store`, `uploads.remove`, `uploads.read_manifest`, `uploads.write_manifest` (Task 2); `document_loader.UnsupportedDocument` (Task 1); `extraction.extract_one` and `reconcile_costs` (Task 3); `dataset_tools.upsert_upload_row`, `delete_upload_row` (Task 5).
- Produces: `POST /api/upload` returning `{"contract_id", "vendor", "renewal_date", "extraction_source", "low_confidence"}`; `POST /api/uploads/{contract_id}/remove` returning `{"removed": true}`. Task 7's JavaScript consumes both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_uploads.py`:

```python
from fastapi.testclient import TestClient


@pytest.fixture
def client(clean_uploads, monkeypatch):
    monkeypatch.setenv("PACT_LLM_MODE", "offline")
    from app.main import app
    return TestClient(app)


def test_upload_txt_returns_a_contract_id(client):
    body = b"VENDOR: Acme Corp\nCATEGORY: Network Circuit Services\n" \
           b"This Agreement continues through 2026-12-31 and will automatically renew.\n"
    response = client.post("/api/upload", files={"file": ("deal.txt", body, "text/plain")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_id"] == "U-0001"
    assert payload["vendor"] == "Acme Corp"


def test_upload_creates_a_contracts_row(client):
    body = b"VENDOR: Acme Corp\nThis Agreement continues through 2026-12-31.\n"
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
    body = b"VENDOR: Acme Corp\nThis Agreement continues through 2026-12-31.\n"
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_uploads.py -v -k "upload_txt or contracts_row or 415 or 413 or 422 or remove_deletes or unknown_id_returns_404"`
Expected: FAIL — 405 Method Not Allowed, since the routes do not exist

- [ ] **Step 3: Write the routes**

In `app/main.py`, extend the FastAPI import on line 16:

```python
from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
```

Add after `api_reset` (line 164):

```python
@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """Accept a contract document, extract its terms, and register it as U-000N.

    Extraction runs synchronously: the user should learn immediately whether we
    could read their contract, not discover it during the next pipeline run."""
    from app.tools import dataset_tools, uploads
    from app.tools.document_loader import UnsupportedDocument
    from app.tools.uploads import UploadTooLarge

    data = await file.read()
    try:
        contract_id, path, text = uploads.store(file.filename or "upload", data)
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UnsupportedDocument as exc:
        status = 415 if "Unsupported file type" in exc.reason else 422
        raise HTTPException(status_code=status, detail=exc.reason) from exc

    # Name the stored file after the contract id so config.document_path can find it.
    final_path = path.with_name(f"{contract_id}.txt")
    path.rename(final_path)
    manifest = uploads.read_manifest()
    manifest["entries"][contract_id]["stored_filename"] = final_path.name

    record = extraction.extract_one(contract_id, text)
    monthly, annual = extraction.reconcile_costs(record.monthly_cost, record.annual_cost)
    record.monthly_cost, record.annual_cost = monthly, annual

    manifest["entries"][contract_id]["terms"] = record.model_dump(mode="json")
    uploads.write_manifest(manifest)
    dataset_tools.upsert_upload_row(record)

    return {
        "contract_id": contract_id,
        "vendor": record.vendor,
        "renewal_date": record.renewal_date,
        "extraction_source": record.extraction_source,
        # The spec keeps a file whose LLM extraction returned nothing, falling back
        # to regex - but says so, rather than presenting a guess as a reading.
        "low_confidence": record.extraction_source == "offline" and bool(record.unresolved_fields),
    }


@app.post("/api/uploads/{contract_id}/remove")
def api_upload_remove(contract_id: str):
    from app.tools import dataset_tools, uploads

    if not uploads.remove(contract_id):
        raise HTTPException(status_code=404, detail=f"No uploaded contract {contract_id}.")
    dataset_tools.delete_upload_row(contract_id)
    return {"removed": True}
```

Confirm `extraction` is already imported at module scope in `app/main.py`; if not, import it inside `api_upload` alongside the others.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_uploads.py -v && .venv/bin/pytest -q`
Expected: PASS on both

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_uploads.py
git commit -m "Add upload and remove routes"
```

---

### Task 7: Waste and benchmark decline uploads honestly

**Files:**
- Modify: `app/agents/waste.py`, `app/agents/benchmark.py` (locate the per-contract loops first)
- Modify: `app/templates/contract_detail.html`
- Modify: `tests/test_uploads.py` (append)

**Interfaces:**
- Consumes: `dataset_tools.fetch_upload_ids` (Task 5).
- Produces: no new public functions; uploaded contracts produce zero waste and zero benchmark findings, and the detail template receives `is_upload: bool` from `app/views.py`.

- [ ] **Step 1: Locate the agents**

Run: `ls app/agents/ && grep -n "def run" app/agents/waste.py app/agents/benchmark.py`

Signatures differ, and the tests must match them:
- `waste.run() -> list[Finding]`
- `benchmark.run() -> tuple[list[Finding], str]`
- `renewal.run() -> tuple[list[RenewalRisk], str]`

Only `waste.run()` returns a bare list. Unpack the other two.

Both agents iterate contracts from `dataset_tools`. Uploaded rows have NULL utilization columns and no child assets, so they may already produce nothing — the test in Step 2 establishes which behavior is actual before any code changes.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_uploads.py`:

```python
def test_waste_produces_no_findings_for_an_uploaded_contract(client):
    body = b"VENDOR: Acme Corp\nThis Agreement continues through 2026-12-31.\n"
    contract_id = client.post(
        "/api/upload", files={"file": ("deal.txt", body, "text/plain")}
    ).json()["contract_id"]

    from app.agents import waste
    findings = waste.run()
    assert not [f for f in findings if f.contract_id == contract_id], (
        "waste findings require utilization telemetry, which a contract document "
        "does not contain - inventing one would be a fabricated number"
    )


def test_renewal_risk_includes_an_uploaded_contract(client):
    body = (b"VENDOR: Acme Corp\nThis Agreement continues through 2026-09-30 and will "
            b"automatically renew unless either party gives notice of non-renewal at "
            b"least 30 days before expiration.\n")
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
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/pytest tests/test_uploads.py -v -k "waste_produces or renewal_risk_includes"`

If both already pass, the agents behave correctly by construction — record that and skip to Step 5. If waste fails, add the guard in Step 4.

- [ ] **Step 4: Guard the waste and benchmark loops (only if Step 3 failed)**

At the top of each agent's `run()`:

```python
    # Uploaded contracts carry no utilization telemetry, so any finding here would
    # be invented rather than measured. Skipping them is the honest result.
    upload_ids = dataset_tools.fetch_upload_ids()
```

and skip inside the per-contract loop:

```python
        if contract["contract_id"] in upload_ids:
            continue
```

Import `dataset_tools` in each agent if it is not imported already.

- [ ] **Step 5: Surface the reason on the detail page**

In `app/views.py`, add to the returned dict in the contract-detail builder:

```python
        "is_upload": (contract or {}).get("source") == "upload",
```

In `app/templates/contract_detail.html`, wherever waste findings render, add the alternative branch:

```html
{% if is_upload %}
<p class="note note-unavailable">
  Utilization findings require your usage data, which this contract does not contain.
</p>
{% endif %}
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/agents/ app/views.py app/templates/contract_detail.html tests/test_uploads.py
git commit -m "Report utilization findings as unavailable for uploaded contracts"
```

---

### Task 8: Upload card UI

**Files:**
- Modify: `app/templates/mission_control.html`
- Modify: `app/static/js/app.js`
- Modify: `app/static/css/theme.css`
- Modify: `app/views.py` (add `uploads` to the mission-control context)

**Interfaces:**
- Consumes: `POST /api/upload` and `POST /api/uploads/{id}/remove` (Task 6), `uploads.read_manifest` (Task 2).
- Produces: no code interface — this is the last task.

- [ ] **Step 1: Pass the upload list into the template**

In `app/views.py`, in the mission-control context builder, add:

```python
    from app.tools import uploads as upload_store
    context["uploads"] = sorted(
        upload_store.read_manifest()["entries"].values(), key=lambda e: e["contract_id"]
    )
```

Match the surrounding style — if the builder returns a dict literal rather than mutating `context`, add the key there instead.

- [ ] **Step 2: Add the card markup**

In `app/templates/mission_control.html`, immediately above the pipeline section:

```html
<section class="card upload-card">
  <h2>Analyze your own contract</h2>
  <p class="card-sub">PDF or text, up to 10 MB. We extract clause terms and renewal
     risk. Utilization findings need usage data a contract does not contain.</p>

  <div id="upload-drop" class="upload-drop">
    <input type="file" id="upload-input" accept=".pdf,.txt" hidden>
    <button type="button" id="upload-browse" class="btn">Choose a file</button>
    <span class="upload-hint">or drag it here</span>
  </div>

  <p id="upload-status" class="upload-status" role="status" aria-live="polite"></p>

  {% if uploads %}
  <ul class="upload-list">
    {% for item in uploads %}
    <li data-contract-id="{{ item.contract_id }}">
      <a href="/contracts/{{ item.contract_id }}">{{ item.contract_id }}</a>
      <span class="upload-vendor">{{ item.terms.vendor if item.terms else item.original_filename }}</span>
      <span class="upload-renewal">{{ item.terms.renewal_date if item.terms else "" }}</span>
      <button type="button" class="btn-remove" data-remove="{{ item.contract_id }}">Remove</button>
    </li>
    {% endfor %}
  </ul>
  {% endif %}
</section>
```

- [ ] **Step 3: Add the behavior**

Append to `app/static/js/app.js`, matching the file's existing event-binding style:

```javascript
// --- Contract upload ---------------------------------------------------------
(function () {
  const drop = document.getElementById('upload-drop');
  if (!drop) return;
  const input = document.getElementById('upload-input');
  const status = document.getElementById('upload-status');

  document.getElementById('upload-browse').addEventListener('click', () => input.click());
  input.addEventListener('change', () => input.files[0] && send(input.files[0]));

  ['dragover', 'dragleave', 'drop'].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      drop.classList.toggle('is-over', name === 'dragover');
      if (name === 'drop' && event.dataTransfer.files[0]) send(event.dataTransfer.files[0]);
    });
  });

  async function send(file) {
    status.textContent = `Reading ${file.name}...`;
    status.className = 'upload-status';
    const body = new FormData();
    body.append('file', file);
    try {
      const response = await fetch('/api/upload', { method: 'POST', body });
      const payload = await response.json();
      if (!response.ok) {
        // The API's detail names the actual cause - show it rather than "upload failed".
        status.textContent = payload.detail || 'Upload failed.';
        status.classList.add('is-error');
        return;
      }
      status.innerHTML = `Added <strong>${payload.contract_id}</strong>` +
        `${payload.vendor ? ` - ${payload.vendor}` : ''}. ` +
        `Re-run the analysis to include it.`;
      status.classList.add('is-ok');
    } catch (err) {
      status.textContent = `Upload failed: ${err.message}`;
      status.classList.add('is-error');
    }
  }

  document.querySelectorAll('[data-remove]').forEach((button) => {
    button.addEventListener('click', async () => {
      const id = button.dataset.remove;
      const response = await fetch(`/api/uploads/${id}/remove`, { method: 'POST' });
      if (response.ok) button.closest('li').remove();
    });
  });
})();
```

- [ ] **Step 4: Style it**

Append to `app/static/css/theme.css`, reusing the existing custom properties rather than hard-coded colors:

```css
.upload-drop {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1.25rem;
  border: 1px dashed var(--border);
  border-radius: 8px;
}
.upload-drop.is-over { border-color: var(--accent); background: var(--surface-2); }
.upload-hint { color: var(--text-muted); font-size: 0.9rem; }
.upload-status { margin-top: 0.75rem; min-height: 1.25rem; font-size: 0.9rem; }
.upload-status.is-ok { color: var(--ok); }
.upload-status.is-error { color: var(--danger); }
.upload-list { list-style: none; margin-top: 1rem; padding: 0; }
.upload-list li {
  display: grid;
  grid-template-columns: 6rem 1fr auto auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.5rem 0;
  border-top: 1px solid var(--border);
}
.note-unavailable { color: var(--text-muted); font-style: italic; }
```

Check the real variable names in `theme.css` first (`--ok`, `--danger`, `--accent`, `--surface-2`, `--border`, `--text-muted`) and substitute whatever the file actually defines.

- [ ] **Step 5: Verify in the running app**

Run: `.venv/bin/uvicorn app.main:app --reload --port 8000`

Then check by hand: upload a `.txt`, confirm the card reports the new `U-0001` and prompts a re-run; upload a `.docx` and confirm the error names the permitted types; re-run the pipeline and confirm the uploaded contract appears in `/contracts`; open its detail page and confirm the utilization note; click Remove and confirm it disappears; press Reset and confirm the upload survives.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest -q
git add app/templates/mission_control.html app/static/js/app.js app/static/css/theme.css app/views.py
git commit -m "Add the contract upload card"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Component 1: storage, `runtime/uploads/`, `source` column, `U-000N` ids | 2, 5 |
| Component 2: `document_loader`, txt/pdf, scanned detection | 1 |
| Component 3: `monthly_cost` / `annual_cost`, derivation in code | 3 |
| Component 4: upload + remove routes, appears in `/contracts`, re-run prompt | 6, 8 |
| Component 5: dashboard card, upload list, detail-page note, Reset keeps uploads | 7, 8 |
| Security: allow-list, 10 MB cap, sanitization, duplicate suffixing | 1, 2 |
| Error handling: 415 / 422 / 413 / corrupt PDF / low confidence / 404 | 1, 2, 6 |
| Testing: all 11 listed cases | 1, 2, 5, 6, 7 |
| Both directories read by extraction and vector_store | 4 |

Every spec test case maps to a named test. The `Reset` behavior is verified manually in Task 8 Step 5 rather than by an automated test, because reset is a UI-driven state change over the run object, not the upload store.

**Deviations from the spec, both flagged above:**
1. The uploads manifest and `_rehydrate_uploads()` — required because `build_database()` deletes the database file, which the spec's `ALTER TABLE` migration does not survive.
2. Uploaded files are stored as extracted `.txt` named `<contract_id>.txt`, not as the original bytes. This lets `config.document_path()` find them by id and keeps PDF parsing to once per upload. The original filename is preserved in the manifest for display.

**Open risk:** `tests/conftest.py:17` calls `build_database()` as a session-autouse fixture against the real `runtime/pact.db`, so running the suite reseeds the developer's database. Task 5's rehydration means uploads now survive that, but the underlying "tests mutate real runtime state" issue is pre-existing and out of scope here. Worth a separate fix.
