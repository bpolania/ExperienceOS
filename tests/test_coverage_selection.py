"""Phase 9 Prompt 5: coverage-aware context selection tests.

All tests run offline and deterministically.
"""

import json
from pathlib import Path

import pytest

from experienceos import ExperienceOS
from experienceos.context.builder import ContextBuilder
from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
    normalize_query,
)
from experienceos.context.selection import (
    COVERAGE_WEIGHTS,
    CoverageSelectionStrategy,
    SelectionRequest,
    candidate_facets,
    extract_query_facets,
    redundancy_signals,
)
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.semantic import METADATA_KEY, SemanticNormalizer
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.providers import MockProvider

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "benchmarks/fixtures/phase9_dev/coverage_selection/cases.json"
    ).read_text()
)

_NORMALIZER = SemanticNormalizer()


def entry(kind, text, session="s1", identity=None):
    record = ExperienceEntry(
        user_id="u", text=text, kind=kind, status=MemoryStatus.ACTIVE,
        source_session_id=session,
    )
    resolved = identity or (
        _NORMALIZER.normalize(kind, text)
        and _NORMALIZER.normalize(kind, text).to_metadata()
    )
    if resolved:
        record.metadata[METADATA_KEY] = dict(resolved)
    return record


def coverage_strategy():
    selector = CoverageSelectionStrategy()
    return HybridRetrievalStrategy(selection_strategy=selector), selector


def retrieve(memories, query, k=4, token_budget=None):
    strategy, selector = coverage_strategy()
    result = strategy.retrieve(
        RetrievalRequest(
            query=query, memories=tuple(memories), k=k,
            token_budget=token_budget,
        )
    )
    return result, selector


def selected_texts(result):
    return [m.text for m in result.selected]


def scored_candidates(memories, query, k=8):
    plain = HybridRetrievalStrategy()
    result = plain.retrieve(
        RetrievalRequest(query=query, memories=tuple(memories), k=k)
    )
    return tuple(c for c in result.candidates if c.rank > 0)


# --- Query facet extraction --------------------------------------------------------


def facets_for(text):
    return extract_query_facets(normalize_query(text))


def test_single_attribute_facet():
    facets = facets_for("What is my employer?")
    assert "attribute:employer" in facets.facets
    assert not facets.multi_facet


def test_two_explicit_attributes_multi_facet():
    facets = facets_for("What phone do I use and where do I work?")
    assert "attribute:phone" in facets.facets
    assert "attribute:employer" in facets.facets
    assert facets.multi_facet


def test_conjunction_cue():
    assert facets_for("Book a flight and also a hotel.").multi_facet


def test_multiple_entities_multi_facet():
    facets = facets_for("Compare Globex and Initech for me.")
    assert facets.multi_facet
    entity_facets = [f for f in facets.facets if f.startswith("entity:")]
    assert len(entity_facets) >= 2


def test_scoped_query_tokens_present():
    facets = facets_for("Plan my long international trip.")
    assert "token:international" in facets.facets
    assert "domain:travel" in facets.facets


def test_multi_valued_request_cue():
    assert facets_for("Which languages do I speak?").multi_valued
    assert not facets_for("What is my employer?").multi_valued


def test_no_facets_inferred_from_unrelated_words():
    facets = facets_for("Hello there!")
    assert not any(
        f.startswith("attribute:") for f in facets.facets
    )


def test_facet_ordering_is_stable():
    a = facets_for("What phone do I use and where do I work?")
    b = facets_for("What phone do I use and where do I work?")
    assert a.facets == b.facets
    assert a.version == "1"


# --- Candidate facets ---------------------------------------------------------------


def test_candidate_facets_grounded_in_metadata_and_evidence():
    memories = [entry("fact", "Works for Globex.", "s7")]
    candidate = scored_candidates(memories, "What is my employer Globex?")[0]
    facets = candidate_facets(candidate)
    assert "attribute:employer" in facets
    assert "value:employer=globex" in facets
    assert "kind:fact" in facets
    assert any(f.startswith("entity:globex") for f in facets)
    # provenance untouched
    assert candidate.memory.source_session_id == "s7"
    assert candidate.memory.metadata[METADATA_KEY]["attribute"] == "employer"


def test_candidate_scope_facet():
    memories = [
        entry("preference", "Prefers window seats for long international trips.")
    ]
    candidate = scored_candidates(
        memories, "Book my long international flight."
    )[0]
    assert "scope:long_international_trip" in candidate_facets(candidate)


# --- Redundancy ---------------------------------------------------------------------


def pair(query, first, second):
    candidates = scored_candidates([first, second], query)
    by_text = {c.memory.text: c for c in candidates}
    return by_text[first.text], by_text[second.text]


def test_same_slot_same_value_is_redundant():
    a, b = pair(
        "Which phone do I have?",
        entry("fact", "Phone is a Pixel 9."),
        entry("fact", "Current phone is Pixel 9."),
    )
    assert "same_slot_value" in redundancy_signals(b, [a])


def test_multi_valued_different_values_not_redundant():
    a, b = pair(
        "Which languages do I speak?",
        entry("fact", "Speaks Spanish."),
        entry("fact", "Speaks Portuguese."),
    )
    assert redundancy_signals(b, [a]) == ()


def test_conflicting_slot_flagged():
    a, b = pair(
        "What is my employer?",
        entry("fact", "Works for Globex."),
        entry("fact", "Works for Initech."),
    )
    assert "conflicting_slot" in redundancy_signals(b, [a])


def test_same_session_different_attributes_not_redundant():
    a, b = pair(
        "Where do I work and which phone do I use?",
        entry("fact", "Works for Globex.", "s1"),
        entry("fact", "Phone is a Pixel 9.", "s1"),
    )
    assert redundancy_signals(b, [a]) == ()


def test_near_duplicate_text_redundant():
    a, b = pair(
        "Which seat should I book for trips?",
        entry("preference", "Prefers aisle seats for short work trips."),
        entry("preference", "Prefers aisle seats for short work trips!"),
    )
    assert "near_duplicate_text" in redundancy_signals(b, [a])


# --- Coverage selection ----------------------------------------------------------


def test_strongest_direct_match_stays_first():
    memories = [
        entry("fact", "Works for Globex.", "s1"),
        entry("fact", "Globex office is in Austin.", "s2"),
        entry("preference", "Likes tea.", "s3"),
    ]
    result, _ = retrieve(memories, "What is my employer?")
    assert selected_texts(result)[0] == "Works for Globex."


def test_uncovered_attribute_beats_paraphrase():
    memories = [
        entry("fact", "Phone is a Pixel 9.", "s1"),
        entry("fact", "Works for Globex.", "s2"),
        entry("fact", "Current phone is Pixel 9.", "s3"),
    ]
    result, _ = retrieve(
        memories, "What phone do I use and where do I work?", k=2
    )
    texts = selected_texts(result)
    assert len(texts) == 2
    assert any("Globex" in t for t in texts)
    assert any("Pixel 9" in t for t in texts)


def test_multi_value_complement_selected():
    memories = [
        entry("fact", "Speaks Spanish.", "s1"),
        entry("fact", "Speaks Portuguese.", "s2"),
    ]
    result, _ = retrieve(memories, "Which languages do I speak?", k=2)
    assert sorted(selected_texts(result)) == [
        "Speaks Portuguese.", "Speaks Spanish.",
    ]


def test_instruction_preserved_for_applicable_query():
    memories = [
        entry("instruction", "Use Celsius for weather reports.", "s1"),
        entry("fact", "Lives in Seattle.", "s2"),
        entry("preference", "Likes hiking.", "s3"),
    ]
    result, _ = retrieve(memories, "Give me tomorrow's weather forecast.", k=2)
    assert "Use Celsius for weather reports." in selected_texts(result)


def test_source_diversity_is_bounded_not_quota():
    # Two useful memories from ONE session both selected.
    memories = [
        entry("fact", "Works for Globex.", "s1"),
        entry("fact", "Globex office is in Austin.", "s1"),
    ]
    result, _ = retrieve(
        memories, "Where do I work and where is the office?", k=2
    )
    assert len(result.selected) == 2


def test_no_positive_utility_stops_selection():
    memories = [
        entry("fact", "Works for Globex."),
        entry("preference", "Likes tea."),
    ]
    result, selector = retrieve(memories, "What's the capital of France?")
    assert result.selected == []
    # zero-relevance exclusion upstream; nothing reaches selection
    assert selector.counters["selected_total"] == 0


def test_no_zero_padding_with_spare_k():
    memories = [
        entry("fact", "Works for Globex."),
        entry("preference", "Likes tea."),
        entry("preference", "Likes hiking."),
    ]
    result, _ = retrieve(memories, "What is my employer?", k=4)
    assert selected_texts(result) == ["Works for Globex."]  # unused K allowed


def test_conflict_gets_warning_not_diversity():
    memories = [
        entry("fact", "Works for Globex.", "s1"),
        entry("fact", "Works for Initech.", "s2"),
    ]
    result, selector = retrieve(memories, "What is my employer?", k=2)
    # The conflict must be visible: either a selected step carries the
    # warning, or the conflicting candidate is explicitly CONTAINED —
    # never presented as useful source diversity, never concealed.
    assert result.coverage["conflict_warnings"] >= 1
    contained = [
        c for c in result.candidates
        if c.exclusion_reason == "conflict_contained"
    ]
    warned_steps = [
        s for s in result.coverage["steps"] if s["conflict_warning"]
    ]
    assert contained or warned_steps
    for step in warned_steps:
        assert step["source_diversity_gain"] == 0.0
        assert "UNRESOLVED CONFLICT" in step["reason"]
    assert selector.counters["selected_with_conflict_warning"] == 1
    # Exactly one employer value reaches context; the other stays out.
    # Which one wins follows the pre-existing deterministic recency
    # tie-break (Prompt 4 rank), with the conflict visibly contained.
    assert len(result.selected) == 1
    assert result.selected[0].text == "Works for Initech."


def test_token_efficiency_and_weights_versioned():
    assert COVERAGE_WEIGHTS["token_efficiency"] < COVERAGE_WEIGHTS["base_relevance"]
    selector = CoverageSelectionStrategy()
    summary = selector.summary()
    assert summary["coverage_weights_version"] == "1"
    assert summary["selection_strategy_version"] == "1"
    assert summary["zero_value_padding"] is False


# --- Lifecycle safety ------------------------------------------------------------


def test_inactive_never_reaches_selection():
    memories = [
        entry("fact", "Phone is a Pixel 9."),
        entry("fact", "Phone is a Pixel 6."),
    ]
    memories[1].status = MemoryStatus.SUPERSEDED
    forgotten = entry("preference", "Prefers morning flights.")
    forgotten.status = MemoryStatus.FORGOTTEN
    memories.append(forgotten)
    result, _ = retrieve(memories, "Which phone do I have?")
    assert selected_texts(result) == ["Phone is a Pixel 9."]
    inactive = [c for c in result.candidates if c.status != "active"]
    assert all(c.rank == 0 and not c.selected for c in inactive)


def test_inactive_never_compressed_or_rendered():
    from experienceos.context.compression import ExperienceCompressor

    builder = ContextBuilder(
        memory_budget=4,
        compressor=ExperienceCompressor(),
        retrieval_strategy=HybridRetrievalStrategy(
            selection_strategy=CoverageSelectionStrategy()
        ),
    )
    old = entry("fact", "Phone is a Pixel 6.")
    old.status = MemoryStatus.SUPERSEDED
    build = builder.build_context(
        "u", "s", "Which phone do I have?",
        [entry("fact", "Phone is a Pixel 9."), old],
    )
    rendered = " ".join(m["content"] for m in build.messages)
    assert "Pixel 6" not in rendered
    for summary in build.summaries:
        assert "Pixel 6" not in summary.text


def test_selection_does_not_mutate_state():
    memory = entry("fact", "Works for Globex.")
    before = json.dumps(memory.metadata, sort_keys=True, default=str)
    result, _ = retrieve([memory], "What is my employer?")
    assert memory.status == "active"
    assert json.dumps(memory.metadata, sort_keys=True, default=str) == before
    assert result.selected[0] is memory  # same object, unmodified


# --- K and budget ------------------------------------------------------------------


def test_k_never_exceeded():
    memories = [entry("fact", f"Globex fact number {i}.") for i in range(8)]
    result, _ = retrieve(memories, "Tell me about Globex.", k=3)
    assert len(result.selected) == 3
    assert result.k_compliant
    skipped = [
        c for c in result.candidates
        if c.exclusion_reason in ("not_top_k", "not_selected_by_coverage")
    ]
    assert len(skipped) == 5


def test_token_budget_enforced_deterministically():
    big = entry("fact", "Globex " + "detail " * 60 + "record.")
    small = entry("fact", "Globex badge is 42.")
    result, _ = retrieve(
        [big, small], "Tell me about Globex.", k=2, token_budget=30
    )
    assert result.budget_compliant
    assert result.context_token_estimate <= 30
    budgeted = [
        c for c in result.candidates
        if c.exclusion_reason == "token_budget"
    ]
    assert budgeted
    rerun, _ = retrieve(
        [big, small], "Tell me about Globex.", k=2, token_budget=30
    )
    assert selected_texts(rerun) == selected_texts(result)


# --- Diagnostics -------------------------------------------------------------------


def test_step_diagnostics_complete():
    memories = [
        entry("fact", "Phone is a Pixel 9.", "s1"),
        entry("fact", "Works for Globex.", "s2"),
    ]
    result, _ = retrieve(
        memories, "What phone do I use and where do I work?", k=2
    )
    steps = result.coverage["steps"]
    assert len(steps) == 2
    for step in steps:
        assert step["utility"] > 0
        assert step["retrieval_rank"] >= 1
        assert isinstance(step["new_facets"], list)
        assert "reason" in step
    assert result.coverage["strategy_version"] == "1"
    assert result.coverage["weights_version"] == "1"


def test_retrieval_component_scores_preserved():
    memories = [entry("fact", "Works for Globex.")]
    result, _ = retrieve(memories, "What is my employer?")
    candidate = next(c for c in result.candidates if c.selected)
    # Prompt 4 evidence untouched by selection.
    assert candidate.component_scores["attribute_score"] == 1.0
    assert candidate.final_score > 0


def test_skip_reasons_recorded():
    memories = [
        entry("fact", "Works for Globex."),
        entry("fact", "Globex office is in Austin."),
        entry("fact", "Globex badge is 42."),
    ]
    result, _ = retrieve(memories, "Tell me about Globex.", k=1)
    reasons = {
        c.memory.text: c.exclusion_reason
        for c in result.candidates
        if not c.selected
    }
    assert set(reasons.values()) <= {
        "not_top_k", "not_selected_by_coverage", "zero_relevance",
    }
    assert len(reasons) == 2


# --- V1/V2 isolation ---------------------------------------------------------------


def test_prompt4_default_selection_unchanged():
    strategy = HybridRetrievalStrategy()
    assert strategy.selection_strategy is None
    memories = [entry("fact", f"Globex fact number {i}.") for i in range(5)]
    result = strategy.retrieve(
        RetrievalRequest(
            query="Tell me about Globex.", memories=tuple(memories), k=3
        )
    )
    # Prompt 4 top-K: strict rank order, no coverage evidence.
    assert [c.rank for c in result.candidates if c.selected] == [1, 2, 3]
    assert result.coverage == {}


def test_coverage_adapter_registration_and_provenance():
    from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
    from benchmarks.contract import SystemId

    assert SystemId.EXPERIENCEOS_COVERAGE_V2 in ADAPTER_SYSTEM_IDS
    system = create_system(SystemId.EXPERIENCEOS_COVERAGE_V2)
    assert system.system_id == "experienceos_coverage_v2"
    assert "coverage_selection" in system.memory_policy_label


def test_coverage_adapter_uses_rules_extraction():
    from benchmarks.adapters.experienceos_coverage_v2 import (
        ExperienceOSCoverageV2Adapter,
    )
    from benchmarks.adapters.experienceos_hybrid_retrieval_v2 import (
        ExperienceOSHybridRetrievalV2Adapter,
    )
    from benchmarks.contract import case_from_dict

    case = case_from_dict(
        {
            "scenario_id": "synthetic-coverage-001",
            "schema_version": "1",
            "title": "Synthetic",
            "category": "retrieval",
            "description": "Synthetic coverage adapter test case.",
            "tags": ["domain:test"],
            "seed": 7,
            "context_budget": 4,
            "selection_k": 4,
            "turns": [],
            "current_message": "What is my employer?",
            "current_session_id": "s1",
            "expected": {"memory_actions": []},
            "evaluation_mode": "deterministic",
        }
    )
    coverage = ExperienceOSCoverageV2Adapter()
    retrieval = ExperienceOSHybridRetrievalV2Adapter()
    for system in (coverage, retrieval):
        system.initialize(case)
        system.process_turn(0, "s1", "I work for Globex now.")
    # Same K/budget; rules extraction in both (Globex is a v1 gap).
    assert coverage.config.context_budget == retrieval.config.context_budget
    assert coverage.config.selection_k == retrieval.config.selection_k
    assert coverage.final_state().entries == ()
    assert coverage.diagnostics["memory_extraction_strategy"] == (
        "v1_rules_unchanged"
    )
    assert coverage.diagnostics["selection_strategy"] == "coverage_selection"
    assert coverage.diagnostics["generalized_supersession_enabled"] is False
    assert coverage.diagnostics["zero_value_padding"] is False
    assert "coverage_v2" in coverage.diagnostics
    # Prompt 4 adapter provenance untouched.
    assert retrieval.diagnostics["selection_strategy"] == (
        "deterministic_top_k"
    )
    assert "coverage_v2" not in retrieval.diagnostics


def test_dev_composition_is_labeled_and_not_registered():
    from benchmarks.adapters.experienceos_hybrid_retrieval_v2 import (
        ExperienceOSExtractRetrievalV2Adapter,
    )
    from benchmarks.contract import KNOWN_SYSTEM_IDS

    dev = ExperienceOSExtractRetrievalV2Adapter(coverage_selection=True)
    assert dev.system_id == "dev_extract_retrieval_coverage"
    assert dev.system_id not in KNOWN_SYSTEM_IDS
    plain = ExperienceOSExtractRetrievalV2Adapter()
    assert plain.system_id == "experienceos_extract_retrieval_v2"


def test_no_coverage_metrics_for_results_without_diagnostics():
    from benchmarks.evaluators.coverage_v2 import coverage_v2_contributions

    class Result:
        diagnostics = {}

    assert coverage_v2_contributions(object(), Result()) == []


# --- Integration ----------------------------------------------------------------


def coverage_agent(**kwargs):
    return ExperienceOS(
        model=MockProvider(),
        context_builder=ContextBuilder(
            memory_budget=4,
            retrieval_strategy=HybridRetrievalStrategy(
                selection_strategy=CoverageSelectionStrategy()
            ),
        ),
        **kwargs,
    )


def selected_from_last_context(agent):
    events = [e for e in agent.events if str(e.type) == "context_built"]
    return [
        r["text"]
        for r in events[-1].payload["selection_records"]
        if r["selected"]
    ]


def test_rules_memories_selected_by_coverage():
    agent = coverage_agent()
    agent.chat(user_id="u", session_id="s1", message="My employer is Globex.")
    agent.chat(user_id="u", session_id="s2", message="My phone is a Pixel 9.")
    agent.chat(
        user_id="u", session_id="s3",
        message="What phone do I use and where do I work?",
    )
    selected = selected_from_last_context(agent)
    assert any("Globex" in t for t in selected)
    assert any("Pixel 9" in t for t in selected)


def test_sqlite_loaded_memories_identical(tmp_path):
    db = tmp_path / "memories.db"
    agent = coverage_agent(memory_store=SQLiteMemoryStore(db))
    agent.chat(user_id="u", session_id="s1", message="My employer is Globex.")
    del agent

    reopened = coverage_agent(memory_store=SQLiteMemoryStore(db))
    reopened.chat(user_id="u", session_id="s2", message="Where do I work?")
    assert "Employer is Globex." in selected_from_last_context(reopened)


def test_repeated_selection_is_deterministic():
    memories = [
        entry("fact", "Speaks Spanish.", "s1"),
        entry("fact", "Speaks French.", "s2"),
        entry("fact", "Speaks Portuguese.", "s3"),
    ]
    outputs = set()
    for _ in range(5):
        result, _ = retrieve(memories, "Which languages do I speak?", k=2)
        outputs.add(tuple(selected_texts(result)))
    assert len(outputs) == 1


# --- Fixture-driven checks ---------------------------------------------------------


def _fixture_entries(case):
    memories = []
    for item in case["memories"]:
        kind, text, session = item[0], item[1], item[2]
        identity = item[3] if len(item) > 3 else None
        memories.append(entry(kind, text, session, identity))
    return memories


@pytest.mark.parametrize(
    "klass", [k for k in FIXTURES if not k.startswith("_")]
)
def test_fixture_class(klass):
    for case in FIXTURES[klass]:
        memories = _fixture_entries(case)
        expect = case.get("expect", {})
        result, selector = retrieve(
            memories, case["query"], k=case.get("k", 4),
            token_budget=case.get("token_budget"),
        )
        texts = selected_texts(result)
        if "first_selected_contains" in expect:
            assert texts and expect["first_selected_contains"] in texts[0], (
                klass, texts,
            )
        if "selected_contains" in expect:
            assert any(expect["selected_contains"] in t for t in texts)
        if "selected_contains_all" in expect:
            for term in expect["selected_contains_all"]:
                assert any(term in t for t in texts), (klass, term, texts)
        if "selected_excludes" in expect:
            for term in expect["selected_excludes"]:
                assert not any(term in t for t in texts), (klass, term)
        if "selected_excludes_first" in expect:
            assert expect["selected_excludes_first"] not in texts[0]
        if "selected_count" in expect:
            assert len(texts) == expect["selected_count"], (klass, texts)
        if "selected_count_max" in expect:
            assert len(texts) <= expect["selected_count_max"]
        if expect.get("redundant_penalized"):
            penalized = any(
                s["redundancy_penalty"] > 0
                for s in result.coverage["steps"]
            ) or any(
                c.exclusion_reason
                in ("not_selected_by_coverage", "not_top_k")
                for c in result.candidates
                if not c.selected and c.status == "active"
            )
            assert penalized, klass
        if expect.get("conflict_warning"):
            assert result.coverage["conflict_warnings"] >= 1, klass
        if expect.get("budget_compliant"):
            assert result.budget_compliant
        if expect.get("deterministic"):
            rerun, _ = retrieve(
                memories, case["query"], k=case.get("k", 4),
                token_budget=case.get("token_budget"),
            )
            assert selected_texts(rerun) == texts, klass
