"""The LLM provider interface (section 3.5). Swapping providers is one file."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Protocol

from ...schemas import Answer, Passage

# Per-request generation metadata (tokens, attempts, fallback) for the trace. A ContextVar
# keeps concurrent requests in FastAPI's thread pool from overwriting each other.
GEN_META: ContextVar[dict[str, Any]] = ContextVar("GEN_META", default={})


class LLMProvider(Protocol):
    name: str

    def generate(self, question: str, passages: list[Passage], prompt: str | None = None) -> Answer:
        """Answer the question from the passages, as an `Answer`. When `prompt` is given
        (services/answer.py always gives it) the provider sends exactly that text."""
        ...
