#!/usr/bin/env python3
"""A03 B: how often does the LLM faithfulness judge agree with our hand labels?

    python eval/agreement.py eval/results/<ts>_baseline.json [--labels eval/human_labels.jsonl]

human_labels.jsonl: one line per hand-labelled answer
    {"id": "g01", "trace_id": "...", "answer": "<the answer text that was labelled>",
     "label": "supported" | "unsupported", "why": "...", "labeller": "..."}

A label is compared only with the judge verdict on the *same answer text* (labels are about an
answer, not a question). Prints the confusion table and writes it into the result file under
runs[i].e2e.judge_agreement.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9.%]+", " ", (s or "").lower()).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", type=Path)
    ap.add_argument("--labels", type=Path, default=Path(__file__).resolve().parent / "human_labels.jsonl")
    args = ap.parse_args()
    res = json.loads(args.result.read_text(encoding="utf-8"))
    labels = [json.loads(x) for x in args.labels.read_text(encoding="utf-8").splitlines() if x.strip()]
    for i, run in enumerate(res["runs"]):
        rows = {r["id"]: r for r in run["e2e"]["per_question"]}
        table = {"judge_yes_human_yes": 0, "judge_yes_human_no": 0, "judge_no_human_yes": 0,
                 "judge_no_human_no": 0}
        compared, skipped, detail = 0, [], []
        for lab in labels:
            r = rows.get(lab["id"])
            if not r or norm(r.get("answer", "")) != norm(lab.get("answer", "")) or \
                    r.get("judge", {}).get("supported") is None:
                skipped.append(lab["id"])
                continue
            j = bool(r["judge"]["supported"])
            h = lab["label"] == "supported"
            table[f"judge_{'yes' if j else 'no'}_human_{'yes' if h else 'no'}"] += 1
            compared += 1
            detail.append({"id": lab["id"], "judge": j, "human": h, "agree": j == h})
        agree = table["judge_yes_human_yes"] + table["judge_no_human_no"]
        out = {"compared": compared, "agreement": round(agree / compared, 4) if compared else None,
               "confusion": table, "skipped_answer_changed": skipped, "detail": detail}
        run["e2e"]["judge_agreement"] = out
        run["e2e"]["judge_human_agreement"] = out["agreement"]
        run["e2e"]["judge_human_labels_compared"] = compared
        print(f"run {i + 1}: agreement {out['agreement']} on {compared} labelled answers; "
              f"confusion {table}; skipped (answer differs) {skipped}")
    res["summary"]["e2e.judge_human_agreement"] = res["runs"][0]["e2e"]["judge_human_agreement"]
    args.result.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
