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

# A03 fix: this used to be compiled with re.IGNORECASE, which made the "ALL-CAPS line"
# branch match ANY word line ("Withdrawn", "Excellent"): every cell of an HTML table became
# its own section and its own 1-word chunk. Case-insensitivity now applies only to the
# keyword branches.
_HEADING_RE = re.compile(
    r"""
    ^(?:
        \#{1,6}\s+.+               # Markdown heading
        | (?:\d+\.)+\d*\s+\S.*     # Numbered  e.g. "5.4 Title"
        | \d+\.\s+\S.*             # Numbered  e.g. "1. Title"
        | [A-Z][A-Z\s\-]{3,}$     # ALL-CAPS line (min 4 chars), case-sensitive
        | (?i:CHAPTER)\s+\d+.*          # CHAPTER N ...
        | (?i:APPENDIX)\s+\S.*          # APPENDIX A ...
        | (?i:SECTION)\s+\d+.*          # SECTION 3 ...
        | (?i:PART)\s+[IVXLC\d]+.*     # PART II ...
    )$
    """,
    re.VERBOSE,
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

def _chunk_id(doc_key: str, version: str, page: int, text: str, seen: dict[str, int]) -> str:
    """Content-addressed id (A03 A2): the same text on the same page of the same document
    version always gets the same id, so an unchanged document produces zero new ids and an
    edited paragraph changes only the ids of the chunks that contain it. `seen` disambiguates
    identical texts on one page (e.g. a repeated table row)."""
    base = hashlib.sha256(f"{doc_key}|{version}|{page}|{text}".encode()).hexdigest()[:20]
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f"{base}-{n}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk
    under *size* tokens, with *overlap* tokens shared between neighbours.

    Every chunk retains the section heading it sits under, its page number,
    doc_version, and superseded flag.
    """
    # A03 fix: the A02 version emitted one chunk per paragraph and never packed small units
    # together, so CHUNK_SIZE had almost no effect (median chunk 21 words on the handbook,
    # 2 words on the HTML pages). Units are now packed greedily, across section boundaries
    # within a page, up to `size` words; headings stay in the text, and the chunk's section
    # metadata is the heading it starts under.
    all_chunks: list[Chunk] = []
    seen: dict[str, int] = {}

    for page in doc.pages:
        tagged: list[tuple[str, str]] = []          # (heading, unit text)
        for heading, body in _split_into_sections(page.text):
            units = []
            for u in _split_to_size(_split_paragraphs(body), size):
                w = u.split()
                # last resort: a sentence longer than `size` (tables, unpunctuated OCR text)
                units.extend([" ".join(w[i:i + size]) for i in range(0, len(w), size)]
                             if len(w) > size else [u])
            if heading:
                units = [heading + "\n" + units[0]] + units[1:] if units else [heading]
            tagged.extend((heading, u) for u in units)
        all_chunks.extend(_pack(tagged, page.page, doc, size, overlap, seen))

    return all_chunks


def _pack(tagged: list[tuple[str, str]], page: int, doc: Document, size: int, overlap: int,
          seen: dict[str, int]) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_heading = ""
    tail = ""

    def flush() -> None:
        nonlocal buf, tail
        if not buf:
            return
        body = "\n".join(buf)
        text = (tail + "\n" + body).strip() if tail else body.strip()
        cid = _chunk_id(doc.doc_id or doc.source, doc.doc_version, page, text, seen)
        chunks.append(Chunk(id=cid, text=text, source=doc.source, section=buf_heading,
                            page=page, doc_version=doc.doc_version, superseded=doc.superseded,
                            doc_id=doc.doc_id or doc.source, title=doc.title))
        words = body.split()
        tail = " ".join(words[-overlap:]) if overlap > 0 else ""
        buf = []

    current_heading = ""
    for heading, unit in tagged:
        current_heading = heading or current_heading
        if buf and _word_count("\n".join(buf)) + _word_count(unit) > size:
            flush()
        if not buf:
            buf_heading = current_heading
        buf.append(unit)
    flush()
    return chunks


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
    seen: dict[str, int] | None = None,
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

        text = text.strip()
        chunk_id = _chunk_id(doc.doc_id or doc.source, doc.doc_version, page, text,
                             seen if seen is not None else {})
        chunks.append(
            Chunk(
                id=chunk_id,
                text=text,
                source=doc.source,
                section=heading,
                page=page,
                doc_version=doc.doc_version,
                superseded=doc.superseded,
                doc_id=doc.doc_id or doc.source,
                title=doc.title,
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
