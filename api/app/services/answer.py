"""Turns a question into an AskResponse, and writes one trace record per query (A03 D1).

Stages (each one timed into the trace and into rahbar_stage_seconds):
  cache      semantic cache lookup, scoped to collection + index_version
  rewrite    abbreviation expansion and version-intent detection
  embed      question -> vector with the pinned embedding model
  retrieve   top (top_k * candidate_pool) from Chroma, superseded filter unless version intent
  rerank     lexical rerank, keep top_k
  guardrail  injection rail on the query and on the retrieved chunks
  generate   prompt -> schema-constrained Answer (validate, retry once, fall back)
  validate   drop citations that do not match a chunk in the context
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from .. import guardrails, tracing
from ..config import Settings
from ..logjson import request_id_var
from ..prompting import build_prompt, prompt_hash
from ..providers.llm.base import GEN_META, LLMProvider
from ..rerank import rerank, rewrite
from ..retrieval.base import Retriever
from ..routes import metrics as M
from ..schemas import Answer, AskResponse, Citation, Passage, RetrievedRef

log = logging.getLogger("rahbar.answer")

_ABSTAIN = Answer(
    reasoning="No retrieved passage met the relevance threshold.",
    answer=("I could not find this in the FAST-NUCES documents I have indexed, so I cannot "
            "answer it reliably. Please check with the relevant office."),
    citations=[],
    answered_from_context=False,
    confidence="low",
)


def _citation_in_retrieved(citation: Citation, passages: list[Passage]) -> bool:
    """A citation is valid when its source matches a context chunk and, if it names a page,
    the page matches that chunk too. Sections are free text the model may shorten."""
    for p in passages:
        if p.source == citation.source and (citation.page is None or citation.page == p.page):
            return True
    return False


def resolve_citation(c: Citation, ctx: list[Passage]) -> tuple[Citation | None, str]:
    """Map a model citation onto a chunk that was actually in the context, or reject it.

    The 3B model often copies the right source but the wrong page: the *printed* page number
    from the text (e.g. 5 for PDF page 10) or the evidence block number (1, 2, ...). In the
    first baseline that dropped valid citations and the grounding rail then suppressed correct
    answers. Repair is grounded, never invented: a citation is only ever mapped to a chunk in
    the context, and the trace records the status of every raw citation.
      exact          source and page match a context chunk
      block-index    page is an evidence block number whose chunk has that source
      section-text   the cited section/clause label occurs in exactly one same-source chunk
      single-source  only one context chunk has that source
      rejected       none of the above (fabricated or ambiguous)
    """
    same = [p for p in ctx if p.source == c.source]
    if not same:
        return None, "rejected"
    if c.page is None or any(p.page == c.page for p in same):
        return c, "exact"
    if c.page is not None and 1 <= c.page <= len(ctx) and ctx[c.page - 1].source == c.source:
        p = ctx[c.page - 1]
        return Citation(source=p.source, section=p.section or c.section, page=p.page), "block-index"
    label = (c.section or "").strip()
    if len(label) >= 2:
        hits = [p for p in same if label.lower() in p.text.lower()]
        if len({p.page for p in hits}) == 1:
            return Citation(source=c.source, section=c.section, page=hits[0].page), "section-text"
    if len({p.page for p in same}) == 1:
        return Citation(source=c.source, section=c.section, page=same[0].page), "single-source"
    return None, "rejected"


class _Timer:
    def __init__(self) -> None:
        self.ms: dict[str, float] = {}

    def run(self, stage: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
        t = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - t
            self.ms[stage] = round(self.ms.get(stage, 0.0) + elapsed * 1000, 2)
            M.STAGE_LATENCY.labels(stage=stage).observe(elapsed)


def _ref(p: Passage, rank: int | None = None) -> dict[str, Any]:
    d = {"chunk_id": p.chunk_id, "doc_id": p.doc_id, "source": p.source,
         "doc_version": p.doc_version, "page": p.page, "section": p.section[:80],
         "score": round(p.score, 4), "superseded": p.superseded}
    if rank is not None:
        d["rank"] = rank
    return d


def retrieve_ranked(question: str, retriever: Retriever, settings: Settings, k: int,
                    timer: _Timer | None = None) -> dict[str, Any]:
    """Rewrite -> embed -> search -> rerank. Shared by /api/ask and /api/retrieve (eval)."""
    timer = timer or _Timer()
    rewritten, version_intent = timer.run("rewrite", rewrite, question)
    where = None if version_intent else {"superseded": False}
    vec = timer.run("embed", retriever.embed, rewritten)
    pool = timer.run("retrieve", retriever.search, vec, max(k, k * settings.candidate_pool), where)
    ranked, rr_scores = timer.run("rerank", rerank, rewritten, pool, settings.rerank)
    return {"rewritten": rewritten, "version_intent": version_intent, "where": where,
            "pool": pool, "ranked": ranked[:k], "rr_scores": rr_scores[:k], "timer": timer}


def answer_question(question: str, retriever: Retriever, provider: LLMProvider,
                    settings: Settings, use_cache: bool = True) -> AskResponse:
    started = time.perf_counter()
    timer = _Timer()
    trace_id = request_id_var.get()
    if trace_id in ("", "-"):
        import uuid

        trace_id = uuid.uuid4().hex
    info = retriever.info() if hasattr(retriever, "info") else {}
    scope = f"{settings.collection}:{info.get('index_version', '')}"
    record: dict[str, Any] = {
        "kind": "trace", "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "release": settings.release, "pod": os.environ.get("HOSTNAME", "local"),
        "query": question,
        "embedding": {"model": info.get("embed_model", settings.embed_model),
                      "version": info.get("embed_digest", "unknown"),
                      "dimension": info.get("dimension"),
                      "configured_model": settings.embed_model},
        "collection": {"name": settings.collection, "index_version": info.get("index_version"),
                       "chunk_size": info.get("chunk_size"), "chunk_overlap": info.get("chunk_overlap")},
    }

    # ---- cache --------------------------------------------------------------------------
    cache = None
    cache_state = "bypass"
    if use_cache:
        try:
            from .cache import SemanticCache

            cache = SemanticCache(settings, scope=scope)
            cached = timer.run("cache", cache.get, question)
            cache_state = "miss"
            if cached is not None:
                M.CACHE_HITS.inc()
                resp = AskResponse.model_validate({**cached, "request_id": trace_id,
                                                   "trace_id": trace_id, "cache": "hit"})
                record.update({"cache": "hit", "cached_from_trace_id": cached.get("trace_id"),
                               "rewritten_query": None, "filters": None,
                               "retrieval": {"candidates": [r.model_dump() for r in resp.retrieved]},
                               "reranked_order": [r.chunk_id for r in resp.retrieved],
                               "context_chunk_ids": [r.chunk_id for r in resp.retrieved],
                               "prompt": None, "model": None,
                               "response": {"answer": resp.answer,
                                            "answered_from_context": resp.answered_from_context,
                                            "confidence": resp.confidence},
                               "citations": [c.model_dump() for c in resp.citations],
                               "guardrails": resp.guardrails, "abstained": not resp.answered_from_context,
                               "latency_ms": {**timer.ms, "total": round((time.perf_counter() - started) * 1000, 2)}})
                tracing.emit(record, settings.trace_dir)
                M.QUERIES.labels(outcome="cache_hit").inc()
                return resp
            M.CACHE_MISSES.inc()
        except Exception as exc:
            log.warning("cache check failed, continuing", extra={"error": str(exc)})
            cache, cache_state = None, "error"

    # ---- retrieve -----------------------------------------------------------------------
    r = retrieve_ranked(question, retriever, settings, settings.top_k, timer)
    pool: list[Passage] = r["pool"]
    ranked: list[Passage] = r["ranked"]
    top1 = max((p.score for p in pool), default=0.0)
    if pool:
        M.TOP1_SIMILARITY.observe(top1)

    # ---- guardrails ---------------------------------------------------------------------
    actions: list[dict[str, Any]] = []
    context = ranked
    if settings.guardrails:
        def _rails() -> tuple[list[Passage], list[dict[str, Any]]]:
            q_actions = guardrails.check_query(question)
            kept, c_actions = guardrails.filter_passages(ranked)
            return kept, q_actions + c_actions
        context, actions = timer.run("guardrail", _rails)
        for a in actions:
            if a["rail"] == "injection":
                M.INJECTION_FLAGGED.labels(stage=a["stage"]).inc()

    prompt_question = question
    for a in actions:
        if a.get("stage") == "query" and a.get("sanitized_query"):
            prompt_question = a["sanitized_query"]
    above_floor = [p for p in context if p.score >= settings.relevance_floor]
    GEN_META.set({})
    prompt_text: str | None = None
    citations_dropped = 0
    citations_repaired = 0
    citations_raw: list[dict[str, Any]] = []
    if not above_floor:
        answer = _ABSTAIN
        abstain_reason = "no chunk above relevance floor"
    else:
        prompt_text = build_prompt(prompt_question, above_floor, settings.prompt_template)
        answer = timer.run("generate", provider.generate, prompt_question, above_floor, prompt_text)
        abstain_reason = None if answer.answered_from_context else "model abstained"

        def _validate() -> Answer:
            valid: list[Citation] = []
            seen: set[tuple] = set()
            if not answer.answered_from_context:
                return answer.model_copy(update={"citations": []})  # an abstention cites nothing
            for c in answer.citations:
                fixed, status = resolve_citation(c, above_floor)
                citations_raw.append({**c.model_dump(), "status": status,
                                      "resolved_page": fixed.page if fixed else None})
                if fixed is None:
                    continue
                key = (fixed.source, fixed.page)
                if key not in seen:
                    seen.add(key)
                    valid.append(fixed)
            return answer.model_copy(update={"citations": valid})
        citations_raw: list[dict[str, Any]] = []
        validated = timer.run("validate", _validate)
        citations_dropped = sum(1 for c in citations_raw if c["status"] == "rejected")
        citations_repaired = sum(1 for c in citations_raw if c["status"] not in ("exact", "rejected"))
        if validated.answered_from_context and not validated.citations:
            # grounding rail: a claim with no citation to a context chunk is not served
            actions.append({"rail": "grounding", "stage": "output", "action": "suppressed",
                            "reason": "answered_from_context=true but no valid citation",
                            "suppressed_answer": validated.answer[:200]})
            validated = _ABSTAIN.model_copy(update={"reasoning": "uncited answer suppressed"})
            abstain_reason = "grounding rail: uncited answer suppressed"
        answer = validated
    gen = GEN_META.get() or {}
    if gen.get("fallback"):
        M.FALLBACKS.inc()
    M.TOKENS_IN.inc(gen.get("tokens_in", 0))
    M.TOKENS_OUT.inc(gen.get("tokens_out", 0))
    if not answer.answered_from_context:
        M.ABSTENTIONS.inc()
    M.QUERIES.labels(outcome="answered" if answer.answered_from_context else "abstained").inc()
    M.RETRIEVAL_LATENCY.observe((timer.ms.get("embed", 0) + timer.ms.get("retrieve", 0)) / 1000)
    if "generate" in timer.ms:
        M.GENERATION_LATENCY.observe(timer.ms["generate"] / 1000)
    timer.ms["total"] = round((time.perf_counter() - started) * 1000, 2)

    response = AskResponse(
        request_id=trace_id, trace_id=trace_id,
        answer=answer.answer, citations=answer.citations,
        answered_from_context=answer.answered_from_context, confidence=answer.confidence,
        retrieved=[RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section,
                                page=p.page, score=p.score, doc_id=p.doc_id,
                                doc_version=p.doc_version) for p in above_floor],
        provider=provider.name, cache=cache_state, guardrails=actions,
        collection=settings.collection, release=settings.release,
    )

    record.update({
        "cache": cache_state,
        "rewritten_query": r["rewritten"] if r["rewritten"] != question else None,
        "version_intent": r["version_intent"],
        "filters": r["where"] or {},
        "retrieval": {"k": settings.top_k, "pool_size": len(pool),
                      "candidates": [_ref(p, i + 1) for i, p in enumerate(pool)]},
        "reranker": {"name": settings.rerank, "scores": r["rr_scores"]},
        "reranked_order": [p.chunk_id for p in ranked],
        "relevance_floor": settings.relevance_floor,
        "top1_similarity": round(top1, 4),
        "context_chunk_ids": [p.chunk_id for p in above_floor],
        "context": [_ref(p) for p in above_floor],
        "guardrails": actions,
        "prompt_question": prompt_question if prompt_question != question else None,
        "prompt": ({"template": settings.prompt_template, "hash": prompt_hash(prompt_text),
                    "text": prompt_text} if prompt_text else None),
        "model": {"provider": provider.name, "name": settings.llm_model,
                  "temperature": settings.temperature, "seed": settings.seed,
                  "top_k": settings.top_k, "candidate_pool": settings.candidate_pool,
                  "tokens_in": gen.get("tokens_in"), "tokens_out": gen.get("tokens_out"),
                  "attempts": gen.get("attempts"), "fallback": gen.get("fallback", False)},
        "response": {"answer": answer.answer, "answered_from_context": answer.answered_from_context,
                     "confidence": answer.confidence},
        "citations": [c.model_dump() for c in answer.citations],
        "citations_dropped": citations_dropped,
        "citations_repaired": citations_repaired,
        "citations_raw": citations_raw,
        "abstained": not answer.answered_from_context,
        "abstain_reason": abstain_reason,
        "latency_ms": timer.ms,
    })
    tracing.emit(record, settings.trace_dir)

    if answer.answered_from_context and cache is not None and not actions:
        try:
            cache.put(question, response.model_dump())
        except Exception as exc:
            log.warning("cache put failed", extra={"error": str(exc)})
    return response
