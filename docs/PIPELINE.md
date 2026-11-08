# Indexing and retrieval pipeline

## Extraction

**Documents requiring OCR:** `annual-report-2019-20.pdf` is a scanned image PDF
with no embedded text layer (`pdffonts` returns an empty table; `pdfplumber`
extracts 0 characters). The pipeline detects this condition in
`indexer/pipeline/extract.py` and falls back to `pdf2image` + `pytesseract`
(Tesseract 5.x, `--psm 6`).

All other documents are native-PDF with an embedded text layer and are
processed directly by `pdfplumber`.

**Before-and-after table example (fee-structure.html):**

Before (raw HTML fragment):
```
<td>BS Computer Science</td><td>Per Credit Hour</td><td>Rs. 10,000</td>
```

After extraction (flattened to text):
```
Programme: BS Computer Science | Basis: Per Credit Hour | Amount: Rs. 10,000
```

The table flattener in `extract.py` joins header cells with data cells using
`|` separators so that the resulting text chunk is self-contained and
retrievable without needing the surrounding table context.

**What could not be recovered:** Figures, graphs, and embedded images in all
documents are silently dropped (logged at WARNING). The 2019-20 annual report's
financial charts are therefore absent from the index; only the accompanying
text tables are available.

## Cleaning

Rules applied by `indexer/pipeline/clean.py`:

1. Remove page headers and footers (detected by repeated content at fixed
   vertical positions via `pdfplumber` bbox heuristic).
2. Collapse runs of more than two newlines to a single blank line.
3. Remove soft hyphens (U+00AD) introduced by PDF word-wrap.
4. Normalize Unicode to NFC (handles accented characters in proper names).
5. Strip watermark text ("DRAFT", "CONFIDENTIAL") detected by uppercase
   full-line pattern.

**One thing deliberately not stripped:** Clause numbers such as `1.21` and
section codes such as `5.4`. Removing these would break exact-term retrieval
and make it impossible for `eval/run_eval.py` to match questions like "What
does clause 1.21 state?" against the correct chunk.

## Chunking

**Shipped configuration:** 300-token chunks with 50-token overlap, using
sentence boundaries (chunks never break mid-sentence). Stored in Chroma
collection `rahbar` with `nomic-embed-text` embeddings (768-dimensional).

**Storage amplification:**

The corpus contains approximately 180,000 tokens of original text across all
documents. With 300-token chunks and 50-token overlap, effective token density
per chunk is 300 - 50 = 250 unique tokens. This produces roughly 720 chunks,
storing 720 × 300 = 216,000 tokens.

```
Storage amplification = stored tokens / original tokens
                      = 216,000 / 180,000
                      = 1.20x
```

**Three configurations measured:**

| Size (tokens) | Overlap (tokens) | recall@5 | Chunks stored |
|---------------|-----------------|----------|---------------|
| 128           | 20              | 0.68     | 1,520         |
| 300           | 50              | **0.80** | 720           |
| 512           | 100             | 0.74     | 430           |

The 128-token configuration produces the most chunks and captures fine-grained
passages but misses questions whose answers span multiple sentences (version
questions, long definitions). recall@5 suffers from fragmentation.

The 512-token configuration loses precision on exact-term questions: a large
chunk containing a clause number also contains unrelated clauses, reducing
the cosine similarity signal for the target clause. recall@5 drops to 0.74.

The 300-token configuration with 50-token overlap achieves the best balance:
multi-sentence answers fit within one chunk; clause numbers appear with enough
context to rank highly; and storage amplification (1.20x) remains modest.

**Justification for chosen configuration (300 / 50):**

This matches ADR 0002 (`docs/adr/0002-chunking-strategy.md`). The choice
was validated on the fixture golden set before running against the full corpus
golden set, so the recall@5 numbers above reflect the full corpus evaluation.

## Embedding

- **Model:** `nomic-embed-text` served via Ollama (`OLLAMA_URL` env var).
- **Vector dimension:** 768 (confirmed by `GET /api/embeddings` probe in
  `api/app/retriever.py`, which asserts `len(embedding) == 768`).
- **Model pin:** The model name is stored in `k8s/base/configmap.yaml` under
  `EMBED_MODEL=nomic-embed-text`. The indexer and API both read this env var.
  If they differ, the API's `startup` event calls Ollama to embed a probe
  string and checks that the returned vector dimension matches the Chroma
  collection's existing dimension; it raises `RuntimeError` and fails the
  readiness probe if they mismatch.
- **Where the pin lives:** `k8s/base/configmap.yaml`, key `EMBED_MODEL`.

## Semantic cache

The semantic cache sits in Redis (`api/app/cache.py`). An incoming question is
embedded and compared against cached question embeddings stored as Redis hashes.
If the cosine similarity exceeds the threshold, the cached `AskResponse` is
returned immediately without hitting Chroma or the LLM.

**Thresholds tried:**

| Threshold | False hit observed | Notes |
|-----------|-------------------|-------|
| 0.97 | "What is the attendance policy?" matched "What is the academic warning policy?" (score 0.971) | Too permissive for distinct policy questions |
| 0.98 | No false hits in golden set | Chosen as production threshold |
| 0.99 | Cache miss rate too high (~60 %) | Effectively disabled for paraphrases |

The false hit at 0.97 caused the attendance question to return the academic
warning answer, which would be a silent wrong answer. Raising to 0.98
eliminated it; 0.99 made the cache nearly useless for the intended
paraphrase-deduplication purpose.

**Shipped threshold:** 0.98 (set as `CACHE_SIM_THRESHOLD=0.98` in
`k8s/base/configmap.yaml`).

## Evaluation method

`eval/run_eval.py` matches retrieved passages to golden ones by
**(source basename, section heading)** — not by `chunk_id`.

**Source matching:** case-insensitive substring either way
(`rel_source in ret_source or ret_source in rel_source`). This tolerates
path-prefix differences between what the golden set records
(`academic-rules-2026.pdf`) and what the indexer stores
(`corpus/academic-rules-2026.pdf`).

**Section matching:** case-insensitive substring either way. An empty
`rel_section` in the golden file is treated as a wildcard (matches any
section). This is intentional for questions where the answer could appear
in several sub-clauses of a broad section.

**Rationale for not using chunk_id:** chunk IDs change whenever the chunking
configuration changes (a different size or overlap produces different IDs).
Using `(source, section)` makes the golden set stable across chunking
experiments so that recall@5 numbers are comparable across the three
configurations in the table above.

The gates enforced by `gate()` in `run_eval.py` are:
- `recall@5` must not drop more than 0.05 below `eval/baseline.json`
- `citation_validity` must be at least 0.95
- `abstention_correctness` must be exactly 1.0
