#!/usr/bin/env python3
"""A03 D3: summarise the trace log over a time window.

    python scripts/trace_metrics.py traces/                      # every record
    python scripts/trace_metrics.py traces/ --since 2026-11-26T10:00 --until 2026-11-26T12:00
    kubectl logs -n rahbar -l app=api --tail=-1 | python scripts/trace_metrics.py -   # from stdout

Reports: top-1 retrieval similarity distribution, abstention rate, cache hit rate, p95
latency per stage, injection attempts flagged (query and retrieval rails), grounding-rail
suppressions, and a breakdown by release / collection. Input lines that are not trace
records (ordinary JSON logs, plain text) are skipped.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def read(paths: list[str]) -> Iterable[dict[str, Any]]:
    for p in paths:
        if p == "-":
            lines: Iterable[str] = sys.stdin
        else:
            path = Path(p)
            files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
            lines = (ln for f in files for ln in f.read_text(encoding="utf-8").splitlines())
        for ln in lines:
            ln = ln.strip()
            if not ln.startswith("{"):
                continue
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "trace":
                yield rec


def ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    v = sorted(v)
    k = (len(v) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return round(v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f), 4)


def summarise(recs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(recs)
    top1 = [r["top1_similarity"] for r in recs if r.get("top1_similarity") is not None]
    hist: Counter[str] = Counter()
    for s in top1:
        lo = math.floor(s * 20) / 20
        hist[f"{lo:.2f}-{lo + 0.05:.2f}"] += 1
    cache = Counter(r.get("cache", "?") for r in recs)
    lookups = cache["hit"] + cache["miss"]
    stages: dict[str, list[float]] = defaultdict(list)
    for r in recs:
        for k, v in (r.get("latency_ms") or {}).items():
            stages[k].append(v)
    inj = Counter()
    grounding = 0
    flagged_ids = []
    for r in recs:
        for g in r.get("guardrails") or []:
            if g.get("rail") == "injection":
                inj[g.get("stage", "?")] += 1
                flagged_ids.append(r["trace_id"])
            elif g.get("rail") == "grounding":
                grounding += 1
    abst = sum(1 for r in recs if r.get("abstained"))
    return {
        "records": n,
        "window": {"first": min((r["timestamp"] for r in recs), default=None),
                   "last": max((r["timestamp"] for r in recs), default=None)},
        "top1_similarity": {"n": len(top1), "min": pct(top1, 0), "p10": pct(top1, .1), "p25": pct(top1, .25),
                            "median": pct(top1, .5), "p75": pct(top1, .75), "p90": pct(top1, .9),
                            "max": pct(top1, 1), "histogram": dict(sorted(hist.items()))},
        "abstention_rate": round(abst / n, 4) if n else None, "abstentions": abst,
        "cache": dict(cache), "cache_hit_rate": round(cache["hit"] / lookups, 4) if lookups else None,
        "p95_latency_ms_by_stage": {k: pct(v, .95) for k, v in sorted(stages.items())},
        "p50_latency_ms_by_stage": {k: pct(v, .5) for k, v in sorted(stages.items())},
        "injection_attempts_flagged": sum(inj.values()), "injection_by_stage": dict(inj),
        "injection_trace_ids": sorted(set(flagged_ids)),
        "grounding_suppressions": grounding,
        "by_release_collection": dict(Counter(f"{r.get('release')} | {r['collection']['name']} | "
                                              f"{r['embedding']['model']}@{r['embedding']['version']}"
                                              for r in recs)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="trace dir(s), .jsonl file(s), or - for stdin")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--out", type=Path, help="write the summary JSON here")
    args = ap.parse_args()
    recs = list(read(args.paths))
    if args.since:
        recs = [r for r in recs if ts(r["timestamp"]) >= ts(args.since)]
    if args.until:
        recs = [r for r in recs if ts(r["timestamp"]) <= ts(args.until)]
    s = summarise(recs)
    s["filter"] = {"since": args.since, "until": args.until}
    t = s["top1_similarity"]
    print(f"trace records       {s['records']}  ({s['window']['first']} .. {s['window']['last']})")
    print(f"top-1 similarity    min {t['min']}  p25 {t['p25']}  median {t['median']}  p75 {t['p75']}  max {t['max']}")
    for b, c in t["histogram"].items():
        print(f"   {b}  {'#' * c} {c}")
    print(f"abstention rate     {s['abstention_rate']}  ({s['abstentions']}/{s['records']})")
    print(f"cache hit rate      {s['cache_hit_rate']}  {s['cache']}")
    print("p95 latency (ms)    " + "  ".join(f"{k}={v}" for k, v in s["p95_latency_ms_by_stage"].items()))
    print(f"injection flagged   {s['injection_attempts_flagged']}  {s['injection_by_stage']}")
    print(f"grounding rail      {s['grounding_suppressions']} uncited answers suppressed")
    print("release | collection | embedding")
    for k, v in s["by_release_collection"].items():
        print(f"   {k}: {v}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(s, indent=2), encoding="utf-8")
        print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
