#!/usr/bin/env python3
"""Take real terminal screenshots for the report appendix.

Each capture opens a Git Bash terminal window (mintty), runs the commands live against the
minikube cluster from the repository root, and saves a screenshot of that window with
Win32 PrintWindow. Nothing is redrawn: the PNG is the terminal window as it appeared.

    python docs/report/shoot.py              # all captures, in order
    python docs/report/shoot.py F3 D1 D2     # only some (prefix match on the label)

Output: docs/report/shots/<label>.png and a plain-text log <label>.log of the same session.
Long output (a full trace record, the trace tool) is saved to a file once and paged with
`fold | sed -n` so no screenshot is cropped; each page shows the command that printed it.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "shots"
WORK = OUT / "_work"                       # session scripts, logs, paged files (gitignored)
MINTTY = r"C:\Program Files\Git\usr\bin\mintty.exe"


def bpath(p: Path) -> str:
    """Windows path -> Git Bash path."""
    s = str(p.resolve()).replace("\\", "/")
    return "/" + s[0].lower() + s[2:]


W = "docs/report/shots/_work"            # relative to the repo root (works for bash and Windows python)
ASK = 'scripts/release_demo.sh ask "What minimum CGPA is required to avoid academic warning?"'
NEWEST_API = ("$(kubectl get pods -n rahbar -l app=api --sort-by=.metadata.creationTimestamp "
              "-o jsonpath='{.items[-1:].metadata.name}')")

# (label, title, commands, columns, rows)
CAPTURES: list[tuple[str, str, list[str], int, int]] = [
    ("A1", "A1 verification report for Batch B (pass/fail per check, with reasons)",
     ["kubectl exec -n rahbar datalake-shell -- ls /data/reports/ | tail -5",
      "kubectl exec -n rahbar datalake-shell -- cat /data/reports/20261127T003938Z/verification.md"],
     250, 76),
    ("A2", "A2 second ingestion run on an unchanged corpus: 0 chunks embedded",
     ["scripts/a2_demo.sh unchanged", "scripts/a2_demo.sh counts | tail -25"], 200, 58),
    ("B", "B evaluation summary, all three levels (baseline, two seeded runs)",
     ["cat eval/results/20261126T232355Z_baseline.md"], 200, 58),
    ("C-fail", "C2 release gate FAILING (bad candidate c60)",
     ["python eval/gate.py --candidate eval/results/20261127T001656Z_candidate-c60.json "
      "--baseline eval/results/baseline.json; echo \"exit status: $?\""], 170, 30),
    ("C-pass", "C2 release gate PASSING (released c250, live run after Batch B)",
     ["python eval/gate.py --candidate eval/results/20261127T010412Z_live.json "
      "--baseline eval/results/baseline.json; echo \"exit status: $?\""], 170, 30),
    ("F3-1-release", "F3 bad release (c60) rolled out with a rolling update, watched with rollout status",
     ["kubectl get deployment api -n rahbar -o jsonpath='{.spec.strategy}'; echo",
      "scripts/release_demo.sh release rahbar_v3_c60 v3-c60-bad"], 200, 50),
    ("F3-2-trace-bad", "F3 trace during the bad release (collection rahbar_v3_c60)",
     [ASK], 200, 58),
    ("F3-3-undo", "F3 kubectl rollout undo + kubectl rollout status",
     ["scripts/release_demo.sh undo"], 200, 45),
    ("F3-4-trace-after", "F3 trace after the undo: previous collection and embedding version",
     [ASK], 200, 58),
    ("D1", "D1 one full trace record (kubectl logs of an api pod, saved and paged)",
     [f"mkdir -p {W} && kubectl logs -n rahbar {NEWEST_API} --tail=200 | grep '\"kind\": \"trace\"' "
      f"| tail -1 | python -m json.tool > {W}/d1_trace.json && wc -l {W}/d1_trace.json"],
     230, 76),
    ("D2", "D2 trace tool rebuilding the exact context and prompt for a trace id",
     [f"TID=$(python -c \"import json;print(json.load(open('{W}/d1_trace.json'))['trace_id'])\"); echo trace_id=$TID",
      f"kubectl exec -n rahbar deploy/api -- python -m app.trace_tool $TID > {W}/d2_tool.txt; "
      f"echo \"exit status: $?\"; wc -l {W}/d2_tool.txt"],
     230, 76),
    ("E-before", "E2 coverage BEFORE adding the new golden questions (first 33 questions)",
     [f"mkdir -p {W} && head -33 eval/golden.jsonl > {W}/golden33.jsonl && wc -l {W}/golden33.jsonl",
      f"python eval/coverage.py --label before --golden {W}/golden33.jsonl --out-dir {W}/cov; "
      "echo \"exit status: $?\""], 200, 58),
    ("E-after", "E4 coverage AFTER adding 8 golden questions (41 questions)",
     ["wc -l eval/golden.jsonl",
      f"python eval/coverage.py --label after --out-dir {W}/cov; echo \"exit status: $?\""], 200, 58),
    ("F1", "F1 kubectl get all,pvc,configmap,cronjob,job in namespace rahbar",
     [f"kubectl get all,pvc,configmap,cronjob,job -n rahbar > {W}/f1_get_all.txt; echo \"exit status: $?\"; wc -l {W}/f1_get_all.txt"],
     250, 76),
    ("F2-ingest", "F2 logs of a completed ingestion Job (the only writer to Chroma)",
     ["kubectl get job ingest-run -n rahbar", "kubectl logs -n rahbar job/ingest-run"], 250, 76),
    ("F2-eval", "F2 logs of a completed evaluation Job (kubectl apply -f k8s/eval-job.yaml)",
     ["kubectl get job eval -n rahbar", "kubectl logs -n rahbar job/eval | tail -60"], 230, 76),
    ("F2-configmap", "F2 gate result changes after a ConfigMap edit (same image, no rebuild)",
     ["kubectl get configmap rahbar-gate -n rahbar -o jsonpath='{.data.gate\\.yaml}' | grep citation",
      "kubectl patch configmap rahbar-gate -n rahbar --type merge -p \"$(kubectl get configmap rahbar-gate "
      "-n rahbar -o json | python -c \"import json,sys;d=json.load(sys.stdin)['data'];"
      "print(json.dumps({'data':{'gate.yaml':d['gate.yaml'].replace('min_citation_validity: 0.70',"
      "'min_citation_validity: 0.80')}}))\")\"",
      "scripts/k8s_job.sh k8s/jobs/gate-job.yaml | tail -11",
      "kubectl patch configmap rahbar-gate -n rahbar --type merge -p \"$(kubectl get configmap rahbar-gate "
      "-n rahbar -o json | python -c \"import json,sys;d=json.load(sys.stdin)['data'];"
      "print(json.dumps({'data':{'gate.yaml':d['gate.yaml'].replace('min_citation_validity: 0.80',"
      "'min_citation_validity: 0.70')}}))\")\"",
      "scripts/k8s_job.sh k8s/jobs/gate-job.yaml | tail -11"], 200, 76),
]
# Paged follow-ups: label -> (file in WORK, columns, rows per page)
PAGED = {"D1": ("d1_trace.json", 230, 76), "D2": ("d2_tool.txt", 230, 76),
         "F1": ("f1_get_all.txt", 250, 76)}

# ---------------------------------------------------------------- Win32 window capture
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()


def find_window(title: str) -> int:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.rstrip('  ') == title and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0


def grab(hwnd: int) -> Image.Image:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)           # PW_RENDERFULLCONTENT

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)


# ---------------------------------------------------------------- one terminal session
def session(label: str, title: str, cmds: list[str], cols: int, rows: int) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    done = WORK / f"{label}.done"
    log = WORK / f"{label}.log"
    done.unlink(missing_ok=True)
    wtitle = f"RAHBAR [{label}] {title}"
    lines = [
        "export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8",
        f"cd '{bpath(ROOT)}'",
        f"exec > >(tee '{bpath(log)}') 2>&1",
        f"printf '\\e[1;37m# [{label}] {title}\\e[0m\\n'",
        "printf '\\e[90m# %s  (minikube, namespace rahbar)\\e[0m\\n' \"$(date -u '+%Y-%m-%d %H:%M:%S UTC')\"",
    ]
    for c in cmds:
        q = c.replace("'", "'\\''")
        lines += [
            "printf '\\n\\e[32m%s@%s \\e[35mMINGW64 \\e[33m~/rahbar\\e[36m (a03)\\e[0m\\n' \"$USERNAME\" \"$HOSTNAME\"",
            f"printf '$ %s\\n' '{q}'",
            c,
        ]
    lines += ["printf '\\n\\e[32m%s@%s \\e[35mMINGW64 \\e[33m~/rahbar\\e[36m (a03)\\e[0m\\n$ ' \"$USERNAME\" \"$HOSTNAME\"",
              "sleep 0.5", f"touch '{bpath(done)}'", "sleep 3600"]
    script = WORK / f"{label}.sh"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    font_h = 9 if (cols <= 200 and rows <= 58) else (8 if (cols <= 220 and rows <= 66) else 7)
    p = subprocess.Popen([MINTTY, "--nodaemon", "-t", wtitle, "-p", "0,0", "-s", f"{cols},{rows}",
                          "-o", "Font=Consolas", "-o", f"FontHeight={font_h}",
                          "-o", "Scrollbar=none", "-o", "Padding=6", "-o", "BellType=0",
                          "-o", "BackgroundColour=12,12,12", "-o", "ForegroundColour=220,220,220",
                          "-o", "Locale=C.UTF-8", "-o", "Charset=UTF-8",
                          "-e", "/usr/bin/bash", bpath(script)])
    t0 = time.time()
    while not done.exists():
        if p.poll() is not None:
            raise RuntimeError(f"{label}: terminal exited early")
        if time.time() - t0 > 3 * 3600:
            raise RuntimeError(f"{label}: timeout")
        time.sleep(1)
    time.sleep(1.5)
    hwnd = find_window(wtitle)
    if not hwnd:
        p.kill()
        raise RuntimeError(f"{label}: window not found")
    img = grab(hwnd)
    OUT.mkdir(exist_ok=True)
    png = OUT / f"{label}.png"
    img.save(png)
    user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    time.sleep(0.5)
    if p.poll() is None:
        p.kill()
    # warn if the session scrolled (the top would be cut off)
    text = log.read_text(encoding="utf-8", errors="replace")
    used = sum(max(1, math.ceil(len(l) / cols)) for l in text.splitlines()) + 1
    flag = "  !! SCROLLED: increase rows" if used > rows else ""
    print(f"{label}: {png.name} {img.size[0]}x{img.size[1]}, {used}/{rows} rows{flag}", flush=True)
    return png


def main() -> int:
    want = sys.argv[1:]
    for label, title, cmds, cols, rows in CAPTURES:
        if want and not any(label.startswith(w) for w in want):
            continue
        for old in OUT.glob(f"{label}*.png"):
            old.unlink()
        if label in PAGED:
            session(label + "-0", title, cmds, cols, rows)
            fname, pc, pr = PAGED[label]
            f = WORK / fname
            n = sum(max(1, math.ceil(len(l) / pc)) for l in f.read_text(encoding="utf-8").splitlines())
            per = pr - 11
            pages = math.ceil(n / per)
            for i in range(pages):
                a, b = i * per + 1, (i + 1) * per
                session(f"{label}-{i + 1}", f"{title} - page {i + 1}/{pages}",
                        [f"fold -w {pc} {W}/{fname} | sed -n '{a},{b}p'"], pc, pr)
        else:
            session(label, title, cmds, cols, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
