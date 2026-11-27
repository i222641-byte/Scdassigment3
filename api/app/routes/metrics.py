"""Prometheus metrics at /metrics (section 4.8).

Request count and latency are wired up already. The generation, retrieval,
cache, abstention, fallback and token metrics are populated from answer.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

router = APIRouter()

# --- HTTP layer ---
REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

# --- RAG pipeline ---
RETRIEVAL_LATENCY = Histogram(
    "rahbar_retrieval_seconds",
    "Vector retrieval latency",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2),
)
GENERATION_LATENCY = Histogram(
    "rahbar_generation_seconds",
    "LLM generation latency",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)

CACHE_HITS = Counter("rahbar_cache_hits_total", "Semantic cache hits")
CACHE_MISSES = Counter("rahbar_cache_misses_total", "Semantic cache misses")
ABSTENTIONS = Counter("rahbar_abstentions_total", "Questions answered_from_context=false")
FALLBACKS = Counter("rahbar_fallbacks_total", "LLM validation failures that used the canned fallback")

# --- A03 D3: RAGOps monitoring signals -------------------------------------------------
TOP1_SIMILARITY = Histogram(
    "rahbar_top1_similarity",
    "Cosine similarity of the best retrieved chunk per query (before the relevance floor)",
    buckets=(0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0),
)
STAGE_LATENCY = Histogram(
    "rahbar_stage_seconds",
    "Latency per query-pipeline stage",
    ["stage"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
INJECTION_FLAGGED = Counter("rahbar_injection_flagged_total",
                            "Injection attempts flagged by the guardrail", ["stage"])
QUERIES = Counter("rahbar_queries_total", "Queries answered, by outcome", ["outcome"])

TOKENS_IN = Counter("rahbar_tokens_in_total", "Input tokens sent to the LLM")
TOKENS_OUT = Counter("rahbar_tokens_out_total", "Output tokens received from the LLM")


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
