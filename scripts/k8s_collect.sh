#!/usr/bin/env bash
# Copy everything the cluster produced back into the repository (A03: result files committed):
#   /ops/results     -> eval/results/            (suite results, gate results, baseline)
#   /ops/traces      -> traces/                  (trace JSON lines, one file per pod)
#   /data/reports    -> eval/results/ingest/     (verification + ingestion reports per run)
#   lake registry    -> eval/results/ingest/registry.json (document vectors stripped)
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not rewrite /data paths
set -euo pipefail
NS=rahbar
kubectl get pod datalake-shell -n $NS >/dev/null 2>&1 || kubectl apply -f k8s/tools/datalake-shell.yaml
kubectl wait --for=condition=Ready pod/datalake-shell -n $NS --timeout=180s >/dev/null
mkdir -p eval/results/ingest traces
kubectl exec -n $NS datalake-shell -- tar cf - -C /ops/results . | tar xf - -C eval/results
kubectl exec -n $NS datalake-shell -- tar cf - -C /ops/traces . | tar xf - -C traces
kubectl exec -n $NS datalake-shell -- tar cf - -C /data/reports . | tar xf - -C eval/results/ingest
kubectl exec -n $NS datalake-shell -- cat /data/lake/registry.json | python -c "
import json,sys
r=json.load(sys.stdin)
for d in r['docs'].values():
    for v in d['versions'].values(): v.pop('doc_vec', None)
json.dump(r, open('eval/results/ingest/registry.json','w'), indent=1)"
kubectl exec -n $NS datalake-shell -- sh -c 'cd /data && find quarantine archive -type f | sort' > eval/results/ingest/lake_files.txt
echo "collected: $(ls eval/results | wc -l) result entries, $(ls traces | wc -l) trace files"
