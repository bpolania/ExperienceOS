"""Optional local sentence-transformers embedding provider (Phase 11).

An inference adapter only: supplied text in, vectors out. All
sentence-transformers specifics live in this module; the dependency is
optional (``pip install -e ".[embeddings-local]"``), imported lazily on
first embedding call — never at module or package import — and never
triggers a download: the model is loaded only from an explicitly
configured, already-existing local path (a sentence-transformers model
directory such as a locally saved ``all-MiniLM-L6-v2``). A model name
that would resolve against the Hugging Face hub is never passed to the
library, so nothing can be fetched from the network.

Diagnostics never contain the configured path: ``model_id`` is the
directory basename (or an explicit ``model_label``), availability
details reference the environment variable by name, and load failures
report only the exception type name.
"""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from typing import Sequence

from experienceos.embeddings.base import (
    EmbeddingAvailability,
    EmbeddingInputError,
    EmbeddingResult,
    EmbeddingUnavailableError,
    EmbeddingUnavailableReason,
    require_text,
    validate_vector,
)

MODEL_PATH_ENV = "EXPERIENCEOS_EMBEDDING_MODEL_PATH"
PROVIDER_ID = "sentence-transformers-local"

_INSTALL_HINT = (
    "Install the optional embedding dependency with: "
    'pip install -e ".[embeddings-local]"'
)
_CONFIGURE_HINT = (
    f"Set {MODEL_PATH_ENV} to an existing local sentence-transformers "
    "model directory, or pass model_path."
)
_MISSING_HINT = (
    f"{MODEL_PATH_ENV} does not point to an existing local model; "
    "models are never downloaded automatically."
)


class SentenceTransformerEmbeddingProvider:
    """CPU-only, local-files-only optional provider.

    Configuration precedence per setting: explicit constructor value,
    then environment variable, then unavailable. Construction reads
    configuration but never imports the library, loads weights, or
    mutates global state; the model loads lazily on the first
    embedding call and is cached per provider instance.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        model_label: str | None = None,
    ) -> None:
        raw = model_path if model_path is not None else os.environ.get(
            MODEL_PATH_ENV
        )
        self._model_path = Path(raw) if raw else None
        if model_label:
            self._model_label = model_label
        elif self._model_path is not None:
            # Basename only: safe to display, never the full path.
            self._model_label = f"local:{self._model_path.name}"
        else:
            self._model_label = "local:unconfigured"
        self._model = None
        self._dimensions: int | None = None

    @property
    def provider_id(self) -> str:
        return PROVIDER_ID

    @property
    def model_id(self) -> str:
        return self._model_label

    @property
    def dimensions(self) -> int | None:
        """Unknown until the first successful embedding call."""
        return self._dimensions

    def availability(self) -> EmbeddingAvailability:
        """Shallow readiness check; never imports or loads the model."""
        if importlib.util.find_spec("sentence_transformers") is None:
            return EmbeddingAvailability(
                available=False,
                reason=EmbeddingUnavailableReason.DEPENDENCY_MISSING,
                detail=_INSTALL_HINT,
            )
        if self._model_path is None:
            return EmbeddingAvailability(
                available=False,
                reason=EmbeddingUnavailableReason.MODEL_NOT_CONFIGURED,
                detail=_CONFIGURE_HINT,
            )
        if not self._model_path.exists():
            return EmbeddingAvailability(
                available=False,
                reason=EmbeddingUnavailableReason.MODEL_MISSING,
                detail=_MISSING_HINT,
            )
        return EmbeddingAvailability(available=True)

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed_batch((require_text(text),))[0]

    def embed_memories(
        self, texts: Sequence[str]
    ) -> tuple[EmbeddingResult, ...]:
        if isinstance(texts, str):
            raise EmbeddingInputError(
                "embed_memories expects a sequence of texts, not one str"
            )
        checked = tuple(require_text(text) for text in texts)
        if not checked:
            return ()
        return self._embed_batch(checked)

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        availability = self.availability()
        if not availability.available:
            raise EmbeddingUnavailableError(availability)
        # The only sentence-transformers import in ExperienceOS: lazy,
        # CPU-only, and pointed at an existing local directory — a hub
        # model name is never passed, so no download can occur.
        import sentence_transformers  # noqa: PLC0415

        try:
            self._model = sentence_transformers.SentenceTransformer(
                str(self._model_path), device="cpu"
            )
        except Exception as exc:
            raise EmbeddingUnavailableError(
                EmbeddingAvailability(
                    available=False,
                    reason=EmbeddingUnavailableReason.LOAD_FAILED,
                    # Type name only: exception text may embed paths.
                    detail=f"model load failed: {type(exc).__name__}",
                )
            ) from exc
        return self._model

    def _embed_batch(
        self, texts: tuple[str, ...]
    ) -> tuple[EmbeddingResult, ...]:
        model = self._ensure_model()
        started = time.perf_counter()
        try:
            rows = model.encode(list(texts))
        except Exception as exc:
            raise EmbeddingUnavailableError(
                EmbeddingAvailability(
                    available=False,
                    reason=EmbeddingUnavailableReason.LOAD_FAILED,
                    detail=f"embedding failed: {type(exc).__name__}",
                )
            ) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        per_text = elapsed_ms / len(texts)
        results = []
        for row in rows:
            vector = validate_vector(
                tuple(float(value) for value in row),
                expected_dimensions=self._dimensions,
            )
            if self._dimensions is None:
                self._dimensions = len(vector)
            results.append(
                EmbeddingResult(
                    vector=vector,
                    dimensions=len(vector),
                    provider_id=PROVIDER_ID,
                    model_id=self._model_label,
                    deterministic=False,
                    elapsed_ms=round(per_text, 3),
                )
            )
        return tuple(results)
