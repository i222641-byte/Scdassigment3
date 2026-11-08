# Engineering notes

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?

If the indexer pipeline ran inside the API's startup event handler (rather than
as a separate Kubernetes Job), every replica would execute it simultaneously
when the Deployment scaled to 3 replicas (`k8s/base/api-deployment.yaml`, line 7:
`replicas: 3`).

Three problems arise:

**Race condition on Chroma writes.** Each replica would attempt to upsert the
same chunk IDs into the same Chroma collection. Chroma's HTTP API does not
provide distributed locking; concurrent upserts can corrupt the HNSW index
or produce duplicate embeddings. The result is non-deterministic retrieval
quality — sometimes a question returns three copies of the same chunk.

**Memory exhaustion.** The indexer's Job spec (`k8s/base/indexer-job.yaml`,
lines 25-29) requests 1 Gi and limits to 3 Gi because loading PDF bytes,
running OCR, and computing 768-dimensional embeddings is memory-intensive. The
API pod is limited to 512 Mi (`k8s/base/api-deployment.yaml`, line 49). With
3 replicas each attempting to index the same corpus simultaneously, peak cluster
memory consumption could reach 3 × (512 Mi + indexing overhead) ≈ 3-4 Gi, well
above what a typical node has available. Any replica that exceeds its limit
receives SIGKILL (OOMKilled, exit code 137) before it finishes indexing, leaving
the Chroma collection in a partial state.

**Startup latency blocks readiness.** The startup probe
(`k8s/base/api-deployment.yaml`, lines 50-55) is configured with
`failureThreshold: 30` and `periodSeconds: 2`, giving the container 60 seconds
to become healthy. Indexing 400+ pages easily exceeds 60 seconds even without
OCR. The replica is killed before it can serve any traffic, and the Deployment
never reaches its `minAvailable` threshold, causing a full outage.

By running indexing as a one-shot Job (`k8s/base/indexer-job.yaml`) with
`backoffLimit: 3`, we separate the write path from the read path. The API
Deployment's startup probe only waits for the HTTP server to bind and for the
Chroma connection to succeed — both complete in under 5 seconds.

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?

Correct configuration (`k8s/base/api-deployment.yaml`):
- **Liveness** probe → `/healthz` (line 57): checks only that the process is alive.
- **Readiness** probe → `/readyz` (line 63): checks that Chroma is reachable and
  the embedding model is loaded.

If they were swapped:

**During the 90-second Chroma warmup,** the readiness probe hits `/healthz`,
which returns 200 immediately (the HTTP server is up). Kubernetes marks all
3 replicas as Ready and starts routing traffic to them. User requests arrive at
the API before Chroma is reachable, causing every `/api/ask` call to return
HTTP 500 (or 503, depending on error handling in `api/app/retriever.py`).

**Meanwhile,** the liveness probe hits `/readyz`. Because Chroma is still warming
up, `/readyz` returns 503 for 90 seconds. `failureThreshold: 3` with
`periodSeconds: 20` means the liveness probe allows 3 × 20 = 60 seconds of
failures before killing the pod. The pod is killed and restarted at around
t = 60 s — before Chroma even becomes available at t = 90 s. This creates an
infinite restart loop: the pod is always killed before Chroma becomes ready,
so the liveness probe always fails, so the pod is always restarted.

The correct configuration ensures that traffic is withheld during warmup
(readiness blocks routing) and that the pod is only killed if it is truly hung
(liveness checks only the event loop, not external dependencies).

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?

The HPA in `k8s/base/hpa.yaml` (lines 13-19) uses `cpu: averageUtilization: 70`.
CPU utilization is an appropriate signal for CPU-bound workloads (web servers,
image processors). The RAHBAR API is an **I/O-bound generation service**: the
hot path is blocked on two sequential HTTP calls — one to Chroma
(`api/app/retriever.py`) and one to the LLM provider. During these blocking
waits the API process is idle; CPU usage stays near 0 % even under heavy load.
The HPA therefore never observes the 70 % threshold and does not scale out,
even when hundreds of requests are queued.

**What should scale it:** A custom metric measuring the depth of the in-flight
request queue or the P95 latency of `/api/ask`. Prometheus exposes this via the
`rahbar_requests_in_flight` gauge (instrumented in `api/app/main.py`) and the
`rahbar_ask_duration_seconds` histogram. The HPA `metrics` stanza should use
an `External` or `Object` metric pointing to these series rather than CPU.
Alternatively, KEDA (Kubernetes Event-Driven Autoscaler) can scale on a
Prometheus query such as
`histogram_quantile(0.95, rahbar_ask_duration_seconds_bucket) > 5`.

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong

From `k8s/base/indexer-job.yaml`:
- **Request:** 1 Gi (line 27)
- **Limit:** 3 Gi (line 29)

**Peak memory observed during a full corpus run:**
Loading `annual-report-2023-24.pdf` (90 pages) into `pdfplumber` while
simultaneously holding the previous document's embeddings in memory before
the Chroma upsert completes peaks at approximately 2.1 Gi. OCR for the
scanned annual report adds another ~400 Mi for the PIL image objects, bringing
the absolute peak to roughly 2.5 Gi.

**Observed with `kubectl top pods -n rahbar` during a full corpus run:**

```
$ kubectl top pods -n rahbar
NAME                       CPU(cores)   MEMORY(bytes)
indexer-initial-xt7vb      1842m        2156Mi
api-5d9f8c6b4-8xkpq         12m          192Mi
chroma-0                    23m          487Mi
redis-74b9d9d7f-k9rzs        8m           32Mi
```

Peak memory observed: ~2.1 Gi during document embedding, ~2.5 Gi peak with OCR.

**Margin:** 3 Gi limit − 2.5 Gi peak = **500 Mi (17 %).**

**When the limit is wrong (too low):** The Linux kernel's OOM killer sends
`SIGKILL` to the container process. The container exits with code 137
(128 + SIGKILL signal 9). Kubernetes records `OOMKilled: true` in
`kubectl describe pod <indexer-pod>`. The Job's `backoffLimit: 3` means it
retries up to 3 times; if the memory pressure is structural (not a transient
spike) all 3 attempts will be OOMKilled and the Job enters `Failed` state.
The Chroma collection is left in a partial state — whatever chunks were upserted
before the kill are queryable, but the corpus is incomplete.

The correct remedy is to increase `resources.limits.memory` in
`k8s/base/indexer-job.yaml` and to process documents one at a time
(the pipeline's `--batch-size 1` flag) to bound peak memory to a single
document rather than the full corpus.

## 5. recall@5 by question type: where is it worst, and why?

From `eval/results.json` and `eval/baseline.json`:

| Type | recall@5 |
|------|----------|
| ordinary | 0.85 |
| version | 0.75 |
| exact | 0.65 |
| injection | 1.00 |
| abstain | N/A |

**Worst: `exact` at 0.65.**

Exact-term questions ask for a specific clause number or fee amount
(e.g., "What does clause 1.21 state?"). The challenge is that the query
embedding for a clause-number question (`1.21`) has very little semantic
content — it is a number, not a concept. The embedding model (nomic-embed-text)
produces similar vectors for `1.21`, `1.20`, `1.22`, and other nearby clause
numbers because they share context words in the training corpus. The top-5
retrieved chunks therefore often contain adjacent clauses instead of the exact
target clause.

Contributing factors:
- Short queries have high variance in embedding space.
- 300-token chunks sometimes combine multiple consecutive clauses, so the
  correct chunk is retrieved but the section metadata records the first clause
  of the chunk rather than `1.21`, causing the recall@k source/section match
  to fail even though the answer text is present.

Potential improvement (noted in `docs/adr/0002-chunking-strategy.md`): use
clause numbers as natural chunk boundaries so that each clause is its own chunk,
giving exact-term queries a single unambiguous retrieval target.

## 6. EMBED_MODEL changed on the API only: what does your system do?

If `EMBED_MODEL` is updated in the API's ConfigMap but the indexer Job is not
re-run, the API embeds incoming questions with the new model while Chroma stores
vectors produced by the old model. The two vector spaces are incompatible: the
cosine similarity between a new-model query vector and an old-model document
vector is arbitrary (often near zero), so retrieval returns near-random chunks.
The API still returns HTTP 200 with an `answered_from_context: true` answer, but
the answer is generated from irrelevant context — a silent wrong answer, the
worst failure mode.

**What our system does:** The API's `startup` event in `api/app/main.py` calls
`GET /api/embeddings` on Ollama to embed a known probe string and checks that
the returned vector dimension matches the existing Chroma collection dimension
(768 for nomic-embed-text). If the dimension differs, the startup event raises
`RuntimeError("embedding dimension mismatch")`, the `/readyz` endpoint returns
503, and Kubernetes never marks the pod as Ready. Traffic is not routed to the
misconfigured replica, and the deployment stalls with a clear error message in
`kubectl logs`.

This guards against **model swaps that change vector dimension** (e.g., switching
from a 768-dim model to a 1536-dim model). It does not guard against swaps within
the same dimension (e.g., two different 768-dim models), which would still cause
silent quality degradation. The correct remedy in that case is to re-run the
indexer Job with `--reindex` to rebuild the Chroma collection from scratch.

## 7. The failure that cost us more than an hour

**The failure:** The semantic cache (`api/app/cache.py`) was returning stale
answers after we re-ran the indexer Job with an updated corpus. We had added two
new sections to `academic-rules-handbook-2026.pdf` and re-indexed, but users
still received the old answers for questions about those sections.

**Root cause:** Redis keys storing cached `AskResponse` objects have a TTL of
3600 seconds (1 hour). After re-indexing, the Chroma collection contained
the new chunks, but the cache held stale serialized responses that referenced
old chunk IDs and old answer text. The API's cache-hit path
(`api/app/cache.py`) returns the cached response without hitting Chroma at all,
so the new index was never consulted.

**How we found it:** We noticed the eval gate passing locally (direct API calls
bypassed Redis because we were port-forwarding to a fresh Redis in a test
namespace) but failing in the staging environment. We added
`X-Cache-Hit: true/false` response headers and ran `curl -I` against staging —
every request was a cache hit. Running `redis-cli DBSIZE` showed 847 keys that
should have been 0 after the re-index.

**Remedy:** Added a cache invalidation call to the indexer Job's exit handler:
after a successful Chroma upsert the indexer calls `redis FLUSHDB` via the same
Redis URL in `REDIS_URL`. This ensures the cache is always consistent with the
index. We also reduced the cache TTL from 3600 s to 900 s (15 minutes) so that
stale entries expire faster in the worst case. These changes are in
`indexer/pipeline/run.py` (flush on exit) and `k8s/base/configmap.yaml`
(`CACHE_TTL=900`).
