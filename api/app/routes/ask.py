"""Query routes. The Ingress sends /api/* here unchanged, so the prefix stays.

  POST /api/ask              answer a question (writes a trace)
  POST /api/retrieve         ranked retrieval only, no generation (component-level eval, A03 B)
  GET  /api/trace/{id}       a trace record plus the prompt rebuilt from its chunk ids (A03 D2)
  GET  /api/info             release, collection, embedding model and version
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .. import tracing
from ..prompting import build_prompt, prompt_hash
from ..schemas import AskRequest, AskResponse
from ..services.answer import answer_question, retrieve_ranked

router = APIRouter(prefix="/api")


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request,
        x_no_cache: str | None = Header(default=None)) -> AskResponse:
    state = request.app.state
    return answer_question(body.question, state.retriever, state.provider, state.settings,
                           use_cache=not x_no_cache)


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    k: int = Field(default=10, ge=1, le=50)
    include_text: bool = False


@router.post("/retrieve")
def retrieve(body: RetrieveRequest, request: Request) -> dict:
    state = request.app.state
    t = time.perf_counter()
    r = retrieve_ranked(body.question, state.retriever, state.settings, body.k)
    return {
        "question": body.question, "rewritten": r["rewritten"], "filters": r["where"] or {},
        "collection": state.settings.collection,
        "top1_similarity": round(max((p.score for p in r["pool"]), default=0.0), 4),
        "ranked": [{"rank": i + 1, "chunk_id": p.chunk_id, "doc_id": p.doc_id, "source": p.source,
                    "doc_version": p.doc_version, "page": p.page, "score": round(p.score, 4),
                    "rerank_score": s, **({"text": p.text} if body.include_text else {})}
                   for i, (p, s) in enumerate(zip(r["ranked"], r["rr_scores"]))],
        "latency_ms": {**r["timer"].ms, "total": round((time.perf_counter() - t) * 1000, 2)},
    }


@router.get("/trace/{trace_id}")
def trace(trace_id: str, request: Request) -> dict:
    state = request.app.state
    rec = tracing.find(trace_id, state.settings.trace_dir)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} not found")
    return {"record": rec, "rebuild": rebuild_prompt(rec, state.retriever)}


def rebuild_prompt(rec: dict, retriever: object) -> dict:
    """Fetch the context chunks by id from the vector store and re-render the template.
    A matching hash proves the stored prompt is exactly what produced the answer."""
    ids = rec.get("context_chunk_ids") or []
    prompt = rec.get("prompt") or {}
    if not ids or not prompt:
        return {"rebuilt": False, "reason": "no prompt was sent (abstained before generation or cache hit)"}
    chunks = retriever.get_chunks(ids)  # type: ignore[attr-defined]
    missing = [i for i in ids if i not in chunks]
    if missing:
        return {"rebuilt": False, "reason": f"chunks no longer in the collection: {missing}"}
    passages = [chunks[i] for i in ids]
    text = build_prompt(rec.get("prompt_question") or rec["query"], passages, prompt.get("template", "v1"))
    h = prompt_hash(text)
    return {"rebuilt": True, "hash": h, "matches_trace": h == prompt.get("hash"), "text": text}


@router.get("/info")
def info(request: Request) -> dict:
    s = request.app.state.settings
    r = request.app.state.retriever
    return {"release": s.release, "collection": s.collection,
            "collection_metadata": r.info(max_age=0) if hasattr(r, "info") else {},
            "embed_model": s.embed_model, "llm_model": s.llm_model, "top_k": s.top_k,
            "temperature": s.temperature, "seed": s.seed, "rerank": s.rerank,
            "relevance_floor": s.relevance_floor, "prompt_template": s.prompt_template}
