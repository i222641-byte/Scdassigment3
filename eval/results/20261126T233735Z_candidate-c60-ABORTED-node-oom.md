# RAGOps evaluation — candidate — 20261126T233735Z

API `http://api-candidate` · release `v3-c60-candidate` · collection `rahbar_v3_c60` · embed `nomic-embed-text` @ `0a109f422b47` · chunk 60/0 · top_k 5 · golden 33 questions · seed 42

| level | metric | run 1 |
|---|---|---|
| module | paraphrase_mean_cosine | 0.7815 |
| module | unrelated_mean_cosine | 0.3352 |
| module | gap | 0.4463 |
| module | embed_ms_per_chunk_sequential | 59.9 |
| module | determinism_max_abs_diff_same_request | 0 |
| component | recall@3 | 0.8929 |
| component | recall@5 | 0.8929 |
| component | mrr | 0.7798 |
| component | ndcg@5 | 0.8062 |
| e2e | faithfulness | 0.8 |
| e2e | judge_human_agreement | 0.6667 |
| e2e | abstention_correctness | 1 |
| e2e | false_abstention_rate | 0.25 |
| e2e | citation_validity | 1 |
| e2e | answer_match | 0.7727 |
| e2e | latency_p50_ms | 1.553e+04 |
| e2e | latency_p95_ms | 6e+05 |

**Noise test** (seeded typos in ~30% of words of length >= 4 (swap/drop/duplicate), seed 42):

| metric | clean | noisy | change |
|---|---|---|---|
| recall@3 | 0.8929 | 0.8214 | -0.0715 |
| recall@5 | 0.8929 | 0.8214 | -0.0715 |
| mrr | 0.7798 | 0.7714 | -0.0084 |
| ndcg@5 | 0.8062 | 0.779 | -0.0272 |

**Retrieval by category:** answerable: recall@5 1.0, MRR 0.8667, hard: recall@5 0.625, MRR 0.5625

**p95 latency per stage (ms):** embed 106.442, generate 20702.36, guardrail 0.257, rerank 0.481, retrieve 228.966, rewrite 0.037, total 20764.898, validate 0.087

## Release gate: **FAIL** (baseline `/ops/results/baseline.json`)

| check | value | threshold | result |
|---|---|---|---|
| recall@5 drop vs baseline | 0.8929 | >= 0.8750 - 0.02 = 0.8550 | pass |
| faithfulness | 0.8 | >= 0.8 | pass |
| p95 latency (ms) | 600000.0 | <= 45000 | FAIL |
| abstention correctness | 1.0 | >= 1.0 (baseline) | pass |
| citation validity | 1.0 | >= 0.8 | pass |
| false abstention rate | 0.25 | <= 0.4 | pass |
