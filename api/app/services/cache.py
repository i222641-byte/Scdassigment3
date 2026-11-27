"""Semantic cache using Redis (section 3.3).

Questions that are semantically near (cosine similarity >= cache_threshold)
a previously seen question get their response served instantly, without
touching the retriever or the LLM.

If Redis is unavailable the cache degrades silently: get() always returns
None and put() is a no-op, so the rest of the pipeline is unaffected.
"""

from __future__ import annotations

import json
import logging
import math

import httpx

from ..config import Settings

log = logging.getLogger("rahbar.cache")

_CACHE_KEY_PREFIX = "rahbar:cache:"
_INDEX_KEY = "rahbar:cache:index"  # sorted set: member=cache_key, score=0 (for SSCAN)


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    def __init__(self, settings: Settings, scope: str = "") -> None:
        # A03: entries are scoped by collection + index_version. A re-index bumps
        # index_version, so stale answers are never served and the ingestion Job needs no
        # access to Redis (it stays the only writer of exactly one store: Chroma).
        self._prefix = _CACHE_KEY_PREFIX + (scope + ":" if scope else "")
        self._index_key = self._prefix + "index"
        self._settings = settings
        self._redis = None
        self._embed_url = settings.ollama_url
        self._embed_model = settings.embed_model

        try:
            import redis

            r = redis.from_url(settings.redis_url, decode_responses=True)
            r.ping()
            self._redis = r
            log.info("redis cache connected", extra={"url": settings.redis_url})
        except Exception as exc:
            log.warning(
                "redis unavailable, cache disabled", extra={"error": str(exc)}
            )
            self._redis = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float] | None:
        """Embed a single string via Ollama. Returns None on failure."""
        try:
            url = f"{self._embed_url}/api/embed"
            resp = httpx.post(
                url,
                json={"model": self._embed_model, "input": [text]},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings") or data.get("embedding")
            if isinstance(embeddings[0], list):
                return embeddings[0]
            return embeddings
        except Exception as exc:
            log.warning("cache embed failed", extra={"error": str(exc)})
            return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, question: str) -> dict | None:
        """Return a cached AskResponse dict if a near-enough question exists."""
        if self._redis is None:
            return None

        vec = self._embed(question)
        if vec is None:
            return None

        try:
            # Walk all cache keys stored in our index set
            cursor = 0
            best_sim = -1.0
            best_key: str | None = None

            while True:
                cursor, members = self._redis.sscan(self._index_key, cursor=cursor, count=100)
                for key in members:
                    raw = self._redis.get(key)
                    if raw is None:
                        continue
                    entry = json.loads(raw)
                    stored_vec: list[float] = entry["vector"]
                    sim = _cosine(vec, stored_vec)
                    if sim > best_sim:
                        best_sim = sim
                        best_key = key
                        best_response = entry["response"]
                if cursor == 0:
                    break

            if best_key is not None and best_sim >= self._settings.cache_threshold:
                log.info(
                    "cache hit",
                    extra={"similarity": round(best_sim, 4), "key": best_key},
                )
                return best_response  # type: ignore[return-value]

            return None
        except Exception as exc:
            log.warning("cache get failed", extra={"error": str(exc)})
            return None

    @staticmethod
    def _never_cache(response: dict) -> bool:
        """Return True for responses that must never be cached.

        Abstentions (answered_from_context=False) must not be stored — a
        re-index may add the previously-missing document, and replaying a
        cached abstention would silently regress recall for that topic.
        """
        return not response.get("answered_from_context", True)

    def put(self, question: str, response: dict) -> None:
        """Store the question vector and response dict in Redis."""
        if self._redis is None:
            return
        if self._never_cache(response):
            log.debug("skipping cache put: abstention never cached")
            return

        vec = self._embed(question)
        if vec is None:
            return

        try:
            import hashlib

            key = self._prefix + hashlib.sha256(question.encode()).hexdigest()
            entry = json.dumps({"vector": vec, "response": response})
            self._redis.set(key, entry, ex=7 * 24 * 3600)
            self._redis.sadd(self._index_key, key)
            log.debug("cache put", extra={"key": key})
        except Exception as exc:
            log.warning("cache put failed", extra={"error": str(exc)})

    def invalidate_all(self) -> None:
        """Flush all cache entries – called after a re-index so stale answers are evicted."""
        if self._redis is None:
            return

        try:
            # Collect all tracked keys then delete them and the index
            keys = list(self._redis.smembers(self._index_key))
            if keys:
                self._redis.delete(*keys)
            self._redis.delete(self._index_key)
            log.info("cache invalidated", extra={"evicted": len(keys)})
        except Exception as exc:
            log.warning("cache invalidate failed", extra={"error": str(exc)})
