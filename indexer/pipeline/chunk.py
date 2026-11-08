"""Stage 3: Chunk. Structure-aware, with overlap."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from .models import Chunk, Document, Page

# ---------------------------------------------------------------------------
# Heading-detection pattern
# ---------------------------------------------------------------------------
# Matches lines like:
#   "5.4 Academic Warning"
#   "CHAPTER 1"
#   "Introduction"  (single word, all-caps, >= 4 chars)
#   "1. Overview"
#   "## Section"  (Markdown headings)

_HEADING_RE = re.compile(
    r"""
    ^(?:
        \#{1,6}\s+.+               # Markdown heading
        | (?:\d+\.)+\d*\s+\S.*     # Numbered  e.g. "5.4 Title"
        | \d+\.\s+\S.*             # Numbered  e.g. "1. Title"
        | [A-Z][A-Z\s\-]{3,}$     # ALL-CAPS line (min 4 chars)
        | CHAPTER\s+\d+.*          # CHAPTER N ...
        | APPENDIX\s+\S.*          # APPENDIX A ...
        | SECTION\s+\d+.*          # SECTION 3 ...
        | PART\s+[IVXLC\d]+.*     # PART II ...
    )$
    """,
    re.VERBOSE | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Token-count approximation
# ---------------------------------------------------------------------------

def _word_count(text: str) -> int:
    """Approximate token count with word count (fast, good enough)."""
    return len(text.split())


# ---------------------------------------------------------------------------
# Stable chunk ID
# ---------------------------------------------------------------------------

def _chunk_id(source: str, page: int, position: int) -> str:
    key = f"{source}::{page}::{position}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk
    under *size* tokens, with *overlap* tokens shared between neighbours.

    Every chunk retains the section heading it sits under, its page number,
    doc_version, and superseded flag.
    """
    all_chunks: list[Chunk] = []
    position = 0  # global position counter across the whole document

    for page in doc.pages:
        sections = _split_into_sections(page.text)
        for heading, body in sections:
            paragraphs = _split_paragraphs(body)
            # Flatten paragraphs into token-sized units
            units = _split_to_size(paragraphs, size)
            # Apply overlap and emit chunks
            page_chunks = _apply_overlap(
                units=units,
                heading=heading,
                page=page.page,
                doc=doc,
                size=size,
                overlap=overlap,
                start_position=position,
            )
            for c in page_chunks:
                all_chunks.append(c)
            position += len(page_chunks)

    return all_chunks


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split *text* into (heading, body) pairs.

    If there are no headings the whole text is one section with heading "".
    """
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []

    for line in lines:
        if _HEADING_RE.match(line.rstrip()):
            # Save whatever we accumulated before this heading
            body = "\n".join(current_body).strip()
            if body or current_heading:
                sections.append((current_heading, body))
            current_heading = line.strip()
            current_body = []
        else:
            current_body.append(line)

    # Flush the last section
    body = "\n".join(current_body).strip()
    if body or current_heading:
        sections.append((current_heading, body))

    # Always return at least one entry
    if not sections:
        sections = [("", text)]

    return sections


# ---------------------------------------------------------------------------
# Paragraph and sentence splitting
# ---------------------------------------------------------------------------

def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; return non-empty paragraphs."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Naïve sentence splitter on sentence-ending punctuation."""
    parts = _SENTENCE_END_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _split_to_size(paragraphs: list[str], size: int) -> list[str]:
    """Break paragraphs that exceed *size* tokens down to sentence level.

    Returns a flat list of text units, each fitting within *size* tokens
    (best-effort — a single very long sentence won't be split further).
    """
    units: list[str] = []
    for para in paragraphs:
        if _word_count(para) <= size:
            units.append(para)
        else:
            # Try sentence-level splitting
            sentences = _split_sentences(para)
            current: list[str] = []
            current_wc = 0
            for sent in sentences:
                swc = _word_count(sent)
                if current_wc + swc > size and current:
                    units.append(" ".join(current))
                    current = [sent]
                    current_wc = swc
                else:
                    current.append(sent)
                    current_wc += swc
            if current:
                units.append(" ".join(current))
    return units


# ---------------------------------------------------------------------------
# Overlap application
# ---------------------------------------------------------------------------

def _apply_overlap(
    units: list[str],
    heading: str,
    page: int,
    doc: Document,
    size: int,
    overlap: int,
    start_position: int,
) -> list[Chunk]:
    """Combine units into Chunk objects, prepending overlap from the previous
    chunk's tail to the start of each new chunk.
    """
    if not units:
        return []

    chunks: list[Chunk] = []
    overlap_tail = ""  # trailing words from the previous chunk

    for idx, unit in enumerate(units):
        # Prepend overlap text from the previous chunk
        if overlap_tail:
            text = overlap_tail + "\n" + unit
        else:
            text = unit

        # If combining with overlap pushes us over size, trim the overlap
        if _word_count(text) > size + overlap:
            words = text.split()
            text = " ".join(words[:size])

        chunk_id = _chunk_id(doc.source, page, start_position + idx)
        chunks.append(
            Chunk(
                id=chunk_id,
                text=text.strip(),
                source=doc.source,
                section=heading,
                page=page,
                doc_version=doc.doc_version,
                superseded=doc.superseded,
            )
        )

        # Compute the overlap tail for the next chunk
        if overlap > 0:
            words = unit.split()
            tail_words = words[-overlap:] if len(words) > overlap else words
            overlap_tail = " ".join(tail_words)
        else:
            overlap_tail = ""

    return chunks
