"""Phase 11 Prompt 3: semantic retrieval mode and ranking tests.

All fixtures use the deterministic feature-hash provider and are built
around its documented token-overlap behavior — shared meaningful
tokens score high, disjoint texts score near zero. No fixture pretends
the provider understands synonyms.
"""

import pytest

from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.context.semantic import (
    DEFAULT_SEMANTIC_FLOOR,
    SEMANTIC_MODES,
    SemanticCandidateGenerator,
    memory_embedding_text,
)
from experienceos.embeddings import DeterministicEmbeddingProvider
from experienceos.memory.schema import ExperienceEntry


def entry(text, kind="fact", metadata=None, user="u1"):
    return ExperienceEntry(
        user_id=user, text=text, kind=kind, metadata=metadata or {}
    )


def semantic_strategy(mode="semantic_only", floor=DEFAULT_SEMANTIC_FLOOR,
                      **kwargs):
    generator = SemanticCandidateGenerator(
        DeterministicEmbeddingProvider(), relevance_floor=floor
    )
    return HybridRetrievalStrategy(
        semantic_generator=generator, semantic_mode=mode, **kwargs
    ), generator


def test_mode_validation():
    assert SEMANTIC_MODES == ("disabled", "score_only", "semantic_only")
    with pytest.raises(ValueError):
        HybridRetrievalStrategy(semantic_mode="fusion")
    with pytest.raises(ValueError):
        HybridRetrievalStrategy(semantic_mode="semantic_only")  # no generator


def test_semantic_only_retrieves_strongly_related_memory_first():
    strategy, _ = semantic_strategy()
    memories = (
        entry("prefers green tea daily"),
        entry("budget report due Friday"),
        entry("lives in Lisbon"),
    )
    result = strategy.retrieve(
        RetrievalRequest(query="green tea preference", memories=memories, k=2)
    )
    assert [m.text for m in result.selected] == ["prefers green tea daily"]
    top = next(c for c in result.candidates if c.selected)
    assert top.component_scores["semantic_score"] > DEFAULT_SEMANTIC_FLOOR
    assert top.semantic["considered"] is True
    assert top.semantic["rank"] == 1


def test_lexical_text_mismatch_found_through_canonicalization():
    """The memory text shares no token with the query; the canonical
    embedding text adds the semantic-identity attribute/value tokens
    (preferred, drink), which the query matches strongly. This
    validates canonicalization plumbing — lexical retrieval's own
    structured attribute signal would also score this memory, so no
    superiority claim is made."""
    target = entry(
        "Cappuccino, oat milk, extra hot.",
        kind="preference",
        metadata={
            "semantic_identity": {
                "attribute": "preferred_drink",
                "value": "cappuccino",
            }
        },
    )
    strategy, _ = semantic_strategy()
    result = strategy.retrieve(
        RetrievalRequest(
            query="preferred drink",
            memories=(target, entry("budget report due Friday")),
            k=1,
        )
    )
    assert [m.id for m in result.selected] == [target.id]
    # And the canonical text is exactly what made this possible.
    canonical = memory_embedding_text(target)
    assert "preferred drink" in canonical
    assert "cappuccino" in canonical


def test_unrelated_text_stays_below_floor_and_is_not_padded():
    strategy, _ = semantic_strategy()
    memories = (
        entry("prefers green tea daily"),
        entry("budget report due Friday"),
        entry("cat photos folder backup"),
    )
    result = strategy.retrieve(
        RetrievalRequest(query="green tea preference", memories=memories, k=3)
    )
    # K=3 but only one memory qualifies: no zero-score padding.
    assert len(result.selected) == 1
    floored = [
        c for c in result.candidates
        if c.exclusion_reason == "below_semantic_floor"
    ]
    assert len(floored) == 2
    for candidate in floored:
        assert candidate.semantic["above_floor"] is False
        assert candidate.selected is False


def test_deterministic_double_run_identical():
    strategy, generator = semantic_strategy()
    memories = (
        entry("prefers green tea daily"),
        entry("green tea in the morning"),
        entry("budget report due Friday"),
    )
    request = RetrievalRequest(
        query="green tea preference", memories=memories, k=2
    )
    first = strategy.retrieve(request)
    hits_before = generator.cache.counters["hits"]
    second = strategy.retrieve(request)
    assert [m.id for m in first.selected] == [m.id for m in second.selected]
    assert [
        (c.memory.id, c.final_score, c.rank) for c in first.candidates
    ] == [(c.memory.id, c.final_score, c.rank) for c in second.candidates]
    # Second run resolved memory vectors from the cache.
    assert generator.cache.counters["hits"] > hits_before


def test_semantic_only_tie_break_is_stable():
    a = entry("green tea", kind="preference")
    b = entry("green tea", kind="preference")
    strategy, _ = semantic_strategy()
    result = strategy.retrieve(
        RetrievalRequest(query="green tea", memories=(b, a), k=2)
    )
    ranked = [c for c in result.candidates if c.rank]
    # Identical scores, kinds, confidence: created_at then ID decides,
    # deterministically.
    assert [c.memory.id for c in ranked] == sorted(
        [a.id, b.id],
        key=lambda mid: next(
            (-m.created_at.timestamp(), m.id) for m in (a, b) if m.id == mid
        ),
    )


def test_candidate_limit_enforced_in_semantic_mode():
    memories = tuple(
        entry(f"green tea variation {i}") for i in range(6)
    )
    strategy, _ = semantic_strategy()
    strategy.candidate_limit = 3
    result = strategy.retrieve(
        RetrievalRequest(query="green tea", memories=memories, k=2)
    )
    limited = [
        c for c in result.candidates
        if c.exclusion_reason == "below_candidate_limit"
    ]
    assert len(limited) == 3  # 6 qualify, limit max(3, k=2) = 3
    assert len(result.selected) == 2


def test_token_budget_enforced_in_semantic_mode():
    strategy, _ = semantic_strategy()
    long_text = "green tea " * 40
    result = strategy.retrieve(
        RetrievalRequest(
            query="green tea",
            memories=(entry("green tea daily"), entry(long_text.strip())),
            k=2,
            token_budget=20,
        )
    )
    budgeted = [
        c for c in result.candidates if c.exclusion_reason == "token_budget"
    ]
    assert len(budgeted) == 1
    assert result.budget_compliant is True
    assert result.context_token_estimate <= 20


def test_score_only_mode_preserves_lexical_ranking():
    memories = (
        entry("prefers green tea daily"),
        entry("green tea in the morning"),
        entry("budget report due Friday"),
    )
    request = RetrievalRequest(
        query="green tea preference", memories=memories, k=2
    )
    baseline = HybridRetrievalStrategy().retrieve(request)
    strategy, _ = semantic_strategy(mode="score_only")
    scored = strategy.retrieve(request)
    assert [m.id for m in baseline.selected] == [
        m.id for m in scored.selected
    ]
    assert [(c.memory.id, c.rank, c.final_score)
            for c in baseline.candidates] == [
        (c.memory.id, c.rank, c.final_score) for c in scored.candidates
    ]
    # But semantic evidence rides along for considered candidates.
    considered = [c for c in scored.candidates if c.semantic]
    assert considered
    assert all(
        "score" in c.semantic
        for c in considered if c.semantic.get("considered")
    )
    assert scored.semantic["mode"] == "score_only"


def test_zero_vector_query_produces_no_semantic_candidates():
    strategy, _ = semantic_strategy()
    result = strategy.retrieve(
        RetrievalRequest(
            query="...", memories=(entry("green tea daily"),), k=1
        )
    )
    assert result.selected == []
    assert result.semantic["query_zero_vector"] is True
    assert result.semantic["semantic_candidate_count"] == 0
    floored = [
        c for c in result.candidates
        if c.exclusion_reason == "below_semantic_floor"
    ]
    assert len(floored) == 1
    assert floored[0].component_scores["semantic_score"] == 0.0


def test_retrieval_summary_reports_semantic_block_only_when_enabled():
    strategy, _ = semantic_strategy()
    summary = strategy.summary()
    assert summary["semantic_retrieval"]["mode"] == "semantic_only"
    assert summary["semantic_retrieval"]["relevance_floor"] == (
        DEFAULT_SEMANTIC_FLOOR
    )
    assert "semantic_retrieval" not in HybridRetrievalStrategy().summary()


def test_result_semantic_summary_fields():
    strategy, _ = semantic_strategy()
    result = strategy.retrieve(
        RetrievalRequest(
            query="green tea",
            memories=(entry("green tea daily"), entry("budget Friday")),
            k=1,
        )
    )
    block = result.semantic
    assert block["enabled"] is True
    assert block["provider_available"] is True
    assert block["provider_id"] == "deterministic"
    assert block["model_id"] == "stable-feature-hash-v1"
    assert block["dimensions"] == 512
    assert block["eligible_count"] == 2
    assert block["scored_count"] == 2
    assert block["fallback_used"] is False
    assert "elapsed_ms" in block["query_embedding"]
    assert "elapsed_ms" in block["memory_embedding"]
    assert block["cache"]["size"] == 2
    # No raw vectors anywhere in the summary: every value is a scalar,
    # None, or a small dict of scalars.
    for value in block.values():
        assert not isinstance(value, (tuple, list))
        if isinstance(value, dict):
            assert all(
                not isinstance(v, (tuple, list)) for v in value.values()
            )


def test_diagnostics_contain_no_vectors_or_personal_paths():
    strategy, _ = semantic_strategy()
    result = strategy.retrieve(
        RetrievalRequest(
            query="green tea", memories=(entry("green tea daily"),), k=1
        )
    )
    for candidate in result.candidates:
        text = str(candidate.semantic)
        assert "/Users/" not in text and "/home/" not in text
        assert "(0." not in text  # no tuple-of-floats vector reprs


def test_canonicalization_includes_meaning_and_excludes_lifecycle():
    memory = entry(
        "Green tea every morning.",
        kind="preference",
        metadata={
            "semantic_identity": {
                "attribute": "preferred_drink",
                "value": "green_tea",
                "scope": "weekday_mornings",
            },
            "tags": ["food", "routine"],
        },
    )
    canonical = memory_embedding_text(memory)
    assert canonical == (
        "Green tea every morning.\npreferred drink\ngreen tea\n"
        "weekday mornings\nfood\nroutine"
    )
    assert memory.id not in canonical
    assert memory.user_id not in canonical.split("\n")[0]
    assert "active" not in canonical
    # global scope and empty fields are omitted.
    plain = entry("Just text.")
    assert memory_embedding_text(plain) == "Just text."


def test_canonical_text_change_changes_cache_digest():
    from experienceos.embeddings import content_digest

    a = entry("green tea", metadata={"tags": ["food"]})
    b = entry("green tea", metadata={"tags": ["travel"]})
    assert content_digest(memory_embedding_text(a)) != content_digest(
        memory_embedding_text(b)
    )


def test_generator_rejects_invalid_floor():
    with pytest.raises(ValueError):
        SemanticCandidateGenerator(
            DeterministicEmbeddingProvider(), relevance_floor=1.5
        )
