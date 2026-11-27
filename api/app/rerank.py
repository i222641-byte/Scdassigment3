"""Query rewrite and a light lexical reranker (A03 D1 asks the trace to record both).

Rewrite: expands a few campus abbreviations the corpus spells out, and detects a
*version intent* ("2023 rules", "previous policy") that lifts the superseded filter.

Rerank: embeddings blur exact terms (clause numbers, fees, CGPA values: A02 failure mode 7),
so the candidate pool is re-ordered by 0.85 * cosine + 0.15 * term overlap, where tokens that
contain a digit count double.
"""

from __future__ import annotations

import re

from .schemas import Passage

_ABBREV = [
    (re.compile(r"\bHoD\b"), "Head of Department (HoD)"),
    (re.compile(r"\bFYP\b"), "Final Year Project (FYP)"),
    (re.compile(r"\bCSO\b"), "Career Services Office (CSO)"),
]
_VERSION_INTENT = re.compile(
    r"\b(previous|older|old|earlier|former|archived|superseded|before 20\d\d|20(0\d|1\d|2[0-5]))\b",
    re.I)
_STOP = set("""a an the of to in on for and or is are was were be by with at from as what which who
whom how when where why can could do does did i my me we our you your it its this that these those
there their they them about into than then so if not no yes any all per under over fast nuces
university student students""".split())


def rewrite(question: str) -> tuple[str, bool]:
    q = re.sub(r"\s+", " ", question).strip()
    for rx, full in _ABBREV:
        if rx.search(q) and full not in q:
            q = rx.sub(full, q, count=1)
    return q, bool(_VERSION_INTENT.search(question))


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9.,%/-]*", text.lower())
            if t not in _STOP and (len(t) > 2 or any(c.isdigit() for c in t))]


def lexical_overlap(query: str, text: str) -> float:
    q = set(t.strip(".,") for t in _tokens(query))
    if not q:
        return 0.0
    d = set(t.strip(".,") for t in _tokens(text))
    weight = {t: (2.0 if any(c.isdigit() for c in t) else 1.0) for t in q}
    return sum(w for t, w in weight.items() if t in d) / sum(weight.values())


def rerank(query: str, passages: list[Passage], mode: str = "lexical") -> tuple[list[Passage], list[float]]:
    if mode == "none" or not passages:
        return passages, [round(p.score, 4) for p in passages]
    scored = [(0.85 * p.score + 0.15 * lexical_overlap(query, p.section + " " + p.text), p)
              for p in passages]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored], [round(s, 4) for s, _ in scored]
