"""The retriever interface. The rest of the API only ever sees this."""

from __future__ import annotations

from typing import Any, Protocol

from ..schemas import Passage


class Retriever(Protocol):
    name: str

    def retrieve(self, question: str, k: int) -> list[Passage]:
        """Return up to k passages, best first."""
        ...

    def info(self, max_age: float = 15.0) -> dict[str, Any]: ...

    def embed(self, text: str) -> list[float]: ...

    def search(self, vec: list[float], k: int, where: dict[str, Any] | None) -> list[Passage]: ...

    def get_chunks(self, ids: list[str]) -> dict[str, Passage]: ...
