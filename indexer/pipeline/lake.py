"""A03 Part A: the data lake. Lives on a PersistentVolumeClaim mounted at DATA_DIR.

    corpus/<batch>/            the landing zone people drop documents into (+ _index.json)
    lake/registry.json         every document version the lake knows, and its status
    lake/docs/<id>/<ver>/      the accepted copy of each version
    archive/<id>/<ver>/        superseded versions (kept so they can be restored)
    quarantine/<run>/          files that failed verification, with <file>.reason.json
    reports/<run>/             verification and ingestion reports for every run
    cache/extract/<sha>.json   extracted text keyed by file hash (OCR runs once per file)

Status of a version: active | archived | deleted. Quarantined files are never registered
as versions; they are listed under registry["quarantine"].
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import Document, Page

SUPPORTED = {".pdf", ".html", ".htm", ".md", ".txt"}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def text_sha(text: str) -> str:
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def slug(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem or "doc"


class Lake:
    def __init__(self, data_dir: str) -> None:
        self.root = Path(data_dir)
        self.corpus = self.root / "corpus"
        self.lake = self.root / "lake"
        self.archive = self.root / "archive"
        self.quarantine = self.root / "quarantine"
        self.reports = self.root / "reports"
        self.cache = self.root / "cache" / "extract"
        for d in (self.corpus, self.lake / "docs", self.archive, self.quarantine,
                  self.reports, self.cache):
            d.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.lake / "registry.json"
        self.registry: dict[str, Any] = self._load()

    # ------------------------------------------------------------------ registry
    def _load(self) -> dict[str, Any]:
        if self.registry_path.exists():
            return json.loads(self.registry_path.read_text(encoding="utf-8"))
        return {"docs": {}, "quarantine": [], "runs": []}

    def save(self) -> None:
        tmp = self.registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.registry, indent=1), encoding="utf-8")
        os.replace(tmp, self.registry_path)

    def versions(self, statuses: tuple[str, ...] = ("active", "archived")) -> list[dict[str, Any]]:
        out = []
        for doc_id, d in self.registry["docs"].items():
            for ver, v in d["versions"].items():
                if v["status"] in statuses:
                    out.append({"doc_id": doc_id, "version": ver, **v})
        return out

    def by_file(self) -> dict[str, dict[str, Any]]:
        return {v["file"]: v for v in self.versions(("active", "archived"))}

    def put_version(self, doc_id: str, version: str, entry: dict[str, Any]) -> None:
        d = self.registry["docs"].setdefault(doc_id, {"versions": {}, "pinned": None})
        d["versions"][version] = entry

    def set_status(self, doc_id: str, version: str, status: str) -> None:
        self.registry["docs"][doc_id]["versions"][version]["status"] = status

    # ------------------------------------------------------------------ corpus scan
    def scan(self) -> list[dict[str, Any]]:
        """Every document file in corpus/**, merged with its batch _index.json entry and
        (for Markdown) its front matter. Returns [{file, path, meta}] sorted by path."""
        found: list[dict[str, Any]] = []
        for batch in sorted(p for p in self.corpus.iterdir() if p.is_dir()):
            sidecar: dict[str, dict[str, Any]] = {}
            idx = batch / "_index.json"
            if idx.exists():
                for e in json.loads(idx.read_text(encoding="utf-8")):
                    sidecar[e["file"]] = e
            for path in sorted(batch.iterdir()):
                if path.suffix.lower() not in SUPPORTED or path.name.startswith("_"):
                    continue
                if path.name.lower().startswith("readme"):
                    continue
                meta = dict(sidecar.get(path.name, {}))
                if path.suffix.lower() == ".md":
                    for k, v in front_matter(path).items():
                        meta.setdefault(k, v)
                rel = f"{batch.name}/{path.name}"
                meta.setdefault("batch", batch.name)
                found.append({"file": rel, "path": path, "meta": meta})
        return found

    # ------------------------------------------------------------------ file moves
    def quarantine_file(self, run_id: str, path: Path, verdict: dict[str, Any]) -> str:
        dest_dir = self.quarantine / run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        shutil.move(str(path), dest)
        (dest_dir / (path.name + ".reason.json")).write_text(json.dumps(verdict, indent=2),
                                                             encoding="utf-8")
        return str(dest.relative_to(self.root))

    def store_copy(self, doc_id: str, version: str, path: Path, archived: bool = False) -> str:
        base = self.archive if archived else self.lake / "docs"
        dest_dir = base / doc_id / version
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        if path.exists():
            shutil.copy2(path, dest)
        return str(dest.relative_to(self.root))

    def archive_version(self, doc_id: str, version: str) -> str:
        """Copy an accepted version into archive/ (it stays restorable after supersession)."""
        v = self.registry["docs"][doc_id]["versions"][version]
        src = self.root / v.get("lake_path", "")
        dest_dir = self.archive / doc_id / version
        dest_dir.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dest_dir / src.name)
            return str((dest_dir / src.name).relative_to(self.root))
        return ""

    # ------------------------------------------------------------------ extraction cache
    def cached_extract(self, sha: str) -> Document | None:
        p = self.cache / f"{sha}.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return Document(source=d["source"], doc_version=d["doc_version"], superseded=False,
                        pages=[Page(**pg) for pg in d["pages"]])

    def put_extract(self, sha: str, doc: Document) -> None:
        p = self.cache / f"{sha}.json"
        p.write_text(json.dumps({"source": doc.source, "doc_version": doc.doc_version,
                                 "pages": [asdict(pg) for pg in doc.pages]}), encoding="utf-8")

    def report_dir(self, run_id: str) -> Path:
        d = self.reports / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d


def front_matter(path: Path) -> dict[str, str]:
    """`key: value` lines between leading '---' markers (Markdown documents)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        if key.strip():
            meta[key.strip()] = value.strip().strip('"')
    return meta


def run_id_now() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
