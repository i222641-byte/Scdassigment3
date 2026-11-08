# RAHBAR — Grounded RAG on Kubernetes

[![CI](https://github.com/YOUR_ORG/rahbar/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_ORG/rahbar/actions/workflows/ci.yml)

**Authors:** Zurain (22i-2429) · Taha Yasir (22i-2641)
**Course:** Software Construction & Development — Assignment 02

---

## Problem Statement

A student at FAST-NUCES asks whether they can register for a course after failing its prerequisite. The answer exists — it is in a university policy PDF. But general-purpose language models describe some other university's rules because they have never read yours. RAHBAR (Retrieval-Augmented Handbook-Based Answer Retrieval) solves this: it embeds the question, retrieves the most relevant passages from the actual FAST-NUCES documents, builds a grounded prompt, and generates a cited answer. When the corpus does not cover the topic, it says so rather than inventing an answer.

## Architecture

```
                        User
                          │
                     ┌────▼────┐
                     │ Ingress │  rahbar.local
                     │  nginx  │  / → ui   /api → api
                     └────┬────┘
              ┌───────────┴──────────┐
         ┌────▼────┐          ┌──────▼──────┐
         │   ui    │          │     api     │
         │ nginx   │          │  FastAPI    │
         │ 1 rep   │          │  3 replicas │
         └─────────┘          └──────┬──────┘
                                     │ reads only
                              ┌──────▼──────┐
                              │   chroma    │
                              │ StatefulSet │
                              │   1 replica │
                              │  PVC 2 Gi   │
                              └─────────────┘
                                     ▲ writes only
                              ┌──────┴──────┐
                              │  indexer    │
                              │  Job/Cron   │
                              │ extract→    │
                              │ clean→      │
                              │ chunk→      │
                              │ embed→store │
                              └─────────────┘
                              
         ┌─────────┐  ┌───────────────────┐  ┌──────────────┐
         │  redis  │  │    ConfigMap       │  │    Secret    │
         │ cache   │  │ EMBED_MODEL        │  │ LLM_API_KEY  │
         │ PVC 1Gi │  │ TOP_K, TEMP…       │  │ gitignored   │
         └─────────┘  └───────────────────┘  └──────────────┘
```

**Key design decision:** The indexer is a Kubernetes Job, never API startup code. With 3 API replicas, startup indexing would cause three concurrent writers on one Chroma PVC. See `docs/adr/0001-indexer-as-job.md`.

---

## Prerequisites

- [minikube](https://minikube.sigs.k8s.io/) ≥ 1.33
- kubectl ≥ 1.29
- Docker Desktop (or Docker Engine)
- Python 3.12+ (for local tests only)
- [Ollama](https://ollama.com/) on your laptop (for `ollama-host` mode)

---

## Quick Start: From Clean Clone to Answered Question

### 1. Start the cluster (once)

```bash
minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
minikube addons enable metrics-server
minikube addons enable ingress
```

### 2. Start Ollama on your laptop (for LLM generation)

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 3. Build images and load into minikube

```bash
make images
# Builds: rahbar-api:latest, rahbar-indexer:latest, rahbar-ui:latest
# Loads them into minikube's Docker daemon
```

### 4. Apply manifests in this exact order

```bash
# 1. Namespace (must exist before all other objects)
kubectl apply -f k8s/base/namespace.yaml

# 2. Config and secrets
kubectl apply -f k8s/base/configmap.yaml
kubectl apply -f k8s/base/serviceaccount.yaml
# Create the secret from the command line — never from a committed file:
kubectl create secret generic rahbar-secret -n rahbar \
  --from-literal=LLM_API_KEY="${LLM_API_KEY:-placeholder}"

# 3. All remaining manifests via kustomize
kubectl apply -k k8s/overlays/dev
# Or equivalently: make apply
```

### 5. Run the indexer Job to build the vector index

```bash
# Option A: Use the fixture corpus (fast, for testing)
kubectl create job indexer-initial \
  --from=cronjob/reindex \
  -n rahbar

# Option B: Use the real FAST-NUCES corpus
#  First download it: python corpus/fetch.py
#  Then mount the corpus PVC and run the job
kubectl wait --for=condition=complete job/indexer-initial -n rahbar --timeout=300s
```

### 6. Wait for the API to become ready

```bash
kubectl rollout status deployment/api -n rahbar
# "deployment "api" successfully rolled out"
```

### 7. Ask a question

```bash
# Add rahbar.local to /etc/hosts if not already done:
echo "$(minikube ip) rahbar.local" | sudo tee -a /etc/hosts

# Using curl:
curl -s -X POST http://rahbar.local/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the minimum attendance required at FAST-NUCES?"}' \
  | python -m json.tool

# Or open the chat UI: http://rahbar.local
```

Expected response (abbreviated):
```json
{
  "answer": "Students must attend at least 80% of scheduled sessions...",
  "citations": [{"source": "academic-rules-handbook-2026.pdf", "section": "1.21 Attendance", "page": 15}],
  "answered_from_context": true,
  "confidence": "high"
}
```

---

## Re-indexing (without redeploy)

```bash
kubectl create job --from=cronjob/reindex manual-reindex-$(date +%s) -n rahbar
```

The API pods remain serving the old index while the Job runs. Once the Job completes, the API's
readiness probe detects the new collection and new questions use the new index automatically.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ask` | Ask a question. Body: `{"question": "..."}` (3–500 chars). Returns `AskResponse` JSON. |
| GET  | `/healthz` | Liveness check. Returns `{"status": "alive"}`. Never touches dependencies. |
| GET  | `/readyz` | Readiness check. Returns 200 when Chroma is reachable, collection non-empty, Redis reachable, and embedding model matches. Returns 503 naming the failed dependency otherwise. |
| GET  | `/metrics` | Prometheus metrics in text format. Includes request count/latency, retrieval latency, generation latency, cache hit ratio, abstention count, fallback count. |

---

## Configuration (ConfigMap)

| Key | Default | Description |
|-----|---------|-------------|
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model — must match between indexer and API |
| `LLM_MODEL` | `llama3.2:3b` | LLM for generation |
| `LLM_PROVIDER` | `ollama-host` | `stub` / `ollama-host` / `ollama-incluster` / `hosted` |
| `TOP_K` | `5` | Number of chunks to retrieve |
| `TEMPERATURE` | `0.2` | LLM temperature (0–0.3 for factual JSON) |
| `RELEVANCE_FLOOR` | `0.35` | Minimum cosine similarity to include a passage |
| `CACHE_THRESHOLD` | `0.92` | Cosine similarity to trigger a cache hit |
| `CHUNK_SIZE` | `400` | Target chunk size in tokens |
| `CHUNK_OVERLAP` | `80` | Overlap between adjacent chunks in tokens |

---

## Corpus

The corpus covers FAST-NUCES public documents. PDFs are not committed — download with:

```bash
python corpus/fetch.py --sources corpus/sources.yaml
```

See `corpus/MANIFEST.md` for the full list of URLs and SHA-256 checksums.

---

## Running Tests

```bash
make install    # create .venv, install deps
make test       # pytest (api + indexer)
make lint       # ruff + mypy
```

---

## Running the Submission Checker

```bash
python scripts/check_submission.py
```

---

## Licence

MIT — see `LICENSE`.
