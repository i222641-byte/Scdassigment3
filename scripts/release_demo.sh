#!/usr/bin/env bash
# A03 C2/C3/F2/F3 on the cluster, one step at a time (each step prints the commands it runs).
#
#   scripts/release_demo.sh candidate rahbar_v3_c60 v3-c60-candidate   # point api-candidate, run gated eval
#   scripts/release_demo.sh candidate rahbar_v2_c250 v2-c250-candidate
#   scripts/release_demo.sh gate                                       # re-apply gate from ConfigMap only
#   scripts/release_demo.sh release rahbar_v2_c250 v2-c250             # rolling update of the live api
#   scripts/release_demo.sh ask "question"                             # one query + its trace summary
#   scripts/release_demo.sh undo                                       # kubectl rollout undo + status
export MSYS_NO_PATHCONV=1
set -uo pipefail
NS=rahbar
run() { echo "\$ $*"; "$@"; }
step=${1:?step}
case "$step" in
  candidate)
    coll=${2:?collection}; rel=${3:?release}
    kubectl get deployment api-candidate -n $NS >/dev/null 2>&1 || run kubectl apply -f k8s/release/api-candidate.yaml
    run kubectl set env deployment/api-candidate -n $NS CHROMA_COLLECTION="$coll" RELEASE="$rel"
    run kubectl rollout status deployment/api-candidate -n $NS --timeout=300s
    run scripts/k8s_job.sh k8s/jobs/eval-candidate-job.yaml 7200 ;;
  gate)
    run kubectl get configmap rahbar-gate -n $NS -o jsonpath='{.data.gate\.yaml}'; echo
    run scripts/k8s_job.sh k8s/jobs/gate-job.yaml 600 ;;
  release)
    coll=${2:?collection}; rel=${3:?release}
    run kubectl set env deployment/api -n $NS CHROMA_COLLECTION="$coll" RELEASE="$rel"
    run kubectl annotate deployment/api -n $NS kubernetes.io/change-cause="release $rel: collection $coll" --overwrite
    run kubectl rollout status deployment/api -n $NS --timeout=600s
    run kubectl rollout history deployment/api -n $NS ;;
  undo)
    run kubectl rollout undo deployment/api -n $NS
    run kubectl rollout status deployment/api -n $NS --timeout=600s
    run kubectl rollout history deployment/api -n $NS ;;
  ask)
    q=${2:?question}
    # wait until old pods are gone, then use the newest pod of the current ReplicaSet
    while kubectl get pods -n $NS -l app=api --no-headers | grep -q Terminating; do sleep 3; done
    pod=$(kubectl get pods -n $NS -l app=api --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}')
    echo "\$ kubectl exec -n $NS $pod -- python -c '<POST /api/ask>'"
    kubectl exec -n $NS "$pod" -- python -c "
import json,urllib.request
req=urllib.request.Request('http://localhost:8000/api/ask',data=json.dumps({'question':'''$q'''}).encode(),headers={'Content-Type':'application/json','X-No-Cache':'1'})
d=json.load(urllib.request.urlopen(req,timeout=600))
print(json.dumps({k:d[k] for k in ('trace_id','release','collection','answered_from_context','answer','citations','cache','guardrails')},indent=1))"
    echo "\$ kubectl logs -n $NS $pod --tail=50 | grep '\"kind\": \"trace\"' | tail -1  (summarised)"
    kubectl logs -n $NS "$pod" --tail=50 | grep '"kind": "trace"' | tail -1 | python -c "
import json,sys
r=json.loads(sys.stdin.read())
print(json.dumps({'trace_id':r['trace_id'],'timestamp':r['timestamp'],'release':r['release'],'collection':r['collection'],'embedding':r['embedding'],'guardrails':r['guardrails']},indent=1))" ;;
  *) echo "unknown step $step"; exit 2 ;;
esac
