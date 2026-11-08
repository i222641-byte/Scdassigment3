"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import IndexerSettings

# Maximum number of texts sent to Ollama in a single request
_BATCH_SIZE = 100


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed *texts* with *settings.embed_model* via the Ollama API.

    Calls POST {ollama_url}/api/embed with body::

        {"model": "<model>", "input": ["text1", "text2", ...]}

    Ollama returns::

        {"embeddings": [[0.1, 0.2, ...], ...]}

    Requests are batched at _BATCH_SIZE texts per call to avoid timeouts
    on large corpora.  Returns one float vector per input text, in order.
    """
    all_vectors: list[list[float]] = []
    url = settings.ollama_url.rstrip("/") + "/api/embed"

    for batch_start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[batch_start : batch_start + _BATCH_SIZE]
        vectors = _call_ollama(url, settings.embed_model, batch)
        all_vectors.extend(vectors)

    return all_vectors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_ollama(url: str, model: str, texts: list[str]) -> list[list[float]]:
    """POST one batch to the Ollama /api/embed endpoint and return embeddings."""
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama embed request failed with HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {url}: {exc.reason}"
        ) from exc

    embeddings = body.get("embeddings")
    if not isinstance(embeddings, list):
        raise RuntimeError(
            f"Unexpected Ollama response (no 'embeddings' key): {body!r}"
        )
    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"Ollama returned {len(embeddings)} vectors for {len(texts)} texts"
        )
    return embeddings
