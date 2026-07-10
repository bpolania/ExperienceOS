"""Optional CPU-backed local model runner.

An inference adapter only: it turns prompts plus a JSON schema into a
parsed structured object. It makes no memory decisions, holds no store
access, and emits no events. All llama.cpp specifics live in this
module; the dependency is optional (``pip install -e ".[local]"``),
imported lazily, and never triggers a download — the model is loaded
only from an explicitly configured local GGUF file.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from experienceos.policy.base import FallbackReason

MODEL_PATH_ENV = "EXPERIENCEOS_LOCAL_MODEL_PATH"
CONTEXT_SIZE_ENV = "EXPERIENCEOS_LOCAL_MODEL_CONTEXT_SIZE"
MAX_TOKENS_ENV = "EXPERIENCEOS_LOCAL_MODEL_MAX_TOKENS"
THREADS_ENV = "EXPERIENCEOS_LOCAL_MODEL_THREADS"

DEFAULT_CONTEXT_SIZE = 2048
DEFAULT_MAX_TOKENS = 512

_INSTALL_HINT = (
    'Install the optional local dependency with: pip install -e ".[local]"'
)
_CONFIGURE_HINT = (
    f"Set {MODEL_PATH_ENV} to a readable GGUF file, or pass model_path."
)


class LocalModelRunnerError(RuntimeError):
    """Base for local runner failures; ``reason`` maps to FallbackReason."""

    reason = FallbackReason.GENERATION_FAILED


class LocalModelDependencyMissing(LocalModelRunnerError):
    reason = FallbackReason.DEPENDENCY_MISSING


class LocalModelUnavailable(LocalModelRunnerError):
    reason = FallbackReason.MODEL_UNAVAILABLE


class LocalModelLoadFailed(LocalModelRunnerError):
    reason = FallbackReason.MODEL_LOAD_FAILED


class LocalModelGenerationFailed(LocalModelRunnerError):
    reason = FallbackReason.GENERATION_FAILED


class LocalModelInvalidOutput(LocalModelRunnerError):
    reason = FallbackReason.INVALID_OUTPUT


@dataclass(frozen=True)
class LocalModelAvailability:
    """Shallow readiness report; never loads model weights.

    ``available=True`` means the runtime appears ready to attempt
    loading (dependency discoverable, path valid) — not that model
    construction has already succeeded.
    """

    available: bool
    reason: str | None = None
    detail: str | None = None
    model_path: str | None = None


@dataclass(frozen=True)
class LocalModelResult:
    """Parsed structured output plus bounded diagnostics only."""

    data: dict
    model_path: str
    model_name: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    elapsed_ms: float | None = None


class LocalModelRunner(Protocol):
    """Provider-independent local structured-inference seam."""

    def availability(self) -> LocalModelAvailability:
        ...

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Mapping[str, object],
    ) -> LocalModelResult:
        ...


def _summarize_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_threads() -> int:
    return min(4, max(1, os.cpu_count() or 1))


class LlamaCppLocalModelRunner:
    """CPU-oriented llama.cpp runner for structured JSON generation.

    Configuration precedence per setting: explicit constructor value,
    then environment variable, then default (or unavailable, for the
    model path). The model is loaded lazily on first generation and
    cached per runner instance; a failed load may be retried later.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        context_size: int | None = None,
        max_tokens: int | None = None,
        threads: int | None = None,
        temperature: float = 0.0,
    ):
        self._explicit_model_path = str(model_path) if model_path else None
        self._explicit_context_size = context_size
        self._explicit_max_tokens = max_tokens
        self._explicit_threads = threads
        self.temperature = temperature
        self._model = None
        self._model_path: str | None = None
        self._load_failure_detail: str | None = None

    # --- configuration resolution -------------------------------------------

    @property
    def context_size(self) -> int:
        if self._explicit_context_size is not None:
            return self._explicit_context_size
        return _env_int(CONTEXT_SIZE_ENV, DEFAULT_CONTEXT_SIZE)

    @property
    def max_tokens(self) -> int:
        if self._explicit_max_tokens is not None:
            return self._explicit_max_tokens
        return _env_int(MAX_TOKENS_ENV, DEFAULT_MAX_TOKENS)

    @property
    def threads(self) -> int:
        if self._explicit_threads is not None:
            return self._explicit_threads
        return _env_int(THREADS_ENV, _default_threads())

    def _resolve_model_path(self) -> tuple[str | None, str | None]:
        """(normalized path, problem detail) — detail None when valid."""
        raw = self._explicit_model_path or os.environ.get(MODEL_PATH_ENV)
        if not raw:
            return None, _CONFIGURE_HINT
        path = Path(raw).expanduser()
        if not path.exists():
            return str(path), "Configured local model path does not exist."
        if not path.is_file():
            return str(path), "Configured local model path is not a regular file."
        if not os.access(path, os.R_OK):
            return str(path), "Configured local model path is not readable."
        return str(path), None

    # --- availability ----------------------------------------------------------

    def availability(self) -> LocalModelAvailability:
        # Discovery only — never imports or loads the runtime here.
        if importlib.util.find_spec("llama_cpp") is None:
            return LocalModelAvailability(
                available=False,
                reason=FallbackReason.DEPENDENCY_MISSING,
                detail=_INSTALL_HINT,
            )
        model_path, problem = self._resolve_model_path()
        if problem is not None:
            return LocalModelAvailability(
                available=False,
                reason=FallbackReason.MODEL_UNAVAILABLE,
                detail=problem,
                model_path=model_path,
            )
        if self._load_failure_detail is not None:
            return LocalModelAvailability(
                available=False,
                reason=FallbackReason.MODEL_LOAD_FAILED,
                detail=self._load_failure_detail,
                model_path=model_path,
            )
        return LocalModelAvailability(available=True, model_path=model_path)

    # --- generation --------------------------------------------------------------

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Mapping[str, object],
    ) -> LocalModelResult:
        model, model_path = self._ensure_model()
        started = time.perf_counter()
        try:
            response = model.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object", "schema": dict(schema)},
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=False,
            )
        except Exception as exc:
            raise LocalModelGenerationFailed(
                f"Local model generation failed: {_summarize_exception(exc)}"
            ) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        data = self._parse_structured(response)
        usage = response.get("usage") if isinstance(response, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return LocalModelResult(
            data=data,
            model_path=model_path,
            model_name=Path(model_path).name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            elapsed_ms=elapsed_ms,
        )

    def _ensure_model(self):
        """Lazy import and per-instance cached model construction."""
        if self._model is not None:
            return self._model, self._model_path

        if importlib.util.find_spec("llama_cpp") is None:
            raise LocalModelDependencyMissing(_INSTALL_HINT)
        model_path, problem = self._resolve_model_path()
        if problem is not None:
            raise LocalModelUnavailable(problem)

        try:
            import llama_cpp  # lazy: the only runtime import in ExperienceOS

            model = llama_cpp.Llama(
                model_path=model_path,
                n_ctx=self.context_size,
                n_threads=self.threads,
                n_gpu_layers=0,  # CPU-only by design
                verbose=False,
            )
        except Exception as exc:
            self._load_failure_detail = _summarize_exception(exc)
            raise LocalModelLoadFailed(
                f"Local model failed to load: {self._load_failure_detail}"
            ) from exc

        self._load_failure_detail = None
        self._model = model
        self._model_path = model_path
        return model, model_path

    @staticmethod
    def _parse_structured(response) -> dict:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LocalModelInvalidOutput(
                f"Unsupported local model response shape: "
                f"{str(response)[:200]}"
            ) from exc
        if not content or not isinstance(content, str):
            raise LocalModelInvalidOutput("Local model returned empty content.")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LocalModelInvalidOutput(
                f"Local model returned malformed JSON: {content[:200]}"
            ) from exc
        if not isinstance(data, dict):
            raise LocalModelInvalidOutput(
                f"Local model output must be a JSON object, got "
                f"{type(data).__name__}."
            )
        return data
