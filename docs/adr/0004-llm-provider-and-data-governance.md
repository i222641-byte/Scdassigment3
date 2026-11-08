# ADR 0004: LLM provider choice and data governance

## Status

Accepted · 2026-10-25

## Context

RAHBAR answers questions about FAST-NUCES academic rules, fees, and student
policies. Some questions may include student-identifying context (e.g., "My
student ID is 22i-XXXX; am I on academic warning?"). The corpus is not
confidential, but we have an obligation not to send student data to third-party
systems without explicit consent.

We also need a provider that can return structured JSON output (the `Answer`
schema defined in `api/app/schemas.py`) reliably, since the eval pipeline
depends on parsing `answered_from_context`, `citations`, and `confidence`.

Three options were evaluated: a commercial cloud API (OpenAI / Google Gemini),
a self-hosted open-weight model via Ollama, and a hybrid approach.

## Decision

We use **Ollama** running inside the Kubernetes cluster to serve an open-weight
instruction-tuned model (default: `llama3.2:3b`, configurable via
`LLM_MODEL` in `k8s/base/configmap.yaml`). The API communicates with Ollama
over the cluster-internal network; no question text or retrieved passages leave
the cluster.

The LLM API key environment variable (`LLM_API_KEY`) is kept in the
configuration for future use, but is set to a stub value in the dev overlay.

## Options considered

**Option A — OpenAI GPT-4o (rejected for primary use).**
GPT-4o supports structured JSON output natively (`response_format: json_schema`)
and reliably follows the `Answer` schema. However, every question (including
any student-identifying context) is sent to OpenAI's servers. Pakistan's data
protection obligations and FAST-NUCES's internal policy require that student
data not be shared with third parties without explicit consent. Additionally,
the API incurs per-token cost that makes it unsuitable for a coursework system
handling many concurrent students.

**Option B — Ollama with open-weight model (chosen).**
`llama3.2:3b` is small enough to run on a node with 8-16 Gi RAM, which matches
typical student lab server specifications. All inference happens inside the
cluster; no data leaves the network boundary. The model is prompted with a JSON
schema and instructed to output only valid JSON (see `api/app/generator.py`).
Structured output is enforced by validating the response against the `Answer`
Pydantic model; a `ValidationError` triggers a retry with a corrective system
prompt.

Data governance properties:
- No student query data leaves the cluster.
- No third-party API keys are required for basic operation.
- The corpus (FAST-NUCES public documents) is not copyrighted in a way that
  prohibits embedding or indexing.

Tradeoffs accepted:
- `llama3.2:3b` occasionally fails to follow the JSON schema strictly, requiring
  a retry (~8 % of requests in testing). The retry logic adds up to 3 s latency.
- Generation speed is ~15 tokens/s on CPU (no GPU), giving P95 latency of ~6 s
  for typical 90-token answers. Acceptable for a coursework assistant.

**Option C — Hybrid: Ollama for PII-sensitive queries, OpenAI for complex ones.**
Routing based on query classification adds significant complexity and a new
failure mode (misclassification). Deferred; can be revisited if generation
quality proves insufficient.

## Consequences

**Easier:**
- Zero student data leaves the cluster, satisfying data governance requirements.
- No API billing or rate-limit surprises during peak exam periods.
- The `LLM_API_KEY` secret can be left as a stub in dev without breaking CI.

**Harder:**
- The Ollama container requires a node with sufficient RAM. The prod overlay
  (`k8s/overlays/prod/`) must target a node with >= 8 Gi free RAM.
- JSON schema compliance requires a retry loop in `api/app/generator.py`. If
  the model repeatedly fails to produce valid JSON, the endpoint returns
  HTTP 500 after 3 attempts.
- Upgrading the model requires re-running `ollama pull <model>` in the cluster
  and re-testing structured output reliability.

**Watch for:**
- Monitor `rahbar_generator_retries_total` Prometheus counter. If the retry
  rate exceeds 20 %, consider switching to a larger model or adding a
  constrained-decoding library (e.g., `outlines`) to guarantee JSON output.
