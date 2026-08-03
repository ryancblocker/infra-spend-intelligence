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


class UnsupportedFileType(UnsupportedDocument):
    """Raised specifically when the file extension is not in the allow-list.

    A distinct subclass rather than relying on callers pattern-matching the
    reason string: main.py needs to pick 415 vs 422, and substring-matching
    "Unsupported file type" against exc.reason coupled that HTTP decision to
    this module's exact wording - rewording the message here would silently
    flip which status code a caller returns, with no test catching it."""


def load_document(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in config.ALLOWED_UPLOAD_SUFFIXES:
        permitted = ", ".join(config.ALLOWED_UPLOAD_SUFFIXES)
        raise UnsupportedFileType(f"Unsupported file type '{suffix or filename}'. Permitted types: {permitted}.")
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
