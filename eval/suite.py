#!/usr/bin/env python3
"""A03 Part B: the offline test suite at three levels (paper 4.2.5, Table 1). One command:

    python eval/suite.py --api http://localhost:8080 --label baseline
    python eval/suite.py --api ... --label baseline --repeat 2          # stochasticity (B)
    python eval/suite.py --api ... --label candidate --gate             # + release gate (C2)

  module level     embedding model: paraphrase vs unrelated cosine, gap, time per chunk,
                   determinism (same text twice, largest component difference)
  component level  retrieval: recall@3, recall@5, MRR, nDCG@5 on the golden set, then a
                   noise test (seeded typos in every query) and the change in each metric
  end-to-end       answers: faithfulness (LLM judge + agreement with hand labels),
                   abstention correctness, citation validity, answer match, latency p50/p95

Writes eval/results/<UTC timestamp>_<label>.json and .md (summary table). With --gate it then
applies eval/gate.py and exits 1 when the gate fails (the Kubernetes eval Job fails with it).
All randomness is seeded: the typo generator (SEED), the generator and the judge (Ollama seed).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
SEED = int(os.environ.get("SEED", 42))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("//")]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f)


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


class Clients:
    def __init__(self, api: str, ollama: str, embed_model: str, judge_model: str, host: str | None):
        headers = {"Host": host} if host else {}
        self.api = api.rstrip("/")
        self.http = httpx.Client(timeout=600.0, headers=headers)
        self.ollama = ollama.rstrip("/")
        self.embed_model = embed_model
        self.judge_model = judge_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(f"{self.ollama}/api/embed", json={"model": self.embed_model, "input": texts},
                       timeout=300.0)
        r.raise_for_status()
        return r.json()["embeddings"]

    def info(self) -> dict[str, Any]:
        return self.http.get(f"{self.api}/api/info").json()

    def retrieve(self, q: str, k: int = 10, include_text: bool = False) -> dict[str, Any]:
        r = self.http.post(f"{self.api}/api/retrieve", json={"question": q, "k": k,
                                                            "include_text": include_text})
        r.raise_for_status()
        return r.json()

    def ask(self, q: str) -> tuple[dict[str, Any], float]:
        t = time.perf_counter()
        r = self.http.post(f"{self.api}/api/ask", json={"question": q}, headers={"X-No-Cache": "1"})
        r.raise_for_status()
        return r.json(), (time.perf_counter() - t) * 1000

    def trace(self, trace_id: str) -> dict[str, Any] | None:
        r = self.http.get(f"{self.api}/api/trace/{trace_id}")
        return r.json()["record"] if r.status_code == 200 else None


# ---------------------------------------------------------------------------
# module level: the embedding model
# ---------------------------------------------------------------------------

def module_level(c: Clients, pairs: list[dict[str, Any]], golden: list[dict[str, Any]]) -> dict[str, Any]:
    para = [p for p in pairs if p["kind"] == "paraphrase"]
    unrel = [p for p in pairs if p["kind"] == "unrelated"]
    def sims(ps: list[dict[str, Any]]) -> list[float]:
        va = c.embed([p["a"] for p in ps])
        vb = c.embed([p["b"] for p in ps])
        return [cosine(x, y) for x, y in zip(va, vb)]
    sp, su = sims(para), sims(unrel)
    # chunk-sized texts from the live index for the timing test
    texts: list[str] = []
    for q in golden[:12]:
        for item in c.retrieve(q["question"], k=3, include_text=True)["ranked"]:
            if item.get("text") and item["text"] not in texts:
                texts.append(item["text"])
    texts = texts[:30]
    c.embed(texts[:1])                      # warm the model so load time is not counted
    t = time.perf_counter()
    for tx in texts:
        c.embed([tx])
    per_chunk_ms = (time.perf_counter() - t) * 1000 / max(1, len(texts))
    t = time.perf_counter()
    c.embed(texts)
    batched_ms = (time.perf_counter() - t) * 1000 / max(1, len(texts))
    det_texts = texts[:10]
    v1, v2 = c.embed(det_texts), c.embed(det_texts)
    max_diff = max(max(abs(a - b) for a, b in zip(x, y)) for x, y in zip(v1, v2))
    v3 = [c.embed([t_])[0] for t_ in det_texts[:5]]       # single vs batched request
    max_diff_single_vs_batch = max(max(abs(a - b) for a, b in zip(x, y)) for x, y in zip(v1[:5], v3))
    return {
        "paraphrase_pairs": len(sp), "unrelated_pairs": len(su),
        "paraphrase_mean_cosine": r4(statistics.mean(sp)),
        "unrelated_mean_cosine": r4(statistics.mean(su)),
        "gap": r4(statistics.mean(sp) - statistics.mean(su)),
        "paraphrase_min": r4(min(sp)), "unrelated_max": r4(max(su)),
        "separable": min(sp) > max(su),
        "paraphrase_p10": r4(pct(sp, 0.10)), "unrelated_p90": r4(pct(su, 0.90)),
        "embed_ms_per_chunk_sequential": round(per_chunk_ms, 2),
        "embed_ms_per_chunk_batched": round(batched_ms, 2),
        "timing_chunks": len(texts),
        "timing_chunk_mean_words": round(statistics.mean(len(t_.split()) for t_ in texts), 1) if texts else None,
        "determinism_max_abs_diff_same_request": max_diff,
        "determinism_max_abs_diff_single_vs_batch": max_diff_single_vs_batch,
        "pair_details": [{"kind": p["kind"], "a": p["a"], "b": p["b"], "cosine": r4(s)}
                         for p, s in zip(para + unrel, sp + su)],
    }


# ---------------------------------------------------------------------------
# component level: retrieval
# ---------------------------------------------------------------------------

def is_hit(item: dict[str, Any], target: dict[str, Any]) -> bool:
    """A target is {doc_id, pages?, doc_version?} or {any: [targets]} (any one counts)."""
    if "any" in target:
        return any(is_hit(item, t) for t in target["any"])
    if item.get("doc_id") != target["doc_id"]:
        return False
    if target.get("doc_version") and item.get("doc_version") and item["doc_version"] != target["doc_version"]:
        return False
    pages = target.get("pages")
    return not pages or item.get("page") in pages


def retrieval_scores(ranked: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, float]:
    """recall@k: share of ground-truth targets (doc_id + pages) found in the top k.
    MRR: 1 / rank of the first relevant chunk in the top 10 (0 if none).
    nDCG@5: a chunk gains 1 when it covers a target not covered by a higher-ranked chunk;
            IDCG assumes the min(5, #targets) targets come first."""
    def recall(k: int) -> float:
        return sum(any(is_hit(it, t) for it in ranked[:k]) for t in targets) / len(targets)
    rr = 0.0
    for i, it in enumerate(ranked[:10], 1):
        if any(is_hit(it, t) for t in targets):
            rr = 1.0 / i
            break
    covered: set[int] = set()
    dcg = 0.0
    for i, it in enumerate(ranked[:5], 1):
        new = [j for j, t in enumerate(targets) if j not in covered and is_hit(it, t)]
        if new:
            covered.add(new[0])
            dcg += 1.0 / math.log2(i + 1)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(5, len(targets)) + 1))
    return {"recall@3": recall(3), "recall@5": recall(5), "mrr": rr, "ndcg@5": dcg / idcg if idcg else 0.0}


def typo(question: str, rng: random.Random, rate: float = 0.3) -> str:
    words = question.split()
    out = []
    for w in words:
        core = re.sub(r"[^A-Za-z]", "", w)
        if len(core) >= 4 and rng.random() < rate:
            i = rng.randrange(1, len(w) - 1) if len(w) > 2 else 0
            op = rng.choice(["swap", "drop", "dup"])
            if op == "swap" and i + 1 < len(w):
                w = w[:i] + w[i + 1] + w[i] + w[i + 2:]
            elif op == "drop":
                w = w[:i] + w[i + 1:]
            else:
                w = w[:i] + w[i] + w[i:]
        out.append(w)
    return " ".join(out)


def component_level(c: Clients, golden: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [q for q in golden if q.get("ground_truth")]
    def run(perturb: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        rng = random.Random(SEED)
        per_q = []
        for q in scored:
            text = typo(q["question"], rng) if perturb else q["question"]
            r = c.retrieve(text, k=10)
            s = retrieval_scores(r["ranked"], q["ground_truth"])
            per_q.append({"id": q["id"], "category": q["category"], "query": text,
                          "top1_similarity": r["top1_similarity"], **{k: round(v, 4) for k, v in s.items()},
                          "top5": [f"{it['doc_id']}@p{it['page']}" for it in r["ranked"][:5]]})
        agg = {m: mean([p[m] for p in per_q]) for m in ("recall@3", "recall@5", "mrr", "ndcg@5")}
        by_cat: dict[str, Any] = {}
        for cat in sorted({p["category"] for p in per_q}):
            sub = [p for p in per_q if p["category"] == cat]
            by_cat[cat] = {m: mean([p[m] for p in sub]) for m in ("recall@5", "mrr")}
        agg["by_category"] = by_cat
        return agg, per_q
    clean, per_clean = run(False)
    noisy, per_noisy = run(True)
    delta = {m: r4((noisy[m] or 0) - (clean[m] or 0)) for m in ("recall@3", "recall@5", "mrr", "ndcg@5")}
    return {"questions": len(scored), **{k: v for k, v in clean.items()},
            "noise_test": {"kind": "seeded typos in ~30% of words of length >= 4 (swap/drop/duplicate)",
                           "seed": SEED, "metrics": {k: v for k, v in noisy.items() if k != "by_category"},
                           "delta": delta},
            "per_question": per_clean, "per_question_noisy": per_noisy}


# ---------------------------------------------------------------------------
# end-to-end: answers
# ---------------------------------------------------------------------------

# Judge v3 "quote and verify". v1 (free-form JSON verdict) agreed with our hand labels on 3/12
# answers in the first baseline (eval/results/20261126T175718Z_baseline.json): the 3B judge
# called clearly supported answers unsupported. v3 makes the model quote the supporting
# sentence, then checks in code that (a) the quote really occurs in the evidence and (b) every
# number in the answer occurs in the evidence block the quote comes from.
JUDGE_VERSION = "v3-quote-verify"
JUDGE = """QUESTION: {question}

ANSWER: {answer}

EVIDENCE:
{evidence}

Check the ANSWER against the EVIDENCE.
First copy, word for word, the ONE shortest sentence from the EVIDENCE that best supports the
answer (or "none" if no sentence does). Then give the verdict: "supported" if every fact in the
answer is stated in that sentence or elsewhere in the evidence, otherwise "unsupported"."""
JUDGE_SCHEMA = {"type": "object", "properties": {
    "quote": {"type": "string"},
    "verdict": {"type": "string", "enum": ["supported", "unsupported"]}}, "required": ["quote", "verdict"]}


def evidence_from_prompt(prompt_text: str) -> str:
    blocks = re.findall(r"\[EVIDENCE \d+\].*?\[/EVIDENCE \d+\]", prompt_text or "", flags=re.S)
    return "\n".join(blocks)


def _toks(x: str) -> set[str]:
    return {t for t in norm(x).split() if len(t) > 2}


def _nums(x: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)*", (x or "").replace(",", "")))


def judge(c: Clients, question: str, evidence: str, answer: str) -> dict[str, Any]:
    r = httpx.post(f"{c.ollama}/api/chat", timeout=300.0, json={
        "model": c.judge_model, "stream": False, "format": JUDGE_SCHEMA,
        "options": {"temperature": 0.0, "seed": SEED, "num_ctx": 8192, "num_predict": 400},
        "messages": [{"role": "user", "content": JUDGE.format(question=question, evidence=evidence[:12000],
                                                               answer=answer)}]})
    try:
        d = json.loads(r.json()["message"]["content"])
    except Exception as exc:
        return {"supported": None, "error": str(exc), "judge_version": JUDGE_VERSION}
    quote = d.get("quote", "")
    qn = norm(quote)
    quote_ok = bool(qn) and qn != "none" and (
        qn in norm(evidence) or len(_toks(quote) & _toks(evidence)) >= 0.8 * max(1, len(_toks(quote))))
    blocks = re.findall(r"\[EVIDENCE \d+\].*?\[/EVIDENCE \d+\]", evidence, flags=re.S)
    block = max(blocks, key=lambda b: len(_toks(quote) & _toks(b)), default="")
    nums_ok = _nums(answer) <= _nums(block)
    overlap = len(_toks(answer) & _toks(quote)) / max(1, len(_toks(answer)))
    supported = quote_ok and nums_ok and (d.get("verdict") == "supported" or overlap >= 0.5)
    return {"supported": supported, "model_verdict": d.get("verdict"), "quote": quote[:300],
            "quote_in_evidence": quote_ok, "numbers_in_quoted_block": nums_ok,
            "judge_version": JUDGE_VERSION}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9.%]+", " ", (s or "").lower()).strip()


def e2e_level(c: Clients, golden: list[dict[str, Any]], human: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for q in golden:
        try:
            resp, ms = c.ask(q["question"])
        except Exception as exc:   # one broken request must not lose the whole run
            rows.append({"id": q["id"], "category": q["category"], "question": q["question"],
                         "error": f"{type(exc).__name__}: {exc}", "answered": False, "answer": "",
                         "latency_ms": 600000.0, "stage_ms": {}, "citations": [],
                         "citations_dropped": 0, "guardrails": [], "answer_match": None})
            print(f"  {q['id']:<5} ERROR {type(exc).__name__}", flush=True)
            continue
        rec = c.trace(resp.get("trace_id", "")) or {}
        answered = bool(resp.get("answered_from_context"))
        row: dict[str, Any] = {"id": q["id"], "category": q["category"], "question": q["question"],
                               "trace_id": resp.get("trace_id"), "answered": answered,
                               "answer": resp.get("answer"), "latency_ms": round(ms, 1),
                               "stage_ms": rec.get("latency_ms", {}),
                               "citations": resp.get("citations", []),
                               "citations_dropped": rec.get("citations_dropped", 0),
                               "citations_raw": rec.get("citations_raw", []),
                               "citations_repaired": rec.get("citations_repaired", 0),
                               "guardrails": resp.get("guardrails", []),
                               "top1_similarity": rec.get("top1_similarity"),
                               "context": [f"{x['doc_id']}@p{x['page']}" for x in rec.get("context", [])]}
        exp = q.get("expected") or []
        row["answer_match"] = (all(norm(e) in norm(resp.get("answer", "")) for e in exp)
                               if exp and q["category"] != "unanswerable" else None)
        if q.get("ground_truth") and row["citations"]:
            src2doc = {x["source"]: (x["doc_id"], x.get("doc_version")) for x in resp.get("retrieved", [])}
            row["citation_hits_ground_truth"] = any(
                is_hit({"doc_id": src2doc.get(ci.get("source"), (None, None))[0],
                        "doc_version": src2doc.get(ci.get("source"), (None, None))[1],
                        "page": ci.get("page")}, t)
                for ci in row["citations"] for t in q["ground_truth"])
        if answered and rec.get("prompt"):
            row["judge"] = judge(c, q["question"], evidence_from_prompt(rec["prompt"]["text"]), resp.get("answer", ""))
        h = human.get(q["id"])
        if h:
            row["human_label"] = h["label"]
            row["human_label_matches_this_answer"] = norm(h.get("answer", "")) == norm(resp.get("answer", ""))
        rows.append(row)
        print(f"  {q['id']:<5} {ms/1000:6.1f}s answered={answered!s:<5} {q['question'][:60]}", flush=True)

    unans = [r for r in rows if r["category"] == "unanswerable"]
    answerable = [r for r in rows if r["category"] != "unanswerable"]
    judged = [r for r in rows if r.get("judge", {}).get("supported") is not None]
    valid = sum(len(r["citations"]) for r in rows)
    dropped = sum(r["citations_dropped"] for r in rows)
    raw_total = sum(len(r.get("citations_raw", [])) for r in rows)
    raw_exact = sum(sum(1 for c in r.get("citations_raw", []) if c.get("status") == "exact") for r in rows)
    lat = [r["latency_ms"] for r in rows]
    stage_names = sorted({k for r in rows for k in r["stage_ms"]})
    stage_p95 = {s: r4(pct([r["stage_ms"][s] for r in rows if s in r["stage_ms"]], 0.95)) for s in stage_names}
    agree_rows = [r for r in rows if r.get("human_label") and r.get("human_label_matches_this_answer")
                  and r.get("judge", {}).get("supported") is not None]
    agreement = (sum((r["judge"]["supported"]) == (r["human_label"] == "supported") for r in agree_rows)
                 / len(agree_rows)) if agree_rows else None
    matches = [r["answer_match"] for r in answerable if r["answer_match"] is not None]
    return {
        "questions": len(rows),
        "errors": [r["id"] for r in rows if r.get("error")],
        "faithfulness": r4(sum(r["judge"]["supported"] for r in judged) / len(judged)) if judged else None,
        "faithfulness_judged": len(judged),
        "judge_model": c.judge_model, "judge_version": JUDGE_VERSION,
        "judge_human_agreement": r4(agreement), "judge_human_labels_compared": len(agree_rows),
        "abstention_correctness": r4(sum(not r["answered"] for r in unans) / len(unans)) if unans else None,
        "false_abstention_rate": r4(sum(not r["answered"] for r in answerable) / len(answerable)) if answerable else None,
        # raw = the model's own citations that exactly match a context chunk (source + page);
        # served = citations the user receives after grounded repair (always context chunks)
        "citation_validity": r4(raw_exact / raw_total) if raw_total else (r4(valid / (valid + dropped)) if (valid + dropped) else None),
        "citation_validity_served": r4(valid / (valid + dropped)) if (valid + dropped) else None,
        "citations_raw_total": raw_total, "citations_raw_exact": raw_exact,
        "citations_repaired": sum(r.get("citations_repaired", 0) for r in rows),
        "citations_valid": valid, "citations_dropped_invalid": dropped,
        "answer_match": r4(sum(matches) / len(matches)) if matches else None,
        "latency_p50_ms": r4(pct(lat, 0.5)), "latency_p95_ms": r4(pct(lat, 0.95)),
        "stage_p95_ms": stage_p95,
        "injection_flags": sum(1 for r in rows for g in r["guardrails"] if g.get("rail") == "injection"),
        "per_question": rows,
    }


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

HEADLINE = [
    ("module", "paraphrase_mean_cosine"), ("module", "unrelated_mean_cosine"), ("module", "gap"),
    ("module", "embed_ms_per_chunk_sequential"), ("module", "determinism_max_abs_diff_same_request"),
    ("component", "recall@3"), ("component", "recall@5"), ("component", "mrr"), ("component", "ndcg@5"),
    ("e2e", "faithfulness"), ("e2e", "judge_human_agreement"), ("e2e", "abstention_correctness"),
    ("e2e", "false_abstention_rate"), ("e2e", "citation_validity"), ("e2e", "answer_match"),
    ("e2e", "latency_p50_ms"), ("e2e", "latency_p95_ms"),
]


def headline(run: dict[str, Any]) -> dict[str, Any]:
    return {f"{lvl}.{m}": run[lvl].get(m) for lvl, m in HEADLINE}


def markdown(result: dict[str, Any]) -> str:
    runs = result["runs"]
    lines = [f"# RAGOps evaluation — {result['label']} — {result['timestamp']}", "",
             f"API `{result['api']}` · release `{result['info'].get('release')}` · collection "
             f"`{result['info'].get('collection')}` · embed `{result['info'].get('embed_model')}` @ "
             f"`{result['info'].get('collection_metadata', {}).get('embed_digest')}` · chunk "
             f"{result['info'].get('collection_metadata', {}).get('chunk_size')}/"
             f"{result['info'].get('collection_metadata', {}).get('chunk_overlap')} · top_k "
             f"{result['info'].get('top_k')} · golden {result['golden_size']} questions · seed {SEED}", ""]
    hdr = ["level", "metric"] + [f"run {i + 1}" for i in range(len(runs))]
    if len(runs) > 1:
        hdr.append("|run2 - run1|")
    lines += ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    heads = [headline(r) for r in runs]
    for lvl, m in HEADLINE:
        key = f"{lvl}.{m}"
        vals = [h[key] for h in heads]
        row = [lvl, m] + ["—" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v)) for v in vals]
        if len(runs) > 1:
            a, b = vals[0], vals[1]
            row.append("—" if a is None or b is None else f"{abs(b - a):.4g}")
        lines.append("| " + " | ".join(row) + " |")
    nt = runs[0]["component"]["noise_test"]
    lines += ["", f"**Noise test** ({nt['kind']}, seed {nt['seed']}):", "",
              "| metric | clean | noisy | change |", "|---|---|---|---|"]
    for m in ("recall@3", "recall@5", "mrr", "ndcg@5"):
        lines.append(f"| {m} | {runs[0]['component'][m]} | {nt['metrics'][m]} | {nt['delta'][m]:+} |")
    bc = runs[0]["component"].get("by_category", {})
    if bc:
        lines += ["", "**Retrieval by category:** " + ", ".join(
            f"{k}: recall@5 {v['recall@5']}, MRR {v['mrr']}" for k, v in bc.items())]
    lines += ["", f"**p95 latency per stage (ms):** " + ", ".join(
        f"{k} {v}" for k, v in runs[0]["e2e"]["stage_p95_ms"].items())]
    if result.get("gate"):
        g = result["gate"]
        lines += ["", f"## Release gate: **{'PASS' if g['passed'] else 'FAIL'}** (baseline `{g.get('baseline')}`)", "",
                  "| check | value | threshold | result |", "|---|---|---|---|"]
        for ch in g["checks"]:
            lines.append(f"| {ch['check']} | {ch['value']} | {ch['threshold']} | {'pass' if ch['passed'] else 'FAIL'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="RAHBAR RAGOps offline test suite (A03 Part B)")
    ap.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8080"))
    ap.add_argument("--host", default=os.environ.get("API_HOST"))
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text"))
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "llama3.2:3b"))
    ap.add_argument("--golden", type=Path, default=Path(os.environ.get("GOLDEN", HERE / "golden.jsonl")))
    ap.add_argument("--pairs", type=Path, default=HERE / "embedding_pairs.jsonl")
    ap.add_argument("--human", type=Path, default=HERE / "human_labels.jsonl")
    ap.add_argument("--label", default=os.environ.get("EVAL_LABEL", "run"))
    ap.add_argument("--repeat", type=int, default=int(os.environ.get("EVAL_REPEAT", 1)))
    ap.add_argument("--out-dir", type=Path, default=Path(os.environ.get("RESULTS_DIR", HERE / "results")))
    ap.add_argument("--gate", action="store_true", default=os.environ.get("EVAL_GATE", "") == "1")
    ap.add_argument("--gate-config", type=Path, default=Path(os.environ.get("GATE_CONFIG", HERE / "gate.yaml")))
    ap.add_argument("--baseline", type=Path, default=Path(os.environ.get("BASELINE", HERE / "results" / "baseline.json")))
    ap.add_argument("--save-baseline", action="store_true", default=os.environ.get("SAVE_BASELINE", "") == "1")
    ap.add_argument("--skip", default=os.environ.get("EVAL_SKIP", ""), help="comma list: module,component,e2e")
    args = ap.parse_args()

    golden = load_jsonl(args.golden)
    pairs = load_jsonl(args.pairs)
    human = {h["id"]: h for h in load_jsonl(args.human)} if args.human.exists() else {}
    c = Clients(args.api, args.ollama, args.embed_model, args.judge_model, args.host)
    info = c.info()
    skip = set(filter(None, args.skip.split(",")))
    print(f"suite: label={args.label} api={args.api} collection={info.get('collection')} "
          f"golden={len(golden)} repeat={args.repeat}", flush=True)
    runs = []
    for i in range(args.repeat):
        print(f"== run {i + 1}/{args.repeat}", flush=True)
        run: dict[str, Any] = {}
        run["module"] = {} if "module" in skip else module_level(c, pairs, golden)
        print("   module level done", flush=True)
        run["component"] = {} if "component" in skip else component_level(c, golden)
        print("   component level done", flush=True)
        run["e2e"] = {} if "e2e" in skip else e2e_level(c, golden, human)
        print("   end-to-end level done", flush=True)
        runs.append(run)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result: dict[str, Any] = {"label": args.label, "timestamp": ts, "api": args.api, "info": info,
                              "golden": str(args.golden), "golden_size": len(golden), "seed": SEED,
                              "runs": runs, "summary": headline(runs[0])}
    if len(runs) > 1:
        h1, h2 = headline(runs[0]), headline(runs[1])
        result["stochasticity"] = {k: (None if v is None or h2[k] is None else r4(abs(h2[k] - v)))
                                   for k, v in h1.items()}
        diffs = []
        for a, b in zip(runs[0]["e2e"]["per_question"], runs[1]["e2e"]["per_question"]):
            if norm(a["answer"]) != norm(b["answer"]) or a["answered"] != b["answered"]:
                diffs.append({"id": a["id"], "run1": a["answer"], "run2": b["answer"],
                              "answered": [a["answered"], b["answered"]]})
        result["stochasticity_answer_differences"] = diffs
    exit_code = 0
    if args.gate:
        from gate import apply_gate, load_thresholds
        baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else None
        g = apply_gate(result["summary"], baseline.get("summary") if baseline else None,
                       load_thresholds(args.gate_config))
        g["baseline"] = str(args.baseline) if baseline else None
        g["gate_config"] = str(args.gate_config)
        result["gate"] = g
        exit_code = 0 if g["passed"] else 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{ts}_{args.label}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = markdown(result)
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    (args.out_dir / f"latest_{args.label}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.save_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\n" + md, flush=True)
    print(f"results: {out}", flush=True)
    if args.gate:
        print(f"RELEASE GATE: {'PASS' if exit_code == 0 else 'FAIL'}", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
