# Golden set and evaluation data (A03 Part B, E)

| File | What it is |
|---|---|
| `golden.jsonl` | The golden set: one question per line (format below) |
| `synthetic_candidates.jsonl` | Raw LLM-drafted candidates from `synth_questions.py` (before review) |
| `embedding_pairs.jsonl` | 16 paraphrase pairs + 16 unrelated pairs for the module-level test |
| `human_labels.jsonl` | Hand labels (supported / unsupported) of answers, to measure judge agreement |
| `live_queries.jsonl` | E1: 40 queries "as if from users" (28 in-domain, 12 off-topic) |
| `gate.yaml` | C2: release-gate thresholds (cluster copy: ConfigMap `rahbar-gate`) |

## Composition (before E4)

| category | count | requirement |
|---|---|---|
| answerable (ground-truth document + page) | 20 | >= 15 |
| unanswerable (correct behaviour: abstain) | 5 | >= 5 |
| hard (2 paraphrase, 2 multi-chunk, 1 injection, 3 Batch B) | 8 | >= 5 |
| **total** | **33** (41 after E4) | >= 25 |
| origin `human` | 24 | >= 8 |
| origin `synthetic`, all `reviewed: true` | 9 | >= 8 reviewed |

E4 added 8 questions (g34-g41) for the uncovered topics: 6 must-abstain (transport, transport fee, cafeteria, sports booking, parking, Wi-Fi) and 2 answerable (SGPA formula, rechecking fee). Coverage rose from 65% to 92.5%.

## Line format

```json
{"id": "g01", "question": "...", "category": "answerable|unanswerable|hard",
 "hard_kind": null|"paraphrase"|"multi-chunk"|"injection"|"batch-b",
 "origin": "human|synthetic", "reviewed": true,
 "ground_truth": [{"doc_id": "ug-academic-rules", "pages": [24, 25], "doc_version": "optional"}],
 "expected": ["2.00"], "notes": "..."}
```

* `ground_truth` lists the targets a retriever must find. A target names a `doc_id` (stable
  across versions), the PDF page numbers (1-based page index of the file, not the printed page
  number), and optionally a `doc_version`. `{"any": [targets]}` means any one of them counts
  (for example, the B+ grade point appears in three documents).
* The academic rules handbook is printed as two-page spreads, so most clauses appear on two
  consecutive PDF pages; both pages are listed.
* `expected` holds short strings the answer must contain (case and punctuation ignored); it
  drives the `answer_match` metric, not the gate.

## How the questions were made (be honest about this in the report)

* **synthetic (9):** drafted by `llama3.2:3b` from sampled chunks by `synth_questions.py`
  (`synthetic_candidates.jsonl` keeps all 18 raw drafts). A reviewer kept 9: 3 unchanged,
  6 reworded to stand alone; each fact was checked on the cited page. Dropped drafts were
  unanswerable from their own chunk (#5, #10, #13), asked for a URL (#14), had a wrong draft
  answer (#4, #1) or an ambiguous page context (#6, Islamabad acreage).
* **human (24 + 8 in E4):** written for this set (not generated from chunks) and checked against
  the cited PDF page. They were drafted with AI assistance (Claude); see `docs/AI-USAGE.md`.
* **Hand labels** in `human_labels.jsonl` are judgements of specific answers from the baseline
  run, made by reading the answer against the evidence in its trace; all 17 were re-checked
  against their trace evidence on 27 Nov 2026 (3 unsupported: g20, g27, g28).
