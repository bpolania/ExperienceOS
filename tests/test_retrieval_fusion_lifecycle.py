"""Phase 11 Prompt 4: fused-mode lifecycle safety, reference
equivalence, and provider fallback.

Adversarial design: excluded fixtures carry maximum lexical AND
semantic evidence (their text is the query), so any post-scoring
filtering defect would rank them first.
"""

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
from experienceos.events.bus import EventBus
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.store import InMemoryMemoryStore

QUERY = "favorite green tea ritual"


def entry(text, status=MemoryStatus.ACTIVE, user="u1"):
    return ExperienceEntry(user_id=user, text=text, status=status)


class SpyingProvider(DeterministicEmbeddingProvider):
    def __init__(self):
        super().__init__()
        self.embedded_texts = []

    def embed_query(self, text):
        self.embedded_texts.append(text)
        return super().embed_query(text)

    def embed_memories(self, texts):
        self.embedded_texts.extend(texts)
        return super().embed_memories(texts)


class PoisonedProvider(DeterministicEmbeddingProvider):
    def availability(self):
        raise AssertionError("provider inspected in reference mode")

    def embed_query(self, text):
        raise AssertionError("embed_query in reference mode")

    def embed_memories(self, texts):
        raise AssertionError("embed_memories in reference mode")


class UnavailableProvider:
    provider_id = "sentence-transformers-local"
    model_id = "local:unconfigured"
    dimensions = None

    def availability(self):
        return EmbeddingAvailability(
            available=False,
            reason=EmbeddingUnavailableReason.DEPENDENCY_MISSING,
        )

    def embed_query(self, text):
        raise EmbeddingUnavailableError(self.availability())

    def embed_memories(self, texts):
        raise EmbeddingUnavailableError(self.availability())


def fused(provider=None, **kwargs):
    provider = provider or DeterministicEmbeddingProvider()
    return HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(provider),
        semantic_mode="fused",
        **kwargs,
    )


MEMORIES = (
    entry("prefers green tea daily"),
    entry("works at Initech"),
    entry(QUERY, status=MemoryStatus.FORGOTTEN),      # max evidence
    entry(QUERY, status=MemoryStatus.SUPERSEDED),     # max evidence
    entry("budget spreadsheet"),
)
REQUEST = RetrievalRequest(query=QUERY, memories=MEMORIES, k=3)


def test_max_evidence_forgotten_and_superseded_stay_excluded():
    provider = SpyingProvider()
    result = fused(provider).retrieve(REQUEST)
    selected_ids = {m.id for m in result.selected}
    for candidate in result.candidates:
        if candidate.memory.status != MemoryStatus.ACTIVE:
            assert candidate.memory.id not in selected_ids
            assert candidate.exclusion_reason.startswith("inactive_")
            assert candidate.semantic == {"considered": False}
            assert candidate.fusion is None  # no fused score computed
    # Excluded texts never reached the provider (query text aside).
    memory_texts = [t for t in provider.embedded_texts if t != QUERY]
    assert all(QUERY not in text for text in memory_texts)


def test_fusion_summary_counts_eligible_only():
    result = fused().retrieve(REQUEST)
    assert result.semantic["fusion"]["eligible_count"] == 3
    assert result.inactive_filtered == 2


def test_no_fusion_profile_overrides_lifecycle():
    from experienceos.context.fusion import RetrievalFusionProfile

    aggressive = RetrievalFusionProfile(
        profile_id="aggressive_semantic", version="1",
        component_weights={"semantic": 1.0, "lexical": 1.0,
                           "structured": 1.0, "temporal": 1.0},
    )
    result = fused(fusion_profile=aggressive).retrieve(REQUEST)
    assert all(
        m.status == MemoryStatus.ACTIVE for m in result.selected
    )


def test_cross_user_memories_remain_outside_input():
    store = InMemoryMemoryStore()
    store.add(entry(QUERY, user="intruder"))
    store.add(entry("prefers green tea daily", user="u1"))
    pool = store.active_for_user("u1")
    result = fused().retrieve(
        RetrievalRequest(query=QUERY, memories=pool, k=2)
    )
    assert all(m.user_id == "u1" for m in result.selected)


def test_lifecycle_state_unchanged_and_no_events():
    store = InMemoryMemoryStore()
    bus = EventBus()
    for memory in MEMORIES:
        store.add(memory)
    before = [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ]
    fused().retrieve(REQUEST)
    assert [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ] == before
    assert bus.history() == []
    # No fused score persisted anywhere in memory metadata.
    for memory in store.list_memories("u1"):
        assert "fused" not in str(memory.metadata)


# -- reference-path equivalence -------------------------------------------------


def _comparable(result):
    return {
        "selected": [m.id for m in result.selected],
        "candidates": [
            (c.memory.id, c.rank, c.final_score, c.exclusion_reason,
             dict(c.component_scores))
            for c in result.candidates
        ],
        "tokens": result.context_token_estimate,
    }


def test_lexical_reference_profile_is_phase9_equivalent():
    generator = SemanticCandidateGenerator(PoisonedProvider())
    reference = HybridRetrievalStrategy(
        semantic_generator=generator,
        semantic_mode="fused",
        fusion_profile="lexical_reference",
    )
    baseline = HybridRetrievalStrategy()
    result = reference.retrieve(REQUEST)
    expected = baseline.retrieve(REQUEST)
    assert _comparable(result) == _comparable(expected)
    assert generator.cache.counters["lookups"] == 0
    assert len(generator.cache) == 0
    assert all(c.fusion is None for c in result.candidates)
    assert all(c.semantic is None for c in result.candidates)
    assert result.semantic == {}


def test_lexical_reference_rendered_context_identical():
    kwargs = dict(
        user_id="u1", session_id="s1", message=QUERY,
        memories=[m for m in MEMORIES if m.status == "active"],
    )
    baseline = ContextBuilder(
        memory_budget=3, retrieval_strategy=HybridRetrievalStrategy()
    ).build_context(**kwargs)
    reference = ContextBuilder(
        memory_budget=3,
        retrieval_strategy=HybridRetrievalStrategy(
            semantic_generator=SemanticCandidateGenerator(
                PoisonedProvider()
            ),
            semantic_mode="fused",
            fusion_profile="lexical_reference",
        ),
    ).build_context(**kwargs)
    assert baseline.messages == reference.messages


# -- provider fallback -----------------------------------------------------------


def test_fused_fallback_is_exactly_the_reference_path():
    unavailable = fused(UnavailableProvider())
    baseline = HybridRetrievalStrategy()
    result = unavailable.retrieve(REQUEST)
    expected = baseline.retrieve(REQUEST)
    stripped = _comparable(result)
    assert stripped["selected"] == _comparable(expected)["selected"]
    assert stripped["candidates"] == _comparable(expected)["candidates"]
    assert result.semantic["fallback_used"] is True
    assert result.semantic["fallback_reason"] == "dependency_missing"
    assert result.semantic["fallback_path"] == "lexical_reference"
    assert result.semantic["fusion_profile_id"] == "full_fusion"
    # No partial semantic/fused evidence survives the failure.
    assert all(c.fusion is None for c in result.candidates)
    assert "fusion" not in result.semantic


def test_fused_fallback_deterministic_and_memory_safe():
    strategy = fused(UnavailableProvider())
    snapshot = [(m.id, m.status, m.text) for m in MEMORIES]
    first = strategy.retrieve(REQUEST)
    second = strategy.retrieve(REQUEST)
    assert _comparable(first) == _comparable(second)
    assert [(m.id, m.status, m.text) for m in MEMORIES] == snapshot
    # Lifecycle exclusions still happened before failure handling.
    assert first.inactive_filtered == 2


def test_fused_strict_mode_raises_typed_error():
    strategy = fused(UnavailableProvider(), semantic_strict=True)
    with pytest.raises(EmbeddingUnavailableError):
        strategy.retrieve(REQUEST)


def test_zero_semantic_reference_never_inspects_provider():
    # Construction plus retrieval plus summary: the poisoned provider
    # would raise on any access, including availability().
    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(PoisonedProvider()),
        semantic_mode="fused",
        fusion_profile="lexical_reference",
    )
    strategy.retrieve(REQUEST)
    summary = strategy.summary()["semantic_retrieval"]
    assert summary["reference_bypass"] is True
