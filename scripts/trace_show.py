#!/usr/bin/env python3
"""A03 D2 (offline copy): print the exact context and prompt behind an answer from a trace
file, without the cluster. On the cluster use the in-pod tool, which also rebuilds the
prompt from the vector store and checks its hash:

    kubectl exec -n rahbar deploy/api -- python -m app.trace_tool <trace_id>
    python scripts/trace_show.py <trace_id> [traces/]          # from committed trace samples
    python scripts/trace_show.py <trace_id> --api http://localhost:8080   # via /api/trace (rebuild)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def find(trace_id: str, root: Path) -> dict | None:
    files = sorted(root.rglob("*.jsonl")) if root.is_dir() else [root]
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if trace_id in line and line.startswith("{"):
                rec = json.loads(line)
                if rec.get("trace_id") == trace_id:
                    return rec
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_id")
    ap.add_argument("path", nargs="?", default="traces")
    ap.add_argument("--api", help="ask the running API to rebuild the prompt from the vector store")
    args = ap.parse_args()
    rebuild = None
    if args.api:
        import httpx

        d = httpx.get(f"{args.api.rstrip('/')}/api/trace/{args.trace_id}", timeout=30).json()
        rec, rebuild = d.get("record"), d.get("rebuild")
    else:
        rec = find(args.trace_id, Path(args.path))
    if not rec:
        print(f"trace {args.trace_id} not found")
        return 1
    print(f"trace_id    {rec['trace_id']}\ntimestamp   {rec['timestamp']}   release {rec.get('release')}")
    print(f"query       {rec['query']}")
    print(f"collection  {rec['collection']['name']}  index_version {rec['collection'].get('index_version')}")
    print(f"embedding   {rec['embedding']['model']} @ {rec['embedding']['version']}")
    print(f"filters     {json.dumps(rec.get('filters'))}   guardrails {json.dumps(rec.get('guardrails'))}")
    print("\n--- CONTEXT ---")
    for i, c in enumerate(rec.get("context") or [], 1):
        print(f"[{i}] {c['chunk_id']}  {c['doc_id']}@{c['doc_version']}  p.{c['page']}  score {c['score']}")
    p = rec.get("prompt") or {}
    print(f"\n--- PROMPT ({p.get('hash')}) ---\n{p.get('text') or '(none: abstained before generation)'}")
    if p.get("text"):
        h = "sha256:" + hashlib.sha256(p["text"].encode("utf-8")).hexdigest()
        print(f"\nstored prompt hashes to {h}: {'matches' if h == p.get('hash') else 'MISMATCH'}")
    if rebuild:
        print(f"rebuilt from vector store: {rebuild.get('rebuilt')}  matches trace: {rebuild.get('matches_trace')}")
    print("\n--- RESPONSE ---\n" + json.dumps(rec.get("response"), indent=2))
    print("citations " + json.dumps(rec.get("citations")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
