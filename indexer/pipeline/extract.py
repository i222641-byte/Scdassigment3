"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .models import Document, Page


class ExtractionError(RuntimeError):
    """The file could not be parsed at all (corrupt, truncated, wrong format)."""


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    The OCR libraries need system packages in your Dockerfile (tesseract-ocr,
    poppler-utils), not only pip packages.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    source = p.name

    if suffix == ".pdf":
        return _extract_pdf(p, source, doc_version, superseded)
    elif suffix in (".html", ".htm"):
        return _extract_html(p, source, doc_version, superseded)
    elif suffix in (".md", ".txt"):
        return _extract_text(p, source, doc_version, superseded)
    else:
        # Best-effort: try as plain text
        return _extract_text(p, source, doc_version, superseded)


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def _ocr_pdf_page(path: Path, page_index: int) -> str:
    """Rasterise page at *page_index* (0-based) and run Tesseract on it.

    Returns the extracted text, or "" if OCR libraries are not available.
    """
    try:
        from pdf2image import convert_from_path  # type: ignore
        import pytesseract  # type: ignore

        images = convert_from_path(
            str(path),
            first_page=page_index + 1,
            last_page=page_index + 1,
            dpi=200,
        )
        if not images:
            return ""
        return pytesseract.image_to_string(images[0])
    except Exception:
        return ""


def _extract_pdf(path: Path, source: str, doc_version: str, superseded: bool) -> Document:
    """Extract text with pdfplumber; fall back to pypdf; OCR blank pages."""
    try:
        import pdfplumber  # type: ignore

        pages: list[Page] = []
        with pdfplumber.open(str(path)) as pdf:
            for i, pdf_page in enumerate(pdf.pages):
                text = (pdf_page.extract_text() or "").strip()
                ocr_used = False
                if not text:
                    # No text layer — rasterise and OCR
                    text = _ocr_pdf_page(path, i).strip()
                    ocr_used = bool(text)   # only claim OCR when it recovered something
                pages.append(Page(source=source, page=i + 1, text=text, ocr=ocr_used))
        return Document(source=source, doc_version=doc_version, superseded=superseded, pages=pages)

    except Exception as first_error:
        # pdfplumber not installed or file unreadable — try pypdf; if that fails too the
        # file is corrupt or truncated and the verification stage quarantines it.
        try:
            return _extract_pdf_pypdf(path, source, doc_version, superseded)
        except Exception as second_error:
            raise ExtractionError(
                f"pdf unreadable: pdfplumber={type(first_error).__name__}: {first_error}; "
                f"pypdf={type(second_error).__name__}: {second_error}"
            ) from second_error


def _extract_pdf_pypdf(path: Path, source: str, doc_version: str, superseded: bool) -> Document:
    """Fallback PDF extractor using pypdf (no OCR support here)."""
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(path), strict=False)
    pages: list[Page] = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        pages.append(Page(source=source, page=i + 1, text=text, ocr=False))
    return Document(source=source, doc_version=doc_version, superseded=superseded, pages=pages)


# ---------------------------------------------------------------------------
# HTML helper
# ---------------------------------------------------------------------------

def _extract_html(path: Path, source: str, doc_version: str, superseded: bool) -> Document:
    """Strip tags from HTML, preserving logical line breaks."""
    raw = path.read_text(encoding="utf-8", errors="replace")

    # Drop non-visible content blocks
    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
    # Site chrome (A03): the nu.edu.pk pages carry a ~1,500-word navigation menu in
    # <header>/<nav> and a link farm in <footer>. Left in, it dominates every chunk and
    # makes every page of the site look like a near-duplicate of every other.
    for tag in ("header", "nav", "footer"):
        raw = re.sub(rf"<{tag}[\s>].*?</{tag}>", "\n", raw, flags=re.DOTALL | re.IGNORECASE)

    # Headings → their text on its own line
    raw = re.sub(
        r"<h[1-6][^>]*>(.*?)</h[1-6]>",
        r"\n\1\n",
        raw,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Block-level tags → newline
    raw = re.sub(
        r"</?(?:p|br|div|li|tr|td|th|section|article|header|footer|main|nav|aside)[^>]*>",
        "\n",
        raw,
        flags=re.IGNORECASE,
    )

    # Remove all remaining tags
    raw = re.sub(r"<[^>]+>", "", raw)

    # Decode HTML entities and tidy up whitespace
    text = html.unescape(raw).replace("﻿", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?:[ \t]*\n){3,}", "\n\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text).strip()

    return Document(
        source=source,
        doc_version=doc_version,
        superseded=superseded,
        pages=[Page(source=source, page=1, text=text, ocr=False)],
    )


# ---------------------------------------------------------------------------
# Plain-text / Markdown helper
# ---------------------------------------------------------------------------

def _extract_text(path: Path, source: str, doc_version: str, superseded: bool) -> Document:
    """Read the file verbatim (Markdown, .txt, or unknown format)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return Document(
        source=source,
        doc_version=doc_version,
        superseded=superseded,
        pages=[Page(source=source, page=1, text=text, ocr=False)],
    )
