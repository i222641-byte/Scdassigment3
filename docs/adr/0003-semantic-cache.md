# ADR 0003: Semantic cache in Redis (not a Chroma collection)

## Status

Accepted · 2026-10-22

## Context

The `/api/ask` endpoint calls two external services sequentially: Chroma
(vector search, ~50 ms P50) and the LLM provider (~2-8 s P50 for a generation
request). For repeated or paraphrased questions the LLM call dominates latency.
A cache that returns previously computed `AskResponse` objects for semantically
similar questions can reduce median response time by an order of magnitude.

Two implementation options were considered: a Redis hash store with cosine
similarity computed in-process, and a second Chroma collection used as the cache
(where each cached question is a document and retrieval serves as the similarity
lookup).

## Decision

We cache in **Redis** (`api/app/cache.py`). Each cache entry stores:
- The question embedding as a JSON array (key: `cache:emb:<hash>`).
- The serialized `AskResponse` JSON (key: `cache:resp:<hash>`).

On each request the API embeds the incoming question, iterates over all stored
embedding keys, and computes cosine similarity in-process using NumPy. If any
score exceeds the threshold (0.98), the corresponding response is returned
without calling Chroma or the LLM.

Cache entries have a TTL of 900 seconds (`CACHE_TTL=900` in
`k8s/base/configmap.yaml`), after which they expire automatically.

## Options considered

**Option A — Second Chroma collection as cache (rejected).**
Store each cached question as a Chroma document; use the collection's ANN
search to find the nearest cached question. Rejected because:
1. Chroma's ANN search has a fixed overhead (~10-30 ms per query) even for small
   collections. For a cache with tens or hundreds of entries, an exact linear
   scan in-process over NumPy arrays is both faster and more accurate (no ANN
   approximation error).
2. Using Chroma as a cache couples the read and write paths to the same
   service. A Chroma restart would simultaneously flush the index (acceptable:
   the indexer Job can rebuild it) and the cache (acceptable independently), but
   the coupling makes reasoning about consistency harder.
3. Chroma does not natively support TTL-based expiry. Implementing a background
   cleanup task adds complexity.

**Option B — Redis with in-process cosine similarity (chosen).**
Redis is already in the stack (`k8s/base/redis-deployment.yaml`) as the session
store for the UI. Reusing it for the semantic cache adds no new infrastructure.
Redis `EXPIRE` handles TTL automatically. Cosine similarity over in-process
NumPy arrays is accurate (no ANN approximation) and fast for cache sizes up to
~10,000 entries (the entire scan completes in < 5 ms on a single CPU core).

**False hit that ruled out threshold 0.97:**
During development we observed that the question "What is the attendance
policy?" (embedding A) matched "What is the academic warning policy?"
(embedding B) with cosine similarity 0.971. These questions have different
correct answers. Returning the cached attendance answer for the academic
warning question would be a silent wrong answer. Raising the threshold to 0.98
eliminated this false hit; the similarity between A and B was 0.971 < 0.98.

**Shipped threshold:** 0.98. This admits near-exact paraphrases (e.g.,
"minimum attendance" vs "attendance requirement") which score ~0.993-0.998, while
rejecting topically related but distinct questions.

## Consequences

**Easier:**
- No new infrastructure component: Redis is already deployed.
- TTL-based expiry is automatic; the indexer Job's exit handler calls
  `FLUSHDB` to invalidate stale entries after a re-index.
- Exact cosine similarity (not ANN) means no false negatives from quantization.

**Harder:**
- In-process scan over all embeddings is O(N) in cache size. For N > 10,000
  entries this may become a latency bottleneck. At the current TTL of 900 s and
  typical query rate the cache stays well below 1,000 entries in production.
- The similarity computation runs on the API pod's CPU; this is not measured
  by the HPA's CPU metric (the scan is too fast to register as significant CPU
  utilization). No scaling issue in practice, but worth monitoring if cache
  size grows.

**Watch for:**
- If cache scan latency appears in the P95 metrics, switch to Redis's native
  vector similarity search (available in Redis Stack / RediSearch) which
  provides approximate NN search at O(log N) cost.
