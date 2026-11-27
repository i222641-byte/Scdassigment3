"""Ingestion configuration, from the same ConfigMap the API reads (A02 4.1, A03 F2).

Everything is an environment variable so one image runs as the Job, the CronJob,
the candidate-collection build and the restore Job, with only env changed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexerSettings:
    embed_model: str        # EMBED_MODEL: must equal the API's value (A02 4.4)
    chroma_host: str
    chroma_port: int
    collection: str         # CHROMA_COLLECTION: rahbar_v1 (live), rahbar_v2_c250 (candidate) ...
    corpus_dir: str         # CORPUS_DIR: legacy single-folder corpus (A02); used when DATA_DIR has no corpus/
    chunk_size: int
    chunk_overlap: int
    ollama_url: str
    # --- A03 Part A: the data lake on a PersistentVolumeClaim -----------------------------
    data_dir: str = "/data"          # DATA_DIR: corpus/, lake/, quarantine/, archive/, reports/, cache/
    near_dup_threshold: float = 0.985  # NEAR_DUP_THRESHOLD: doc-embedding cosine that flags a near-duplicate
    min_chars: int = 200             # MIN_CHARS: fewer extracted characters than this = empty extraction
    min_clean_ratio: float = 0.85    # MIN_CLEAN_RATIO: share of "normal" characters; below = garbled
    min_text_page_ratio: float = 0.5  # MIN_TEXT_PAGE_RATIO: share of pages that yielded text


def get_settings() -> IndexerSettings:
    return IndexerSettings(
        embed_model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
        chroma_host=os.environ.get("CHROMA_HOST", "chroma"),
        chroma_port=int(os.environ.get("CHROMA_PORT", 8000)),
        collection=os.environ.get("CHROMA_COLLECTION", "rahbar_v1"),
        corpus_dir=os.environ.get("CORPUS_DIR", "/corpus"),
        chunk_size=int(os.environ.get("CHUNK_SIZE", 400)),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", 80)),
        ollama_url=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"),
        data_dir=os.environ.get("DATA_DIR", "/data"),
        near_dup_threshold=float(os.environ.get("NEAR_DUP_THRESHOLD", 0.985)),
        min_chars=int(os.environ.get("MIN_CHARS", 200)),
        min_clean_ratio=float(os.environ.get("MIN_CLEAN_RATIO", 0.85)),
        min_text_page_ratio=float(os.environ.get("MIN_TEXT_PAGE_RATIO", 0.5)),
    )
