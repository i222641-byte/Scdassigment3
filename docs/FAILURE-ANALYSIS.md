# Failure analysis

We deliberately broke four pipeline stages, one at a time, observed the
symptoms, diagnosed the fault as if we had not caused it, then restored each
stage before moving to the next. All commands were run against a local k3d
cluster using the fixture corpus in `eval/fixtures/`.

---

## Stage 1 · Extraction

- **What we broke:** Set `pytesseract.pytesseract.tesseract_cmd` to a
  non-existent path (`/usr/bin/tesseract-missing`) in
  `indexer/pipeline/extract.py` before running the indexer Job. This causes
  OCR to fail silently: the pipeline catches `TesseractNotFoundError` and logs
  a WARNING but continues, storing an empty string as the page text.

- **Symptom:** The indexer Job completed successfully (exit 0, no retry). The
  Chroma collection reported the expected number of chunks. However, `eval/run_eval.py`
  showed `recall@5 = 0.00` for all questions whose answers came from the scanned
  annual report (`annual-report-2019-20.pdf`). The eval gate failed:
  `recall@5 dropped too far: 0.62 < 0.80 - 0.05`.

- **Diagnosis, as if we had not caused it:**
  ```
  kubectl logs job/indexer | grep WARNING
  # WARNING  extract: OCR failed for annual-report-2019-20.pdf page 4: TesseractNotFoundError
  ```
  Filtering the Chroma collection for `source=annual-report-2019-20.pdf`
  returns chunks, but each chunk has `text=""`. The eval results JSON shows
  `by_type.ordinary` down only slightly but all questions tagged with the
  annual report source score 0. Cross-referencing the eval JSON with the golden
  file reveals that the affected questions all share the same source, pointing
  to an extraction failure for that specific document.

- **Remedy:** Verify Tesseract is installed in the indexer Docker image. The
  `indexer/Dockerfile` installs `tesseract-ocr` and `poppler-utils` via `apt`.
  After confirming `RUN apt-get install -y tesseract-ocr`, rebuild and re-run
  the indexer Job. The WARNING log disappears and recall@5 recovers to 0.80.

---

## Stage 2 · Chunking

- **What we broke:** Changed the chunker's `max_tokens` parameter from 300 to
  30 (a factor of 10 reduction) in `indexer/pipeline/chunk.py`. This causes
  every sentence to become its own chunk, fragmenting multi-sentence answers
  across many tiny chunks.

- **Symptom:** Chroma reported approximately 7,200 chunks (10× the normal 720).
  `eval/run_eval.py` showed `recall@5 = 0.47`, well below the baseline.
  The eval gate failed. Individual row inspection showed that `version` and
  `exact` questions were worst (recall@5 ≈ 0.3), because their answers span
  multiple sentences that were now split across dozens of tiny chunks, none of
  which individually scored high enough to rank in the top 5.

- **Diagnosis, as if we had not caused it:**
  Run the Chroma collection stats endpoint:
  ```
  curl http://chroma:8000/api/v1/collections/rahbar | python -m json.tool
  # "count": 7231
  ```
  Normal chunk count for this corpus is ~720. A count 10× higher than expected
  indicates the chunker was misconfigured (too-small window). Confirm by
  fetching a sample chunk and checking its text length:
  ```
  curl http://chroma:8000/api/v1/collections/rahbar/get \
    -d '{"limit": 5, "include": ["documents"]}' | python -m json.tool
  # Each "document" is 10-15 tokens — far below the target 300.
  ```

- **Remedy:** Restore `max_tokens=300` in `indexer/pipeline/chunk.py`, re-run
  the indexer Job, and confirm the Chroma collection returns to ~720 chunks.
  recall@5 recovers to 0.80 on the next eval run.

---

## Stage 3 · Embedding / retrieval mismatch

- **What we broke:** After running the indexer with `nomic-embed-text` (768-dim),
  we changed `EMBED_MODEL` in `k8s/base/configmap.yaml` to `all-minilm` (384-dim)
  and redeployed only the API — without re-running the indexer Job. This creates
  a dimension mismatch between query vectors (384-dim) and stored document
  vectors (768-dim).

- **Symptom:** All API pods remained in `NotReady` state. `kubectl get pods -n rahbar`
  showed `0/3 Ready`. Requests timed out in the browser. No 500 errors were
  visible because traffic was never routed to the pods.

- **Diagnosis, as if we had not caused it:**
  ```
  kubectl logs deployment/api -n rahbar | tail -20
  # RuntimeError: embedding dimension mismatch: model returns 384, collection expects 768
  ```
  The startup event in `api/app/main.py` probes the embedding model and the
  Chroma collection dimension on start. The mismatch raises `RuntimeError`,
  preventing `app.state.ready = True`. The `/readyz` endpoint returns 503, so
  the readiness probe never passes.

- **Remedy:** Either revert `EMBED_MODEL` to `nomic-embed-text` and redeploy the
  API, or re-run the indexer Job with the new model to rebuild the Chroma
  collection. The correct production procedure is: update `EMBED_MODEL` in the
  ConfigMap, run the indexer Job first, wait for it to complete, then roll out
  the new API Deployment.

---

## Stage 4 · Generation / abstention

- **What we broke:** Modified the system prompt in `api/app/generator.py` to
  remove the instruction "If the answer is not found in the provided passages,
  set answered_from_context to false". The generator was left with no explicit
  instruction to abstain, so it hallucinated answers for must-abstain questions
  using its pre-training knowledge.

- **Symptom:** `eval/run_eval.py` reported `abstention_correctness = 0.0`.
  Both must-abstain questions (q13: hostel facilities, q14: endowment fund
  scholarships) returned `answered_from_context: true` with plausible-sounding
  but fabricated answers about FAST-NUCES hostel procedures. The eval gate
  failed: `abstention_correctness 0.0 < required 1.0`.

- **Diagnosis, as if we had not caused it:**
  Inspect the raw API response for a must-abstain question:
  ```bash
  curl -s -X POST http://localhost:8080/api/ask \
    -H "Content-Type: application/json" \
    -d '{"question": "How do I apply for a hostel room?"}' | python -m json.tool
  # "answered_from_context": true,
  # "answer": "To apply for a hostel room at FAST-NUCES, submit Form HS-01 ...",
  # "retrieved": []   ← zero passages retrieved, yet model claims to answer
  ```
  The `retrieved` list is empty (Chroma returned no results above the similarity
  threshold) but `answered_from_context` is `true`. This is the classic
  hallucination pattern: the model answered from pre-training knowledge when it
  should have abstained. The root cause is a missing abstention instruction in
  the system prompt.

- **Remedy:** Restore the abstention instruction to the system prompt in
  `api/app/generator.py`. Re-run eval to confirm `abstention_correctness = 1.0`.
  The exact wording used: "If the context does not contain sufficient information
  to answer the question, respond with answered_from_context: false and explain
  that the topic is not covered in the available documents."
