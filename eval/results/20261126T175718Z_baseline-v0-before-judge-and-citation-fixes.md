# RAGOps evaluation — baseline — 20261126T175718Z

API `http://api` · release `v1-c400` · collection `rahbar_v1` · embed `nomic-embed-text` @ `0a109f422b47` · chunk 400/80 · top_k 5 · golden 33 questions · seed 42

| level | metric | run 1 | run 2 | |run2 - run1| |
|---|---|---|---|---|
| module | paraphrase_mean_cosine | 0.7815 | 0.7815 | 0 |
| module | unrelated_mean_cosine | 0.3352 | 0.3352 | 0 |
| module | gap | 0.4463 | 0.4463 | 0 |
| module | embed_ms_per_chunk_sequential | 185.3 | 367.8 | 182.5 |
| module | determinism_max_abs_diff_same_request | 0 | 0 | 0 |
| component | recall@3 | 0.8214 | 0.8214 | 0 |
| component | recall@5 | 0.875 | 0.875 | 0 |
| component | mrr | 0.7452 | 0.7452 | 0 |
| component | ndcg@5 | 0.7634 | 0.7634 | 0 |
| e2e | faithfulness | 0.2105 | 0.1579 | 0.0526 |
| e2e | judge_human_agreement | — | — | — |
| e2e | abstention_correctness | 1 | 1 | 0 |
| e2e | false_abstention_rate | 0.3214 | 0.3214 | 0 |
| e2e | citation_validity | 0.6852 | 0.6981 | 0.0129 |
| e2e | answer_match | 0.5556 | 0.5769 | 0.0213 |
| e2e | latency_p50_ms | 3.794e+04 | 3.063e+04 | 7312 |
| e2e | latency_p95_ms | 4.623e+04 | 6.172e+04 | 1.549e+04 |

**Noise test** (seeded typos in ~30% of words of length >= 4 (swap/drop/duplicate), seed 42):

| metric | clean | noisy | change |
|---|---|---|---|
| recall@3 | 0.8214 | 0.7679 | -0.0535 |
| recall@5 | 0.875 | 0.8036 | -0.0714 |
| mrr | 0.7452 | 0.7224 | -0.0228 |
| ndcg@5 | 0.7634 | 0.7299 | -0.0335 |

**Retrieval by category:** answerable: recall@5 1.0, MRR 0.8333, hard: recall@5 0.5625, MRR 0.525

**p95 latency per stage (ms):** embed 130.614, generate 46065.9, guardrail 4.396, rerank 5.632, retrieve 73.522, rewrite 0.25, total 46215.644, validate 0.29
