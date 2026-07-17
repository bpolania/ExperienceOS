"""One response model for every system (the fairness seam).

The baselines call ``provider.complete(list[str])`` while the ExperienceOS
SDK path calls ``provider.complete(list[dict])``. To answer every system
with the *same* underlying model, this wrapper accepts either shape and
normalizes the string form into role-tagged messages before delegating
to one wrapped provider (a `MockProvider` offline, a `QwenCloudProvider`
live). It changes only message *shape*, never message *content*, so the
comparison stays fair: the same assembled context each system produced is
what the shared model sees.

The wrapper exposes the wrapped provider's public identity (name, model,
temperature, timeout, is_configured) but never its credentials.
"""

from __future__ import annotations


class UnifiedResponseProvider:
    """Adapt one model provider to both the baseline and SDK contracts."""

    def __init__(self, base):
        self._base = base
        self.request_count = 0

    # -- identity (no credentials) -------------------------------------------

    @property
    def name(self) -> str:
        return getattr(self._base, "name", type(self._base).__name__)

    @property
    def model(self):
        return getattr(self._base, "model", None)

    @property
    def temperature(self):
        return getattr(self._base, "temperature", None)

    @property
    def timeout(self):
        return getattr(self._base, "timeout", None)

    @property
    def is_configured(self) -> bool:
        return bool(getattr(self._base, "is_configured", True))

    # -- unified completion ---------------------------------------------------

    def complete(self, messages) -> str:
        self.request_count += 1
        return self._base.complete(self._normalize(messages))

    @staticmethod
    def _normalize(messages):
        """Return dict-form messages. Dict input passes through unchanged;
        a list of strings becomes system context + a final user turn,
        with content preserved verbatim."""
        if not messages:
            return []
        if isinstance(messages[0], dict):
            return list(messages)
        normalized = []
        last = len(messages) - 1
        for index, text in enumerate(messages):
            role = "user" if index == last else "system"
            normalized.append({"role": role, "content": text})
        return normalized
