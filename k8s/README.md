# RAHBAR on Kubernetes — fresh cluster to working RAGOps pipeline

Every manifest is in this folder. Run all commands from the repository root, in Git Bash
(Windows) or any POSIX shell. Namespace: `rahbar`.

| Folder | What it holds | Applied how |
|---|---|---|
| `base/` | Namespace, ServiceAccounts, ConfigMaps (`rahbar-config`, `rahbar-gate`), PVCs (`datalake-pvc`, `ops-pvc`), Chroma StatefulSet, Redis, live `api` Deployment, ui, Services, Ingress, `ingest` CronJob, NetworkPolicies, HPA | `kubectl apply -k k8s/base` |
| `eval-job.yaml` | The Part B suite as a Job against the live API, with the release gate | `scripts/k8s_job.sh k8s/eval-job.yaml` |
| `jobs/` | One-off Jobs: ingestion run, candidate/bad collection builds, restore/unpin, chunk counts, baseline and candidate evaluations | `scripts/k8s_job.sh k8s/jobs/<file>` |
| `release/` | The candidate Deployment + Service (`api-candidate`) for controlled releases | `kubectl apply -f k8s/release/api-candidate.yaml` |
| `tools/` | `datalake-shell` helper pod (busybox) for copying files in and out of the volumes | applied by the scripts |

`scripts/k8s_job.sh` deletes an earlier Job with the same name, applies the manifest, waits,
prints the logs, and exits with the Job's status. Job names are fixed, so a Job cannot simply be
re-applied while the old one exists.

## 1. Cluster and model (once)

```bash
minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
minikube addons enable metrics-server
minikube addons enable ingress
# Ollama on the laptop, listening on all interfaces (the pods reach it at host.minikube.internal)
OLLAMA_HOST=0.0.0.0 ollama serve        # on Windows: set OLLAMA_HOST=0.0.0.0 in the environment
ollama pull llama3.2:3b && ollama pull nomic-embed-text
```

## 2. Images (built inside minikube, tagged by version, never `:latest`)

```bash
for i in api indexer eval ui; do minikube image build -t rahbar-$i:3.0.0 $i; done
```

## 3. Apply the manifests, in this order

```bash
kubectl apply -k k8s/base                       # everything long-running + the ingest CronJob
scripts/k8s_sync_evaldata.sh                    # extra: rahbar-evaldata ConfigMap (golden set etc.)
kubectl apply -f k8s/tools/datalake-shell.yaml  # extra: helper pod for the volumes
kubectl rollout status statefulset/chroma -n rahbar
```

The `api` pods stay `0/1 READY` until the first ingestion has written the collection: the
readiness probe checks that the collection exists, is non-empty and was built with the same
`EMBED_MODEL` (A02 section 4.4).

## 4. Data: load Batch A and run the ingestion Job

```bash
python corpus/fetch.py                          # Batch A PDFs/HTML -> corpus/raw/ (not committed)
scripts/k8s_load_batch.sh a                     # -> /data/corpus/batch_a on datalake-pvc
scripts/k8s_job.sh k8s/jobs/ingest-job.yaml     # verify -> lake -> incremental index (Part A)
kubectl rollout status deployment/api -n rahbar
```

To re-run the CronJob's template by hand: `kubectl create job --from=cronjob/ingest ingest-manual-1 -n rahbar`.

## 5. Use it

```bash
kubectl port-forward -n rahbar svc/api 8080:80 &
curl -s -X POST localhost:8080/api/ask -H 'Content-Type: application/json' \
     -d '{"question":"What minimum CGPA is required to avoid academic warning?"}'
curl -s localhost:8080/metrics | grep rahbar_          # F4: metrics endpoint
kubectl logs -n rahbar -l app=api --tail=5 | grep '"kind": "trace"'   # F4: traces on stdout
```

## 6. Evaluation, gate and release (Parts B, C, F3)

```bash
scripts/k8s_job.sh k8s/jobs/eval-baseline-job.yaml       # baseline, run twice, saves baseline.json
scripts/k8s_job.sh k8s/jobs/ingest-candidate-job.yaml    # candidate collection rahbar_v2_c250
kubectl apply -f k8s/release/api-candidate.yaml
kubectl rollout status deployment/api-candidate -n rahbar
scripts/k8s_job.sh k8s/jobs/eval-candidate-job.yaml      # gate: Complete = pass, Failed = stop
# only if it passed: release to the live Deployment with a rolling update
kubectl set env deployment/api -n rahbar CHROMA_COLLECTION=rahbar_v2_c250 RELEASE=v2-c250
kubectl annotate deployment/api -n rahbar kubernetes.io/change-cause="release v2: rahbar_v2_c250" --overwrite
kubectl rollout status deployment/api -n rahbar
scripts/k8s_job.sh k8s/eval-job.yaml                     # the gate against the live API
```

Changing a threshold without rebuilding: `kubectl edit configmap rahbar-gate -n rahbar` (or
edit `base/configmap-gate.yaml` and `kubectl apply -k k8s/base`), then re-run the eval Job.

Undoing a bad release: `kubectl rollout undo deployment/api -n rahbar`, then
`kubectl rollout status deployment/api -n rahbar`; the next trace shows the previous collection.

## 7. Copy results back into the repository

```bash
scripts/k8s_collect.sh     # /ops/results -> eval/results, /ops/traces -> traces, reports -> eval/results/ingest
```

## Resource requests and limits (F5)

Set from `kubectl top pods` measurements taken during ingestion and evaluation; the numbers
and the reasoning are in `docs/RAGOPS.md` (F5) and the raw output in `eval/results/k8s/`.
