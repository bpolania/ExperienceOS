"""Phase 11 Prompt 4: fused candidate union, ranking, and mode tests.

Fixture note: lexical retrieval strips a stopword list (remember,
know, what, you, ...) while the semantic representation keeps every
token. A query made of lexical stopwords therefore has zero lexical
relevance everywhere but strong deterministic-provider similarity to a
memory sharing those words — the honest way to build a semantic-only
evidence candidate without pretending the provider knows synonyms.
These are mechanism tests, not benchmark evidence.
"""

import os
import subprocess
import sys

import pytest

from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.context.semantic import SemanticCandidateGenerator
from experienceos.embeddings import DeterministicEmbeddingProvider
from experienceos.memory.schema import ExperienceEntry

STOPWORD_QUERY = "remember what you know"
# Shares ONLY lexical-stopword tokens with the stopword query: zero
# lexical relevance, strong semantic overlap.
SEMANTIC_ONLY_TEXT = "remember what you know about me"


def entry(text, kind="fact", metadata=None):
    return ExperienceEntry(
        user_id="u1", text=text, kind=kind, metadata=metadata or {}
    )


def fused_strategy(profile="full_fusion", **kwargs):
    return HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            DeterministicEmbeddingProvider()
        ),
        semantic_mode="fused",
        fusion_profile=profile,
        **kwargs,
    )


def test_union_admits_all_three_evidence_sources():
    memories = (
        entry("green tea every morning"),        # lexical for "green tea"
        entry(SEMANTIC_ONLY_TEXT),               # stopword-only lexically
        entry("unrelated budget spreadsheet"),   # no evidence
    )
    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="green tea " + STOPWORD_QUERY, memories=memories, k=3
        )
    )
    by_text = {c.memory.text: c for c in result.candidates}
    lexical = by_text["green tea every morning"]
    semantic_only = by_text[SEMANTIC_ONLY_TEXT]
    none = by_text["unrelated budget spreadsheet"]
    assert lexical.fusion["evidence_source"] == "lexical_and_semantic"
    assert semantic_only.fusion["evidence_source"] == "semantic_only"
    assert semantic_only.selected or semantic_only.rank > 0
    assert none.exclusion_reason == "no_fused_evidence"
    assert none.fusion is None
    summary = result.semantic["fusion"]
    assert summary["semantic_only_count"] == 1
    assert summary["union_count"] == 2
    assert summary["promoted_by_semantic"] == 1


def test_semantic_only_candidate_below_floor_does_not_enter():
    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="green tea",
            memories=(entry("green tea daily"), entry("weekly retro notes")),
            k=2,
        )
    )
    excluded = next(
        c for c in result.candidates
        if c.memory.text == "weekly retro notes"
    )
    assert excluded.exclusion_reason == "no_fused_evidence"
    assert len(result.selected) == 1  # no padding to K


def test_below_floor_semantic_still_refines_lexical_candidate():
    """A lexically relevant memory keeps its (below-floor) semantic
    contribution — the documented §13 rule."""
    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="what drink does the user prefer",
            memories=(
                entry(
                    "Green tea every morning, always.",
                    metadata={"semantic_identity": {
                        "attribute": "preferred_drink",
                        "value": "green tea",
                    }},
                ),
            ),
            k=1,
        )
    )
    candidate = next(c for c in result.candidates if c.rank)
    assert candidate.semantic["above_floor"] is False
    assert candidate.fusion["evidence_source"] == "lexical_only"
    semantic_contribution = candidate.fusion["contributions"]["semantic"]
    assert semantic_contribution > 0.0  # refines despite below floor


def test_union_has_no_duplicates():
    memory = entry("green tea " + SEMANTIC_ONLY_TEXT)
    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="green tea " + STOPWORD_QUERY, memories=(memory,), k=2
        )
    )
    assert sum(
        1 for c in result.candidates if c.memory.id == memory.id
    ) == 1


def test_exact_lexical_match_stays_competitive():
    exact = entry("prefers green tea daily")
    weak_semantic = entry("remember what you know about tea")
    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="green tea preference",  # no lexical stopwords
            memories=(exact, weak_semantic),
            k=2,
        )
    )
    ranked = sorted(
        (c for c in result.candidates if c.rank), key=lambda c: c.rank
    )
    assert ranked[0].memory.id == exact.id
    # The outcome follows the documented contributions, not a rule
    # that exact matches always win.
    assert ranked[0].fusion["fused_score"] > (
        ranked[1].fusion["fused_score"] if len(ranked) > 1 else 0.0
    )


def test_semantic_evidence_changes_rank_in_fused_profile():
    """Improvement-mechanism fixture: the competitor wins on lexical
    evidence (shares "tea" AND "supplies" with the query), the target
    wins on semantic overlap (shares the stopword tokens the lexical
    path strips). Fusion reorders them; the lexical baseline does
    not."""
    target = entry("tea ritual: remember what you know about tea")
    competitor = entry("tea supplies restock list")
    query = "tea supplies " + STOPWORD_QUERY
    lexical_result = HybridRetrievalStrategy().retrieve(
        RetrievalRequest(query=query, memories=(competitor, target), k=2)
    )
    lexical_top = next(
        c for c in lexical_result.candidates if c.rank == 1
    )
    assert lexical_top.memory.id == competitor.id  # lexical order
    fused_result = fused_strategy().retrieve(
        RetrievalRequest(query=query, memories=(competitor, target), k=2)
    )
    fused_top = next(c for c in fused_result.candidates if c.rank == 1)
    assert fused_top.memory.id == target.id  # semantic reordered
    assert fused_top.fusion["contributions"]["semantic"] > 0.0
    assert fused_top.fusion["lexical_rank"] == 2
    assert fused_top.fusion["fused_rank"] == 1
    assert fused_top.fusion["rank_delta"] == 1
    demoted = next(
        c for c in fused_result.candidates
        if c.memory.id == competitor.id
    )
    assert demoted.fusion["rank_delta"] == -1
    assert fused_result.semantic["fusion"]["demoted_after_fusion"] == 1


def test_rank_fields_and_deltas_consistent():
    memories = (
        entry("green tea every morning"),
        entry("green tea supplies restock"),
        entry(SEMANTIC_ONLY_TEXT),
    )
    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="green tea " + STOPWORD_QUERY, memories=memories, k=3
        )
    )
    for candidate in result.candidates:
        if candidate.fusion is None:
            continue
        assert candidate.fusion["fused_rank"] == candidate.rank or (
            candidate.rank == 0  # trimmed by a later limit
        )
        if candidate.fusion["lexical_rank"] is not None:
            assert candidate.fusion["rank_delta"] == (
                candidate.fusion["lexical_rank"]
                - candidate.fusion["fused_rank"]
            )
        else:
            assert candidate.fusion["evidence_source"] == "semantic_only"


def test_candidate_limit_and_budget_enforced_in_fused_mode():
    memories = tuple(
        entry(f"green tea variation number {i}") for i in range(6)
    )
    strategy = fused_strategy()
    strategy.candidate_limit = 3
    result = strategy.retrieve(
        RetrievalRequest(
            query="green tea", memories=memories, k=2, token_budget=12
        )
    )
    assert sum(
        1 for c in result.candidates
        if c.exclusion_reason == "below_candidate_limit"
    ) == 3
    assert result.semantic["fusion"]["post_limit_count"] == 3
    assert len(result.selected) <= 2
    assert result.context_token_estimate <= 12
    assert result.budget_compliant is True


def test_score_only_mode_still_ranking_neutral():
    memories = (
        entry("green tea every morning"),
        entry(SEMANTIC_ONLY_TEXT),
        entry("budget spreadsheet"),
    )
    request = RetrievalRequest(
        query="green tea " + STOPWORD_QUERY, memories=memories, k=2
    )
    baseline = HybridRetrievalStrategy().retrieve(request)
    score_only = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            DeterministicEmbeddingProvider()
        ),
        semantic_mode="score_only",
    ).retrieve(request)
    assert [m.id for m in baseline.selected] == [
        m.id for m in score_only.selected
    ]
    assert [(c.memory.id, c.rank, c.final_score)
            for c in baseline.candidates] == [
        (c.memory.id, c.rank, c.final_score)
        for c in score_only.candidates
    ]
    # No semantic-only candidate entered, and no fusion ran.
    assert all(c.fusion is None for c in score_only.candidates)


def test_semantic_only_mode_unchanged_and_distinct_from_fused():
    memories = (entry("green tea daily"), entry("prefers green tea"))
    request = RetrievalRequest(query="green tea", memories=memories, k=2)
    semantic_only = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            DeterministicEmbeddingProvider()
        ),
        semantic_mode="semantic_only",
    ).retrieve(request)
    for candidate in semantic_only.candidates:
        # Pure semantic ranking: no lexical mixing, no fusion dict.
        assert candidate.fusion is None
        assert "lexical_score" not in candidate.component_scores
    assert semantic_only.selected


def test_embedding_only_profile_delegates_to_semantic_only_path():
    memories = (entry("green tea daily"), entry("prefers green tea"))
    request = RetrievalRequest(query="green tea", memories=memories, k=2)
    via_mode = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            DeterministicEmbeddingProvider()
        ),
        semantic_mode="semantic_only",
    ).retrieve(request)
    via_profile = fused_strategy(profile="embedding_only").retrieve(request)
    assert [(c.memory.id, c.final_score, c.rank)
            for c in via_mode.candidates] == [
        (c.memory.id, c.final_score, c.rank)
        for c in via_profile.candidates
    ]


def test_fused_double_run_is_identical_and_hashseed_independent():
    script = (
        "from tests.test_retrieval_fusion_modes import _fused_fingerprint\n"
        "print(_fused_fingerprint())\n"
    )
    outputs = set()
    for seed in ("0", "31337"):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
            env=dict(os.environ, PYTHONPATH=".", PYTHONHASHSEED=seed),
        )
        outputs.add(completed.stdout.strip())
    assert len(outputs) == 1
    assert _fused_fingerprint() in outputs


def _fused_fingerprint():
    memories = (
        ExperienceEntry(user_id="u1", text="green tea every morning",
                        id="m1"),
        ExperienceEntry(user_id="u1", text=SEMANTIC_ONLY_TEXT, id="m2"),
        ExperienceEntry(user_id="u1", text="budget spreadsheet", id="m3"),
        ExperienceEntry(user_id="u1", text="green tea supplies", id="m4"),
    )
    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="green tea " + STOPWORD_QUERY, memories=memories, k=3
        )
    )
    return repr([
        (c.memory.id, c.rank, c.final_score,
         c.fusion["contributions"] if c.fusion else None)
        for c in sorted(result.candidates, key=lambda c: c.memory.id)
    ])


def test_equal_fused_scores_tie_break_on_stable_id():
    a = ExperienceEntry(user_id="u1", text="green tea", id="aaa",
                        kind="fact")
    b = ExperienceEntry(user_id="u1", text="green tea", id="bbb",
                        kind="fact")
    b.created_at = a.created_at  # force full tie
    result = fused_strategy().retrieve(
        RetrievalRequest(query="green tea", memories=(b, a), k=2)
    )
    ranked = sorted(
        (c for c in result.candidates if c.rank), key=lambda c: c.rank
    )
    assert [c.memory.id for c in ranked] == ["aaa", "bbb"]


def test_diagnostics_serialize_without_vectors_or_paths():
    import json as _json

    result = fused_strategy().retrieve(
        RetrievalRequest(
            query="green tea", memories=(entry("green tea daily"),), k=1
        )
    )
    candidate = next(c for c in result.candidates if c.rank)
    payload = _json.dumps(
        {"fusion": candidate.fusion, "summary": result.semantic}
    )
    assert "/Users/" not in payload and "/home/" not in payload
    assert "[0." not in payload  # no serialized vector arrays
