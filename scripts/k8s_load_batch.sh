#!/usr/bin/env bash
# Copy a document batch into the data-lake landing zone on the datalake-pvc (A03 A, F1).
#   scripts/k8s_load_batch.sh a          # Batch A: corpus/raw/* + corpus/batch_a/_index.json
#   scripts/k8s_load_batch.sh b          # Batch B: corpus/batch_b/*  (run corpus/make_batch_b.py first)
#   scripts/k8s_load_batch.sh demo DIR   # any folder of new documents, e.g. for the demo
# Nothing is indexed until the ingestion Job runs.
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not rewrite /data paths
set -euo pipefail
NS=rahbar
kind=${1:?usage: k8s_load_batch.sh a|b|demo [dir]}
kubectl get pod datalake-shell -n $NS >/dev/null 2>&1 || kubectl apply -f k8s/tools/datalake-shell.yaml
kubectl wait --for=condition=Ready pod/datalake-shell -n $NS --timeout=180s >/dev/null
case "$kind" in
  a)    src=$(mktemp -d); cp corpus/raw/*.pdf corpus/raw/*.html "$src"/; cp corpus/batch_a/_index.json "$src"/; dest=batch_a ;;
  b)    src=corpus/batch_b; dest=batch_b ;;
  demo) src=${2:?folder}; dest=batch_$(basename "$src") ;;
  *)    echo "unknown batch $kind"; exit 2 ;;
esac
kubectl exec -n $NS datalake-shell -- mkdir -p /data/corpus/$dest
tar cf - -C "$src" . | kubectl exec -i -n $NS datalake-shell -- tar xf - -C /data/corpus/$dest
echo "loaded into /data/corpus/$dest:"
kubectl exec -n $NS datalake-shell -- ls -l /data/corpus/$dest
