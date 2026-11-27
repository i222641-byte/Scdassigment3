#!/usr/bin/env python3
"""Build docs/report/Zurain_Awan_22i-2641_Taha_Yasir_22i-2429_RAGOps_Report.pdf from the committed result files (A03 Part G).

    python docs/report/build_report.py

Every number in the PDF is read from eval/results/ (suite runs, gate results, coverage,
ingestion/verification reports, trace metrics, kubectl output) at build time. The file each
table comes from is printed under it. The prose lives in docs/report/report_text.py.
The appendix holds real terminal screenshots taken by docs/report/shoot.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "eval" / "results"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_text as T  # noqa: E402

ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=ss["BodyText"], fontSize=8.6, leading=10.6, spaceAfter=3)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.2, leading=8.6, textColor=colors.HexColor("#555555"))
CELL = ParagraphStyle("cell", parent=BODY, fontSize=7.2, leading=8.4, spaceAfter=0)
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=12.5, spaceBefore=6, spaceAfter=3)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=10, spaceBefore=4, spaceAfter=2)
TITLE = ParagraphStyle("title", parent=ss["Title"], fontSize=17, alignment=TA_CENTER, spaceAfter=4)


def load(name: str) -> Any:
    return json.loads((RES / name).read_text(encoding="utf-8"))


def P(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def table(rows: list[list[Any]], widths: list[float] | None = None, header: bool = True) -> Table:
    data = [[c if isinstance(c, Paragraph) else P("" if c is None else str(c), CELL) for c in r] for r in rows]
    t = Table(data, colWidths=[w * cm for w in widths] if widths else None, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
             ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6ECF5")))
    t.setStyle(TableStyle(style))
    return t


def src(*names: str) -> Paragraph:
    return P("Source: " + ", ".join(f"<font face='Courier'>{n}</font>" for n in names), SMALL)


def fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    return str(v)


# Appendix: real terminal-window screenshots taken by docs/report/shoot.py (label, caption).
SHOTS = [
    ("A1", "A1 - verification report for Batch B (pass/fail per check, with reasons)"),
    ("A2", "A2 - second ingestion run on an unchanged corpus: 0 chunks embedded; chunk count by doc id"),
    ("B", "B - evaluation summary with all three levels (module, component, end-to-end) and stochasticity"),
    ("C-fail", "C2 - release gate failing (bad candidate c60)"),
    ("C-pass", "C2 - release gate passing (released c250, live run after Batch B)"),
    ("D1-*", "D1 - one full trace record from kubectl logs"),
    ("D2-*", "D2 - trace tool rebuilding the exact context and prompt for that trace id"),
    ("E-before", "E2 - coverage before adding the new golden questions"),
    ("E-after", "E4 - coverage after adding the new golden questions"),
    ("F1-*", "F1 - kubectl get all,pvc,configmap,cronjob,job -n rahbar"),
    ("F2-ingest", "F2 - logs of a completed ingestion Job"),
    ("F2-eval", "F2 - logs of a completed evaluation Job (exit status = release gate)"),
    ("F2-configmap", "F2 - gate result changing after a ConfigMap edit, same image"),
    ("F3-1-release", "F3 - bad release rolled out (maxUnavailable 0), kubectl rollout status"),
    ("F3-2-trace-bad", "F3 - trace during the bad release shows collection rahbar_v3_c60"),
    ("F3-3-undo", "F3 - kubectl rollout undo and kubectl rollout status"),
    ("F3-4-trace-after", "F3 - trace after the undo shows the previous collection and embedding version"),
]


def appendix() -> list[Any]:
    from PIL import Image as PImage
    from reportlab.platypus import NextPageTemplate
    shots = Path(__file__).resolve().parent / "shots"
    if not shots.exists():
        return []
    out: list[Any] = [NextPageTemplate("landscape"), PageBreak(),
                      P("Appendix: screenshots (not counted in the 8 pages)", H1),
                      P("Each screenshot is a real Git Bash terminal window on our laptop, showing the command "
                        "and its output against our minikube cluster (namespace rahbar). They were taken with "
                        "docs/report/shoot.py, which opens the terminal, runs the commands live and saves the "
                        "window. Long output (the full trace record and the trace tool) is saved to a file once "
                        "and paged with fold | sed -n, so nothing is cropped; each page shows its command.", SMALL)]
    lw, lh = landscape(A4)
    maxw, maxh = lw - 3 * cm, lh - 4.0 * cm
    for pat, caption in SHOTS:
        if pat.endswith("*"):
            files = sorted((p for p in shots.glob(pat[:-1] + "*.png")),
                           key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        else:
            files = [shots / f"{pat}.png"] if (shots / f"{pat}.png").exists() else []
        for i, png in enumerate(files, 1):
            w, h = PImage.open(png).size
            scale = min(maxw / w, maxh / h)
            extra = ""
            if len(files) > 1:
                extra = " (command)" if png.stem.endswith("-0") else f" (page {i - 1}/{len(files) - 1})"
            cap = P(f"<b>{caption}</b>{extra}", SMALL)
            out.append(KeepTogether([cap, Image(str(png), width=w * scale, height=h * scale)]))
            out.append(Spacer(1, 6))
    return out


def footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.drawString(1.5 * cm, 0.9 * cm, "RAHBAR · Assignment 03 RAGOps · CS4032 Fall 2026")
    canvas.drawRightString(A4[0] - 1.5 * cm, 0.9 * cm, f"page {doc.page}")
    canvas.restoreState()


def footer_land(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    lw = landscape(A4)[0]
    canvas.drawString(1.5 * cm, 0.9 * cm, "RAHBAR · Assignment 03 RAGOps · CS4032 Fall 2026 · appendix")
    canvas.drawRightString(lw - 1.5 * cm, 0.9 * cm, f"page {doc.page}")
    canvas.restoreState()


def build(out: Path) -> None:
    story: list[Any] = []
    for block in T.sections(load, P, table, src, fmt, H1, H2, TITLE, BODY, SMALL, CELL):
        if block == "PAGEBREAK":
            story.append(PageBreak())
        elif block == "SPACER":
            story.append(Spacer(1, 4))
        elif isinstance(block, list):
            story.append(KeepTogether(block))
        else:
            story.append(block)
    story += appendix()
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
    doc = BaseDocTemplate(str(out), pagesize=A4, title="RAHBAR RAGOps — Assignment 03",
                          author="Zurain Awan (22i-2641), Taha Yasir (22i-2429)")
    pw, ph = A4
    portrait_frame = Frame(1.5 * cm, 1.4 * cm, pw - 3 * cm, ph - 2.7 * cm, id="p",
                           leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    lw, lh = landscape(A4)
    land_frame = Frame(1.5 * cm, 1.4 * cm, lw - 3 * cm, lh - 2.7 * cm, id="l",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="portrait", frames=[portrait_frame], onPage=footer, pagesize=A4),
        PageTemplate(id="landscape", frames=[land_frame], onPage=footer_land, pagesize=landscape(A4)),
    ])
    doc.build(story)
    print(f"wrote {out}")


if __name__ == "__main__":
    build(Path(__file__).resolve().parent / "Zurain_Awan_22i-2641_Taha_Yasir_22i-2429_RAGOps_Report.pdf")
