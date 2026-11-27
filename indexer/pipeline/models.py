"""The shapes passed between stages. Metadata fields are required (A02 section 3.1, A03 Part A)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    """Text of one page, as extraction produced it."""

    source: str              # file name, e.g. academic-rules-handbook-jun-2026.pdf
    page: int                # 1-based
    text: str
    ocr: bool = False        # True when this page had no text layer and was OCR'd


@dataclass
class Document:
    source: str
    doc_version: str         # e.g. "2026-06"; from the batch _index.json sidecar
    superseded: bool         # True for an older (archived) version of a document
    pages: list[Page] = field(default_factory=list)
    doc_id: str = ""         # stable family id shared by all versions of one document
    title: str = ""


@dataclass
class Chunk:
    id: str                  # content-addressed: same doc_id + version + page + text -> same id
    text: str
    source: str
    section: str             # the heading this chunk sits under, e.g. "5.4 Academic Warning"
    page: int
    doc_version: str
    superseded: bool
    doc_id: str = ""
    title: str = ""

    def metadata(self) -> dict[str, str | int | bool]:
        """Chroma metadata values must be str, int, float or bool."""
        return {
            "source": self.source,
            "section": self.section,
            "page": self.page,
            "doc_version": self.doc_version,
            "superseded": self.superseded,
            "doc_id": self.doc_id or self.source,
            "title": self.title,
            "status": "archived" if self.superseded else "active",
        }
