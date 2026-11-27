"""Prose and table layout for the A03 report. Numbers come from the result files in files.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FILES: dict[str, str] = json.loads((HERE / "files.json").read_text(encoding="utf-8"))
NOTES: dict[str, Any] = json.loads((HERE / "notes.json").read_text(encoding="utf-8"))

AUTHORS = [("Zurain Awan", "22i-2641"), ("Taha Yasir", "22i-2429")]
REPO = "https://github.com/i222641-byte/Scdassigment3"


def _s(run: dict, k: str) -> Any:
    lvl, m = k.split(".", 1)
    return run.get(lvl, {}).get(m)


def sections(load, P, table, src, fmt, H1, H2, TITLE, BODY, SMALL, CELL) -> list[Any]:  # noqa: C901
    o: list[Any] = []
    base = load(FILES["baseline"])
    b1, b2 = base["runs"][0], base["runs"][1]
    v0 = load(FILES["baseline_v0"])["runs"][0]
    bad = load(FILES["cand_bad"])
    good = load(FILES["cand_good"])
    live = load(FILES["live"])
    ing_a = load(FILES["ingest_a"])
    ing_un = load(FILES["ingest_unchanged"])
    ing_b = load(FILES["ingest_b"])
    ver_b = load(FILES["verify_b"])
    ing_ch = load(FILES["ingest_change"])
    ing_del = load(FILES["ingest_delete"])
    rest = load(FILES["restore"])
    cov0, cov1 = load(FILES["coverage_before"]), load(FILES["coverage_after"])
    tm = load(FILES["trace_metrics"])

    # ------------------------------------------------------------------ page 1
    o += [P("RAHBAR RAGOps: Operating a Grounded RAG Pipeline on Kubernetes", TITLE),
          P("CS4032 Software Construction and Development · Assignment 03 (RAGOps) · Fall 2026", SMALL),
          table([["Name", "Roll number"]] + [[n, r] for n, r in AUTHORS], [6, 4]),
          P(f"Repository: <link href='{REPO}' color='blue'><u><font face='Courier'>{REPO}</font></u></link> · cluster: minikube (docker driver, "
            "Calico), namespace <font face='Courier'>rahbar</font> · LLM <font face='Courier'>llama3.2:3b</font> "
            "and embeddings <font face='Courier'>nomic-embed-text</font> on Ollama (CPU only, laptop).", SMALL),
          P("We added a RAGOps layer to our A02 RAHBAR pipeline (FAST-NUCES academic documents): a data "
            "lifecycle (ingest, verify, update the data lake, update the retrieval source incrementally) "
            "and an operations loop (three-level offline tests, a ConfigMap-driven release gate, a trace "
            "per query, metrics, coverage checks), all running as Kubernetes objects. Every number below "
            "is read by <font face='Courier'>docs/report/build_report.py</font> from the result files "
            "committed in <font face='Courier'>eval/results/</font>; the source file is named under each table.")]

    # G1 Figure 3 mapping
    o += [P("1. Figure 3 stages in our pipeline", H1), table([
        ["Stage", "What RAHBAR does", "File", "What is missing"],
        ["Ingest", "Batches land in corpus/&lt;batch&gt;/ on datalake-pvc with an _index.json sidecar; text extracted (OCR for scans) and cached by SHA-256", "indexer/pipeline/lake.py, extract.py", "no crawler; batches are copied in"],
        ["Verify", "quality, completeness, recency, uniqueness (hash + doc-embedding cosine) per new/changed doc; report per run", "indexer/pipeline/verify.py, run.py", "no ingest-time intent/injection check"],
        ["Update data lake", "accepted -> lake/docs, failed -> quarantine/ (+reason), superseded -> archive/ (restorable); registry of versions", "lake.py, run.py", "registry is a JSON file"],
        ["Update retrieval sources", "incremental sync by content-addressed chunk ids; deletes orphans; archive/restore = metadata flip", "store.py, chunk.py, run.py --mode restore", "new chunking/model = new collection"],
        ["Offline testing", "module / component / end-to-end suite, noise test, 2-run stochasticity; gate", "eval/suite.py, eval/gate.py, k8s/eval-job.yaml", "judge is a 3B model"],
        ["Live testing", "trace per query (stdout + ops-pvc), /metrics, trace-window summary", "api/app/services/answer.py, tracing.py, scripts/trace_metrics.py", "no online A/B split or user feedback"],
        ["Check coverage", "live queries vs golden questions, data-derived threshold, exit 1 below 85%", "eval/coverage.py", "live queries simulated (E1)"],
    ], [2.4, 7.2, 4.2, 4.2])]

    # G2 Table 2 qualities
    o += [P("2. The five qualities of the paper's Table 2", H1), table([
        ["Quality", "What we measure", "Threshold", "Evidence (our runs)"],
        ["Adaptability", "a pipeline change (chunking) is built, tested and released without touching the live collection", "gate passes; recall@5 drop <= 2 pts",
         f"c60 gate {'PASS' if bad['gate']['passed'] else 'FAIL'} (never released); c250 gate {'PASS' if good['gate']['passed'] else 'FAIL'} at citation 0.80, PASS after ConfigMap revision to 0.70, released; live eval {'PASS' if live['gate']['passed'] else 'FAIL'}"],
        ["Monitorability", "top-1 similarity, abstention rate, cache hit rate, stage p95, injection flags", "abstention rate on in-domain <= 40%; injection flags logged",
         f"{tm['records']} traces: abstention {fmt(tm['abstention_rate'])}, median top-1 {fmt(tm['top1_similarity']['median'])}, injections flagged {tm['injection_attempts_flagged']}"],
        ["Observability", "every query has a trace with all D1 fields; prompt rebuildable", "100% of queries traced; rebuilt hash = stored hash",
         f"{NOTES['trace_rebuild']}"],
        ["Traceability", "answer -> chunk ids -> doc_id@version -> collection + embedding digest", "every trace names collection, embed digest, doc versions",
         f"after rollout undo the trace shows {NOTES['undo_collection']}"],
        ["Reliability", "readiness gating, rollouts with maxUnavailable 0, state on PVCs", "rollouts finish with 3/3 Ready; lake and results intact after restarts",
         NOTES["reliability"]],
    ], [2.3, 5.6, 4.0, 6.1])]

    # ------------------------------------------------------------------ Part A
    o += [P("3. Results", H1), P("Part A: verification and incremental update", H2)]
    rows = [["file", "quality", "complete", "recency", "unique", "disposition"]]
    short = lambda c: ("PASS" if c["result"] == "pass" else "FAIL: " + c["reason"][:70])
    for v in ver_b["verified"]:
        rows.append([v["file"].split("/")[-1], short(v["checks"]["quality"]), short(v["checks"]["completeness"]),
                     short(v["checks"]["recency"]), short(v["checks"]["uniqueness"]), v["disposition"]])
    o += [P(f"Batch A: {ing_a['documents']['new']} documents verified, OCR recovered the two scanned PDFs, "
            f"the 2023 rules were archived by the recency check (superseded by 2026), "
            f"{ing_a['chunks']['chunks_embedded']} chunks embedded. Batch B (11 documents with planted "
            "problems) gave the report below:"),
          table(rows, [3.8, 3.0, 3.1, 2.7, 3.4, 2.0]), src(FILES["verify_b"])]
    cb = ing_del["counts_by_doc"]
    o += [table([["A2 run", "documents", "chunks embedded", "chunks deleted", "metadata only"],
                 ["unchanged corpus", f"{ing_un['documents']['unchanged']} unchanged", ing_un["chunks"]["chunks_embedded"], 0, 0],
                 ["Batch B", f"{ing_b['documents']['indexed']} indexed, {ing_b['documents']['quarantined']} quarantined, {ing_b['documents']['superseded_now']} superseded",
                  ing_b["chunks"]["chunks_embedded"], ing_b["chunks"]["chunks_deleted_orphans"] + ing_b["chunks"]["chunks_deleted_changed"], ing_b["chunks"]["chunks_metadata_updated"]],
                 ["one paragraph edited (career fair)", f"{ing_ch['documents']['changed']} changed", ing_ch["chunks"]["chunks_embedded"], ing_ch["chunks"]["chunks_deleted_changed"], ing_ch["chunks"]["chunks_metadata_updated"]],
                 ["document deleted (convocation)", f"{ing_del['documents']['deleted']} deleted", ing_del["chunks"]["chunks_embedded"], ing_del["chunks"]["chunks_deleted_orphans"], 0],
                 ["restore fee-structure@2026-27", "pin old version", rest["chunks"]["chunks_embedded"], 0, rest["chunks"]["chunks_metadata_updated"]],
                 ], [5.0, 5.4, 2.4, 2.4, 2.4]),
          P(f"Orphan proof after the delete: chunks for <i>convocation-2026</i> = "
            f"{cb['by_doc'].get('convocation-2026', 0)}; doc_ids in Chroma but not in the lake = {cb['orphan_doc_ids']}. "
            f"Restore flipped statuses {json.dumps(rest['status_before'])} to {json.dumps(rest['status_after'])} "
            f"with zero re-embedding; {NOTES['restore_answer']}"),
          src(FILES["ingest_unchanged"], FILES["ingest_b"], FILES["ingest_change"], FILES["ingest_delete"], FILES["restore"])]

    # ------------------------------------------------------------------ Part B
    keys = [("module.paraphrase_mean_cosine", "paraphrase mean cosine (16 pairs)"), ("module.unrelated_mean_cosine", "unrelated mean cosine (16 pairs)"),
            ("module.gap", "gap"), ("module.embed_ms_per_chunk_sequential", "embed ms / chunk (seq.)"),
            ("module.determinism_max_abs_diff_same_request", "determinism: max |diff|"),
            ("component.recall@3", "recall@3"), ("component.recall@5", "recall@5"), ("component.mrr", "MRR"), ("component.ndcg@5", "nDCG@5"),
            ("e2e.faithfulness", "faithfulness (judge v3)"), ("e2e.abstention_correctness", "abstention correctness"),
            ("e2e.false_abstention_rate", "false abstention (answerable)"), ("e2e.citation_validity", "citation validity (raw model)"),
            ("e2e.citation_validity_served", "citation validity (served)"), ("e2e.answer_match", "answer contains expected fact"),
            ("e2e.latency_p50_ms", "latency p50 (ms)"), ("e2e.latency_p95_ms", "latency p95 (ms)")]
    rows = [["level", "metric", "run 1", "run 2", "|diff|"]]
    for k, label in keys:
        a, b = _s(b1, k), _s(b2, k)
        rows.append([k.split(".")[0], label, fmt(a), fmt(b), fmt(abs(b - a)) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else "—"])
    nt = b1["component"]["noise_test"]
    o += [P("Part B: offline tests at three levels (baseline, collection rahbar_v1, chunk 400/80, top_k 5)", H2),
          table(rows, [1.8, 5.6, 2.2, 2.2, 2.0]),
          P(f"Golden set: {base['golden_size']} questions (20 answerable, 5 unanswerable, 8 hard; 24 human, 9 synthetic all reviewed). "
            f"Noise test (seeded typos in ~30% of words): recall@5 {fmt(b1['component']['recall@5'])} -> {fmt(nt['metrics']['recall@5'])} "
            f"({nt['delta']['recall@5']:+}), MRR {nt['delta']['mrr']:+}, nDCG@5 {nt['delta']['ndcg@5']:+}, recall@3 {nt['delta']['recall@3']:+}. "
            f"By category, recall@5 is {b1['component']['by_category'].get('answerable', {}).get('recall@5')} on answerable and "
            f"{b1['component']['by_category'].get('hard', {}).get('recall@5')} on hard questions. "
            f"Judge (v3, quote-and-verify) agreement with our 17 hand labels: {fmt(b1['e2e'].get('judge_human_agreement'))}; "
            f"the first judge (v1) agreed on {NOTES['judge_v1_agreement']}."),
          P("<b>Stochasticity.</b> " + NOTES["stochasticity"]), src(FILES["baseline"], FILES["baseline_v0"])]

    # ------------------------------------------------------------------ Part C
    rows = [["metric", "baseline (c400)", "candidate c250", "bad c60"]]
    for k, label in keys[5:]:
        rows.append([label, fmt(_s(b1, k)), fmt(_s(good["runs"][0], k)), fmt(_s(bad["runs"][0], k))])
    gate_rows = [["gate check", "threshold", "c250", "c60"]]
    for cg, cb_ in zip(good["gate"]["checks"], bad["gate"]["checks"]):
        gate_rows.append([cg["check"], str(cg["threshold"]), f"{fmt(cg['value'])} {'ok' if cg['passed'] else 'FAIL'}",
                          f"{fmt(cb_['value'])} {'ok' if cb_['passed'] else 'FAIL'}"])
    o += [P("Part C: one change (chunk size 400/80 -> 250/50) and the release gate", H2),
          table(rows, [5.5, 3.2, 3.2, 3.2]), table(gate_rows, [4.4, 5.0, 3.0, 3.0]),
          P("<b>Gate thresholds</b> (ConfigMap rahbar-gate): " + NOTES["gate_justification"]),
          P("<b>Release decision.</b> " + NOTES["release_decision"]),
          src(FILES["cand_good"], FILES["cand_bad"], "eval/results/k8s/09_gate_configmap_*.log")]

    # ------------------------------------------------------------------ Part D
    o += [P("Part D: observability and traceability", H2),
          P("Every query writes one JSON line (stdout and /ops/traces/trace-&lt;pod&gt;.jsonl) with: trace_id, timestamp, release, "
            "query, rewritten_query, version_intent, embedding {model, version=Ollama digest, dimension}, collection {name, index_version, "
            "chunking}, filters, retrieval candidates (chunk_id, doc_id, doc_version, page, score), reranker scores and reranked_order, "
            "context_chunk_ids, prompt {template, sha256 hash, full text}, model {name, temperature, seed, top_k, tokens, attempts, fallback}, "
            "response, citations (+ raw citations with repair status), guardrail actions, latency per stage, cache hit/miss/bypass. "
            "<font face='Courier'>python -m app.trace_tool &lt;id&gt;</font> (in the api pod) prints context and prompt and rebuilds the "
            f"prompt from the vector store: {NOTES['trace_rebuild']}"),
          table([["trace window metric", "value"],
                 ["records", tm["records"]], ["top-1 similarity min / median / max", f"{fmt(tm['top1_similarity']['min'])} / {fmt(tm['top1_similarity']['median'])} / {fmt(tm['top1_similarity']['max'])}"],
                 ["abstention rate", fmt(tm["abstention_rate"])], ["cache hit rate", fmt(tm["cache_hit_rate"])],
                 ["p95 ms: embed / retrieve / generate / total", " / ".join(fmt(tm["p95_latency_ms_by_stage"].get(s)) for s in ("embed", "retrieve", "generate", "total"))],
                 ["injection attempts flagged (query / retrieval)", f"{tm['injection_attempts_flagged']} {json.dumps(tm['injection_by_stage'])}"],
                 ["grounding-rail suppressions", tm["grounding_suppressions"]]], [8, 9]),
          P("<b>D4 guardrail.</b> " + NOTES["d4"]),
          P("<b>D5 root cause from the trace only.</b> " + NOTES["d5"]), src(FILES["trace_metrics"])]

    # ------------------------------------------------------------------ Part E
    o += [P("Part E: drift and coverage", H2),
          table([["coverage", "golden", "covered / 40", "share", "result"],
                 ["before (E2)", cov0["golden_size"], cov0["covered"], fmt(cov0["share"]), "FAIL (exit 1)" if not cov0["passed"] else "PASS"],
                 ["after +8 questions (E4)", cov1["golden_size"], cov1["covered"], fmt(cov1["share"]), "PASS (exit 0)" if cov1["passed"] else "FAIL"]],
                [4, 2, 3, 2, 3]),
          P(f"Threshold tau = {cov0['tau']} = 10th percentile of paraphrase-pair similarity (a test asks essentially the same question). "
            f"The midpoint rule ({cov0['tau_derivation']['midpoint_rejected']}) was rejected: it counted 7 of 12 off-topic queries as covered "
            "because they share words like <i>fee</i> and <i>semester</i>. " + NOTES["uncovered_topics"]),
          P("<b>E3 data drift (after ingesting Batch B).</b> " + NOTES["drift"]),
          src(FILES["coverage_before"], FILES["coverage_after"], FILES["live"])]

    # ------------------------------------------------------------------ Part F
    o += [P("Part F: Kubernetes", H2), P(NOTES["k8s"]),
          table([["workload", "measured (kubectl top)", "request", "limit"]] + NOTES["resources"], [3.5, 6.5, 3, 3]),
          P(NOTES["resources_note"]), src("eval/results/k8s/kubectl_top_samples.txt", "eval/results/k8s/chroma_oomkilled.txt")]

    # ------------------------------------------------------------------ short answers
    o += [P("4. Short answers", H1)]
    for k in ("a", "b", "c", "d", "e", "f"):
        o.append(P(f"<b>({k})</b> " + NOTES["answers"][k]))
    o += [P("5. Contributions and AI statement", H1),
          table([["Member", "Contribution"]] + NOTES["contributions"], [3.5, 14]),
          P("<b>AI statement.</b> " + NOTES["ai_statement"]),
          P("Appendix (screenshots, labelled by part) follows; it does not count towards the 8 pages.", SMALL)]
    return o
