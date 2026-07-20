"""Smallest configuration seam for embedding providers.

Nothing in ExperienceOS constructs a provider unless a caller
explicitly asks for one; the default mode is ``disabled`` and returns
``None``. The optional local provider module is imported only when the
``local`` mode is requested, keeping default imports lightweight.
"""

from __future__ import annotations

from pathlib import Path

from experienceos.embeddings.base import EmbeddingProvider
from experienceos.embeddings.deterministic import (
    DEFAULT_DIMENSIONS,
    DeterministicEmbeddingProvider,
)

EMBEDDING_MODES = ("disabled", "deterministic", "local")


class EmbeddingConfigError(ValueError):
    """An explicitly requested embedding configuration is invalid."""


def create_embedding_provider(
    mode: str = "disabled",
    *,
    dimensions: int | None = None,
    model_path: str | Path | None = None,
    model_label: str | None = None,
) -> EmbeddingProvider | None:
    """Construct the requested provider, or ``None`` when disabled.

    ``local`` may return a provider whose ``availability()`` reports
    unavailable (missing dependency/model); callers decide whether to
    skip or fall back. Construction itself never imports the optional
    library, loads a model, or touches the network.
    """
    if mode == "disabled":
        return None
    if mode == "deterministic":
        return DeterministicEmbeddingProvider(
            dimensions=dimensions if dimensions is not None
            else DEFAULT_DIMENSIONS
        )
    if mode == "local":
        from experienceos.embeddings.local import (
            SentenceTransformerEmbeddingProvider,
        )

        return SentenceTransformerEmbeddingProvider(
            model_path=model_path, model_label=model_label
        )
    raise EmbeddingConfigError(
        f"unknown embedding mode {mode!r}; expected one of "
        f"{EMBEDDING_MODES}"
    )
