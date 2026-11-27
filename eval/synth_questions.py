#!/usr/bin/env python3
"""Draft synthetic golden questions from indexed chunks (A03 Part B).

    python eval/synth_questions.py --chroma localhost:8001 --collection rahbar_v1 --n 16

Samples chunks (seeded), asks the LLM for one question the chunk answers plus the answer,
and writes eval/synthetic_candidates.jsonl with the chunk's doc_id, source and page as
ground truth. A person then reviews every candidate: keeps it, rewrites it, or drops it,
and copies the kept ones into eval/golden.jsonl with origin "synthetic", reviewed true.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
PROMPT = """Here is a passage from a university document.

{text}

Write ONE question a student might ask that this passage answers with a specific fact
(a number, a rule, a deadline or a name), and the short answer. The question must make sense
without seeing the passage. Return JSON: {{"question": "...", "answer": "..."}}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma", default="localhost:8001")
    ap.add_argument("--collection", default="rahbar_v1")
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=HERE / "synthetic_candidates.jsonl")
    args = ap.parse_args()

    import chromadb

    host, port = args.chroma.split(":")
    col = chromadb.HttpClient(host=host, port=int(port)).get_collection(args.collection)
    got = col.get(include=["documents", "metadatas"], where={"superseded": False})
    rows = [(i, d, m) for i, d, m in zip(got["ids"], got["documents"], got["metadatas"])
            if len(d.split()) > 80]
    random.Random(args.seed).shuffle(rows)
    out = []
    for cid, text, meta in rows[: args.n]:
        r = httpx.post(f"{args.ollama}/api/chat", timeout=300, json={
            "model": args.model, "stream": False, "format": "json",
            "options": {"temperature": 0.3, "seed": args.seed},
            "messages": [{"role": "user", "content": PROMPT.format(text=text[:2500])}]}).json()
        try:
            qa = json.loads(r["message"]["content"])
        except Exception:
            continue
        out.append({"question": qa.get("question"), "draft_answer": qa.get("answer"),
                    "chunk_id": cid, "doc_id": meta.get("doc_id"), "source": meta.get("source"),
                    "page": meta.get("page"), "generator": args.model,
                    "chunk_excerpt": text[:400]})
        print(json.dumps(out[-1])[:300])
    args.out.write_text("\n".join(json.dumps(o) for o in out) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
