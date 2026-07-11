"""Provider-independent embedding contracts (Phase 11, Prompt 2).

Embedding providers are scoring utilities: they turn supplied text into
fixed-dimension vectors and report safe diagnostics. They hold no
MemoryStore access, receive no mutation callbacks, emit no lifecycle
events, and make no memory decisions. Nothing here is wired into
retrieval yet — semantic candidate generation begins in Prompt 3 per
``docs/phase11_contract.md``, and lifecycle eligibility always remains
decided before any similarity computation.

Diagnostics safety: availability and result metadata never contain
absolute filesystem paths, environment values, credentials, or raw
exception text.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

EmbeddingVector = tuple[float, ...]


class EmbeddingProviderError(RuntimeError):
    """Base for embedding-provider failures."""


class EmbeddingInputError(EmbeddingProviderError):
    """Supplied input is not embeddable (wrong type, not text)."""


class EmbeddingDimensionError(EmbeddingProviderError):
    """A vector violated the dimension or numeric-safety contract."""


class EmbeddingUnavailableError(EmbeddingProviderError):
    """An unavailable provider was asked to embed.

    Carries the availability report so callers can convert the failure
    into a clean skip or fallback instead of parsing the message.
    """

    def __init__(self, availability: "EmbeddingAvailability") -> None:
        super().__init__(
            f"embedding provider unavailable: {availability.reason}"
        )
        self.availability = availability


class EmbeddingUnavailableReason:
    """Stable, display-safe reasons for provider unavailability."""

    DEPENDENCY_MISSING = "dependency_missing"
    MODEL_NOT_CONFIGURED = "model_not_configured"
    MODEL_MISSING = "model_missing"
    LOAD_FAILED = "load_failed"


@dataclass(frozen=True)
class EmbeddingAvailability:
    """Shallow readiness report; producing one never loads a model.

    ``available=True`` means the provider appears ready to attempt
    embedding (dependency discoverable, configuration valid) — not
    that model construction has already succeeded. ``reason`` is one
    of the ``EmbeddingUnavailableReason`` constants when unavailable;
    ``detail`` is a bounded, display-safe hint that never contains
    filesystem paths or secret values.
    """

    available: bool
    reason: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    """One embedded text plus safe runtime metadata.

    ``elapsed_ms`` is wall-clock and non-deterministic; it is excluded
    from ``to_metadata`` so downstream digest-sensitive consumers can
    serialize results without latency noise, and tests must never
    assert exact timing values.
    """

    vector: EmbeddingVector
    dimensions: int
    provider_id: str
    model_id: str
    deterministic: bool
    elapsed_ms: float | None = None

    def to_metadata(self) -> dict:
        """Safe, digest-stable metadata (no vector, no timing)."""
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "dimensions": self.dimensions,
            "deterministic": self.deterministic,
        }


class EmbeddingProvider(Protocol):
    """Provider-independent embedding seam.

    Implementations receive raw text only — never ``ExperienceEntry``
    objects, stores, event buses, or lifecycle state.
    """

    @property
    def provider_id(self) -> str:
        ...

    @property
    def model_id(self) -> str:
        ...

    @property
    def dimensions(self) -> int | None:
        """Vector width, or None until discoverable (e.g. first load)."""
        ...

    def availability(self) -> EmbeddingAvailability:
        ...

    def embed_query(self, text: str) -> EmbeddingResult:
        ...

    def embed_memories(
        self, texts: Sequence[str]
    ) -> tuple[EmbeddingResult, ...]:
        ...


def require_text(value: object) -> str:
    """Reject non-string input with a domain error."""
    if not isinstance(value, str):
        raise EmbeddingInputError(
            f"embedding input must be str, got {type(value).__name__}"
        )
    return value


def validate_vector(
    vector: Sequence[float], expected_dimensions: int | None = None
) -> EmbeddingVector:
    """Enforce numeric safety and (optionally) an expected width.

    Zero vectors are legal — they represent empty normalized content —
    but NaN/inf values and dimension drift are contract violations.
    """
    values = tuple(float(v) for v in vector)
    if expected_dimensions is not None and len(values) != expected_dimensions:
        raise EmbeddingDimensionError(
            f"expected {expected_dimensions} dimensions, got {len(values)}"
        )
    if not values:
        raise EmbeddingDimensionError("empty vector")
    for value in values:
        if not math.isfinite(value):
            raise EmbeddingDimensionError("non-finite vector value")
    return values


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity with strict dimension validation.

    Zero vectors have no direction, so any comparison involving one
    returns 0.0 rather than raising or dividing by zero. This utility
    is provider-independent test/plumbing support; it performs no
    ranking, thresholding, or retrieval.
    """
    left = validate_vector(a)
    right = validate_vector(b, expected_dimensions=len(left))
    norm_left = math.sqrt(sum(v * v for v in left))
    norm_right = math.sqrt(sum(v * v for v in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(left, right))
    return dot / (norm_left * norm_right)
