"""Shared deterministic test doubles.

Not part of the production package. FakeLocalModelRunner exists so
local-policy behavior can be tested without llama.cpp, model files,
GPUs, or network access — and is designed for reuse by future
LocalModelMemoryPolicy tests.
"""

from __future__ import annotations

from experienceos.policy.local_runner import (
    LocalModelAvailability,
    LocalModelResult,
)


class FakeLocalModelRunner:
    """Deterministic LocalModelRunner double.

    Configure either canned ``data`` (returned as a LocalModelResult)
    or an ``error`` (raised on generation). ``calls`` records every
    generate_structured invocation.
    """

    def __init__(
        self,
        *,
        data: dict | None = None,
        error: Exception | None = None,
        available: LocalModelAvailability | None = None,
        prompt_tokens: int | None = 10,
        completion_tokens: int | None = 5,
        elapsed_ms: float | None = 1.0,
    ):
        self.data = data if data is not None else {"status": "ready"}
        self.error = error
        self._availability = available or LocalModelAvailability(
            available=True, model_path="fake.gguf"
        )
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.elapsed_ms = elapsed_ms
        self.calls: list[dict] = []

    def availability(self) -> LocalModelAvailability:
        return self._availability

    def generate_structured(
        self, *, system_prompt, user_prompt, schema
    ) -> LocalModelResult:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema": schema,
            }
        )
        if self.error is not None:
            raise self.error
        return LocalModelResult(
            data=dict(self.data),
            model_path="fake.gguf",
            model_name="fake.gguf",
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            elapsed_ms=self.elapsed_ms,
        )
