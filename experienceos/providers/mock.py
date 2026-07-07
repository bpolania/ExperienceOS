"""Mock provider for tests and offline demos. Deterministic, no network calls."""

from __future__ import annotations

from experienceos.providers.base import ModelProvider

_MEMORY_HEADER = "ExperienceOS retrieved these active user experiences:"


class MockProvider(ModelProvider):
    """Deterministic provider used in tests and offline development."""

    name = "mock"

    def __init__(self, canned_response: str | None = None):
        self.canned_response = canned_response

    def complete(self, messages: list[dict[str, str]]) -> str:
        if self.canned_response is not None:
            return self.canned_response
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]
        last = user_messages[-1] if user_messages else ""
        count = self._count_retrieved_experiences(messages)
        return (
            f'Mock response: I received "{last}" through ExperienceOS '
            f"with {count} retrieved experience entries."
        )

    @staticmethod
    def _count_retrieved_experiences(messages: list[dict[str, str]]) -> int:
        for m in messages:
            if m.get("role") == "system" and _MEMORY_HEADER in m.get("content", ""):
                return m["content"].count("\n- ")
        return 0
