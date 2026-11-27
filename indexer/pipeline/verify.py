"""A03 Part A1: the verification stage. Runs after extraction and before chunking.

Every document gets pass or fail, with a reason, for four checks (paper 4.2.2):

  quality       empty, garbled or failed extraction
  completeness  required metadata present (source, title, date or version, page count)
                and the file is not truncated
  recency       a newer version of the same document (same doc_id) is known
  uniqueness    exact duplicate by SHA-256, near-duplicate by embedding similarity

Disposition (decided in run.py, recorded in the report):
  quality / completeness / uniqueness fail  -> moved to quarantine/, never indexed
  recency fail                              -> archived: indexed with superseded=true and
                                               excluded from retrieval by metadata, restorable
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import Document

CHECKS = ("quality", "completeness", "recency", "uniqueness")


@dataclass
class CheckResult:
    passed: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"result": "pass" if self.passed else "fail", "reason": self.reason}


@dataclass
class Verdict:
    file: str
    doc_id: str
    doc_version: str
    sha256: str
    checks: dict[str, CheckResult] = field(default_factory=dict)
    disposition: str = ""          # indexed | archived | quarantined | unchanged
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def hard_fail(self) -> bool:
        return any(not self.checks[c].passed for c in ("quality", "completeness", "uniqueness")
                   if c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["checks"] = {k: v.as_dict() for k, v in self.checks.items()}
        return d


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------

_NORMAL = re.compile(r"[A-Za-z0-9\s.,;:!?'\"()\[\]{}\-–—/%&@#*+=<>_|`~$₨£€•·…’‘“”°]")


def clean_ratio(text: str) -> float:
    """Share of characters that are letters, digits, whitespace or common punctuation.
    Mojibake (Ã©, â€™), replacement characters and binary noise push this down."""
    if not text:
        return 0.0
    sample = text[:50_000]
    normal = sum(1 for ch in sample if _NORMAL.match(ch))
    return normal / len(sample)


def word_ratio(text: str) -> float:
    """Share of whitespace-separated tokens that look like words (mostly letters)."""
    tokens = text.split()[:5000]
    if not tokens:
        return 0.0
    wordish = sum(1 for t in tokens if sum(c.isalpha() for c in t) >= max(1, len(t) * 0.6))
    return wordish / len(tokens)


def check_quality(doc: Document | None, error: str | None, min_chars: int,
                  min_clean_ratio: float, min_text_page_ratio: float) -> CheckResult:
    if error:
        return CheckResult(False, f"failed extraction: {error[:200]}")
    assert doc is not None
    text = "\n".join(p.text for p in doc.pages)
    chars = len(text.strip())
    if chars < min_chars:
        return CheckResult(False, f"empty extraction: {chars} characters (< {min_chars})")
    pages_with_text = sum(1 for p in doc.pages if len(p.text.strip()) >= 20)
    page_ratio = pages_with_text / max(1, len(doc.pages))
    if page_ratio < min_text_page_ratio:
        return CheckResult(False, f"extraction lost most pages: {pages_with_text}/{len(doc.pages)} "
                                  f"pages yielded text (< {min_text_page_ratio:.0%}); OCR missing or failed")
    norm = unicodedata.normalize("NFKC", text)
    cr = clean_ratio(norm)
    wr = word_ratio(norm)
    if cr < min_clean_ratio or wr < 0.5:
        return CheckResult(False, f"garbled text: clean-char ratio {cr:.2f} (min {min_clean_ratio}), "
                                  f"word-like token ratio {wr:.2f} (min 0.50)")
    ocr_pages = sum(1 for p in doc.pages if p.ocr)
    note = f", {ocr_pages} page(s) recovered by OCR" if ocr_pages else ""
    return CheckResult(True, f"{chars} chars, {pages_with_text}/{len(doc.pages)} pages with text, "
                             f"clean ratio {cr:.2f}{note}")


# ---------------------------------------------------------------------------
# completeness
# ---------------------------------------------------------------------------

REQUIRED_META = ("source", "title")


def is_truncated(path: str, raw: bytes, meta: dict[str, Any]) -> str | None:
    """Return a reason string when the file looks cut short, else None."""
    declared = meta.get("bytes")
    if isinstance(declared, int) and declared > 0 and len(raw) < declared:
        return f"file is {len(raw)} bytes but the manifest declares {declared}"
    if path.lower().endswith(".pdf"):
        tail = raw[-2048:]
        if b"%%EOF" not in tail:
            return "PDF has no %%EOF trailer (download or copy was cut short)"
    if path.lower().endswith((".md", ".txt")):
        text = raw.decode("utf-8", errors="replace").rstrip()
        if text and "<!-- end -->" not in text[-200:] and meta.get("require_end_marker"):
            return "text file is missing its end marker"
    return None


def check_completeness(doc: Document | None, path: str, raw: bytes,
                       meta: dict[str, Any]) -> CheckResult:
    missing = [k for k in REQUIRED_META if not str(meta.get(k, "")).strip()]
    if not (str(meta.get("date", "")).strip() or str(meta.get("doc_version", "")).strip()):
        missing.append("date or version")
    page_count = len(doc.pages) if doc else 0
    if page_count < 1:
        missing.append("page count")
    truncated = is_truncated(path, raw, meta)
    if missing and truncated:
        return CheckResult(False, f"missing metadata: {', '.join(missing)}; truncated: {truncated}")
    if missing:
        return CheckResult(False, f"missing metadata: {', '.join(missing)}")
    if truncated:
        return CheckResult(False, f"truncated: {truncated}")
    return CheckResult(True, f"source, title, version {meta.get('doc_version') or meta.get('date')}, "
                             f"{page_count} page(s); not truncated")


# ---------------------------------------------------------------------------
# recency
# ---------------------------------------------------------------------------

def version_key(v: str) -> tuple[int, ...]:
    """'2026-06' -> (2026, 6); '2027-28' -> (2027, 28); 'unknown' -> ()."""
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def check_recency(doc_id: str, version: str, known_versions: list[str],
                  pinned: str | None) -> CheckResult:
    """Fail when a newer version of the same doc_id is known (in the lake or this run)."""
    newer = sorted((v for v in known_versions if version_key(v) > version_key(version)),
                   key=version_key)
    if pinned and pinned != version:
        return CheckResult(False, f"version {pinned} of {doc_id} is pinned by a restore")
    if newer and not (pinned == version):
        return CheckResult(False, f"superseded: newer version {newer[-1]} of {doc_id} exists")
    older = [v for v in known_versions if version_key(v) < version_key(version)]
    if older:
        return CheckResult(True, f"newest version of {doc_id}; supersedes {', '.join(sorted(older))}")
    return CheckResult(True, f"only version of {doc_id}")


# ---------------------------------------------------------------------------
# uniqueness
# ---------------------------------------------------------------------------

def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def doc_windows(doc: Document, n: int = 6, words: int = 220) -> list[str]:
    """n evenly spaced windows of text, used for a document-level embedding."""
    tokens = " ".join(p.text for p in doc.pages).split()
    if not tokens:
        return []
    if len(tokens) <= words:
        return [" ".join(tokens)]
    starts = [round(i * (len(tokens) - words) / max(1, n - 1)) for i in range(n)]
    return [" ".join(tokens[s:s + words]) for s in sorted(set(starts))]


def mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


def check_uniqueness(sha256: str, text_sha: str, doc_id: str, doc_vec: list[float],
                     known: list[dict[str, Any]], threshold: float) -> tuple[CheckResult, float]:
    """known: [{doc_id, version, sha256, text_sha, doc_vec, file}] for every document already
    accepted into the lake or accepted earlier in this run. Versions of the same doc_id are
    expected to be similar and are not compared for near-duplication."""
    for k in known:
        if k.get("sha256") == sha256:
            return CheckResult(False, f"exact duplicate (sha256 {sha256[:12]}) of {k['file']} "
                                      f"[{k['doc_id']}@{k['version']}]"), 1.0
    for k in known:
        if k.get("text_sha") and k.get("text_sha") == text_sha and k["doc_id"] != doc_id:
            return CheckResult(False, f"exact duplicate text (normalised-text hash) of {k['file']}"), 1.0
    best, best_k = 0.0, None
    for k in known:
        if k["doc_id"] == doc_id or not k.get("doc_vec") or not doc_vec:
            continue
        s = cosine(doc_vec, k["doc_vec"])
        if s > best:
            best, best_k = s, k
    if best_k is not None and best >= threshold:
        return CheckResult(False, f"near-duplicate of {best_k['file']} [{best_k['doc_id']}]: "
                                  f"doc-embedding cosine {best:.4f} >= {threshold}"), best
    nearest = f"; nearest other document {best_k['file']} at {best:.4f}" if best_k else ""
    return CheckResult(True, f"no exact or near duplicate (threshold {threshold}){nearest}"), best
