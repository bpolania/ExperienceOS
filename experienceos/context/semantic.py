"""Lifecycle-safe semantic candidate scoring.

The semantic component scores *supplied* memories against a query
using the embedding abstraction. Callers (the retrieval
strategy) apply lifecycle eligibility first: this module never sees a
store, engine, manager, or event bus, receives only already-admitted
entries, mutates nothing, and can therefore never widen lifecycle
admission. Full lexical+semantic score fusion is handled by a later stage;
here semantic scores either ride along as diagnostics (``score_only``)
or drive a clearly separated ``semantic_only`` candidate mode.

Score semantics: raw cosine similarity is retained for diagnostics;
the semantic score is ``max(0.0, cosine)`` — negative cosine carries
no relevance signal worth ranking on, so scores live in [0, 1]. The
relevance floor (default 0.30) keeps collision and stopword noise from
admitting every eligible memory: measured with the deterministic
provider, unrelated short texts reach ~0.25 (shared stopwords, signed
hash collisions) while texts sharing two or more meaningful tokens
score 0.45-0.60. The floor is a fixed configuration value, never
query- or benchmark-dependent; it is not claimed optimal — weak
single-token matches on long queries can fall below it — and adoption
measurement evaluates it before any adoption decision.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from experienceos.embeddings.base import (
    EmbeddingProvider,
    EmbeddingUnavailableError,
    cosine_similarity,
)
from experienceos.embeddings.cache import (
    EmbeddingCache,
    EmbeddingCacheKey,
    content_digest,
)
from experienceos.memory.schema import ExperienceEntry
from experienceos.memory.semantic import METADATA_KEY

SEMANTIC_MODES = ("disabled", "score_only", "semantic_only", "fused")
DEFAULT_SEMANTIC_FLOOR = 0.30
SEMANTIC_SCORING_VERSION = "1"


def memory_embedding_text(entry: ExperienceEntry) -> str:
    """Canonical text supplied to the embedding provider.

    Includes only meaning-bearing fields: the memory text plus the
    structured semantic-identity attribute/value/scope (underscores
    spaced, ``global`` scope omitted) and sorted tags. Lifecycle
    status, user IDs, timestamps, internal IDs, and diagnostics are
    deliberately excluded — they are not memory meaning. The cache
    digest is computed over exactly this string, so any change to
    embedded meaning changes the digest.
    """
    parts = [entry.text.strip()]
    identity = entry.metadata.get(METADATA_KEY)
    identity = identity if isinstance(identity, dict) else {}
    for key in ("attribute", "value", "scope"):
        raw = str(identity.get(key, "") or "").replace("_", " ").strip()
        if raw and raw != "global":
            parts.append(raw)
    tags = entry.metadata.get("tags")
    if isinstance(tags, (list, tuple)):
        parts.extend(
            sorted(str(tag).replace("_", " ").strip() for tag in tags)
        )
    return "\n".join(part for part in parts if part)


@dataclass(frozen=True)
class SemanticScore:
    """One considered memory's semantic evidence (no vectors)."""

    memory_id: str
    raw_cosine: float
    score: float  # max(0, cosine), in [0, 1]
    above_floor: bool
    cache_status: str  # "hit" | "miss"
    rank: int  # 1-based by (-score, memory_id) over all scored entries


@dataclass
class SemanticScoringOutcome:
    """Scores plus a bounded, vector-free summary of one call."""

    scores: dict = field(default_factory=dict)  # memory_id -> SemanticScore
    provider_id: str = ""
    model_id: str = ""
    dimensions: int | None = None
    relevance_floor: float = DEFAULT_SEMANTIC_FLOOR
    query_zero_vector: bool = False
    eligible_count: int = 0
    above_floor_count: int = 0
    query_embedding: dict = field(default_factory=dict)  # {"elapsed_ms"}
    memory_embedding: dict = field(default_factory=dict)  # {"elapsed_ms"}
    cache: dict = field(default_factory=dict)


class SemanticCandidateGenerator:
    """Scores supplied lifecycle-eligible memories against a query.

    Owns a bounded process-local :class:`EmbeddingCache`. Accepts no
    store, bus, or mutation callback — only an
    :class:`EmbeddingProvider` and per-call immutable inputs.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        cache: EmbeddingCache | None = None,
        relevance_floor: float = DEFAULT_SEMANTIC_FLOOR,
    ) -> None:
        if not 0.0 <= relevance_floor <= 1.0:
            raise ValueError("relevance_floor must be in [0, 1]")
        self.provider = provider
        self.cache = cache if cache is not None else EmbeddingCache()
        self.relevance_floor = float(relevance_floor)

    def availability(self):
        return self.provider.availability()

    def score_memories(
        self, query_text: str, entries: tuple[ExperienceEntry, ...]
    ) -> SemanticScoringOutcome:
        """Score already-admitted entries; raises typed
        ``EmbeddingProviderError`` subclasses on provider failure so
        the caller can fall back deterministically."""
        availability = self.provider.availability()
        if not availability.available:
            raise EmbeddingUnavailableError(availability)

        query_started = time.perf_counter()
        query_result = self.provider.embed_query(query_text)
        query_elapsed = (time.perf_counter() - query_started) * 1000.0
        query_zero = all(v == 0.0 for v in query_result.vector)

        memory_started = time.perf_counter()
        vectors, statuses = self._memory_vectors(entries)
        memory_elapsed = (time.perf_counter() - memory_started) * 1000.0

        raw: list[tuple[str, float, str]] = []
        for entry in entries:
            vector = vectors[entry.id]
            cosine = (
                0.0
                if query_zero
                else cosine_similarity(query_result.vector, vector)
            )
            raw.append((entry.id, cosine, statuses[entry.id]))

        ranked = sorted(
            raw, key=lambda item: (-max(0.0, item[1]), item[0])
        )
        scores: dict = {}
        above_floor = 0
        for rank, (memory_id, cosine, cache_status) in enumerate(
            ranked, start=1
        ):
            score = round(max(0.0, cosine), 6)
            qualifies = score > self.relevance_floor
            above_floor += int(qualifies)
            scores[memory_id] = SemanticScore(
                memory_id=memory_id,
                raw_cosine=round(cosine, 6),
                score=score,
                above_floor=qualifies,
                cache_status=cache_status,
                rank=rank,
            )
        return SemanticScoringOutcome(
            scores=scores,
            provider_id=query_result.provider_id,
            model_id=query_result.model_id,
            dimensions=query_result.dimensions,
            relevance_floor=self.relevance_floor,
            query_zero_vector=query_zero,
            eligible_count=len(entries),
            above_floor_count=above_floor,
            query_embedding={"elapsed_ms": round(query_elapsed, 3)},
            memory_embedding={"elapsed_ms": round(memory_elapsed, 3)},
            cache=self.cache.summary(),
        )

    def _memory_vectors(
        self, entries: tuple[ExperienceEntry, ...]
    ) -> tuple[dict, dict]:
        """Resolve vectors through the cache; batch-embed the misses.

        The optional provider reports ``dimensions=None`` before its
        first embed (late discovery): unknown dimensions make every
        lookup a miss, and entries are stored under the dimensions the
        provider actually returned — the key is never dimensionless.
        """
        vectors: dict = {}
        statuses: dict = {}
        pending: list[tuple[str, str, str]] = []  # (id, text, digest)
        known_dimensions = self.provider.dimensions
        for entry in entries:
            text = memory_embedding_text(entry)
            digest = content_digest(text)
            if known_dimensions is not None:
                cached = self.cache.get(
                    EmbeddingCacheKey(
                        provider_id=self.provider.provider_id,
                        model_id=self.provider.model_id,
                        dimensions=known_dimensions,
                        content_digest=digest,
                    )
                )
                if cached is not None:
                    vectors[entry.id] = cached
                    statuses[entry.id] = "hit"
                    continue
            pending.append((entry.id, text, digest))
        if pending:
            results = self.provider.embed_memories(
                [text for _, text, _ in pending]
            )
            for (memory_id, _, digest), result in zip(pending, results):
                self.cache.put(
                    EmbeddingCacheKey(
                        provider_id=result.provider_id,
                        model_id=result.model_id,
                        dimensions=result.dimensions,
                        content_digest=digest,
                    ),
                    result.vector,
                )
                vectors[memory_id] = result.vector
                statuses[memory_id] = "miss"
        return vectors, statuses
