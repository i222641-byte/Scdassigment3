# The Part B suite as a Kubernetes Job image (A03 F2). The golden set, embedding pairs, hand
# labels and live queries are mounted from the rahbar-evaldata ConfigMap at /evaldata, and the
# gate thresholds from the rahbar-gate ConfigMap at /config, so neither needs a rebuild.
FROM python:3.12-slim
RUN addgroup --system rahbar && adduser --system --ingroup rahbar rahbar
WORKDIR /app/eval
RUN pip install --no-cache-dir httpx==0.28.1 pyyaml==6.0.2
COPY suite.py gate.py coverage.py ./
COPY golden.jsonl embedding_pairs.jsonl live_queries.jsonl gate.yaml ./
USER rahbar
ENTRYPOINT ["python", "suite.py"]
