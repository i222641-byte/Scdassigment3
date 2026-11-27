"""Runtime configuration, read once from environment variables.

On the cluster these variables come from the ConfigMap (envFrom) and, for the values that
define a *release* (collection, release label), from the Deployment's pod template `env`,
so that `kubectl rollout undo` reverts them (A03 F3). Nothing is baked into the image.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    retriever: str = "stub"          # RETRIEVER: stub | chroma
    llm_provider: str = "stub"       # LLM_PROVIDER: stub | ollama-host | ollama-incluster | hosted

    embed_model: str = "nomic-embed-text"

    chroma_host: str = "chroma"
    chroma_port: int = 8000
    collection: str = "rahbar_v1"

    top_k: int = 5
    temperature: float = 0.2
    seed: int = 42                   # SEED: fixed so repeated runs are comparable (A03 B)
    llm_model: str = "llama3.2:3b"
    ollama_url: str = "http://host.minikube.internal:11434"
    hosted_base_url: str = ""
    llm_api_key: str = field(default="", repr=False)

    log_level: str = "INFO"

    relevance_floor: float = 0.35
    cache_threshold: float = 0.92
    redis_url: str = "redis://redis:6379"

    # A03 additions
    rerank: str = "lexical"          # RERANK: lexical | none
    candidate_pool: int = 2          # CANDIDATE_POOL: fetch top_k * this, rerank, keep top_k
    prompt_template: str = "v1"      # PROMPT_TEMPLATE
    trace_dir: str = ""              # TRACE_DIR: volume for trace JSON lines ("" = stdout only)
    release: str = "dev"             # RELEASE: label of the running release (pod template env)
    guardrails: bool = True          # GUARDRAILS: injection rail on query and retrieved chunks


def get_settings() -> Settings:
    return Settings(
        retriever=os.environ.get("RETRIEVER", "stub"),
        llm_provider=os.environ.get("LLM_PROVIDER", "stub"),
        embed_model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
        chroma_host=os.environ.get("CHROMA_HOST", "chroma"),
        chroma_port=_int("CHROMA_PORT", 8000),
        collection=os.environ.get("CHROMA_COLLECTION", "rahbar_v1"),
        top_k=_int("TOP_K", 5),
        temperature=_float("TEMPERATURE", 0.2),
        seed=_int("SEED", 42),
        llm_model=os.environ.get("LLM_MODEL", "llama3.2:3b"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"),
        hosted_base_url=os.environ.get("HOSTED_BASE_URL", ""),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        relevance_floor=_float("RELEVANCE_FLOOR", 0.35),
        cache_threshold=_float("CACHE_THRESHOLD", 0.92),
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379"),
        rerank=os.environ.get("RERANK", "lexical"),
        candidate_pool=_int("CANDIDATE_POOL", 2),
        prompt_template=os.environ.get("PROMPT_TEMPLATE", "v1"),
        trace_dir=os.environ.get("TRACE_DIR", ""),
        release=os.environ.get("RELEASE", "dev"),
        guardrails=os.environ.get("GUARDRAILS", "true").lower() != "false",
    )
