#!/usr/bin/env python3
"""Run the appendix commands against the live cluster and render each as a terminal image.

    python docs/report/capture.py            # all captures
    python docs/report/capture.py F3 D1      # only some

Each capture runs real commands (Git Bash, repo root) and saves:
  docs/report/screens/<label>.txt   the exact commands, timestamp and full output
  docs/report/screens/<label>-N.png the same text rendered as terminal panels (never cropped:
                                    long output is split over several numbered panels)
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "screens"
BASH = r"C:\Program Files\Git\bin\bash.exe"
SCRATCH = os.environ.get("TMP", "/tmp").replace("\\", "/")

ASK = 'scripts/release_demo.sh ask "What minimum CGPA is required to avoid academic warning?"'
CAPTURES: list[tuple[str, str, list[str]]] = [
    ("A1", "A1 - verification report for Batch B",
     ["kubectl exec -n rahbar datalake-shell -- cat /data/reports/20261127T003938Z/verification.md"]),
    ("A2", "A2 - second ingestion run on an unchanged corpus: 0 chunks embedded",
     ["scripts/a2_demo.sh unchanged"]),
    ("B", "B - evaluation summary with all three levels (baseline, two seeded runs)",
     ["cat eval/results/20261126T232355Z_baseline.md"]),
    ("C-fail", "C - release gate failing (bad candidate c60)",
     ["python eval/gate.py --candidate eval/results/20261127T001656Z_candidate-c60.json --baseline eval/results/baseline.json; echo \"exit status: $?\""]),
    ("C-pass", "C - release gate passing (released c250, live run after Batch B)",
     ["python eval/gate.py --candidate eval/results/20261127T010412Z_live.json --baseline eval/results/baseline.json; echo \"exit status: $?\""]),
    ("F3", "F3 - bad release, kubectl rollout status, kubectl rollout undo, trace afterwards",
     ["scripts/release_demo.sh release rahbar_v3_c60 v3-c60-bad", ASK,
      "scripts/release_demo.sh undo", ASK]),
    ("D1", "D1 - one full trace record (from kubectl logs of an api pod)",
     ["kubectl logs -n rahbar $(kubectl get pods -n rahbar -l app=api --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}') --tail=100 | grep '\"kind\": \"trace\"' | tail -1 | python -m json.tool"]),
    ("D2", "D2 - trace tool rebuilding the prompt for a trace id",
     ["kubectl exec -n rahbar deploy/api -- python -m app.trace_tool 269574d1ad4c46dea419bc4ab37083fb"]),
    ("E-before", "E - coverage before adding the new golden questions (33 questions)",
     [f"head -33 eval/golden.jsonl > {SCRATCH}/golden33.jsonl && python eval/coverage.py --label before --golden {SCRATCH}/golden33.jsonl --out-dir {SCRATCH}/cov; echo \"exit status: $?\""]),
    ("E-after", "E - coverage after adding 8 golden questions (41 questions)",
     [f"python eval/coverage.py --label after --out-dir {SCRATCH}/cov; echo \"exit status: $?\""]),
    ("F1", "F1 - kubectl get all,pvc,configmap,cronjob,job",
     ["kubectl get all,pvc,configmap,cronjob,job -n rahbar"]),
    ("F2-ingest", "F2 - logs of a completed ingestion Job",
     ["kubectl get job ingest-run -n rahbar", "kubectl logs -n rahbar job/ingest-run"]),
    ("F2-eval", "F2 - logs of a completed evaluation Job (kubectl apply -f k8s/eval-job.yaml)",
     ["kubectl get job eval -n rahbar", "kubectl logs -n rahbar job/eval | tail -60"]),
    ("F2-configmap", "F2 - gate result changing after a ConfigMap edit (same image, no rebuild)",
     ["kubectl get configmap rahbar-gate -n rahbar -o jsonpath='{.data.gate\\.yaml}' | grep citation",
      "kubectl get configmap rahbar-gate -n rahbar -o jsonpath='{.data.gate\\.yaml}' | sed 's/min_citation_validity: 0.70/min_citation_validity: 0.80/' > gate.tmp && kubectl create configmap rahbar-gate -n rahbar --from-file=gate.yaml=gate.tmp --dry-run=client -o yaml | kubectl apply -f -",
      "scripts/k8s_job.sh k8s/jobs/gate-job.yaml | tail -12",
      "kubectl get configmap rahbar-gate -n rahbar -o jsonpath='{.data.gate\\.yaml}' | sed 's/min_citation_validity: 0.80/min_citation_validity: 0.70/' > gate.tmp && kubectl create configmap rahbar-gate -n rahbar --from-file=gate.yaml=gate.tmp --dry-run=client -o yaml | kubectl apply -f - ; rm -f gate.tmp",
      "scripts/k8s_job.sh k8s/jobs/gate-job.yaml | tail -12"]),
]

FONT = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 15)
BOLD = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 15)
COLS, ROWS, LH = 150, 70, 19


def run(cmds: list[str]) -> tuple[list[tuple[str, str]], str]:
    env = {**os.environ, "MSYS_NO_PATHCONV": "1", "PYTHONIOENCODING": "utf-8"}
    out = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    for c in cmds:
        p = subprocess.run([BASH, "-c", c], cwd=ROOT, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600)
        text = (p.stdout + p.stderr).replace("\r", "")
        text = "\n".join(l for l in text.splitlines() if "CropBox missing" not in l)
        out.append((c, text.rstrip()))
    return out, ts


def render(label: str, title: str, ts: str, blocks: list[tuple[str, str]]) -> list[Path]:
    lines: list[tuple[str, bool]] = []
    for cmd, text in blocks:
        for i, w in enumerate(textwrap.wrap("$ " + cmd, COLS, subsequent_indent="  ") or ["$"]):
            lines.append((w, True))
        for raw in text.splitlines() or [""]:
            for w in (textwrap.wrap(raw, COLS, replace_whitespace=False, drop_whitespace=False) or [""]):
                lines.append((w, False))
    import math
    n_panels = max(1, math.ceil(len(lines) / ROWS))
    per = max(1, math.ceil(len(lines) / n_panels))           # balanced: no near-empty last panel
    panels = [lines[i:i + per] for i in range(0, len(lines), per)] or [[]]
    paths = []
    for n, chunk in enumerate(panels, 1):
        w = 20 + COLS * 8 + 20
        h = 76 + LH * len(chunk) + 20
        img = Image.new("RGB", (w, h), (12, 12, 12))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, w, 52], fill=(45, 45, 48))
        part = f"  ({n}/{len(panels)})" if len(panels) > 1 else ""
        d.text((12, 8), f"MINGW64  zurai@laptop  ~/rahbar  [{label}] {title}{part}", font=BOLD, fill=(220, 220, 220))
        d.text((12, 28), f"captured {ts} · minikube cluster, namespace rahbar", font=FONT, fill=(160, 160, 160))
        y = 64
        for text, is_cmd in chunk:
            d.text((20, y), text, font=BOLD if is_cmd else FONT, fill=(110, 220, 120) if is_cmd else (215, 215, 215))
            y += LH
        p = OUT / f"{label}-{n}.png"
        img.save(p)
        paths.append(p)
    return paths


def rerender() -> None:
    """Re-draw every panel from the saved .txt captures (no commands are re-run)."""
    for label, title, _ in CAPTURES:
        t = OUT / f"{label}.txt"
        if not t.exists():
            continue
        lines = t.read_text(encoding="utf-8").splitlines()
        ts = lines[1].replace("captured ", "").split(" on our")[0]
        blocks: list[tuple[str, str]] = []
        for line in lines[3:]:
            if line.startswith("$ "):
                blocks.append((line[2:], ""))
            elif blocks:
                c, o = blocks[-1]
                blocks[-1] = (c, o + "\n" + line if o else line)
        for old in OUT.glob(f"{label}-*.png"):
            old.unlink()
        print(label, len(render(label, title, ts, blocks)), "panel(s)")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    if sys.argv[1:] == ["--rerender"]:
        rerender()
        return 0
    want = set(sys.argv[1:])
    for label, title, cmds in CAPTURES:
        if want and label not in want:
            continue
        for old in OUT.glob(f"{label}-*.png"):
            old.unlink()
        blocks, ts = run(cmds)
        (OUT / f"{label}.txt").write_text(
            f"[{label}] {title}\ncaptured {ts} on our minikube cluster (namespace rahbar)\n\n" +
            "\n".join(f"$ {c}\n{t}\n" for c, t in blocks), encoding="utf-8")
        ps = render(label, title, ts, blocks)
        print(f"{label}: {len(ps)} panel(s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
