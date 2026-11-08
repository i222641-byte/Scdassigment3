# ADR 0002: Chunking strategy — 300-token windows with 50-token overlap

## Status

Accepted · 2026-10-20

## Context

The retrieval quality of a RAG system depends heavily on how documents are
split into chunks. Chunks must be:
- Large enough to contain a complete, self-contained answer (clause text,
  definition, fee row).
- Small enough for the embedding to capture a specific topic rather than
  averaging over many unrelated sentences.
- Bounded in count so that Chroma index size and embedding cost stay predictable.

We evaluated three configurations on the full FAST-NUCES corpus
(see `docs/PIPELINE.md`, Chunking section for the detailed table).

The corpus has approximately 180,000 tokens across 8 documents.

## Decision

We chunk at **300 tokens per chunk with 50-token overlap**, splitting at
sentence boundaries (never mid-sentence). Section headings are prepended to
every chunk that follows them so that the chunk is self-contained.

This is implemented in `indexer/pipeline/chunk.py`.

## Options considered

**Option A — 128 tokens, 20 overlap (rejected).**
recall@5 = 0.68. Fragments multi-sentence definitions and clause text across
many tiny chunks. A question about a clause that spans 3 sentences produces
3 separate chunks, each scoring below the top-5 threshold individually even
though collectively they contain the answer. Chunk count: ~1,520 (high Chroma
storage cost and slower approximate-NN search). Storage amplification: ~1.08x
(low overlap, so little duplication, but high fragmentation causes poor recall).

**Option B — 300 tokens, 50 overlap (chosen).**
recall@5 = 0.80. The 50-token overlap ensures that a clause near a chunk
boundary appears in full in at least one of the two adjacent chunks. The
300-token window is large enough to hold a complete clause with surrounding
context (the FAST-NUCES clauses average 80-120 tokens). Chunk count: ~720.
Storage amplification: 1.20x (216,000 stored tokens / 180,000 original tokens).

**Option C — 512 tokens, 100 overlap (rejected).**
recall@5 = 0.74. Larger windows hurt exact-term recall: a chunk containing
clause 1.21 also contains clauses 1.19, 1.20, and 1.22. The embedding averages
over all four clauses, diluting the cosine similarity signal for the target.
Clause-number queries ("What does 1.21 state?") rank the correct chunk lower.
Chunk count: ~430. Storage amplification: 1.19x (similar to 300/50 because the
larger overlap is offset by fewer chunks).

**Clause-boundary splitting (considered but deferred).**
Using clause numbers as natural boundaries (a new chunk starts at each `N.N`
pattern) would solve the exact-term dilution problem. Deferred because the
pattern is not consistent across all documents (the student handbook and fee
structure do not use clause numbers), requiring per-document splitting logic.
Noted as a future improvement in the evaluation notes.

## Consequences

**Easier:**
- A single configurable `max_tokens` and `overlap_tokens` parameter covers all
  documents, simplifying the pipeline.
- Storage amplification (1.20x) is predictable and bounded.
- recall@5 of 0.80 passes the CI gate (baseline in `eval/baseline.json`).

**Harder:**
- `exact` question type remains the weakest at recall@5 = 0.65 because clause
  boundaries do not align with chunk boundaries. Future work should implement
  clause-boundary splitting for the academic rules documents.
- Increasing `max_tokens` requires re-running the indexer Job and invalidating
  the semantic cache (Redis `FLUSHDB`).

**Watch for:**
- If a new document has very long clauses (> 300 tokens each), consider
  increasing `max_tokens` to 400 and re-running the baseline eval to verify
  no regression.
