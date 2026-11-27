"""A03 Part A: verification checks and incremental sync planning (no network, no Chroma)."""

from __future__ import annotations

from pipeline.models import Chunk, Document, Page
from pipeline.store import plan_sync
from pipeline.verify import (check_completeness, check_quality, check_recency,
                             check_uniqueness, version_key)


def _doc(text: str, pages: int = 1) -> Document:
    return Document(source="x.md", doc_version="2026", superseded=False,
                    pages=[Page(source="x.md", page=i + 1, text=text) for i in range(pages)])


def test_quality_fails_empty_garbled_and_errors() -> None:
    assert not check_quality(None, "ExtractionError: bad xref", 200, 0.85, 0.5).passed
    assert not check_quality(_doc("tiny"), None, 200, 0.85, 0.5).passed
    garbled = "Ã¢â‚¬Å“ÃƒÂ©Ã¢â‚¬â„¢ �� ÐŸÑ€Ð¸Ð²ÐµÑ‚ " * 40
    assert "garbled" in check_quality(_doc(garbled), None, 200, 0.85, 0.5).reason
    assert check_quality(_doc("Students must attend classes regularly. " * 20), None, 200, 0.85, 0.5).passed


def test_completeness_needs_metadata_and_untruncated_pdf() -> None:
    doc = _doc("text " * 100)
    ok = check_completeness(doc, "a.md", b"text", {"source": "own", "title": "T", "doc_version": "1"})
    assert ok.passed
    missing = check_completeness(doc, "a.md", b"text", {})
    assert not missing.passed and "title" in missing.reason and "date or version" in missing.reason
    cut = check_completeness(doc, "a.pdf", b"%PDF-1.4 ... no trailer", {"source": "s", "title": "t", "date": "d"})
    assert not cut.passed and "truncated" in cut.reason


def test_recency_and_version_order() -> None:
    assert version_key("2027-28") > version_key("2026-27")
    assert not check_recency("fee", "2026-27", ["2027-28"], None).passed
    assert check_recency("fee", "2027-28", ["2026-27"], None).passed
    # a restore pins the old version: the newer one is held back
    assert not check_recency("fee", "2027-28", ["2026-27"], "2026-27").passed


def test_uniqueness_exact_and_near_duplicate() -> None:
    known = [{"doc_id": "a", "version": "1", "sha256": "abc", "text_sha": "t1",
              "doc_vec": [1.0, 0.0], "file": "batch_a/a.pdf"}]
    exact, _ = check_uniqueness("abc", "zz", "b", [0.0, 1.0], known, 0.98)
    assert not exact.passed and "exact duplicate" in exact.reason
    near, s = check_uniqueness("def", "zz", "b", [0.999, 0.01], known, 0.98)
    assert not near.passed and s > 0.98
    same_family, _ = check_uniqueness("def", "zz", "a", [0.999, 0.01], known, 0.98)
    assert same_family.passed   # a new version of the same doc is expected to be similar


def _c(cid: str, doc: str = "d", ver: str = "1", sup: bool = False) -> Chunk:
    return Chunk(id=cid, text=cid, source="s", section="", page=1, doc_version=ver,
                 superseded=sup, doc_id=doc)


def test_plan_sync_is_incremental() -> None:
    existing = {"a": _c("a").metadata(), "b": _c("b").metadata(), "z": _c("z", doc="gone").metadata()}
    plan = plan_sync({("d", "1"): [_c("a"), _c("b")]}, existing)
    assert plan["to_add"] == [] and plan["unchanged"] == 2      # unchanged corpus: 0 to embed
    assert plan["orphans"] == ["z"]                              # deleted document: removed
    plan = plan_sync({("d", "1"): [_c("a"), _c("c")]}, existing)
    assert [c.id for c in plan["to_add"]] == ["c"] and plan["to_delete"] == ["b"]
    plan = plan_sync({("d", "1"): [_c("a", sup=True), _c("b", sup=True)]}, existing)
    assert len(plan["to_flip"]) == 2 and plan["to_add"] == []    # archive = metadata only
