"""Phase 11 Prompt 3: disabled-mode equivalence and provider fallback."""

import pytest

from experienceos.context.builder import ContextBuilder
from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.context.semantic import SemanticCandidateGenerator
from experienceos.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingAvailability,
    EmbeddingUnavailableError,
    EmbeddingUnavailableReason,
)
from experienceos.memory.schema import ExperienceEntry, MemoryStatus


def entry(text, status=MemoryStatus.ACTIVE):
    return ExperienceEntry(user_id="u1", text=text, status=status)


MEMORIES = (
    entry("prefers green tea daily"),
    entry("works at Initech as an engineer"),
    entry("budget report due Friday"),
    entry("stale preference", status=MemoryStatus.SUPERSEDED),
)
REQUEST = RetrievalRequest(
    query="green tea preference", memories=MEMORIES, k=2, token_budget=100
)


class PoisonedProvider(DeterministicEmbeddingProvider):
    """Fails loudly if any embedding call happens."""

    def availability(self):
        raise AssertionError("availability() called in disabled mode")

    def embed_query(self, text):
        raise AssertionError("embed_query called in disabled mode")

    def embed_memories(self, texts):
        raise AssertionError("embed_memories called in disabled mode")


class UnavailableProvider:
    """Protocol-conformant provider that is never available."""

    provider_id = "sentence-transformers-local"
    model_id = "local:unconfigured"
    dimensions = None

    def availability(self):
        return EmbeddingAvailability(
            available=False,
            reason=EmbeddingUnavailableReason.DEPENDENCY_MISSING,
            detail="Install the optional embedding dependency.",
        )

    def embed_query(self, text):
        raise EmbeddingUnavailableError(self.availability())

    def embed_memories(self, texts):
        raise EmbeddingUnavailableError(self.availability())


class MidFlightFailureProvider(DeterministicEmbeddingProvider):
    """Available on inspection, fails on first real embedding call."""

    def embed_query(self, text):
        raise EmbeddingUnavailableError(
            EmbeddingAvailability(
                available=False,
                reason=EmbeddingUnavailableReason.LOAD_FAILED,
                detail="model load failed: RuntimeError",
            )
        )


def _comparable(result):
    return {
        "selected": [m.id for m in result.selected],
        "candidates": [
            (c.memory.id, c.rank, c.final_score, c.exclusion_reason,
             dict(c.component_scores))
            for c in result.candidates
        ],
        "tokens": result.context_token_estimate,
        "counts": (
            result.active_count,
            result.inactive_filtered,
            result.lexical_candidates,
            result.zero_relevance_excluded,
        ),
    }


def test_disabled_mode_never_touches_provider_or_cache():
    generator = SemanticCandidateGenerator(PoisonedProvider())
    strategy = HybridRetrievalStrategy(
        semantic_generator=generator, semantic_mode="disabled"
    )
    result = strategy.retrieve(REQUEST)
    assert result.selected  # retrieval worked
    assert result.semantic == {}
    assert generator.cache.counters["lookups"] == 0
    assert len(generator.cache) == 0
    assert all(c.semantic is None for c in result.candidates)


def test_disabled_mode_is_equivalent_to_phase9_path():
    baseline = HybridRetrievalStrategy().retrieve(REQUEST)
    disabled = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(PoisonedProvider()),
        semantic_mode="disabled",
    ).retrieve(REQUEST)
    assert _comparable(baseline) == _comparable(disabled)


def test_disabled_mode_rendered_context_is_identical():
    store_entries = list(MEMORIES)
    baseline_builder = ContextBuilder(
        memory_budget=2, retrieval_strategy=HybridRetrievalStrategy()
    )
    disabled_builder = ContextBuilder(
        memory_budget=2,
        retrieval_strategy=HybridRetrievalStrategy(
            semantic_generator=SemanticCandidateGenerator(
                PoisonedProvider()
            ),
            semantic_mode="disabled",
        ),
    )
    kwargs = dict(
        user_id="u1",
        session_id="s1",
        message="green tea preference",
        memories=[m for m in store_entries if m.status == "active"],
    )
    baseline = baseline_builder.build_context(**kwargs)
    disabled = disabled_builder.build_context(**kwargs)
    assert baseline.messages == disabled.messages


def test_unavailable_provider_falls_back_to_lexical_path():
    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            UnavailableProvider()
        ),
        semantic_mode="semantic_only",
    )
    result = strategy.retrieve(REQUEST)
    baseline = HybridRetrievalStrategy().retrieve(REQUEST)
    assert [m.id for m in result.selected] == [
        m.id for m in baseline.selected
    ]
    assert result.semantic["fallback_used"] is True
    assert result.semantic["fallback_reason"] == "dependency_missing"
    assert result.semantic["provider_available"] is False
    # No fabricated semantic scores anywhere.
    assert all(
        "semantic_score" not in c.component_scores
        for c in result.candidates
    )


def test_fallback_is_deterministic():
    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            UnavailableProvider()
        ),
        semantic_mode="semantic_only",
    )
    first = strategy.retrieve(REQUEST)
    second = strategy.retrieve(REQUEST)
    assert _comparable(first) == _comparable(second)


def test_mid_flight_provider_failure_falls_back_sanitized():
    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            MidFlightFailureProvider()
        ),
        semantic_mode="semantic_only",
    )
    result = strategy.retrieve(REQUEST)
    assert result.semantic["fallback_used"] is True
    assert result.semantic["fallback_reason"] == "load_failed"
    text = str(result.semantic)
    assert "/Users/" not in text and "/home/" not in text
    assert result.selected  # lexical fallback selected memories


def test_strict_mode_raises_typed_error_instead_of_falling_back():
    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            UnavailableProvider()
        ),
        semantic_mode="semantic_only",
        semantic_strict=True,
    )
    with pytest.raises(EmbeddingUnavailableError) as excinfo:
        strategy.retrieve(REQUEST)
    assert excinfo.value.availability.reason == "dependency_missing"


def test_provider_failure_does_not_bypass_lifecycle_filter():
    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            UnavailableProvider()
        ),
        semantic_mode="semantic_only",
    )
    result = strategy.retrieve(REQUEST)
    superseded = next(
        c for c in result.candidates
        if c.memory.status == MemoryStatus.SUPERSEDED
    )
    assert superseded.exclusion_reason == "inactive_superseded"
    assert superseded.memory.id not in {m.id for m in result.selected}


def test_provider_failure_does_not_mutate_memories():
    memories = tuple(
        ExperienceEntry(user_id="u1", text=f"memory {i}") for i in range(3)
    )
    snapshot = [(m.id, m.status, m.text, m.updated_at) for m in memories]
    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            UnavailableProvider()
        ),
        semantic_mode="semantic_only",
    )
    strategy.retrieve(
        RetrievalRequest(query="memory", memories=memories, k=2)
    )
    assert [
        (m.id, m.status, m.text, m.updated_at) for m in memories
    ] == snapshot


def test_dimension_mismatch_between_query_and_cached_memory_is_impossible():
    """The cache key carries dimensions, so a provider dimension change
    can never pair an old memory vector with a new query vector."""
    from experienceos.embeddings import EmbeddingCache, EmbeddingCacheKey
    from experienceos.embeddings import content_digest

    cache = EmbeddingCache()
    old = EmbeddingCacheKey("p", "m", 4, content_digest("text"))
    cache.put(old, (1.0, 0.0, 0.0, 0.0))
    new = EmbeddingCacheKey("p", "m", 8, content_digest("text"))
    assert cache.get(new) is None
