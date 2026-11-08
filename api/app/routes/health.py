"""Liveness and readiness (section 4.3). They answer different questions.

/healthz  – Is the process alive? Must never touch Chroma, Redis, or the LLM.
/readyz   – Are all runtime dependencies reachable and consistent?
            Returns 503 and names the failing check if anything is wrong.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    """Check all runtime dependencies and return 503 if any are unhealthy."""
    settings = request.app.state.settings
    checks: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 1. Chroma: reachable, collection exists, non-empty, embed model matches
    # ------------------------------------------------------------------
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        col = client.get_collection(settings.collection)
        count = col.count()
        if count == 0:
            raise ValueError("collection is empty")

        meta = col.metadata or {}
        stored_model = meta.get("embed_model", "")
        if stored_model and stored_model != settings.embed_model:
            checks["embed_model"] = (
                f"mismatch: stored={stored_model}, configured={settings.embed_model}"
            )
            response.status_code = 503
            return {"status": "not ready", "checks": checks}

        checks["chroma"] = f"ok ({count} chunks)"
    except Exception as exc:
        checks["chroma"] = f"error: {exc}"
        response.status_code = 503
        return {"status": "not ready", "checks": checks}

    # ------------------------------------------------------------------
    # 2. Redis
    # ------------------------------------------------------------------
    try:
        import redis as redis_lib

        r = redis_lib.from_url(settings.redis_url)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        response.status_code = 503
        return {"status": "not ready", "checks": checks}

    return {"status": "ready", "checks": checks}
