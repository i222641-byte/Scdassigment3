#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

Given: talking to the API, reading the golden set, writing results.json, the exit
code. The four evaluation functions (recall_at_k, citation_validity, summarise, gate)
are implemented below.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions).

    Matching strategy (documented in docs/PIPELINE.md):
    - source: basename match — rel_source substring of ret_source or vice-versa (case-insensitive)
    - section: contains match — rel_section substring of ret_section or vice-versa (case-insensitive);
      an empty rel_section is treated as a wildcard (matches any section).
    """
    if not relevant:
        return None
    top_k = retrieved[:k]
    hits = 0
    for rel in relevant:
        rel_source = rel["source"].lower()
        rel_section = rel.get("section", "").lower().strip()
        for ret in top_k:
            ret_source = ret.get("source", "").lower()
            ret_section = ret.get("section", "").lower().strip()
            # Source: match if either name is a substring of the other
            source_match = rel_source in ret_source or ret_source in rel_source
            # Section: empty rel_section is a wildcard; otherwise substring either way
            section_match = (
                not rel_section
                or rel_section in ret_section
                or ret_section in rel_section
            )
            if source_match and section_match:
                hits += 1
                break
    return hits / len(relevant)


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations.

    A citation is valid when at least one retrieved passage has:
    - a source that contains or is contained by the citation source (case-insensitive)
    - a section that contains or is contained by the citation section (case-insensitive),
      or the citation section is empty (treated as wildcard).
    """
    citations = response.get("citations", [])
    retrieved = response.get("retrieved", [])
    if not citations:
        return None
    retrieved_pairs = [
        (r.get("source", "").lower(), r.get("section", "").lower())
        for r in retrieved
    ]
    valid = 0
    for c in citations:
        c_source = c.get("source", "").lower()
        c_section = c.get("section", "").lower()
        for rs, rsec in retrieved_pairs:
            source_match = c_source in rs or rs in c_source
            section_match = not c_section or c_section in rsec or rsec in c_section
            if source_match and section_match:
                valid += 1
                break
    return valid / len(citations)


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    r3_scores: list[float] = []
    r5_scores: list[float] = []
    cit_scores: list[float] = []
    abstain_correct: list[bool] = []

    # recall@5 by question type: map type -> list of float scores
    by_type: dict[str, list[float]] = {}

    for row in rows:
        relevant = row.get("relevant") or []
        response = row.get("response") or {}
        retrieved = response.get("retrieved") or []
        qtype = row.get("type", "ordinary")

        # Recall metrics — skipped for must-abstain (relevant is empty → None)
        r3 = recall_at_k(relevant, retrieved, 3)
        r5 = recall_at_k(relevant, retrieved, 5)
        if r3 is not None:
            r3_scores.append(r3)
        if r5 is not None:
            r5_scores.append(r5)
            by_type.setdefault(qtype, []).append(r5)

        # Citation validity
        cv = citation_validity(response)
        if cv is not None:
            cit_scores.append(cv)

        # Abstention correctness — only for must-abstain questions
        if row.get("must_abstain"):
            answered = response.get("answered_from_context", True)
            abstain_correct.append(not answered)

    def avg(lst: list[float]) -> float | None:
        return round(sum(lst) / len(lst), 4) if lst else None

    return {
        "recall_at_3": avg(r3_scores),
        "recall_at_5": avg(r5_scores),
        "citation_validity": avg(cit_scores),
        "abstention_correctness": avg([float(b) for b in abstain_correct]),
        "by_type": {t: avg(scores) for t, scores in by_type.items()},
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures: list[str] = []

    # Gate 1: recall@5 must not drop more than MAX_RECALL5_DROP below the baseline
    if baseline is not None:
        baseline_r5 = baseline.get("recall_at_5")
        current_r5 = results.get("recall_at_5")
        if baseline_r5 is not None and current_r5 is not None:
            if current_r5 < baseline_r5 - MAX_RECALL5_DROP:
                failures.append(
                    f"recall@5 dropped too far: {current_r5:.4f} < "
                    f"{baseline_r5:.4f} - {MAX_RECALL5_DROP} "
                    f"(threshold {baseline_r5 - MAX_RECALL5_DROP:.4f})"
                )

    # Gate 2: citation validity must meet the minimum
    cit = results.get("citation_validity")
    if cit is not None and cit < MIN_CITATION_VALIDITY:
        failures.append(
            f"citation_validity {cit:.4f} < required {MIN_CITATION_VALIDITY}"
        )

    # Gate 3: every must-abstain question must be declined
    abstention = results.get("abstention_correctness")
    if abstention is not None and abstention < REQUIRED_ABSTENTION:
        failures.append(
            f"abstention_correctness {abstention:.4f} < required {REQUIRED_ABSTENTION}"
        )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    try:
        results = summarise(rows)
        baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
        failures = gate(results, baseline)
    except NotImplementedError as exc:
        print(f"\nnot implemented yet: {exc}")
        return 2

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
