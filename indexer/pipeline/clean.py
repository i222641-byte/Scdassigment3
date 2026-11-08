"""Stage 2: Clean. Remove artefacts without destroying structure."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace

from .models import Document, Page

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean(doc: Document) -> Document:
    """Strip headers and footers that repeat on every page; keep headings and
    section boundaries, because chunking and citations depend on them.

    Rules applied (in order):
    1. Detect repeated leading lines across pages (page headers) and drop them.
    2. Detect repeated trailing lines across pages (page footers) and drop them.
    3. Remove standalone page-number lines (bare digits or "Page N of M" / "- N -").
    4. Collapse runs of blank lines to at most two consecutive newlines.
    5. Strip leading/trailing whitespace from each page.
    """
    if not doc.pages:
        return doc

    # Only run header/footer detection when there are enough pages to compare
    header_lines: set[str] = _repeated_leading_lines(doc.pages) if len(doc.pages) > 2 else set()
    footer_lines: set[str] = _repeated_trailing_lines(doc.pages) if len(doc.pages) > 2 else set()

    cleaned: list[Page] = []
    for page in doc.pages:
        text = _remove_repeated_lines(page.text, header_lines, footer_lines)
        text = _remove_page_numbers(text)
        text = _normalise_whitespace(text)
        cleaned.append(replace(page, text=text))

    return replace(doc, pages=cleaned)


# ---------------------------------------------------------------------------
# Header / footer detection
# ---------------------------------------------------------------------------

def _page_lines(text: str) -> list[str]:
    """Return non-empty stripped lines from *text*."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _repeated_leading_lines(pages: list[Page]) -> set[str]:
    """Return lines that appear as the first line on the majority of pages.

    A line is considered a header if it appears in the same position on
    at least 60 % of pages (minimum 3 pages).
    """
    threshold = max(3, int(len(pages) * 0.6))
    counter: Counter[str] = Counter()
    for page in pages:
        lines = _page_lines(page.text)
        if lines:
            counter[lines[0]] += 1
    return {line for line, count in counter.items() if count >= threshold}


def _repeated_trailing_lines(pages: list[Page]) -> set[str]:
    """Return lines that appear as the last line on the majority of pages."""
    threshold = max(3, int(len(pages) * 0.6))
    counter: Counter[str] = Counter()
    for page in pages:
        lines = _page_lines(page.text)
        if lines:
            counter[lines[-1]] += 1
    return {line for line, count in counter.items() if count >= threshold}


def _remove_repeated_lines(text: str, headers: set[str], footers: set[str]) -> str:
    """Strip header / footer lines from the beginning and end of *text*."""
    if not headers and not footers:
        return text

    lines = text.splitlines()

    # Drop leading header lines
    while lines and lines[0].strip() in headers:
        lines = lines[1:]

    # Drop trailing footer lines
    while lines and lines[-1].strip() in footers:
        lines = lines[:-1]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Page-number removal
# ---------------------------------------------------------------------------

_PAGE_NUMBER_RE = re.compile(
    r"""
    ^\s*                            # optional leading whitespace
    (?:
        [—\-–]\s*\d+\s*[—\-–]      # — 12 —  or  - 12 -
        | Page\s+\d+\s*(?:of\s+\d+)?  # Page 3  or  Page 3 of 42
        | \d+\s*/\s*\d+             # 3/42
        | \d+                       # bare number on its own line
    )
    \s*$                            # optional trailing whitespace
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _remove_page_numbers(text: str) -> str:
    """Remove lines that look like standalone page numbers."""
    cleaned = [ln for ln in text.splitlines() if not _PAGE_NUMBER_RE.match(ln)]
    return "\n".join(cleaned)


# ---------------------------------------------------------------------------
# Whitespace normalisation
# ---------------------------------------------------------------------------

def _normalise_whitespace(text: str) -> str:
    """Collapse runs of blank lines; strip the whole block."""
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove trailing spaces on each line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text.strip()
