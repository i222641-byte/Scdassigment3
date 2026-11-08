"""Tests for the indexer pipeline stages.

These use in-memory fakes so no Ollama, ChromaDB or real PDFs are needed.
"""

from __future__ import annotations

import hashlib
import math
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# extract stage
# ---------------------------------------------------------------------------

def test_extract_markdown_returns_document_with_pages(tmp_path: Path) -> None:
    md = tmp_path / "rules.md"
    md.write_text("# Section 1\n\nSome text here.\n\n## Section 2\n\nMore text.", encoding="utf-8")
    from pipeline.extract import extract

    doc = extract(str(md), "2026", False)
    assert doc.source == "rules.md"
    assert doc.doc_version == "2026"
    assert doc.superseded is False
    assert len(doc.pages) >= 1
    full_text = "\n".join(p.text for p in doc.pages)
    assert "Section 1" in full_text
    assert "Some text" in full_text


def test_extract_text_file_returns_document(tmp_path: Path) -> None:
    txt = tmp_path / "policy.txt"
    txt.write_text("This is a plain text policy document.", encoding="utf-8")
    from pipeline.extract import extract

    doc = extract(str(txt), "2025", True)
    assert doc.superseded is True
    assert len(doc.pages) == 1
    assert "plain text policy" in doc.pages[0].text


def test_extract_html_strips_tags(tmp_path: Path) -> None:
    html = tmp_path / "fees.html"
    html.write_text(
        "<html><body><h1>Fee Structure</h1><p>Credit hour: <b>10,000</b> PKR</p></body></html>",
        encoding="utf-8",
    )
    from pipeline.extract import extract

    doc = extract(str(html), "2026", False)
    text = doc.pages[0].text
    assert "Fee Structure" in text
    assert "10,000" in text
    # HTML tags should be stripped
    assert "<" not in text


def test_extract_preserves_superseded_flag(tmp_path: Path) -> None:
    md = tmp_path / "old.md"
    md.write_text("Old rules here.", encoding="utf-8")
    from pipeline.extract import extract

    doc_old = extract(str(md), "2023", True)
    doc_new = extract(str(md), "2026", False)
    assert doc_old.superseded is True
    assert doc_new.superseded is False


# ---------------------------------------------------------------------------
# clean stage
# ---------------------------------------------------------------------------

def test_clean_removes_leading_trailing_whitespace(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text("# Heading\n\nContent.\n", encoding="utf-8")
    from pipeline.extract import extract
    from pipeline.clean import clean

    doc = extract(str(md), "2026", False)
    cleaned = clean(doc)
    for page in cleaned.pages:
        assert page.text == page.text.strip()


def test_clean_preserves_section_headings(tmp_path: Path) -> None:
    md = tmp_path / "rules.md"
    md.write_text(
        "# 1. Attendance\n\nStudents must attend 80% of classes.\n\n# 2. Grading\n\nA = 4.0\n",
        encoding="utf-8",
    )
    from pipeline.extract import extract
    from pipeline.clean import clean

    doc = extract(str(md), "2026", False)
    cleaned = clean(doc)
    full_text = "\n".join(p.text for p in cleaned.pages)
    assert "Attendance" in full_text
    assert "Grading" in full_text


def test_clean_returns_document_with_same_metadata(tmp_path: Path) -> None:
    md = tmp_path / "rules.md"
    md.write_text("Some content.", encoding="utf-8")
    from pipeline.extract import extract
    from pipeline.clean import clean

    doc = extract(str(md), "2026", True)
    cleaned = clean(doc)
    assert cleaned.source == doc.source
    assert cleaned.doc_version == doc.doc_version
    assert cleaned.superseded == doc.superseded


# ---------------------------------------------------------------------------
# chunk stage
# ---------------------------------------------------------------------------

def test_chunk_produces_chunks_with_required_metadata(tmp_path: Path) -> None:
    md = tmp_path / "rules.md"
    md.write_text(
        "# 1. Attendance\n\nStudents must attend 80% of lectures to sit the final exam. "
        "Attendance is tracked every session.\n\n"
        "# 2. CGPA\n\nMinimum CGPA of 2.00 to avoid academic warning.\n",
        encoding="utf-8",
    )
    from pipeline.extract import extract
    from pipeline.clean import clean
    from pipeline.chunk import chunk

    doc = clean(extract(str(md), "2026", False))
    chunks = chunk(doc, size=100, overlap=20)
    assert len(chunks) > 0
    for c in chunks:
        assert c.source == "rules.md"
        assert c.doc_version == "2026"
        assert c.superseded is False
        assert c.section  # must not be empty
        assert c.page >= 1
        assert c.id  # stable ID
        assert len(c.text) > 0


def test_chunk_ids_are_stable(tmp_path: Path) -> None:
    md = tmp_path / "rules.md"
    md.write_text("# Section\n\nSome text.\n", encoding="utf-8")
    from pipeline.extract import extract
    from pipeline.clean import clean
    from pipeline.chunk import chunk

    doc = clean(extract(str(md), "2026", False))
    chunks1 = chunk(doc, size=100, overlap=20)
    chunks2 = chunk(doc, size=100, overlap=20)
    ids1 = [c.id for c in chunks1]
    ids2 = [c.id for c in chunks2]
    assert ids1 == ids2


def test_chunk_respects_size_limit(tmp_path: Path) -> None:
    # Build a document with 1000 words
    content = "word " * 1000
    md = tmp_path / "large.md"
    md.write_text(f"# Big Section\n\n{content}\n", encoding="utf-8")
    from pipeline.extract import extract
    from pipeline.clean import clean
    from pipeline.chunk import chunk

    doc = clean(extract(str(md), "2026", False))
    target_size = 100
    chunks = chunk(doc, size=target_size, overlap=20)
    for c in chunks:
        word_count = len(c.text.split())
        # Allow some slack for overlap and sentence boundaries
        assert word_count <= target_size * 2, f"chunk too big: {word_count} words"


def test_chunk_metadata_matches_model_schema(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text("# 1. Rules\n\nRule text here.\n", encoding="utf-8")
    from pipeline.extract import extract
    from pipeline.clean import clean
    from pipeline.chunk import chunk

    doc = clean(extract(str(md), "2026", False))
    chunks = chunk(doc, size=100, overlap=20)
    for c in chunks:
        meta = c.metadata()
        required = {"source", "section", "page", "doc_version", "superseded"}
        assert set(meta.keys()) == required
        assert isinstance(meta["page"], int)
        assert isinstance(meta["superseded"], bool)


# ---------------------------------------------------------------------------
# store stage helpers
# ---------------------------------------------------------------------------

class FakeCollection:
    def __init__(self, name: str, metadata: dict) -> None:
        self.name = name
        self.metadata = metadata
        self.rows: dict = {}

    def add(self, ids, documents, embeddings, metadatas) -> None:
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.rows[i] = {"document": d, "embedding": e, "metadata": m}

    def count(self) -> int:
        return len(self.rows)


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def delete_collection(self, name: str) -> None:
        if name in self.collections:
            del self.collections[name]

    def create_collection(self, name: str, metadata: dict) -> FakeCollection:
        col = FakeCollection(name, metadata)
        self.collections[name] = col
        return col


def test_store_records_embed_model_in_collection_metadata(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text("# A\n\nContent.\n", encoding="utf-8")
    from pipeline.extract import extract
    from pipeline.clean import clean
    from pipeline.chunk import chunk
    from pipeline.models import Chunk

    doc = clean(extract(str(md), "2026", False))
    chunks = chunk(doc, size=50, overlap=10)

    # Use fake vectors
    vectors = [[0.1] * 10 for _ in chunks]

    from pipeline.config import IndexerSettings

    settings = IndexerSettings(
        embed_model="nomic-embed-text",
        chroma_host="localhost",
        chroma_port=8000,
        collection="test",
        corpus_dir=str(tmp_path),
        chunk_size=50,
        chunk_overlap=10,
        ollama_url="http://localhost:11434",
    )

    # Monkey-patch get_client to return FakeClient
    import pipeline.store as store_mod
    fake_client = FakeClient()
    original = store_mod.get_client
    store_mod.get_client = lambda s: fake_client
    try:
        from pipeline.store import store
        count = store(chunks, vectors, settings)
    finally:
        store_mod.get_client = original

    assert count == len(chunks)
    col = fake_client.collections["test"]
    assert col.metadata["embed_model"] == "nomic-embed-text"
    assert "dimension" in col.metadata


def test_store_includes_all_metadata_fields(tmp_path: Path) -> None:
    from pipeline.models import Chunk

    chunks = [
        Chunk(id="c001", text="Some text", source="doc.pdf", section="1. Rules",
              page=1, doc_version="2026", superseded=False),
    ]
    vectors = [[0.5] * 768]

    from pipeline.config import IndexerSettings

    settings = IndexerSettings(
        embed_model="nomic-embed-text",
        chroma_host="localhost",
        chroma_port=8000,
        collection="testcol",
        corpus_dir="/corpus",
        chunk_size=400,
        chunk_overlap=50,
        ollama_url="http://localhost:11434",
    )

    import pipeline.store as store_mod
    fake_client = FakeClient()
    store_mod.get_client = lambda s: fake_client
    try:
        from pipeline.store import store
        store(chunks, vectors, settings)
    finally:
        # Restore is not strictly needed since the test isolation handles it
        pass

    col = fake_client.collections["testcol"]
    row = col.rows["c001"]
    assert row["metadata"]["source"] == "doc.pdf"
    assert row["metadata"]["section"] == "1. Rules"
    assert row["metadata"]["page"] == 1
    assert row["metadata"]["doc_version"] == "2026"
    assert row["metadata"]["superseded"] is False
