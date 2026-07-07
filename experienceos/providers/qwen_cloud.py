"""Qwen Cloud provider adapter (OpenAI-compatible chat completions).

All Qwen-specific configuration, request shaping, and response parsing
lives in this module — the core SDK and engine only see ModelProvider.
Uses the standard library (urllib), so live Qwen support adds no
dependencies and never affects the offline mock path.

Configuration precedence: explicit constructor args, then QWEN_* env
vars, then DASHSCOPE_* env vars, then safe non-secret defaults.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from experienceos.providers.base import ModelProvider

DEFAULT_MODEL = "qwen-plus"
# DashScope OpenAI-compatible endpoint (international). The China region
# uses https://dashscope.aliyuncs.com/compatible-mode/v1 — set QWEN_BASE_URL
# if your Model Studio workspace requires a different regional endpoint.
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_TIMEOUT = 60.0

_MISSING_CREDENTIALS_MESSAGE = (
    "QwenCloudProvider is not configured. Set QWEN_API_KEY or "
    "DASHSCOPE_API_KEY, and set QWEN_BASE_URL if your workspace requires "
    "a regional endpoint."
)


class QwenCloudConfigurationError(RuntimeError):
    """Raised when a live Qwen call is attempted without configuration."""


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


class QwenCloudProvider(ModelProvider):
    """Adapter for Qwen Cloud models behind the ModelProvider interface.

    Construction never makes a network call and works without
    credentials; only complete() requires configuration.
    """

    name = "qwen-cloud"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        self.api_key = api_key or _env("QWEN_API_KEY", "DASHSCOPE_API_KEY")
        self.base_url = (
            base_url or _env("QWEN_BASE_URL", "DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or _env("QWEN_MODEL") or DEFAULT_MODEL
        self.timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.is_configured:
            raise QwenCloudConfigurationError(_MISSING_CREDENTIALS_MESSAGE)

        payload: dict = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens

        return self._parse_response(self._post(payload))

    def _post(self, payload: dict) -> dict:
        """POST to the chat completions endpoint. Mocked in tests."""
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(
                f"Qwen Cloud request failed: HTTP {exc.code} — {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Qwen Cloud request failed: {exc.reason}") from exc

    @staticmethod
    def _parse_response(data: dict) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Qwen Cloud request failed: unexpected response shape: "
                f"{str(data)[:300]}"
            ) from exc
        if isinstance(content, list):
            # Some OpenAI-compatible responses return content as a list of
            # typed parts; join the text parts.
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        if not content:
            raise RuntimeError("Qwen Cloud request failed: empty assistant content.")
        return content


# Convenience alias matching the SDK usage shape: ExperienceOS(model=QwenCloud(...))
QwenCloud = QwenCloudProvider
