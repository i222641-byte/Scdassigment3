#!/usr/bin/env bash
# (Re)create the rahbar-evaldata ConfigMap from the committed eval data files, so the eval Job
# sees a new golden question (E4) without an image rebuild.
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not rewrite /data paths
set -euo pipefail
kubectl create configmap rahbar-evaldata -n rahbar \
  --from-file=eval/golden.jsonl --from-file=eval/embedding_pairs.jsonl \
  --from-file=eval/human_labels.jsonl --from-file=eval/live_queries.jsonl \
  --dry-run=client -o yaml | kubectl apply -f -
