"""The real retriever. Embeds the question with Ollama, queries ChromaDB,
and maps results to Passage objects (sections 3.2 and 4.4).
"""

from __future__ import annotations

import logging

import httpx

from ..config import Settings
from ..schemas import Passage

log = logging.getLogger("rahbar.retrieval.chroma")


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb  # the thin client, from chromadb-client in requirements.txt
        from chromadb.config import Settings as ChromaSettings

        self._settings = settings
        self._client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _embed(self, text: str) -> list[float]:
        """Embed a single string using the Ollama embed endpoint."""
        url = f"{self._settings.ollama_url}/api/embed"
        payload = {"model": self._settings.embed_model, "input": [text]}
        resp = httpx.post(url, json=payload, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        # Ollama /api/embed returns {"embeddings": [[...], ...]}
        embeddings = data.get("embeddings") or data.get("embedding")
        if isinstance(embeddings[0], list):
            return embeddings[0]
        return embeddings

    def retrieve(self, question: str, k: int) -> list[Passage]:
        """Embed the question, query ChromaDB, and return Passages sorted best-first."""
        vec = self._embed(question)

        collection = self._client.get_collection(self._settings.collection)
        results = collection.query(
            query_embeddings=[vec],
            n_results=k,
            where={"superseded": False},
            include=["documents", "metadatas", "distances"],
        )

        passages: list[Passage] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        for chunk_id, text, meta, dist in zip(ids, docs, metas, dists):
            score = 1.0 - float(dist)  # cosine distance -> cosine similarity
            passages.append(
                Passage(
                    chunk_id=str(chunk_id),
                    text=str(text),
                    source=str(meta.get("source", "")),
                    section=str(meta.get("section", "")),
                    page=int(meta["page"]) if meta.get("page") is not None else None,
                    score=score,
                )
            )

        # Highest similarity first
        passages.sort(key=lambda p: p.score, reverse=True)
        log.debug(
            "retrieved",
            extra={
                "question_len": len(question),
                "k": k,
                "hits": len(passages),
                "scores": [round(p.score, 4) for p in passages],
            },
        )
        return passages
