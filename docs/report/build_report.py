#!/usr/bin/env python3
"""Build docs/report/RAGOps_Report.pdf from the committed result files (A03 Part G).

    python docs/report/build_report.py

Every number in the PDF is read from eval/results/ (suite runs, gate results, coverage,
ingestion/verification reports, trace metrics, kubectl output) at build time. The file each
table comes from is printed under it. The prose lives in docs/report/report_text.py.
Screenshots are added by the group as the appendix (they must come from our own terminal).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
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


ORDER = ["A1", "A2", "B", "C-fail", "C-pass", "D1", "D2", "E-before", "E-after", "F1", "F2-ingest",
         "F2-eval", "F2-configmap", "F3"]


def appendix() -> list[Any]:
    shots = Path(__file__).resolve().parent / "screens"
    if not shots.exists():
        return []
    out: list[Any] = [PageBreak(), P("Appendix: screenshots (not counted in the 8 pages)", H1),
                      P("Each panel shows the command and its full output from our minikube cluster, "
                        "captured by docs/report/capture.py; long outputs continue over numbered panels. "
                        "The plain-text copy of every capture is in docs/report/screens/&lt;label&gt;.txt.", SMALL)]
    maxw, maxh = A4[0] - 3 * cm, A4[1] - 4.2 * cm
    for label in ORDER:
        panels = sorted(shots.glob(f"{label}-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        for i, png in enumerate(panels, 1):
            from PIL import Image as PImage
            w, h = PImage.open(png).size
            scale = min(maxw / w, maxh / h)
            cap = P(f"<b>{label}</b>" + (f" (panel {i}/{len(panels)})" if len(panels) > 1 else ""), SMALL)
            out.append(KeepTogether([cap, Image(str(png), width=w * scale, height=h * scale)]))
            out.append(Spacer(1, 6))
    return out


def footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.drawString(1.5 * cm, 0.9 * cm, "RAHBAR · Assignment 03 RAGOps · CS4032 Fall 2026")
    canvas.drawRightString(A4[0] - 1.5 * cm, 0.9 * cm, f"page {doc.page}")
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
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.4 * cm,
                            title="RAHBAR RAGOps — Assignment 03", author="Zurain, Taha Yasir")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"wrote {out}")


if __name__ == "__main__":
    build(Path(__file__).resolve().parent / "RAGOps_Report.pdf")
