# RAGOps evaluation — baseline — 20261126T185430Z

API `http://api` · release `v1-c400` · collection `rahbar_v1` · embed `nomic-embed-text` @ `0a109f422b47` · chunk 400/80 · top_k 5 · golden 33 questions · seed 42

| level | metric | run 1 | run 2 | |run2 - run1| |
|---|---|---|---|---|
| module | paraphrase_mean_cosine | 0.7815 | 0.7815 | 0 |
| module | unrelated_mean_cosine | 0.3352 | 0.3352 | 0 |
| module | gap | 0.4463 | 0.4463 | 0 |
| module | embed_ms_per_chunk_sequential | 194.1 | 244.6 | 50.51 |
| module | determinism_max_abs_diff_same_request | 0 | 0 | 0 |
| component | recall@3 | 0.8214 | 0.8214 | 0 |
| component | recall@5 | 0.875 | 0.875 | 0 |
| component | mrr | 0.7452 | 0.7452 | 0 |
| component | ndcg@5 | 0.7634 | 0.7634 | 0 |
| e2e | faithfulness | 0.9 | 0.9048 | 0.0048 |
| e2e | judge_human_agreement | — | — | — |
| e2e | abstention_correctness | 1 | 1 | 0 |
| e2e | false_abstention_rate | 0.6429 | 0.25 | 0.3929 |
| e2e | citation_validity | 0.8621 | 0.8654 | 0.0033 |
| e2e | answer_match | 0.7692 | 0.6667 | 0.1025 |
| e2e | latency_p50_ms | 6e+05 | 3.368e+04 | 5.663e+05 |
| e2e | latency_p95_ms | 6e+05 | 5.169e+04 | 5.483e+05 |

**Noise test** (seeded typos in ~30% of words of length >= 4 (swap/drop/duplicate), seed 42):

| metric | clean | noisy | change |
|---|---|---|---|
| recall@3 | 0.8214 | 0.7679 | -0.0535 |
| recall@5 | 0.875 | 0.8036 | -0.0714 |
| mrr | 0.7452 | 0.7224 | -0.0228 |
| ndcg@5 | 0.7634 | 0.7299 | -0.0335 |

**Retrieval by category:** answerable: recall@5 1.0, MRR 0.8333, hard: recall@5 0.5625, MRR 0.525

**p95 latency per stage (ms):** embed 139.578, generate 61881.254, guardrail 1.438, rerank 2.676, retrieve 3726.42, rewrite 0.38, total 61960.854, validate 1.124
