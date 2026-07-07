"""Provider abstraction. ExperienceOS attaches to any provider implementing this."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """Minimal interface every model provider must implement.

    ``messages`` is a list of ``{"role": ..., "content": ...}`` dicts,
    ordered context first, user message last.
    """

    name: str = "base"

    @abstractmethod
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return the model's response to a conversation."""
        raise NotImplementedError
