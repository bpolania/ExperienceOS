"""Deterministic test embedding provider (Phase 11, Prompt 2).

A dependency-free, offline, cross-process-stable feature-hashing
provider for unit tests, CI, plumbing validation, and deterministic
benchmark fixtures. It is honestly a *test double for the embedding
interface*: it captures token overlap, not meaning, and must never be
cited as evidence of learned semantic retrieval quality.

Documented algorithm (frozen as ``stable-feature-hash-v1``):

1. Casefold the text and tokenize with the stable rule
   ``[^\\W_]+`` (Unicode word characters minus underscore).
2. For each token, add a signed unit feature; for each token of
   length >= 4, also add its character trigrams at weight 0.25 for
   mild morphological overlap (``preference`` vs ``preferences``).
3. Each feature hashes via SHA-256 (never Python's randomized
   ``hash()``): bytes 0-3 select the dimension index, byte 4's low
   bit selects the sign.
4. L2-normalize the accumulated vector; text with no tokens embeds to
   the zero vector (cosine similarity treats it as similar to
   nothing).

Pure float addition/multiplication/sqrt over identical inputs is
IEEE-754 deterministic, so vectors are byte-equivalent across calls,
processes, and supported machines.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, Sequence

from experienceos.embeddings.base import (
    EmbeddingAvailability,
    EmbeddingDimensionError,
    EmbeddingInputError,
    EmbeddingResult,
    EmbeddingVector,
    require_text,
)

PROVIDER_ID = "deterministic"
MODEL_ID = "stable-feature-hash-v1"
DEFAULT_DIMENSIONS = 512
_MIN_DIMENSIONS = 8
_TRIGRAM_MIN_TOKEN = 4
_TRIGRAM_WEIGHT = 0.25

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """The provider's documented, stable tokenization rule."""
    return _TOKEN_RE.findall(text.casefold())


def _features(tokens: Iterable[str]) -> Iterable[tuple[str, float]]:
    for token in tokens:
        yield token, 1.0
        if len(token) >= _TRIGRAM_MIN_TOKEN:
            for start in range(len(token) - 2):
                yield f"3g:{token[start:start + 3]}", _TRIGRAM_WEIGHT


class DeterministicEmbeddingProvider:
    """Offline stdlib-only provider; always available."""

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS) -> None:
        if dimensions < _MIN_DIMENSIONS:
            raise EmbeddingDimensionError(
                f"dimensions must be >= {_MIN_DIMENSIONS}, got {dimensions}"
            )
        self._dimensions = int(dimensions)

    @property
    def provider_id(self) -> str:
        return PROVIDER_ID

    @property
    def model_id(self) -> str:
        return MODEL_ID

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def availability(self) -> EmbeddingAvailability:
        return EmbeddingAvailability(available=True)

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed(require_text(text))

    def embed_memories(
        self, texts: Sequence[str]
    ) -> tuple[EmbeddingResult, ...]:
        if isinstance(texts, str):
            raise EmbeddingInputError(
                "embed_memories expects a sequence of texts, not one str"
            )
        return tuple(self._embed(require_text(text)) for text in texts)

    def _embed(self, text: str) -> EmbeddingResult:
        accumulator = [0.0] * self._dimensions
        for feature, weight in _features(tokenize(text)):
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            accumulator[index] += sign * weight
        norm = math.sqrt(sum(v * v for v in accumulator))
        vector: EmbeddingVector
        if norm > 0.0:
            vector = tuple(v / norm for v in accumulator)
        else:
            # No tokens (empty/blank/punctuation-only text): the zero
            # vector, which cosine similarity matches with nothing.
            vector = tuple(accumulator)
        return EmbeddingResult(
            vector=vector,
            dimensions=self._dimensions,
            provider_id=PROVIDER_ID,
            model_id=MODEL_ID,
            deterministic=True,
            elapsed_ms=None,
        )
