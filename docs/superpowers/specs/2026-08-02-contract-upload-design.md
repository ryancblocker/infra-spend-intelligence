# Design: Contract Upload

**Date:** 2026-08-02
**Owner:** Sofia
**Status:** Approved

## Problem

PACT analyses a synthetic portfolio only. A viewer cannot try it on their own
contract, which makes the extraction agent impossible to evaluate: the offline
regex patterns are tuned to the exact phrasing the seed generator emits, so 86%
accuracy on generated documents says nothing about real ones. Upload is what
turns the LLM path from a nicety into the product - real contracts vary in
wording, and regex tuned to one generator will not survive them.

## What an uploaded contract can and cannot produce

A contract document states its terms and its price. It does not state how much
of what you bought you actually use.

| Agent | Requires | Available from an uploaded document |
|---|---|---|
| Extraction | document text | yes |
| Renewal risk | end date, notice days, auto-renew, annual cost | yes - all stated in the text |
| Waste detection | seat/port/rack utilization | **no** - telemetry, not contract language |
| Benchmark | unit cost and quantity | partially; skipped for uploads |

Uploads therefore produce **clause extraction and renewal risk**. Waste and
benchmark are reported as unavailable with the reason stated, never fabricated.
This limitation is honest and worth stating out loud: it demonstrates the
system knows the difference between what it read and what it does not know.

## Component 1: Storage and identity

- Uploaded files are written to `runtime/uploads/`, never to
  `app/data/contract_docs/`. The seed corpus stays clean and git-tracked.
- `extraction.run()` and `vector_store.build_index()` read **both** directories.
- Each upload gets a row in `contracts` with a new `source` column
  (`'seed'` | `'upload'`), added by `ALTER TABLE ... ADD COLUMN source TEXT
  DEFAULT 'seed'` when absent, so existing databases migrate without a reseed.
- Contract IDs are allocated as `U-0001`, `U-0002`, ... - visually distinct from
  seed `C-00xx` ids.

## Component 2: Document loading

New module `app/tools/document_loader.py`, single responsibility: bytes plus
filename in, plain text out.

- `.txt` - decoded as UTF-8, falling back to latin-1.
- `.pdf` - `pypdf` (pure Python, no system dependencies), page text joined.
- **Scanned-PDF detection:** if extracted text is under 200 characters the file
  is treated as image-only and rejected with a message naming the cause. Failing
  clearly matters more than failing quietly here, because a silent empty
  extraction would surface later as a contract with no terms and no explanation.

`load_document(filename: str, data: bytes) -> str` raises
`UnsupportedDocument(reason)` for anything it cannot read.

## Component 3: Extraction gains cost fields

`ContractTerms` gains `monthly_cost: float | None` and
`annual_cost: float | None`.

This does not violate the project's rule that the model never produces dollar
figures. The contract *states* its price - "recurring fees of $9,936.97 per
month". Reading a number that is written down is extraction. The optimization
agent remains forbidden from inventing or recomputing any figure; all cost
projections stay deterministic. The distinction is: **extracted figures are
quoted from the document, computed figures are never the model's.**

If only one of monthly/annual is found, the other is derived arithmetically
(x12 or /12) in code, not by the model.

## Component 4: Routes

- `POST /api/upload` - multipart file. Validates, loads text, writes to
  `runtime/uploads/`, runs `extraction.extract_one` on it, inserts a contracts
  row from the extracted terms, returns the new contract id and a summary.
- `POST /api/uploads/{contract_id}/remove` - deletes the file and the row.
- Uploaded contracts appear in `GET /contracts` and on the dashboard once the
  pipeline is re-run.

Uploading does **not** silently mutate a completed run's numbers. The UI prompts
to re-run the pipeline after a successful upload.

## Component 5: UI

A card on the dashboard, above the pipeline:

- File picker plus drag-and-drop target.
- List of uploaded contracts: id, vendor, extracted renewal date, Remove.
- After a successful upload, an inline prompt to re-run the analysis.
- On an uploaded contract's detail page, a note where waste findings would be:
  "Utilization findings require your usage data, which this contract does not
  contain."

`Reset` clears the **run**, not uploads. Deleting a user's files as a side
effect of resetting a demo would be surprising; removal is explicit and
per-contract.

## Security and limits

| Guard | Behavior |
|---|---|
| Extension allow-list | `.pdf`, `.txt` only; anything else 415 |
| Size cap | 10 MB; over that 413 |
| Filename sanitization | basename only, path separators stripped, so `../` cannot escape the upload directory |
| Duplicate names | suffixed `-2`, `-3`; both kept |

## Error handling

| Case | Result |
|---|---|
| Unsupported type | 415, permitted types named |
| Scanned/image PDF | 422, explains OCR is not supported |
| Over size cap | 413 |
| Corrupt PDF | 422, parse failure reported |
| LLM extraction returns nothing | file kept; row created from the regex fallback; flagged as low confidence |
| Remove on unknown id | 404 |

## Testing

- `.txt` upload produces text
- generated digital PDF produces text
- image-only PDF rejected as scanned
- oversized file rejected
- `../../etc/passwd` style filename is sanitized to a basename
- unsupported extension rejected
- upload creates a `contracts` row with `source='upload'`
- renewal risk includes an uploaded contract with a near end date
- waste produces no findings for an uploaded contract
- remove deletes both the file and the row
- duplicate filenames both persist

## Out of scope

OCR for scanned documents, `.docx`, bulk/zip upload, authentication and
per-user isolation, and any attempt to infer utilization for uploaded
contracts.

## Files

| File | Change |
|---|---|
| `app/tools/document_loader.py` | new - PDF/txt to text |
| `app/main.py` | upload and remove routes |
| `app/tools/dataset_tools.py` | insert/delete upload rows, `source` column migration |
| `app/agents/extraction.py` | read both document directories |
| `app/agents/schemas.py` | `monthly_cost`, `annual_cost` on `ContractTerms` |
| `app/tools/vector_store.py` | index both directories |
| `app/templates/mission_control.html`, `contract_detail.html` | upload card, unavailable-findings note |
| `app/static/css/theme.css`, `app/static/js/app.js` | upload UI |
| `app/config.py` | `UPLOAD_DIR`, size cap |
| `requirements.txt` | `pypdf` |
