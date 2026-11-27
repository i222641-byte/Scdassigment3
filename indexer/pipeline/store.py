"""Stage 5: Store. The only code in the whole system that writes to Chroma.

A03 A2 makes it incremental. Chunk ids are content addressed (chunk.py), so syncing a
collection with the data lake is a set difference per (doc_id, doc_version):

    to_add     ids the lake produces that the collection lacks   -> embedded and added
    to_delete  ids the collection has that the lake no longer produces -> deleted
    to_flip    ids whose superseded/status metadata changed (archive or restore) -> metadata only
    orphans    ids whose (doc_id, version) the lake no longer lists (deleted docs) -> deleted

An unchanged corpus therefore embeds zero chunks, an edited document replaces only its own
changed chunks, and a deleted document leaves nothing behind.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .config import IndexerSettings
from .models import Chunk

_BATCH_SIZE = 100


class EmbedPinMismatch(RuntimeError):
    pass


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def open_collection(client: Any, settings: IndexerSettings, digest: str) -> Any:
    """Get or create the collection; refuse to mix vectors from two embedding models."""
    col = client.get_or_create_collection(
        name=settings.collection,
        metadata={"hnsw:space": "cosine", "embed_model": settings.embed_model,
                  "embed_digest": digest, "chunk_size": settings.chunk_size,
                  "chunk_overlap": settings.chunk_overlap, "index_version": "empty"},
    )
    meta = col.metadata or {}
    stored = meta.get("embed_model")
    if stored and stored != settings.embed_model and col.count() > 0:
        raise EmbedPinMismatch(
            f"collection {settings.collection} holds vectors from {stored}; EMBED_MODEL is "
            f"{settings.embed_model}. Use a new collection name for a new embedding model.")
    return col


def existing_index(col: Any) -> dict[str, dict[str, Any]]:
    """id -> metadata for every chunk in the collection."""
    out: dict[str, dict[str, Any]] = {}
    total = col.count()
    offset = 0
    while offset < total:
        got = col.get(include=["metadatas"], limit=1000, offset=offset)
        for cid, meta in zip(got["ids"], got["metadatas"]):
            out[cid] = meta or {}
        if not got["ids"]:
            break
        offset += len(got["ids"])
    return out


def plan_sync(desired: dict[tuple[str, str], list[Chunk]],
              existing: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute the set differences. `desired` maps (doc_id, version) -> chunks."""
    desired_ids: dict[str, Chunk] = {}
    for chunks in desired.values():
        for c in chunks:
            desired_ids[c.id] = c
    to_add = [c for cid, c in desired_ids.items() if cid not in existing]
    to_flip: list[Chunk] = []
    unchanged = 0
    for cid, c in desired_ids.items():
        if cid in existing:
            m = existing[cid]
            if bool(m.get("superseded")) != c.superseded or m.get("status") != c.metadata()["status"]:
                to_flip.append(c)
            else:
                unchanged += 1
    desired_keys = set(desired)
    to_delete: list[str] = []
    orphans: list[str] = []
    for cid, m in existing.items():
        if cid in desired_ids:
            continue
        key = (str(m.get("doc_id", m.get("source", ""))), str(m.get("doc_version", "")))
        (to_delete if key in desired_keys else orphans).append(cid)
    return {"to_add": to_add, "to_flip": to_flip, "to_delete": to_delete,
            "orphans": orphans, "unchanged": unchanged}


def apply_sync(col: Any, plan: dict[str, Any], embed_fn: Any) -> dict[str, int]:
    deletes = plan["to_delete"] + plan["orphans"]
    for i in range(0, len(deletes), _BATCH_SIZE):
        col.delete(ids=deletes[i:i + _BATCH_SIZE])
    flips: list[Chunk] = plan["to_flip"]
    for i in range(0, len(flips), _BATCH_SIZE):
        batch = flips[i:i + _BATCH_SIZE]
        col.update(ids=[c.id for c in batch], metadatas=[c.metadata() for c in batch])
    adds: list[Chunk] = plan["to_add"]
    embedded = 0
    for i in range(0, len(adds), _BATCH_SIZE):
        batch = adds[i:i + _BATCH_SIZE]
        vectors = embed_fn([c.text for c in batch])
        col.add(ids=[c.id for c in batch], documents=[c.text for c in batch],
                embeddings=vectors, metadatas=[c.metadata() for c in batch])
        embedded += len(batch)
    return {"chunks_embedded": embedded, "chunks_added": embedded,
            "chunks_deleted_changed": len(plan["to_delete"]),
            "chunks_deleted_orphans": len(plan["orphans"]),
            "chunks_metadata_updated": len(flips), "chunks_unchanged": plan["unchanged"]}


def update_collection_meta(col: Any, settings: IndexerSettings, digest: str, dim: int | None,
                           index_version: str | None) -> dict[str, Any]:
    meta = {k: v for k, v in (col.metadata or {}).items() if not k.startswith("hnsw:")}
    meta.update({"embed_model": settings.embed_model, "embed_digest": digest,
                 "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap})
    if dim:
        meta["dimension"] = dim
    if index_version:
        meta["index_version"] = index_version
    try:
        col.modify(metadata=meta)
    except Exception:
        col.modify(metadata={"hnsw:space": "cosine", **meta})
    return meta


def counts_by_doc(col: Any) -> dict[str, Any]:
    """Count of chunks by doc_id and by (doc_id, version, status) — the orphan proof."""
    by_doc: Counter[str] = Counter()
    by_ver: dict[str, Counter[str]] = defaultdict(Counter)
    for meta in existing_index(col).values():
        did = str(meta.get("doc_id", meta.get("source", "?")))
        by_doc[did] += 1
        by_ver[did][f"{meta.get('doc_version')}:{meta.get('status', 'active')}"] += 1
    return {"total": sum(by_doc.values()),
            "by_doc": dict(sorted(by_doc.items())),
            "by_doc_version": {k: dict(v) for k, v in sorted(by_ver.items())}}


# Kept for the A02 tests and the dummy index: full rebuild in one call.
def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    if len(chunks) != len(vectors):
        raise ValueError(f"chunks and vectors must have equal length ({len(chunks)} vs {len(vectors)})")
    client = get_client(settings)
    try:
        client.delete_collection(settings.collection)
    except Exception:
        pass
    col = client.create_collection(
        name=settings.collection,
        metadata={"hnsw:space": "cosine", "embed_model": settings.embed_model,
                  "dimension": len(vectors[0]) if vectors else 0},
    )
    for i in range(0, len(chunks), _BATCH_SIZE):
        b = chunks[i:i + _BATCH_SIZE]
        col.add(ids=[c.id for c in b], documents=[c.text for c in b],
                embeddings=vectors[i:i + _BATCH_SIZE], metadatas=[c.metadata() for c in b])
    return len(chunks)
