"""Bounded process-local embedding cache (Phase 11, Prompt 3).

Stores vectors only — never memory records, lifecycle state, or store
handles. The canonical key is
``(provider_id, model_id, dimensions, sha256(text))``, so a change to
the embedded text, provider, model, or dimensions can never reuse an
incompatible vector: it simply produces a different key (implicit
invalidation). Entries are evicted least-recently-used at a documented
bound; nothing is persisted anywhere.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass

from experienceos.embeddings.base import (
    EmbeddingDimensionError,
    EmbeddingVector,
    validate_vector,
)

DEFAULT_MAX_ENTRIES = 4096


def content_digest(text: str) -> str:
    """SHA-256 hex digest of the exact text supplied to the provider."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmbeddingCacheKey:
    """Immutable canonical cache identity (contract §13)."""

    provider_id: str
    model_id: str
    dimensions: int
    content_digest: str


class EmbeddingCache:
    """Bounded LRU vector cache owned by one retrieval component.

    Not a global singleton: each configured semantic component owns
    its own instance. ``get`` re-validates stored vectors against the
    key's dimensions and drops (never returns) incompatible or
    corrupted entries, counting them as ``invalidated``.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.max_entries = int(max_entries)
        self._entries: OrderedDict[EmbeddingCacheKey, EmbeddingVector] = (
            OrderedDict()
        )
        self.counters = {
            "lookups": 0,
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "invalidated": 0,
            "stores": 0,
        }

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: EmbeddingCacheKey) -> EmbeddingVector | None:
        self.counters["lookups"] += 1
        vector = self._entries.get(key)
        if vector is not None:
            try:
                validate_vector(vector, expected_dimensions=key.dimensions)
            except EmbeddingDimensionError:
                del self._entries[key]
                self.counters["invalidated"] += 1
                self.counters["misses"] += 1
                return None
            self._entries.move_to_end(key)
            self.counters["hits"] += 1
            return vector
        self.counters["misses"] += 1
        return None

    def put(self, key: EmbeddingCacheKey, vector: EmbeddingVector) -> None:
        validated = validate_vector(
            vector, expected_dimensions=key.dimensions
        )
        if key in self._entries:
            self._entries.move_to_end(key)
        self._entries[key] = validated
        self.counters["stores"] += 1
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self.counters["evictions"] += 1

    def clear(self) -> None:
        self._entries.clear()

    def summary(self) -> dict:
        """Bounded counter snapshot; never contains vectors."""
        return {
            **self.counters,
            "size": len(self._entries),
            "max_entries": self.max_entries,
        }
