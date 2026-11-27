# Appendix screenshots

Every screenshot in `docs/report/shots/` is a **real Git Bash terminal window** (mintty) on our
laptop, running the command live against our minikube cluster (namespace `rahbar`). They are
taken by:

```bash
python docs/report/shoot.py            # all captures, in order (F3 does a real bad release + undo)
python docs/report/shoot.py F3 D1 D2   # only some
```

`shoot.py` opens a terminal window per capture, prints the prompt and command, runs it, and
saves the window with Win32 `PrintWindow`. The text of each session is kept next to it as
`<label>.txt`. Long output (the full trace record and the trace tool) is saved to a file once and
paged with `fold | sed -n`, so no screenshot is cropped; every page shows the command that printed it.

| Label | What | Command(s) |
|---|---|---|
| A1 | Verification report for Batch B (pass/fail per check, reasons) | `kubectl exec -n rahbar datalake-shell -- cat /data/reports/20261127T003938Z/verification.md` |
| A2 | Second ingestion on an unchanged corpus: 0 chunks embedded; counts by doc id | `scripts/a2_demo.sh unchanged`, `scripts/a2_demo.sh counts` |
| B | Evaluation summary, all three levels | `cat eval/results/20261126T232355Z_baseline.md` |
| C-fail / C-pass | Release gate failing / passing | `python eval/gate.py --candidate <result> --baseline eval/results/baseline.json` |
| D1 | One full trace record | `kubectl logs <newest api pod> \| grep '"kind": "trace"' \| tail -1 \| python -m json.tool` |
| D2 | Trace tool rebuilding the prompt for that trace id | `kubectl exec -n rahbar deploy/api -- python -m app.trace_tool <trace_id>` |
| E-before / E-after | Coverage with 33 and 41 golden questions | `python eval/coverage.py --label before --golden <first 33>` / `--label after` |
| F1 | Everything in the namespace | `kubectl get all,pvc,configmap,cronjob,job -n rahbar` |
| F2-ingest / F2-eval | Logs of completed ingestion and evaluation Jobs | `kubectl logs -n rahbar job/ingest-run`, `kubectl logs -n rahbar job/eval` |
| F2-configmap | Gate result changes after a ConfigMap edit (no rebuild) | `kubectl patch configmap rahbar-gate ...` then `scripts/k8s_job.sh k8s/jobs/gate-job.yaml` |
| F3-1..4 | Bad release, `kubectl rollout status`, `kubectl rollout undo`, trace before and after | `scripts/release_demo.sh release rahbar_v3_c60 v3-c60-bad`, `... ask`, `... undo`, `... ask` |
