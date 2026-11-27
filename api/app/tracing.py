"""Trace records (A03 D1, F4). One JSON line per query:

  * to standard output, so `kubectl logs` shows it (kind = "trace" tells it apart from logs)
  * appended to TRACE_DIR/trace-<pod>.jsonl on a PersistentVolumeClaim, for the report scripts
    (one file per pod, so three replicas never interleave half-written lines)
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def trace_file(trace_dir: str) -> Path | None:
    if not trace_dir:
        return None
    d = Path(trace_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"trace-{os.environ.get('HOSTNAME', 'local')}.jsonl"


def emit(record: dict[str, Any], trace_dir: str) -> None:
    line = json.dumps(record, default=str, ensure_ascii=False)
    with _lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        path = trace_file(trace_dir)
        if path is not None:
            try:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:  # a full or read-only volume must not fail the request
                sys.stdout.write(json.dumps({"kind": "log", "level": "WARNING",
                                             "msg": "trace write failed", "error": str(exc)}) + "\n")


def find(trace_id: str, trace_dir: str) -> dict[str, Any] | None:
    d = Path(trace_dir) if trace_dir else None
    if d is None or not d.exists():
        return None
    for path in sorted(d.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if trace_id in line:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("trace_id") == trace_id:
                        return rec
    return None
