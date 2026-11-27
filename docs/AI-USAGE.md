# AI usage

All AI assistance is disclosed below. Specific disclosure carries no academic penalty.

| Tool | What it wrote or shaped | What we changed afterwards, and why |
|------|------------------------|-------------------------------------|
| Claude Sonnet 4.6 (Claude Code) | Drafted initial implementations of `recall_at_k`, `citation_validity`, `summarise`, and `gate` in `eval/run_eval.py` | Changed the section-matching logic in `recall_at_k` to use a bidirectional substring check (`rel_section in ret_section or ret_section in rel_section`) rather than equality, because equality was too strict for headings that include clause numbers as prefixes (e.g., "5.4 Academic Warning" vs "Academic Warning"). Verified the new logic against all fixture questions manually. |
| Claude Sonnet 4.6 (Claude Code) | Suggested the initial structure of `eval/golden.yaml` and question phrasing for the 15 golden questions | Revised question ids, section names, and `expect` strings to match the actual section headings produced by our chunker (e.g., changing `section: "Warning"` to `section: "Academic Warning"` to match the PDF heading). Added the injection question prefix verbatim from a real adversarial prompt we observed in testing. |
| Claude Sonnet 4.6 (Claude Code) | Drafted boilerplate for `.github/workflows/ci.yml` and `.github/workflows/cd.yml` | Adjusted `working-directory` values to match our monorepo layout; replaced the generic smoke-test curl with the actual `/api/ask` endpoint and response field check; added the `--ignore-missing-imports` flag to mypy because several third-party stubs are absent. |
| Claude Sonnet 4.6 (Claude Code) | Drafted the first version of the system prompt used in `api/app/generator.py` for structured JSON output | Rewrote the abstention instruction after failure analysis (Stage 4 in `docs/FAILURE-ANALYSIS.md`) showed the original wording was not strong enough to prevent hallucination when `retrieved` was empty. |
| Claude Sonnet 4.6 (Claude Code) | Suggested the chunking experiment table structure in `docs/PIPELINE.md` | Replaced placeholder recall@5 numbers with values measured during our actual three-configuration experiments on the fixture corpus. The 128/300/512 token configurations were run by us; the AI did not run any experiments. |
| GitHub Copilot (tab completion) | Auto-completed repetitive Pydantic model field definitions in `api/app/schemas.py` and boilerplate `pytest` fixtures in `api/tests/` | Accepted completions for straightforward field definitions; manually wrote and verified all test assertions to ensure they test real behaviour rather than implementation details. |

## Assignment 03 (RAGOps)

| Tool | What it wrote or shaped | What we checked or changed, and why |
|---|---|---|
| Claude (Claude Code, Opus 5.5) | Most of the A03 code: verification stage, data-lake registry, incremental sync, trace record and trace tool, guardrails, citation repair, evaluation suite, gate, coverage script, Kubernetes manifests and helper scripts, first drafts of `docs/RAGOPS.md` and the report text | Ran the unit tests (34 api + 22 indexer passing) and every Job on our minikube cluster. The runs exposed defects that were then fixed and re-measured: a judge that disagreed with our labels (v1 agreement 0.25 -> v3 0.71), citations with printed page numbers (grounded repair), a generation runaway (token cap), and OOM kills (limits set from kubectl top). Failed runs are kept and labelled in eval/results/k8s/. |
| Claude (Claude Code, Opus 5.5) | Drafted the 24 `human`-labelled golden questions (checked against the cited PDF pages) and the first hand labels of 12 answers | Every question was checked against its cited PDF page, and every hand label was re-checked against the evidence block in its trace on 27 Nov 2026. The questions are marked `human` because they were written for this set rather than generated from chunks; they were drafted with AI assistance, as stated here. |
| `llama3.2:3b` (local, via Ollama) | Generated the 18 raw synthetic question drafts (`eval/synthetic_candidates.jsonl`); also the answer generator and the faithfulness judge inside the pipeline | A reviewer kept 9 drafts and reworded 6 of them; see `eval/GOLDEN.md` |

Every number in the report comes from runs of our own pipeline on our own minikube cluster;
the result files are committed under `eval/results/` and `traces/`.
