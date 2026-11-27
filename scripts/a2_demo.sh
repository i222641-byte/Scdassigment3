#!/usr/bin/env bash
# A03 A2 on the cluster: incremental update, changed document, deleted document, rollback.
# Each step runs the ingestion Job (the only writer) and prints its report.
#
#   scripts/a2_demo.sh unchanged   # re-run on an unchanged corpus -> 0 chunks embedded
#   scripts/a2_demo.sh change      # edit one paragraph of a Batch B doc -> only its chunks replaced
#   scripts/a2_demo.sh delete      # delete a doc from the landing zone -> its chunks removed, count 0
#   scripts/a2_demo.sh restore     # restore fee-structure@2026-27 (archived) -> active again
#   scripts/a2_demo.sh unpin       # undo the restore pin -> 2027-28 active again
#   scripts/a2_demo.sh counts      # chunk count by doc_id (orphan proof)
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not rewrite /data paths
set -euo pipefail
NS=rahbar
step=${1:?step}
shell() { kubectl exec -n $NS datalake-shell -- sh -c "$1"; }
case "$step" in
  unchanged)
    scripts/k8s_job.sh k8s/jobs/ingest-job.yaml | grep -E '"msg": "(scanned|index synced)"|chunks_embedded|chunks_unchanged' ;;
  change)
    f=/data/corpus/batch_b/career-fair-2026-notice.md
    shell "sed -i 's/Formal dress is required\./Formal business dress is required./' $f && grep -n 'dress is required' $f"
    scripts/k8s_job.sh k8s/jobs/ingest-job.yaml | sed -n '/^# Verification report/,/^Chunks left/p' ;;
  delete)
    shell "rm -v /data/corpus/batch_b/convocation-2026-guidelines.md"
    scripts/k8s_job.sh k8s/jobs/ingest-job.yaml | sed -n '/^# Ingestion report/,/^Chunks left/p' ;;
  restore)
    scripts/k8s_job.sh k8s/jobs/restore-job.yaml ;;
  unpin)
    scripts/k8s_job.sh k8s/jobs/unpin-job.yaml ;;
  counts)
    scripts/k8s_job.sh k8s/jobs/counts-job.yaml ;;
  *) echo "unknown step $step"; exit 2 ;;
esac
