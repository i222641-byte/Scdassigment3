#!/usr/bin/env python3
"""A03 E2/E4: do the offline tests still match real usage? (paper 4.2.7)

    python eval/coverage.py --label before            # exit 1 when coverage < --min-share
    python eval/coverage.py --label after --golden eval/golden.jsonl

For every live query (eval/live_queries.jsonl, E1) find the most similar golden question by
cosine similarity of their embeddings (the pinned EMBED_MODEL). A query is *covered* when that
similarity is >= tau.

tau (similarity threshold) is derived from data, not picked: the 10th percentile of
paraphrase-pair similarity in eval/embedding_pairs.jsonl (the module-level test). A live query
is covered only when some golden question is at least as close to it as 90% of known
paraphrase pairs are to each other, i.e. a test asks essentially the same question.
Rejected alternative (reported for comparison): the midpoint between that p10 and the
unrelated-pair p90. On our data it is ~0.50 and counted 7 of 12 off-topic queries
("transport fee", "gym charges") as covered because they share words like "fee" and
"semester" with golden questions.
--min-share (default 0.85, the paper's example) is the share of live queries that must be
covered; below it the script exits 1 so a pipeline (CronJob, CI) can fail on a coverage gap.

Uncovered queries are grouped into topics by single-link clustering of their embeddings.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
_STOP = set("""a an the of to in on for and or is are was were be by with at from as what which who how
when where why can could do does did i my me we our you your it its this that these there their they
them about into than then so if not no any all per much many get got im dont need there campus
university fast nuces student students""".split())


def load_jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def embed(ollama: str, model: str, texts: list[str]) -> list[list[float]]:
    r = httpx.post(f"{ollama.rstrip('/')}/api/embed", json={"model": model, "input": texts}, timeout=300)
    r.raise_for_status()
    return r.json()["embeddings"]


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def pct(v: list[float], q: float) -> float:
    v = sorted(v)
    k = (len(v) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f)


def derive_tau(ollama: str, model: str, pairs_path: Path) -> dict[str, float]:
    pairs = load_jsonl(pairs_path)
    para = [p for p in pairs if p["kind"] == "paraphrase"]
    unrel = [p for p in pairs if p["kind"] == "unrelated"]
    def sims(ps: list[dict[str, Any]]) -> list[float]:
        return [cos(x, y) for x, y in zip(embed(ollama, model, [p["a"] for p in ps]),
                                         embed(ollama, model, [p["b"] for p in ps]))]
    sp, su = sims(para), sims(unrel)
    p10, u90 = pct(sp, 0.10), pct(su, 0.90)
    return {"paraphrase_p10": round(p10, 4), "unrelated_p90": round(u90, 4),
            "midpoint_rejected": round((p10 + u90) / 2, 4), "tau": round(p10, 4),
            "rule": "tau = 10th percentile of paraphrase-pair cosine similarity"}


def topics(items: list[dict[str, Any]], vecs: list[list[float]], link: float) -> list[dict[str, Any]]:
    n = len(items)
    parent = list(range(n))
    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if cos(vecs[i], vecs[j]) >= link:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in sorted(groups.values(), key=len, reverse=True):
        words = Counter(w for i in members for w in re.findall(r"[a-z]+", items[i]["query"].lower())
                        if w not in _STOP and len(w) > 2)
        out.append({"topic": " / ".join(w for w, _ in words.most_common(3)) or "misc",
                    "size": len(members), "queries": [items[i]["query"] for i in members],
                    "ids": [items[i]["id"] for i in members]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", type=Path, default=HERE / "live_queries.jsonl")
    ap.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    ap.add_argument("--pairs", type=Path, default=HERE / "embedding_pairs.jsonl")
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text"))
    ap.add_argument("--threshold", type=float, default=None, help="override the derived tau")
    ap.add_argument("--min-share", type=float, default=float(os.environ.get("COVERAGE_MIN_SHARE", 0.85)))
    ap.add_argument("--topic-link", type=float, default=0.6)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out-dir", type=Path, default=Path(os.environ.get("RESULTS_DIR", HERE / "results")))
    args = ap.parse_args()

    live, golden = load_jsonl(args.live), load_jsonl(args.golden)
    t = derive_tau(args.ollama, args.embed_model, args.pairs)
    tau = args.threshold if args.threshold is not None else t["tau"]
    lv = embed(args.ollama, args.embed_model, [x["query"] for x in live])
    gv = embed(args.ollama, args.embed_model, [g["question"] for g in golden])
    rows = []
    for x, v in zip(live, lv):
        sims = [cos(v, g) for g in gv]
        j = max(range(len(sims)), key=sims.__getitem__)
        rows.append({"id": x["id"], "query": x["query"], "intended": x.get("intended"),
                     "nearest_golden": golden[j]["id"], "nearest_question": golden[j]["question"],
                     "similarity": round(sims[j], 4), "covered": sims[j] >= tau})
    covered = sum(r["covered"] for r in rows)
    share = covered / len(rows)
    unc = [r for r in rows if not r["covered"]]
    unc_vecs = [lv[i] for i, r in enumerate(rows) if not r["covered"]]
    groups = topics(unc, unc_vecs, args.topic_link) if unc else []
    by_intent = {k: {"n": sum(r["intended"] == k for r in rows),
                     "covered": sum(r["covered"] for r in rows if r["intended"] == k)}
                 for k in sorted({r["intended"] for r in rows})}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result = {"label": args.label, "timestamp": ts, "golden": str(args.golden), "golden_size": len(golden),
              "live_queries": len(rows), "tau": tau, "tau_derivation": t, "min_share": args.min_share,
              "covered": covered, "share": round(share, 4), "passed": share >= args.min_share,
              "by_intent": by_intent, "uncovered_topics": groups, "rows": rows}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"coverage_{ts}_{args.label}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = [f"# Query coverage — {args.label} — {ts}", "",
          f"golden `{args.golden.name}` ({len(golden)} questions) · live queries {len(rows)} · "
          f"tau = {tau} (= paraphrase-pair p10; unrelated p90 {t['unrelated_p90']}; rejected midpoint {t['midpoint_rejected']}) · "
          f"required share {args.min_share:.0%}", "",
          f"**Covered: {covered}/{len(rows)} = {share:.1%} -> {'PASS' if result['passed'] else 'FAIL (coverage gap)'}**", "",
          "| intended | queries | covered |", "|---|---|---|"]
    md += [f"| {k} | {v['n']} | {v['covered']} |" for k, v in by_intent.items()]
    md += ["", "## Uncovered queries grouped into topics", ""]
    for g in groups:
        md.append(f"- **{g['topic']}** ({g['size']}): " + "; ".join(f"`{q}`" for q in g["queries"]))
    md += ["", "## All live queries", "", "| id | query | nearest golden | similarity | covered |", "|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['query']} | {r['nearest_golden']} | {r['similarity']} | {'yes' if r['covered'] else 'NO'} |"
           for r in rows]
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:12 + len(by_intent) + len(groups) + 3]))
    print(f"\nresults: {out}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
