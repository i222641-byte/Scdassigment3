"""Turns a question into an AskResponse. This is the full 8-step query pipeline.

Steps (section 3.2):
  1. Validate question (Pydantic, done by the route layer before we're called)
  2. Semantic cache check
  3. Embed + retrieve top_k passages
  4. Filter by relevance_floor
  5. Abstain honestly if no passage clears the floor
  6. Build numbered-evidence prompt (done inside the provider)
  7. Generate, validate with one retry, safe fallback (done inside the provider)
  8. Validate citations against retrieved set; store to cache if answered_from_context
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..schemas import Answer, AskResponse, Citation, RetrievedRef

log = logging.getLogger("rahbar.answer")

_ABSTAIN = Answer(
    reasoning="No retrieved passage met the relevance threshold.",
    answer=(
        "I could not find relevant information in the documentation to answer "
        "your question. Please rephrase or consult the source materials directly."
    ),
    citations=[],
    answered_from_context=False,
    confidence="low",
)


def _citation_in_retrieved(citation: Citation, passages: list) -> bool:
    """Return True if the citation's (source, section, page) matches any passage."""
    for p in passages:
        if p.source == citation.source and p.section == citation.section:
            if citation.page is None or citation.page == p.page:
                return True
    return False


def answer_question(
    question: str,
    retriever: Retriever,
    provider: LLMProvider,
    settings: Settings,
) -> AskResponse:
    # ------------------------------------------------------------------
    # Step 2: Semantic cache check
    # ------------------------------------------------------------------
    cache = None
    try:
        from .cache import SemanticCache

        cache = SemanticCache(settings)
        cached = cache.get(question)
        if cached is not None:
            log.info("serving from semantic cache")
            # Re-hydrate as AskResponse so callers always get a typed object.
            return AskResponse.model_validate(cached)
    except Exception as exc:
        log.warning("cache check failed, continuing", extra={"error": str(exc)})
        cache = None

    # ------------------------------------------------------------------
    # Step 3: Retrieve top_k passages
    # ------------------------------------------------------------------
    passages = retriever.retrieve(question, k=settings.top_k)

    # ------------------------------------------------------------------
    # Step 4: Filter by relevance_floor
    # ------------------------------------------------------------------
    passages = [p for p in passages if p.score >= settings.relevance_floor]

    # ------------------------------------------------------------------
    # Step 5: Abstain if nothing cleared the floor
    # ------------------------------------------------------------------
    if not passages:
        log.info(
            "abstaining: no passages above relevance floor",
            extra={"relevance_floor": settings.relevance_floor},
        )
        answer = _ABSTAIN
    else:
        # ------------------------------------------------------------------
        # Steps 6-7: Generate (prompt-building and retry are inside provider)
        # ------------------------------------------------------------------
        answer = provider.generate(question, passages)

        # ------------------------------------------------------------------
        # Step 8a: Validate that every citation refers to a retrieved passage
        # ------------------------------------------------------------------
        valid_citations = [
            c for c in answer.citations if _citation_in_retrieved(c, passages)
        ]
        if len(valid_citations) != len(answer.citations):
            dropped = len(answer.citations) - len(valid_citations)
            log.warning(
                "dropping hallucinated citations",
                extra={"dropped": dropped, "kept": len(valid_citations)},
            )
            answer = answer.model_copy(update={"citations": valid_citations})

    log.info(
        "answered",
        extra={
            "retriever": retriever.name,
            "provider": provider.name,
            "top_k": settings.top_k,
            "passages_above_floor": len(passages),
            "chunk_ids": [p.chunk_id for p in passages],
            "scores": [round(p.score, 4) for p in passages],
            "answered_from_context": answer.answered_from_context,
            "confidence": answer.confidence,
        },
    )

    response = AskResponse(
        request_id=request_id_var.get(),
        answer=answer.answer,
        citations=answer.citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=[
            RetrievedRef(
                chunk_id=p.chunk_id,
                source=p.source,
                section=p.section,
                page=p.page,
                score=p.score,
            )
            for p in passages
        ],
        provider=provider.name,
    )

    # ------------------------------------------------------------------
    # Step 8b: Store to cache only when we genuinely answered from context
    # ------------------------------------------------------------------
    if answer.answered_from_context and cache is not None:
        try:
            cache.put(question, response.model_dump())
        except Exception as exc:
            log.warning("cache put failed", extra={"error": str(exc)})

    return response
