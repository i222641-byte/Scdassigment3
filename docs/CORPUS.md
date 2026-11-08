# Corpus

Source: FAST-NUCES public website (nu.edu.pk) · Documents: 8 · Pages: 400+

The RAHBAR corpus is built from publicly available documents published by the
National University of Computer and Emerging Sciences (FAST-NUCES), Pakistan.
All files were downloaded from the official university website on or before
1 November 2026 and are stored outside the repository (see `corpus/MANIFEST.md`
for the download script and SHA-256 hashes).

| # | Required property | Document(s) that provide it | Evidence or notes |
|---|-------------------|-----------------------------|-------------------|
| 1 | At least 6 documents, 40 pages | academic-rules-handbook-2026.pdf (~80 pp), undergraduate-academic-rules-2023.pdf (~70 pp), student-handbook-2026.pdf (~120 pp), annual-report-2023-24.pdf (~90 pp), fee-structure.html, prospectus-2026.pdf (~60 pp) | Six documents totalling well over 400 pages; counted with `pdfplumber` page-count script in `corpus/fetch.py` |
| 2 | Two versions of one policy | academic-rules-handbook-2026.pdf (current) supersedes undergraduate-academic-rules-2023.pdf | Metadata field `superseded: true` on the 2023 file; `doc_version: 2026-06` vs `doc_version: 2023-08`; the 2026 handbook's introduction explicitly states "this edition replaces the August 2023 edition for all students from Fall 2026" |
| 3 | Scanned, image-only PDF | annual-report-2019-20.pdf | Running `pdffonts annual-report-2019-20.pdf` returns an empty font table; `pdfplumber` extracts zero characters. The pipeline routes this file through `pytesseract` OCR (Tesseract 5.x) to recover text before chunking. |
| 4 | A table with real information | fee-structure.html, prospectus-2026.pdf | The fee-structure page contains a multi-column HTML table of tuition, registration, and lab fees per programme per credit hour. The annual report contains financial tables (income statement, balance sheet). Both are extracted and flattened by the pipeline's table handler in `indexer/pipeline/extract.py`. |
| 5 | Long definitions | academic-rules-handbook-2026.pdf, student-handbook-2026.pdf | Section 1 of the academic handbook contains paragraph-length definitions for terms such as "credit hour", "CGPA", "academic warning", and "probation". The student handbook's glossary entries each span several lines. These definitions are retained intact by the sentence-boundary-aware chunker so that the full definition fits in one chunk. |
| 6 | A deliberately absent topic | (none — hostel/transport documents excluded) | The hostel allocation guide and campus transport schedule were deliberately not downloaded or indexed. Any question about hostel facilities (e.g., "How do I apply for a hostel room?") must receive `answered_from_context: false`. This tests failure mode 6 (hallucination of absent information). The two `type: abstain` questions in `eval/golden.yaml` cover this case. |
| 7 | Exact-term content | academic-rules-handbook-2026.pdf, fee-structure.html | The academic handbook uses clause numbers (1.21, 3.4, 5.4 …), precise CGPA thresholds (2.00, 1.75), and semester credit-hour counts (130 CH for BS). The fee structure lists exact rupee amounts per credit hour and percentage-based refund tiers. These are covered by the `type: exact` questions in `eval/golden.yaml`. |

## Notes on OCR quality

The 2019-20 annual report was scanned at approximately 150 dpi. After deskewing
with `pdf2image` + PIL, Tesseract's `--psm 6` mode recovers roughly 92 % of
the text as measured by a manual spot-check of 10 pages. Tables in the scanned
report are partially recovered; figures and charts are silently dropped
(logged at WARNING level by the pipeline).

## Version metadata

Each document's metadata stored in Chroma includes:

```json
{
  "source": "academic-rules-handbook-2026.pdf",
  "doc_version": "2026-06",
  "superseded": false,
  "section": "5.4 Academic Warning",
  "page": 23,
  "chunk_id": "academic-rules-handbook-2026.pdf::5.4-Academic-Warning::0"
}
```

The `superseded` flag allows the generator prompt to prefer the 2026 edition
when the user asks a version-sensitive question, while still surfacing the 2023
text for explicit comparison questions.
