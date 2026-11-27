# Appendix screenshots: what to capture

The assignment requires terminal screenshots from **your own cluster**, showing the command
and its full output, labelled by part. Each row gives the command to run in Git Bash from the
repository root. The output we already captured from the same commands is in
`eval/results/k8s/` (use it to check that your screenshot shows the same thing).

Before you start: `minikube start`, then `kubectl get pods -n rahbar` (all Running).

| Label | What | Command | Reference log |
|---|---|---|---|
| A1 | Verification report for Batch B (pass/fail per check, reasons) | `kubectl exec -n rahbar datalake-shell -- cat /data/reports/20261127T003938Z/verification.md` | `12_ingest_batch_b.log` |
| A2 | Second ingestion on an unchanged corpus: 0 chunks embedded | `scripts/a2_demo.sh unchanged` | `02_ingest_unchanged.log` |
| B | Evaluation summary with all three levels | `cat eval/results/20261126T232355Z_baseline.md` (or run `scripts/k8s_job.sh k8s/eval-job.yaml`) | `06_eval_baseline.log` |
| C (fail) | Release gate failing | `python eval/gate.py --candidate eval/results/20261127T001656Z_candidate-c60.json --baseline eval/results/baseline.json` | `08_candidate_bad_c60_gate.log` |
| C (pass) | Release gate passing | `python eval/gate.py --candidate eval/results/20261127T010412Z_live.json --baseline eval/results/baseline.json` | `18_eval_live_after_batch_b.log` |
| D1 | One full trace record | `kubectl logs -n rahbar -l app=api --tail=50 \| grep '"kind": "trace"' \| tail -1 \| python -m json.tool` | `traces/*.jsonl` |
| D2 | Trace tool rebuilding the prompt for a trace id | `kubectl exec -n rahbar deploy/api -- python -m app.trace_tool <trace_id>` | `20_d2_trace_tool.log` |
| E | Coverage before and after the new questions | `python eval/coverage.py --label before --golden <33-question copy>` and `python eval/coverage.py --label after` | `07_coverage_before.log`, `17_coverage_after.log` |
| F1 | Everything in the namespace | `kubectl get all,pvc,configmap,cronjob,job -n rahbar` | `19_kubectl_get_all.txt` |
| F2 (ingest) | Logs of a completed ingestion Job | `kubectl logs -n rahbar job/ingest-run` | `12_ingest_batch_b.log` |
| F2 (eval) | Logs of a completed evaluation Job | `kubectl logs -n rahbar job/eval` | `18_eval_live_after_batch_b.log` |
| F2 (ConfigMap) | Gate result changing after a ConfigMap edit | `scripts/release_demo.sh gate` before and after `kubectl edit configmap rahbar-gate -n rahbar` | `09b_gate_configmap_before_edit.log`, `09c_gate_configmap_after_edit.log` |
| F3 | `kubectl rollout status` and `kubectl rollout undo`, then a trace with the previous collection and embedding version | `scripts/release_demo.sh release rahbar_v3_c60 v3-c60-bad`, `scripts/release_demo.sh undo`, `scripts/release_demo.sh ask "What minimum CGPA is required to avoid academic warning?"` | `11_bad_release_and_undo.log` |

For E "before", recreate the 33-question set with `head -33 eval/golden.jsonl > /tmp/golden33.jsonl`
and pass `--golden /tmp/golden33.jsonl`.

Note: the gate threshold for raw citation validity is now 0.70 in the ConfigMap. To show
FAIL -> PASS again, edit it to 0.80, run `scripts/release_demo.sh gate` (FAIL on the c250
result), set it back to 0.70 and run it again (PASS).
