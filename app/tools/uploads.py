"""
Purpose: Storage for uploaded contracts - where the bytes go, what they are
called, and what we remember about them.

The manifest, not the database, is the durable record of an upload. A reseed
drops and recreates every table (see app/data/seed_db.py), so a contracts row
cannot be the source of truth; it is rebuilt from this manifest instead.

Manifest shape on disk (and as returned by read_manifest):

    {
        "next_id": 3,
        "entries": {
            "U-0001": {"contract_id": "U-0001", "original_filename": "...", "stored_filename": "..."},
            "U-0002": {...}
        }
    }

`next_id` is a monotonic counter: it only ever increases and is never
recomputed from the entries currently present. That is what stops a
contract_id from being reissued after the upload holding the highest id is
removed - recomputing from `max(entries) + 1` would silently alias a new,
unrelated document to an id something else may still reference.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app import config
from app.tools.document_loader import load_document


class UploadTooLarge(Exception):
    """Raised when a file exceeds config.MAX_UPLOAD_BYTES."""


class ManifestError(Exception):
    """Raised when the manifest file exists but cannot be read as valid JSON.

    A missing manifest is the legitimate "nothing uploaded yet" case and is
    not an error. A present-but-corrupt manifest is different: silently
    treating it as empty (the old behavior) means the next store() writes a
    fresh, empty manifest over it, orphaning every prior upload's .txt file
    with no record left of it. Raising instead forces the caller to notice
    before that happens."""


def safe_basename(filename: str) -> str:
    """Reduce an arbitrary client-supplied name to a bare filename.

    PurePath handles the separator cases; the leading-dot guard is what stops
    '../..' from surviving as a name that still means 'parent directory'.
    Null bytes are stripped too - the OS write call rejects them outright, so
    passing one through would surface as a raw, unhandled crash rather than a
    controlled outcome; it is not a traversal, just an ungraceful failure."""
    cleaned = filename.replace("\\", "/").replace("\x00", "")
    name = Path(cleaned).name.strip()
    if not name or set(name) <= {"."}:
        return "upload"
    return name


def _empty_manifest() -> dict:
    return {"next_id": 1, "entries": {}}


def read_manifest() -> dict:
    """Returns {"next_id": int, "entries": {contract_id: {...}}}.

    A missing manifest file means nothing has been uploaded yet, and returns
    the empty default shape. A manifest that exists but fails to parse means
    something is corrupt - raises ManifestError rather than silently
    discarding whatever was recorded (see ManifestError's docstring)."""
    if not config.UPLOAD_MANIFEST_PATH.exists():
        return _empty_manifest()
    try:
        raw = config.UPLOAD_MANIFEST_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(
            f"Could not read manifest at {config.UPLOAD_MANIFEST_PATH}: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"Manifest at {config.UPLOAD_MANIFEST_PATH} is corrupt and could "
            f"not be parsed as JSON: {exc}"
        ) from exc
    if not isinstance(data, dict) or "entries" not in data or "next_id" not in data:
        raise ManifestError(
            f"Manifest at {config.UPLOAD_MANIFEST_PATH} does not have the "
            f"expected {{'next_id', 'entries'}} shape."
        )
    return data


def write_manifest(manifest: dict) -> None:
    """Write the manifest atomically.

    The new content is built in a temp file in the same directory, then
    moved onto the target with os.replace(). Same-directory rename is atomic
    on POSIX, so a crash mid-write leaves either the old manifest or the new
    one fully written on disk - never a half-written, truncated file that
    read_manifest would have to reject."""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=config.UPLOAD_DIR, prefix=".manifest-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
        os.replace(tmp_name, config.UPLOAD_MANIFEST_PATH)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def next_contract_id(manifest: dict) -> str:
    """Allocate the next contract id and advance manifest["next_id"] in place.

    The counter only ever increases - it is never recomputed from the entries
    currently present - so removing the highest-numbered upload does not free
    its id to be reissued to a different document."""
    next_id = manifest.get("next_id", 1)
    manifest["next_id"] = next_id + 1
    return f"U-{next_id:04d}"


def unique_path(basename: str) -> Path:
    """Pick a free name under UPLOAD_DIR, suffixing -2, -3, ... rather than
    overwriting: two contracts genuinely can share a filename, and silently
    replacing one would lose a user's document.

    The suffix is transient. api_upload renames the file to <contract_id>.txt
    as soon as store() returns - config.document_path() resolves documents by
    id - so no -2 file survives past the end of the request. What the suffix
    actually does is stop the second upload from clobbering the first in the
    window before that rename; both documents are then kept under their own
    contract ids."""
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

    Raises UploadTooLarge, document_loader.UnsupportedDocument, or
    ManifestError (if the existing manifest is corrupt)."""
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

    manifest["entries"][contract_id] = {
        "contract_id": contract_id,
        "original_filename": basename,
        "stored_filename": path.name,
    }
    write_manifest(manifest)
    return contract_id, path, text


def update_entry(contract_id: str, changes: dict) -> bool:
    """Merge `changes` into one manifest entry and write it back.

    Reads the manifest immediately before writing - not once, cached, and
    reused across a long operation - so a change some other request made to a
    DIFFERENT entry in between (e.g. a Remove while this contract_id's
    extraction was still running) is preserved rather than clobbered by a
    stale snapshot. This is the fix for the resurrection bug: api_upload used
    to read the manifest once before a 60-75s extraction call and write that
    same dict back afterwards, silently reverting every manifest change made
    while it ran (including removals: unlinked files and deleted DB rows
    stayed gone, but the manifest entry came back, and the next reseed would
    have recreated a contracts row for it).

    Returns False, writing nothing, if `contract_id` is no longer present in
    the manifest - which happens when the user removes the very upload this
    call is trying to update while it is still being processed. Re-adding
    the entry in that case would be the identical bug in a different
    costume: silently overriding an explicit removal because this call
    started before it. Callers must treat a False return as "this upload no
    longer exists, stop processing it" rather than force the entry back."""
    manifest = read_manifest()
    entry = manifest["entries"].get(contract_id)
    if entry is None:
        return False
    entry.update(changes)
    write_manifest(manifest)
    return True


def remove(contract_id: str) -> bool:
    """Delete an upload's file and manifest entry. Returns False for an
    unknown id rather than raising, so callers can treat it as a no-op."""
    manifest = read_manifest()
    entry = manifest["entries"].pop(contract_id, None)
    if entry is None:
        return False
    # .get, not [...]: a hand-edited or partially-written entry missing this
    # key should still be removable from the manifest rather than crashing.
    stored_filename = entry.get("stored_filename")
    if stored_filename:
        (config.UPLOAD_DIR / stored_filename).unlink(missing_ok=True)
    write_manifest(manifest)
    return True
