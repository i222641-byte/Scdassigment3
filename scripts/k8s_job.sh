#!/usr/bin/env bash
# Run a Job manifest from scratch and show its logs:  scripts/k8s_job.sh k8s/eval-job.yaml
# Deletes a previous Job of the same name, applies, waits for Complete or Failed, prints logs.
# Exit status = the Job's result (so a failed release gate exits 1 here too).
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not rewrite /data paths
set -uo pipefail
NS=rahbar
f=${1:?manifest}
timeout=${2:-7200}
name=$(awk '/^metadata:/{m=1} m&&/^  name:/{print $2; exit}' "$f")
kubectl delete job "$name" -n $NS --ignore-not-found >/dev/null
kubectl apply -f "$f"
echo "waiting for job/$name ..."
end=$((SECONDS+timeout))
while (( SECONDS < end )); do
  s=$(kubectl get job "$name" -n $NS -o jsonpath='{.status.succeeded}/{.status.failed}' 2>/dev/null)
  [[ "$s" == 1/* ]] && { kubectl logs -n $NS job/"$name" --tail=-1; echo "job/$name: Complete"; exit 0; }
  [[ "$s" == */1 ]] && { kubectl logs -n $NS job/"$name" --tail=-1; echo "job/$name: Failed"; exit 1; }
  sleep 10
done
echo "timeout waiting for job/$name"; exit 2
