#!/usr/bin/env python3
"""
Purpose: Build docs/demo-assets/sample-contract.pdf from sample-contract.txt.

Hand-rolled, dependency-free PDF writer (stdlib only) rather than piping
through a text-to-PDF tool (cupsfilter, pandoc+pdflatex, etc.): those wrap
lines wherever they feel like it, including mid-word and mid-phrase, which
silently breaks the offline extraction regexes this file exists to
demonstrate (e.g. "at least 45 days" split across a line break no longer
matches `at least (\\d+) days`). Here, line breaks are exactly the ones in
the source .txt - nothing is re-wrapped - so whatever the offline extractor
reads from the .txt, it reads identically from the generated PDF.

Re-run after editing sample-contract.txt:
    python3 docs/demo-assets/make_sample_contract_pdf.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "sample-contract.txt"
OUT = HERE / "sample-contract.pdf"

FONT_SIZE = 9
LEADING = 13  # vertical spacing between lines, in points
PAGE_WIDTH, PAGE_HEIGHT = 850, 792  # wide-letter, so long contract lines don't need re-wrapping
MARGIN_LEFT, MARGIN_TOP = 40, 40
LINES_PER_PAGE = int((PAGE_HEIGHT - 2 * MARGIN_TOP) / LEADING)


def _pdf_escape(text: str) -> str:
    """Escape the three characters that are special inside a PDF string
    literal - anything else, including this document's own Unicode
    right-single-quote apostrophes, is passed through as-is (WinAnsiEncoding
    covers them)."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _lines(raw: str) -> list[str]:
    """The source .txt's own line breaks, verbatim - including blank lines
    between paragraphs. Every content line here is already a single
    unwrapped clause (see the .txt itself), and the three header lines
    (CONTRACT ID / VENDOR / CATEGORY) rely on staying on separate PDF lines
    - merging any of these onto a shared line is exactly the bug this
    generator exists to avoid. So: no merging, no re-wrapping, one .txt
    line in equals one PDF line out."""
    return raw.rstrip("\n").split("\n")


def _paginate(lines: list[str]) -> list[list[str]]:
    """A new page once a page is full. Never splits mid-paragraph in
    practice, since this document's paragraphs are short enough to each
    fit within one page - but if a future edit changes that, a spillover
    paragraph would restart cleanly at the top of the next page rather
    than mid-sentence, because pagination only ever breaks on a blank
    line (paragraph boundary), never inside one."""
    pages: list[list[str]] = [[]]
    for line in lines:
        if not line and len(pages[-1]) >= LINES_PER_PAGE:
            continue  # don't open a page with nothing but a separator
        if len(pages[-1]) >= LINES_PER_PAGE and (not pages[-1] or pages[-1][-1] == ""):
            pages.append([])
        pages[-1].append(line)
    return pages


def _content_stream(lines: list[str]) -> bytes:
    y = PAGE_HEIGHT - MARGIN_TOP
    parts = [f"BT /F1 {FONT_SIZE} Tf {LEADING} TL {MARGIN_LEFT} {y} Td"]
    first = True
    for line in lines:
        if not first:
            parts.append("T*")
        first = False
        parts.append(f"({_pdf_escape(line)}) Tj")
    parts.append("ET")
    return ("\n".join(parts)).encode("latin-1", errors="replace")


def build_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)  # 1-indexed object number

    font_num = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    page_nums = []
    content_nums = []
    for lines in pages:
        stream = _content_stream(lines)
        content_nums.append(add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"))

    # Reserve the /Pages object number now: it's referenced as /Parent by
    # each page object added in the loop below, but can't itself be added
    # until after them - the loop adds exactly len(content_nums) objects
    # before we get there.
    pages_placeholder_num = len(objects) + len(content_nums) + 1
    for content_num in content_nums:
        page_nums.append(add(
            f"<< /Type /Page /Parent {pages_placeholder_num} 0 R "
            f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>".encode()
        ))

    kids = " ".join(f"{n} 0 R" for n in page_nums)
    pages_num = add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>".encode())
    assert pages_num == pages_placeholder_num, "page /Parent refs would point at the wrong object"

    catalog_num = add(f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode())

    out = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(sum(len(o) for o in out))
        out.append(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")

    xref_offset = sum(len(o) for o in out)
    out.append(f"xref\n0 {len(objects) + 1}\n".encode())
    out.append(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.append(f"{off:010d} 00000 n \n".encode())
    out.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF".encode()
    )
    return b"".join(out)


def main() -> None:
    raw = SRC.read_text(encoding="utf-8")
    pages = _paginate(_lines(raw))
    OUT.write_bytes(build_pdf(pages))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(pages)} page(s))")


if __name__ == "__main__":
    main()
