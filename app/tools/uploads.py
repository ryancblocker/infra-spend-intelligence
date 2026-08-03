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
