"""Ollama provider: ollama-host or ollama-incluster (A02 3.5).

Sends a structured-output chat request to Ollama's /api/chat endpoint, parses the Answer
JSON, validates with Pydantic, and retries once on validation failure before returning a
safe fallback. A03: the seed is fixed (SEED) so repeated evaluation runs are comparable,
and token counts and the fallback flag go into the trace through GEN_META.
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from ...config import Settings
from ...prompting import build_prompt
from ...schemas import Answer, Passage
from .base import GEN_META

log = logging.getLogger("rahbar.provider.ollama")

_SCHEMA = Answer.model_json_schema()

_FALLBACK = Answer(
    reasoning="Provider failed to return valid JSON after retry.",
    answer="I was unable to generate a reliable answer. Please try again.",
    citations=[],
    answered_from_context=False,
    confidence="low",
)


def _build_prompt(question: str, passages: list[Passage]) -> str:
    return build_prompt(question, passages)


def _call_ollama(url: str, model: str, prompt: str, temperature: float, seed: int) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": _SCHEMA,          # schema-constrained decoding (Ollama >= 0.5)
        "stream": False,
        # num_predict caps the output: schema-constrained decoding can otherwise run away
        # (endless whitespace) until the context fills; on our CPU that was a >180 s stall.
        "options": {"temperature": temperature, "seed": seed, "num_ctx": 8192,
                    "num_predict": int(os.environ.get("GEN_MAX_TOKENS", 512))},
    }
    resp = httpx.post(url, json=payload, timeout=180.0)
    resp.raise_for_status()
    return resp.json()


def _parse_answer(raw: str) -> Answer:
    return Answer.model_validate(json.loads(raw))


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, question: str, passages: list[Passage], prompt: str | None = None) -> Answer:
        url = f"{self.settings.ollama_url}/api/chat"
        prompt = prompt or _build_prompt(question, passages)
        meta = {"attempts": 0, "fallback": False, "tokens_in": 0, "tokens_out": 0}
        for attempt in range(2):
            meta["attempts"] = attempt + 1
            try:
                data = _call_ollama(url, self.settings.llm_model, prompt,
                                    self.settings.temperature, self.settings.seed)
                meta["tokens_in"] += int(data.get("prompt_eval_count", 0) or 0)
                meta["tokens_out"] += int(data.get("eval_count", 0) or 0)
                answer = _parse_answer(data["message"]["content"])
                GEN_META.set(meta)
                return answer
            except Exception as exc:
                log.warning("ollama generation attempt failed",
                            extra={"attempt": attempt + 1, "error": str(exc)})
        meta["fallback"] = True
        GEN_META.set(meta)
        log.error("ollama generation failed after 2 attempts, returning fallback")
        return _FALLBACK
