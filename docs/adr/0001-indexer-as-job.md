# ADR 0001: Indexer as a Kubernetes Job, not API startup code

## Status

Accepted · 2026-10-15

## Context

The RAHBAR system must index a corpus of PDF and HTML documents before the API
can answer questions. The corpus is stored on a PersistentVolumeClaim mounted at
`/corpus`. The API Deployment runs with `replicas: 3`
(`k8s/base/api-deployment.yaml`, line 7).

A simple approach is to run the indexing pipeline in the FastAPI startup event
handler: when the API process starts, it checks whether the Chroma collection
is empty and, if so, reads and indexes all documents before marking itself ready.

## Decision

We run the indexer as a separate one-shot Kubernetes `Job`
(`k8s/base/indexer-job.yaml`) with `backoffLimit: 3`. The Job is applied before
the API Deployment and must complete successfully before any traffic reaches the
API. The API's readiness probe (`/readyz`) checks for a non-empty Chroma
collection rather than running indexing itself.

## Options considered

**Option A — Startup event handler (rejected).**
Run `pipeline.run()` in the FastAPI `@app.on_event("startup")` handler. Simple
to implement (no extra Kubernetes resource). Rejected because:
1. With 3 replicas starting simultaneously, all three would attempt concurrent
   Chroma upserts, causing index corruption and duplicate embeddings.
2. The API pod is limited to 512 Mi (`k8s/base/api-deployment.yaml`, line 49),
   but OCR + embedding can peak at 2.5 Gi (`k8s/base/indexer-job.yaml`, limit
   set to 3 Gi). The API pod would be OOMKilled before it finished indexing.
3. The startup probe allows only 60 seconds (`failureThreshold: 30`,
   `periodSeconds: 2`). Indexing 400+ pages easily exceeds this, causing an
   infinite restart loop.

**Option B — InitContainer (rejected).**
Run the pipeline as a `initContainer` in the API pod. This solves the concurrent
upsert problem (only one InitContainer per pod runs at a time, though all 3 pods
start their InitContainers simultaneously). Still hits memory limit problems, and
repeats the indexing work identically in every pod, tripling the wall-clock time
and unnecessary embedding API calls.

**Option C — Kubernetes Job (chosen).**
A Job runs exactly once (with retries on failure). The indexer image is
independently sized (`requests: 1Gi, limits: 3Gi`). The Job completes before the
API Deployment is applied (enforced in `docs/README.md` apply order and in the
`e2e-eval` CI job). The API's readiness probe returns 503 until the Job finishes
and the Chroma collection is populated, so traffic is withheld until the index
is ready.

## Consequences

**Easier:**
- Independent resource sizing for the indexer (high-memory, batch) vs the API
  (low-memory, latency-sensitive).
- Clear separation of write path (Job) from read path (API Deployment).
- Re-indexing after a corpus update is a single `kubectl create job` command.
- The indexer Job's exit handler can flush the Redis cache after a successful
  upsert, keeping retrieval results consistent with the index.

**Harder:**
- Apply order matters: the Job must complete before the API is healthy. The
  README and CI pipeline enforce this, but a manual mis-apply will leave the
  API in a 503 readiness loop until the Job is run.
- Corpus updates require a manual or cron-triggered re-run of the indexer Job
  (see `k8s/base/reindex-cronjob.yaml` for the scheduled case).

**Watch for:**
- The Job's `backoffLimit: 3` means three failed OCR runs can exhaust retries.
  Monitor with `kubectl get job indexer -n rahbar` and alert on `failed` count > 0.
