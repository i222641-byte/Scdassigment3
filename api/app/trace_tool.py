"""A03 D2: print the exact context and prompt that produced an answer, given its trace id.

On the cluster (reads the traces volume, rebuilds the prompt from Chroma):
    kubectl exec -n rahbar deploy/api -- python -m app.trace_tool <trace_id>

The rebuild fetches the context chunks by id from the vector store, re-renders the prompt
template with the traced question, and checks the hash against the one in the trace.
"""

from __future__ import annotations

import json
import sys

from .config import get_settings
from .retrieval import get_retriever
from .routes.ask import rebuild_prompt
from .tracing import find


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.trace_tool <trace_id> [--json]")
        return 2
    settings = get_settings()
    rec = find(argv[0], settings.trace_dir)
    if rec is None:
        print(f"trace {argv[0]} not found under {settings.trace_dir or '(TRACE_DIR unset)'}")
        return 1
    rb = rebuild_prompt(rec, get_retriever(settings))
    if "--json" in argv:
        print(json.dumps({"record": rec, "rebuild": rb}, indent=2, default=str))
        return 0
    print(f"trace_id        {rec['trace_id']}")
    print(f"timestamp       {rec['timestamp']}   release {rec.get('release')}   pod {rec.get('pod')}")
    print(f"query           {rec['query']}")
    print(f"rewritten       {rec.get('rewritten_query')}")
    print(f"collection      {rec['collection']['name']} (index_version {rec['collection'].get('index_version')})")
    print(f"embedding       {rec['embedding']['model']} @ {rec['embedding']['version']}")
    print(f"filters         {json.dumps(rec.get('filters'))}")
    print(f"guardrails      {json.dumps(rec.get('guardrails'))}")
    print(f"cache           {rec.get('cache')}")
    print("\n--- CONTEXT (in prompt order) ---")
    for i, c in enumerate(rec.get("context") or [], 1):
        print(f"[{i}] {c['chunk_id']}  {c['doc_id']}@{c['doc_version']}  p.{c['page']}  score {c['score']}")
    p = rec.get("prompt") or {}
    print(f"\n--- PROMPT (template {p.get('template')}, {p.get('hash')}) ---")
    print(p.get("text") or "(no prompt: the query abstained before generation)")
    print("\n--- REBUILD FROM VECTOR STORE ---")
    if rb.get("rebuilt"):
        print(f"rebuilt hash    {rb['hash']}")
        print(f"matches trace   {rb['matches_trace']}")
    else:
        print(f"not rebuilt: {rb.get('reason')}")
    print("\n--- RESPONSE ---")
    print(json.dumps(rec.get("response"), indent=2))
    print("citations", json.dumps(rec.get("citations")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
