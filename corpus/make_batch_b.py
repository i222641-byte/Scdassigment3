#!/usr/bin/env python3
"""Build the derived Batch B files (A03 Part A) from the fetched Batch A corpus.

    python corpus/fetch.py            # Batch A -> corpus/raw/
    python corpus/make_batch_b.py     # derived Batch B files -> corpus/batch_b/

The Markdown documents in corpus/batch_b/ are written by the group and committed. The files
this script makes are derived from public FAST-NUCES documents, so like corpus/raw/ they are
regenerated rather than committed (see .gitignore). Planted problems:

  file                                   problem              check expected to catch it
  prospectus-academic-rules-copy.pdf     exact duplicate      uniqueness (sha256)
  student-handbook-2026-mirror.pdf       exact duplicate      uniqueness (sha256)
  grading-policy-reformatted.md          near-duplicate       uniqueness (embedding)
  annual-report-2023-24-partial.pdf      truncated / corrupt  completeness + quality
  makeup-exam-notice.md (committed)      missing metadata     completeness
  fee-structure-2027-28.html             newer version        recency (old version archived)
  student-affairs-circular-attendance.md injected instruction none at ingest: the query-time
                                         (committed)          injection rail (D4)
  scanned-notice-garbled.txt             garbled extraction   quality
  hostel-annex-scan.pdf                  empty (image-only,   quality
                                         nothing to OCR)
  career-fair-2026-notice.md, convocation-2026-guidelines.md (committed): clean documents
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
OUT = HERE / "batch_b"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def blank_pdf(path: Path) -> None:
    """A one-page PDF with no text layer and nothing drawn: OCR recovers nothing."""
    content = b"q Q\n"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))


def grading_markdown() -> str:
    """The grading page re-saved as Markdown with light edits: a near-duplicate."""
    import html as h

    raw = (RAW / "grading-page.html").read_text(encoding="utf-8", errors="replace")
    for tag in ("script", "style", "header", "nav", "footer"):
        raw = re.sub(rf"<{tag}[\s>].*?</{tag}>", "\n", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", "\n", raw)
    text = h.unescape(raw).replace("﻿", "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    body = "\n".join(lines)
    body = body.replace("Academic Grading", "Grading Policy (reformatted copy)", 1)
    body = body.replace("mid term tests", "midterm tests")
    return ("---\ntitle: Grading Policy (reformatted copy)\ndoc_id: grading-policy-reformatted\n"
            "doc_version: 2026-11\ndate: 2026-11-10\n"
            "source: own (Batch B near-duplicate of the nu.edu.pk grading page)\n---\n\n" + body + "\n")


def fee_2027() -> str:
    """A newer version of the fee-structure page (doc_id fee-structure, 2027-28)."""
    s = (RAW / "fee-structure-page.html").read_text(encoding="utf-8", errors="replace")
    s = s.replace("w.e.f. Fall 2026 semester", "w.e.f. Fall 2027 semester")
    s = s.replace("academic year 2026-27", "academic year 2027-28")
    s = s.replace("Rs. 12,000", "Rs. 13,500")
    s = s.replace("Rs 2,500 towards Students Activities Fund", "Rs 3,000 towards Students Activities Fund")
    s = s.replace("<title>", "<title>[Batch B 2027-28 test version] ", 1)
    return s


def main() -> None:
    OUT.mkdir(exist_ok=True)
    shutil.copy2(RAW / "prospectus-2026-academic-rules-and-regulations.pdf",
                 OUT / "prospectus-academic-rules-copy.pdf")
    shutil.copy2(RAW / "student-handbook-jun-2026.pdf", OUT / "student-handbook-2026-mirror.pdf")
    full = (RAW / "annual-report-2023-24.pdf").read_bytes()
    (OUT / "annual-report-2023-24-partial.pdf").write_bytes(full[: int(len(full) * 0.35)])
    (OUT / "grading-policy-reformatted.md").write_text(grading_markdown(), encoding="utf-8")
    (OUT / "fee-structure-2027-28.html").write_text(fee_2027(), encoding="utf-8")
    garbled = ("Ã¢â‚¬Å“ÃƒÂ©Ã¢â‚¬â„¢ �� ÐŸÑ€Ð¸Ð²ÐµÑ‚ Ã¯Â»Â¿Ã¢â‚¬Â¢ " * 120)
    (OUT / "scanned-notice-garbled.txt").write_text(garbled, encoding="utf-8")
    blank_pdf(OUT / "hostel-annex-scan.pdf")

    index = [
        {"file": "prospectus-academic-rules-copy.pdf", "doc_id": "prospectus-academic-rules-mirror",
         "title": "Academic Rules and Regulations (mirror copy)", "doc_version": "2026",
         "date": "2026-11-01", "source": "own (Batch B exact duplicate)"},
        {"file": "student-handbook-2026-mirror.pdf", "doc_id": "student-handbook-mirror",
         "title": "Student Handbook 2026 (mirror)", "doc_version": "2026-06",
         "date": "2026-11-01", "source": "own (Batch B exact duplicate)"},
        {"file": "annual-report-2023-24-partial.pdf", "doc_id": "annual-report-2023-24-partial",
         "title": "Annual Report 2023-24 (partial download)", "doc_version": "2023-24",
         "date": "2024-06-30", "source": "own (Batch B truncated copy)",
         "bytes": len(full)},
        {"file": "fee-structure-2027-28.html", "doc_id": "fee-structure",
         "title": "Fee Structure page (2027-28)", "doc_version": "2027-28",
         "date": "2027-08-01", "source": "own (Batch B newer version of the nu.edu.pk fee page)"},
        {"file": "scanned-notice-garbled.txt", "doc_id": "scanned-notice",
         "title": "Scanned notice (garbled OCR)", "doc_version": "2026-11",
         "date": "2026-11-12", "source": "own (Batch B garbled text)"},
        {"file": "hostel-annex-scan.pdf", "doc_id": "hostel-annex",
         "title": "Hostel annex (blank scan)", "doc_version": "2026-11",
         "date": "2026-11-12", "source": "own (Batch B empty scan)"},
        {"file": "makeup-exam-notice.md"},   # deliberately no title, no date, no version
    ]
    (OUT / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    for p in sorted(OUT.iterdir()):
        print(f"{p.name:45s} {p.stat().st_size:>10d}  {sha(p)[:12]}")


if __name__ == "__main__":
    main()
