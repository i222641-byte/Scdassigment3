#!/usr/bin/env python3
"""A03 C2: the release gate. Thresholds live in a YAML file: eval/gate.yaml locally, the
`rahbar-gate` ConfigMap mounted at /config/gate.yaml on the cluster (F2), so changing a
threshold changes the outcome without rebuilding any image.

    python eval/gate.py --candidate eval/results/<ts>_candidate.json \
                        --baseline  eval/results/baseline.json  [--config eval/gate.yaml]

Exit 0 = PASS (release may proceed), 1 = FAIL (candidate is stopped).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent


def load_thresholds(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _check(name: str, value: Any, threshold: Any, passed: bool) -> dict[str, Any]:
    return {"check": name, "value": value, "threshold": threshold, "passed": bool(passed)}


def apply_gate(cand: dict[str, Any], base: dict[str, Any] | None, t: dict[str, Any]) -> dict[str, Any]:
    """cand/base are suite summaries (eval/suite.py `summary`). Missing values fail closed."""
    checks: list[dict[str, Any]] = []

    def val(d: dict[str, Any] | None, key: str) -> Any:
        return None if d is None else d.get(key)

    r5, b5 = val(cand, "component.recall@5"), val(base, "component.recall@5")
    drop = float(t.get("max_recall5_drop_points", 2)) / 100.0
    if b5 is None:
        checks.append(_check("recall@5 vs baseline", r5, "no baseline: absolute floor "
                             f"{t.get('min_recall5_absolute', 0.6)}",
                             r5 is not None and r5 >= float(t.get("min_recall5_absolute", 0.6))))
    else:
        checks.append(_check("recall@5 drop vs baseline", r5,
                             f">= {b5:.4f} - {drop:.2f} = {b5 - drop:.4f}",
                             r5 is not None and r5 >= b5 - drop - 1e-9))
    f = val(cand, "e2e.faithfulness")
    checks.append(_check("faithfulness", f, f">= {t.get('min_faithfulness')}",
                         f is not None and f >= float(t.get("min_faithfulness", 0.8))))
    p95 = val(cand, "e2e.latency_p95_ms")
    checks.append(_check("p95 latency (ms)", p95, f"<= {t.get('max_p95_latency_ms')}",
                         p95 is not None and p95 <= float(t.get("max_p95_latency_ms", 60000))))
    a, ba = val(cand, "e2e.abstention_correctness"), val(base, "e2e.abstention_correctness")
    floor = ba if (ba is not None and t.get("abstention_not_below_baseline", True)) else float(
        t.get("min_abstention_correctness", 1.0))
    checks.append(_check("abstention correctness", a,
                         f">= {floor} ({'baseline' if ba is not None else 'absolute'})",
                         a is not None and a >= floor - 1e-9))
    cv = val(cand, "e2e.citation_validity")
    checks.append(_check("citation validity", cv, f">= {t.get('min_citation_validity')}",
                         cv is not None and cv >= float(t.get("min_citation_validity", 0.95))))
    if "max_false_abstention_rate" in t:
        fa = val(cand, "e2e.false_abstention_rate")
        checks.append(_check("false abstention rate", fa, f"<= {t['max_false_abstention_rate']}",
                             fa is not None and fa <= float(t["max_false_abstention_rate"])))
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "thresholds": t}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, default=HERE / "results" / "baseline.json")
    ap.add_argument("--config", type=Path, default=Path(os.environ.get("GATE_CONFIG", HERE / "gate.yaml")))
    args = ap.parse_args()
    cand = json.loads(args.candidate.read_text(encoding="utf-8"))
    base = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else None
    g = apply_gate(cand["summary"], base["summary"] if base else None, load_thresholds(args.config))
    print(f"candidate  {args.candidate}  ({cand['info'].get('collection')}, release {cand['info'].get('release')})")
    print(f"baseline   {args.baseline if base else '(none)'}"
          + (f"  ({base['info'].get('collection')})" if base else ""))
    print(f"thresholds {args.config}")
    print(f"{'check':<28}{'value':>12}  {'threshold':<34}result")
    for c in g["checks"]:
        v = c["value"]
        print(f"{c['check']:<28}{(f'{v:.4f}' if isinstance(v, float) else str(v)):>12}  "
              f"{str(c['threshold']):<34}{'pass' if c['passed'] else 'FAIL'}")
    print(f"\nRELEASE GATE: {'PASS' if g['passed'] else 'FAIL'}")
    return 0 if g["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
