"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

from typing import Any

from .config import IndexerSettings
from .models import Chunk

# Maximum number of items sent to ChromaDB in a single upsert call
_BATCH_SIZE = 100


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def store(
    chunks: list[Chunk],
    vectors: list[list[float]],
    settings: IndexerSettings,
) -> int:
    """Write every chunk with its vector and metadata to ChromaDB.

    Strategy for the old index:
    - Delete the existing collection (if any) before writing the new one.
    - This means the old index is unavailable for the brief window while
      re-indexing runs.  For the RAHBAR use-case (a Kubernetes Job that
      completes before the API Deployment rolls out) this window is
      acceptable and far simpler than a blue/green swap.

    The collection metadata records the embedding model name and vector
    dimension so the query API can verify compatibility at startup (§4.4).

    Returns the number of chunks written.
    """
    if len(chunks) != len(vectors):
        raise ValueError(
            f"chunks and vectors must have equal length "
            f"({len(chunks)} vs {len(vectors)})"
        )

    client = get_client(settings)

    # Determine vector dimension from the first vector
    vector_dim: int = len(vectors[0]) if vectors else 0

    # Drop the old collection so we start fresh
    try:
        client.delete_collection(settings.collection)
    except Exception:
        # Collection did not exist — that is fine
        pass

    # Create collection with HNSW cosine distance and provenance metadata
    collection = client.create_collection(
        name=settings.collection,
        metadata={
            "hnsw:space": "cosine",
            "embed_model": settings.embed_model,
            "dimension": vector_dim,
        },
    )

    # Upsert in batches to avoid exceeding request-size limits
    total = 0
    for batch_start in range(0, len(chunks), _BATCH_SIZE):
        batch_chunks = chunks[batch_start : batch_start + _BATCH_SIZE]
        batch_vectors = vectors[batch_start : batch_start + _BATCH_SIZE]

        collection.add(
            ids=[c.id for c in batch_chunks],
            documents=[c.text for c in batch_chunks],
            embeddings=batch_vectors,
            metadatas=[c.metadata() for c in batch_chunks],
        )
        total += len(batch_chunks)

    return total
