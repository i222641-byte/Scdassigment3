"""The ingestion Job's entry point. It runs once and exits (A02 4.2, A03 Part A and F2).

    python -m pipeline.run                         # sync: ingest -> verify -> update lake -> update index
    python -m pipeline.run --mode restore --target fee-structure@2026-27   # rollback a version
    python -m pipeline.run --mode unpin   --target fee-structure           # undo a restore pin
    python -m pipeline.run --mode counts                                   # chunk count by doc_id
    python -m pipeline.run --dummy                                         # A02 week-1 index

Every run writes reports/<run_id>/{verification,ingestion}.{json,md} on the data-lake volume
and prints the same tables to stdout so `kubectl logs job/ingest` shows them.
Exit code 0 means the lake and the index are consistent; anything else fails the Job.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .config import IndexerSettings, get_settings
from .models import Chunk, Document


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.ingest", "msg": msg, **fields}, default=str), flush=True)


# ---------------------------------------------------------------------------
# A02 compatibility: single-folder corpus discovery (tests and CI fixtures use it)
# ---------------------------------------------------------------------------

def _front_matter(path: Path) -> dict[str, str]:
    from .lake import front_matter

    return front_matter(path)


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    root = Path(corpus_dir)
    index = root / "_index.json"
    if index.exists():
        entries = json.loads(index.read_text(encoding="utf-8"))
        return [(root / e["file"], str(e.get("doc_version", "unknown")),
                 bool(e.get("superseded", False))) for e in entries]
    found = []
    for path in sorted(root.glob("*")):
        if path.suffix.lower() not in {".pdf", ".md", ".html", ".txt"}:
            continue
        if path.name.lower().startswith("readme"):
            continue
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        found.append((path, meta.get("doc_version", "unknown"),
                      meta.get("superseded", "false").lower() == "true"))
    return found


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _extract_cached(lake: Any, path: Path, sha: str, meta: dict[str, Any]) -> tuple[Document | None, str | None]:
    from .extract import extract

    doc = lake.cached_extract(sha)
    if doc is not None:
        return doc, None
    try:
        doc = extract(str(path), str(meta.get("doc_version", "unknown")), False)
    except Exception as exc:  # ExtractionError or anything a broken file throws
        return None, f"{type(exc).__name__}: {exc}"
    lake.put_extract(sha, doc)
    return doc, None


def _doc_for_version(lake: Any, v: dict[str, Any]) -> Document | None:
    doc = lake.cached_extract(v["sha256"])
    if doc is None:
        src = lake.root / v.get("lake_path", "")
        if not src.exists():
            return None
        from .extract import extract

        doc = extract(str(src), v["version"], False)
        lake.put_extract(v["sha256"], doc)
    doc.source = Path(v["file"]).name
    doc.doc_id = v["doc_id"]
    doc.doc_version = v["version"]
    doc.title = v.get("title", "")
    doc.superseded = v["status"] == "archived"
    return doc


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _cell(check: dict[str, str]) -> str:
    return ("PASS" if check["result"] == "pass" else "FAIL") + ": " + check["reason"].replace("|", "/")


# ---------------------------------------------------------------------------
# sync: ingest -> verify -> update data lake -> update retrieval source
# ---------------------------------------------------------------------------

def run_sync(settings: IndexerSettings, run_id: str, verify_only: bool = False) -> dict[str, Any]:
    from .embed import embed, model_digest
    from .lake import Lake, sha256_bytes, slug, text_sha
    from .verify import (Verdict, check_completeness, check_quality, check_recency,
                         check_uniqueness, doc_windows, mean_vector, version_key)

    lake = Lake(settings.data_dir)
    started = time.perf_counter()
    scanned = lake.scan()
    known_by_file = lake.by_file()
    seen_files = {s["file"] for s in scanned}

    # ---- 1. classify every file in the landing zone -------------------------------------
    unchanged, changed, new = [], [], []
    for s in scanned:
        raw = s["path"].read_bytes()
        s["raw"] = raw
        s["sha256"] = sha256_bytes(raw)
        prev = known_by_file.get(s["file"])
        if prev and prev["sha256"] == s["sha256"]:
            unchanged.append(s)
        elif prev:
            s["prev"] = prev
            changed.append(s)
        else:
            new.append(s)
    deleted = [v for f, v in known_by_file.items() if f not in seen_files]
    log("scanned", run_id=run_id, files=len(scanned), unchanged=len(unchanged),
        changed=len(changed), new=len(new), deleted=len(deleted))

    # ---- 2. verify new and changed files ------------------------------------------------
    for s in new + changed:
        m = s["meta"]
        s["doc_id"] = str(m.get("doc_id") or (s["prev"]["doc_id"] if "prev" in s else slug(s["file"])))
        s["version"] = str(m.get("doc_version") or m.get("date") or "unknown")
    pending = sorted(new + changed, key=lambda s: (s["doc_id"], version_key(s["version"])))

    known: list[dict[str, Any]] = [
        {"doc_id": v["doc_id"], "version": v["version"], "sha256": v["sha256"],
         "text_sha": v.get("text_sha"), "doc_vec": v.get("doc_vec"), "file": v["file"]}
        for v in lake.versions(("active", "archived"))
    ]
    verdicts: list[Verdict] = []
    digest = model_digest(settings)

    for s in pending:
        m = s["meta"]
        doc, err = _extract_cached(lake, s["path"], s["sha256"], m)
        v = Verdict(file=s["file"], doc_id=s["doc_id"], doc_version=s["version"], sha256=s["sha256"])
        v.detail["change"] = "changed" if "prev" in s else "new"
        v.checks["quality"] = check_quality(doc, err, settings.min_chars, settings.min_clean_ratio,
                                            settings.min_text_page_ratio)
        meta_for_check = {**m, "source": m.get("source") or m.get("url") or m.get("source_url", "")}
        v.checks["completeness"] = check_completeness(doc, s["file"], s["raw"], meta_for_check)
        others = [k for k in known if k["file"] != s["file"]]
        doc_vec: list[float] = []
        tsha = ""
        if v.checks["quality"].passed and doc is not None:
            full_text = "\n".join(p.text for p in doc.pages)
            tsha = text_sha(full_text)
            windows = doc_windows(doc)
            if windows:
                doc_vec = mean_vector(embed(windows, settings))
        uq, nearest = check_uniqueness(s["sha256"], tsha, s["doc_id"], doc_vec, others,
                                       settings.near_dup_threshold)
        v.checks["uniqueness"] = uq
        v.detail["nearest_similarity"] = round(nearest, 4)
        registry_doc = lake.registry["docs"].get(s["doc_id"], {})
        known_versions = [ver for ver, e in registry_doc.get("versions", {}).items()
                          if e["status"] in ("active", "archived")]
        known_versions += [p["version"] for p in pending
                           if p["doc_id"] == s["doc_id"] and p is not s]
        v.checks["recency"] = check_recency(s["doc_id"], s["version"], known_versions,
                                            registry_doc.get("pinned"))
        if v.hard_fail:
            v.disposition = "quarantined"
        elif not v.checks["recency"].passed:
            v.disposition = "archived"
        else:
            v.disposition = "indexed"
        s["verdict"], s["doc"], s["doc_vec"], s["text_sha"] = v, doc, doc_vec, tsha
        if v.disposition != "quarantined":
            known.append({"doc_id": s["doc_id"], "version": s["version"], "sha256": s["sha256"],
                          "text_sha": tsha, "doc_vec": doc_vec, "file": s["file"]})
        verdicts.append(v)
        log("verified", file=s["file"], doc_id=s["doc_id"], version=s["version"],
            disposition=v.disposition, **{c: v.checks[c].as_dict()["result"] for c in v.checks})

    # ---- 3. update the data lake --------------------------------------------------------
    superseded_now: list[dict[str, str]] = []
    if not verify_only:
        for s in pending:
            v = s["verdict"]
            if v.disposition == "quarantined":
                dest = lake.quarantine_file(run_id, s["path"], v.as_dict())
                lake.registry["quarantine"].append({"file": s["file"], "sha256": s["sha256"],
                                                    "run_id": run_id, "moved_to": dest,
                                                    "reasons": {c: r.reason for c, r in v.checks.items()
                                                                if not r.passed}})
                v.detail["moved_to"] = dest
                if "prev" in s:  # a changed file that now fails: drop the old version too
                    lake.set_status(s["prev"]["doc_id"], s["prev"]["version"], "deleted")
                continue
            if "prev" in s and (s["prev"]["doc_id"], s["prev"]["version"]) != (s["doc_id"], s["version"]):
                lake.set_status(s["prev"]["doc_id"], s["prev"]["version"], "deleted")
            archived = v.disposition == "archived"
            lake_path = lake.store_copy(s["doc_id"], s["version"], s["path"])
            entry = {"file": s["file"], "sha256": s["sha256"], "text_sha": s["text_sha"],
                     "status": "archived" if archived else "active",
                     "title": str(s["meta"].get("title", "")), "date": str(s["meta"].get("date", "")),
                     "source": str(s["meta"].get("source") or s["meta"].get("url") or ""),
                     "batch": s["meta"].get("batch"), "lake_path": lake_path,
                     "doc_vec": s["doc_vec"], "verified_run": run_id,
                     "pages": len(s["doc"].pages) if s["doc"] else 0}
            if archived:
                entry["archived_path"] = lake.store_copy(s["doc_id"], s["version"], s["path"], archived=True)
            lake.put_version(s["doc_id"], s["version"], entry)
            if not archived:
                # every older version of this document is now superseded -> archive
                for ver, e in lake.registry["docs"][s["doc_id"]]["versions"].items():
                    if ver != s["version"] and e["status"] == "active" and \
                            version_key(ver) < version_key(s["version"]):
                        e["status"] = "archived"
                        e["archived_path"] = lake.archive_version(s["doc_id"], ver)
                        superseded_now.append({"doc_id": s["doc_id"], "version": ver,
                                               "superseded_by": s["version"], "file": e["file"]})
        for d in deleted:
            lake.set_status(d["doc_id"], d["version"], "deleted")
            lake.registry["docs"][d["doc_id"]]["versions"][d["version"]]["deleted_run"] = run_id
        lake.registry["runs"].append({"run_id": run_id, "collection": settings.collection})
        lake.save()

    # ---- 4. update the retrieval source (incremental) -----------------------------------
    sync_counts: dict[str, Any] = {}
    counts: dict[str, Any] = {}
    if not verify_only:
        sync_counts, counts = sync_index(settings, lake, digest, run_id)

    report = {
        "run_id": run_id, "collection": settings.collection, "embed_model": settings.embed_model,
        "embed_digest": digest, "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
        "documents": {"scanned": len(scanned), "unchanged": len(unchanged), "new": len(new),
                      "changed": len(changed), "deleted": len(deleted),
                      "indexed": sum(v.disposition == "indexed" for v in verdicts),
                      "archived_on_arrival": sum(v.disposition == "archived" for v in verdicts),
                      "superseded_now": len(superseded_now),
                      "quarantined": sum(v.disposition == "quarantined" for v in verdicts)},
        "deleted_documents": [{"doc_id": d["doc_id"], "version": d["version"], "file": d["file"]}
                              for d in deleted],
        "superseded": superseded_now,
        "chunks": sync_counts,
        "counts_by_doc": counts,
        "seconds": round(time.perf_counter() - started, 1),
    }
    write_reports(lake, run_id, verdicts, report, unchanged)
    return report


def sync_index(settings: IndexerSettings, lake: Any, digest: str, run_id: str) -> tuple[dict, dict]:
    from .chunk import chunk
    from .clean import clean
    from .embed import embed
    from .store import (apply_sync, counts_by_doc, existing_index, get_client, open_collection,
                        plan_sync, update_collection_meta)

    client = get_client(settings)
    col = open_collection(client, settings, digest)
    desired: dict[tuple[str, str], list[Chunk]] = {}
    for v in lake.versions(("active", "archived")):
        doc = _doc_for_version(lake, v)
        if doc is None:
            log("lake file missing, skipping", doc_id=v["doc_id"], version=v["version"])
            continue
        desired[(v["doc_id"], v["version"])] = chunk(clean(doc), settings.chunk_size,
                                                     settings.chunk_overlap)
    existing = existing_index(col)
    plan = plan_sync(desired, existing)
    dims: list[int] = []

    def embed_fn(texts: list[str]) -> list[list[float]]:
        vecs = embed(texts, settings)
        if vecs:
            dims.append(len(vecs[0]))
        return vecs

    result = apply_sync(col, plan, embed_fn)
    changed = any(result[k] for k in ("chunks_added", "chunks_deleted_changed",
                                      "chunks_deleted_orphans", "chunks_metadata_updated"))
    meta = update_collection_meta(col, settings, digest, dims[0] if dims else None,
                                  run_id if changed else None)
    result["collection_total_after"] = col.count()
    result["index_version"] = meta.get("index_version")
    counts = counts_by_doc(col)
    registry_ids = {v["doc_id"] for v in lake.versions(("active", "archived"))}
    counts["orphan_doc_ids"] = sorted(set(counts["by_doc"]) - registry_ids)
    counts["deleted_doc_ids_remaining_chunks"] = {
        did: counts["by_doc"].get(did, 0) for did, d in lake.registry["docs"].items()
        if all(e["status"] == "deleted" for e in d["versions"].values())}
    log("index synced", collection=settings.collection, **result)
    return result, counts


def write_reports(lake: Any, run_id: str, verdicts: list[Any], report: dict[str, Any],
                  unchanged: list[dict[str, Any]]) -> None:
    rdir = lake.report_dir(run_id)
    vrows = [v.as_dict() for v in verdicts]
    (rdir / "verification.json").write_text(json.dumps(
        {"run_id": run_id, "verified": vrows,
         "unchanged_skipped": [s["file"] for s in unchanged]}, indent=2), encoding="utf-8")
    rows = []
    for v in vrows:
        rows.append([v["file"], f"{v['doc_id']}@{v['doc_version']}"] +
                    [_cell(v["checks"][c]) for c in ("quality", "completeness", "recency", "uniqueness")] +
                    [v["disposition"].upper()])
    md = [f"# Verification report — run {run_id}", "",
          f"Collection `{report['collection']}`; {len(vrows)} document(s) verified, "
          f"{len(unchanged)} unchanged document(s) skipped (verified in an earlier run).", "",
          _md_table(["file", "doc_id@version", "quality", "completeness", "recency", "uniqueness",
                     "disposition"], rows) if rows else "_No new or changed documents in this run._"]
    if report["superseded"]:
        md += ["", "## Older versions superseded in this run (recency) -> archived", "",
               _md_table(["doc_id", "archived version", "superseded by", "file"],
                         [[s["doc_id"], s["version"], s["superseded_by"], s["file"]]
                          for s in report["superseded"]])]
    (rdir / "verification.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (rdir / "ingestion.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    ch = report.get("chunks") or {}
    cb = report.get("counts_by_doc") or {}
    imd = [f"# Ingestion report — run {run_id}", "",
           f"Collection `{report['collection']}` · embed `{report['embed_model']}` "
           f"(digest `{report['embed_digest']}`) · chunk {report['chunk_size']}/{report['chunk_overlap']}", "",
           _md_table(["documents", "count"], [[k, str(v)] for k, v in report["documents"].items()]), "",
           _md_table(["chunks", "count"], [[k, str(v)] for k, v in ch.items()]) if ch else "", "",
           "## Chunk count by document id", "",
           _md_table(["doc_id", "chunks", "by version:status"],
                     [[d, str(n), json.dumps(cb.get("by_doc_version", {}).get(d, {}))]
                      for d, n in cb.get("by_doc", {}).items()]) if cb else "", "",
           f"Orphan doc_ids in the vector store (not in the lake): {cb.get('orphan_doc_ids', [])}", "",
           f"Chunks left for deleted documents: {cb.get('deleted_doc_ids_remaining_chunks', {})}"]
    (rdir / "ingestion.md").write_text("\n".join(imd) + "\n", encoding="utf-8")
    # human-readable copy on stdout for `kubectl logs`
    print("\n" + "\n".join(md) + "\n\n" + "\n".join(imd) + "\n", flush=True)
    log("reports written", dir=str(rdir))


# ---------------------------------------------------------------------------
# restore / unpin / counts
# ---------------------------------------------------------------------------

def run_restore(settings: IndexerSettings, run_id: str, target: str, unpin: bool = False) -> dict[str, Any]:
    from .embed import model_digest
    from .lake import Lake

    lake = Lake(settings.data_dir)
    doc_id, _, version = target.partition("@")
    d = lake.registry["docs"].get(doc_id)
    if d is None:
        raise SystemExit(f"unknown doc_id {doc_id!r}")
    before = {ver: e["status"] for ver, e in d["versions"].items()}
    if unpin:
        d["pinned"] = None
        from .verify import version_key

        live = [ver for ver, e in d["versions"].items() if e["status"] != "deleted"]
        newest = max(live, key=version_key)
        for ver in live:
            d["versions"][ver]["status"] = "active" if ver == newest else "archived"
    else:
        if version not in d["versions"] or d["versions"][version]["status"] == "deleted":
            raise SystemExit(f"{doc_id}@{version} is not in the lake")
        d["pinned"] = version
        for ver, e in d["versions"].items():
            if e["status"] != "deleted":
                e["status"] = "active" if ver == version else "archived"
    lake.registry["runs"].append({"run_id": run_id, "restore": target, "unpin": unpin})
    lake.save()
    sync_counts, counts = sync_index(settings, lake, model_digest(settings), run_id)
    after = {ver: e["status"] for ver, e in d["versions"].items()}
    report = {"run_id": run_id, "mode": "unpin" if unpin else "restore", "target": target,
              "status_before": before, "status_after": after, "chunks": sync_counts,
              "counts_for_doc": counts["by_doc_version"].get(doc_id, {})}
    rdir = lake.report_dir(run_id)
    (rdir / "restore.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return report


def run_counts(settings: IndexerSettings) -> dict[str, Any]:
    from .embed import model_digest
    from .store import counts_by_doc, get_client, open_collection

    col = open_collection(get_client(settings), settings, model_digest(settings))
    c = counts_by_doc(col)
    c["collection"] = settings.collection
    c["collection_metadata"] = {k: v for k, v in (col.metadata or {}).items() if not k.startswith("hnsw")}
    print(json.dumps(c, indent=2), flush=True)
    return c


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="RAHBAR ingestion: verify, update the lake and the index.")
    parser.add_argument("--dummy", action="store_true", help="A02: write three fake chunks")
    parser.add_argument("--mode", default=os.environ.get("INGEST_MODE", "sync"),
                        choices=["sync", "verify-only", "restore", "unpin", "counts"])
    parser.add_argument("--target", default=os.environ.get("INGEST_TARGET", ""),
                        help="doc_id@version for restore, doc_id for unpin")
    args = parser.parse_args()
    settings = get_settings()
    from .lake import run_id_now

    run_id = os.environ.get("RUN_ID") or run_id_now()
    log("ingest starting", mode="dummy" if args.dummy else args.mode, run_id=run_id,
        embed_model=settings.embed_model, collection=settings.collection,
        chroma=f"{settings.chroma_host}:{settings.chroma_port}", data_dir=settings.data_dir,
        pod=os.environ.get("HOSTNAME", "-"))
    started = time.perf_counter()
    try:
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
            log("dummy index written", chunks=count)
        elif args.mode in ("sync", "verify-only"):
            report = run_sync(settings, run_id, verify_only=args.mode == "verify-only")
            log("ingest finished", documents=report["documents"], chunks=report["chunks"],
                seconds=round(time.perf_counter() - started, 1))
        elif args.mode == "restore":
            run_restore(settings, run_id, args.target)
        elif args.mode == "unpin":
            run_restore(settings, run_id, args.target, unpin=True)
        elif args.mode == "counts":
            run_counts(settings)
    except Exception as exc:
        log("ingest failed", error=f"{type(exc).__name__}: {exc}")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
