"""The real retriever. Embeds the question with Ollama, queries ChromaDB, and maps results
to Passage objects (A02 3.2 and 4.4). It never writes: the ingestion Job is the only writer.

A03: embedding and search are separate calls so the trace can time each stage, and the
collection metadata (embed model, embed digest, index_version) is read for every trace.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ..config import Settings
from ..schemas import Passage

log = logging.getLogger("rahbar.retrieval.chroma")


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self._settings = settings
        self._client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._info: dict[str, Any] = {}
        self._info_at = 0.0

    def _collection(self) -> Any:
        return self._client.get_collection(self._settings.collection)

    def info(self, max_age: float = 15.0) -> dict[str, Any]:
        """Collection name and metadata, cached for a few seconds."""
        if time.monotonic() - self._info_at > max_age:
            try:
                col = self._collection()
                meta = {k: v for k, v in (col.metadata or {}).items() if not k.startswith("hnsw")}
                self._info = {"name": self._settings.collection, **meta}
            except Exception as exc:
                self._info = {"name": self._settings.collection, "error": str(exc)}
            self._info_at = time.monotonic()
        return self._info

    def embed(self, text: str) -> list[float]:
        url = f"{self._settings.ollama_url}/api/embed"
        resp = httpx.post(url, json={"model": self._settings.embed_model, "input": [text]}, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings") or data.get("embedding")
        if isinstance(embeddings[0], list):
            return embeddings[0]
        return embeddings

    def search(self, vec: list[float], k: int, where: dict[str, Any] | None) -> list[Passage]:
        results = self._collection().query(
            query_embeddings=[vec], n_results=k, where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        passages: list[Passage] = []
        for chunk_id, text, meta, dist in zip(results.get("ids", [[]])[0],
                                              results.get("documents", [[]])[0],
                                              results.get("metadatas", [[]])[0],
                                              results.get("distances", [[]])[0]):
            meta = meta or {}
            passages.append(Passage(
                chunk_id=str(chunk_id), text=str(text),
                source=str(meta.get("source", "")), section=str(meta.get("section", "")),
                page=int(meta["page"]) if meta.get("page") is not None else None,
                score=1.0 - float(dist),
                doc_id=str(meta.get("doc_id", meta.get("source", ""))),
                doc_version=str(meta.get("doc_version", "")),
                superseded=bool(meta.get("superseded", False)),
            ))
        passages.sort(key=lambda p: p.score, reverse=True)
        return passages

    def get_chunks(self, ids: list[str]) -> dict[str, Passage]:
        """Fetch chunks by id (used by the trace tool to rebuild a prompt)."""
        got = self._collection().get(ids=ids, include=["documents", "metadatas"])
        out: dict[str, Passage] = {}
        for cid, text, meta in zip(got["ids"], got["documents"], got["metadatas"]):
            meta = meta or {}
            out[cid] = Passage(chunk_id=cid, text=text, source=str(meta.get("source", "")),
                               section=str(meta.get("section", "")),
                               page=int(meta["page"]) if meta.get("page") is not None else None,
                               score=0.0, doc_id=str(meta.get("doc_id", "")),
                               doc_version=str(meta.get("doc_version", "")),
                               superseded=bool(meta.get("superseded", False)))
        return out

    def retrieve(self, question: str, k: int) -> list[Passage]:
        return self.search(self.embed(question), k, {"superseded": False})
