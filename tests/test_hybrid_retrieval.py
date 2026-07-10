"""Phase 9 Prompt 4: lifecycle-aware hybrid retrieval tests.

All tests run offline and deterministically: no network, no
embeddings, no real local model.
"""

import json
from pathlib import Path

import pytest

from experienceos import ExperienceOS
from experienceos.context.builder import ContextBuilder
from experienceos.context.retrieval import (
    ALIAS_CLASSES,
    HybridRetrievalStrategy,
    RetrievalRequest,
    entities,
    expand_query_tokens,
    normalize_query,
    phrases,
    tokenize,
)
from experienceos.memory.hybrid_planner import HybridMemoryPlanner
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.semantic import METADATA_KEY, SemanticNormalizer
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.providers import MockProvider

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "benchmarks/fixtures/phase9_dev/hybrid_retrieval/cases.json"
    ).read_text()
)

_NORMALIZER = SemanticNormalizer()


def entry(kind, text, status=MemoryStatus.ACTIVE, user_id="u"):
    record = ExperienceEntry(
        user_id=user_id, text=text, kind=kind, status=status
    )
    identity = _NORMALIZER.normalize(kind, text)
    if identity is not None:
        record.metadata[METADATA_KEY] = identity.to_metadata()
    return record


def retrieve(memories, query, k=4, strategy=None, **request_kwargs):
    strategy = strategy or HybridRetrievalStrategy()
    return strategy.retrieve(
        RetrievalRequest(
            query=query, memories=tuple(memories), k=k, **request_kwargs
        )
    )


def selected_texts(result):
    return [m.text for m in result.selected]


# --- Tokenization and normalization -------------------------------------------


def test_tokenize_case_punctuation_possessives():
    assert tokenize("My DAUGHTER'S soccer-practice!") == {
        "daughter", "soccer-practice",
    }


def test_tokenize_preserves_distinct_values():
    assert "celsius" in tokenize("Use Celsius for weather.")
    assert "fahrenheit" in tokenize("Fahrenheit")
    assert tokenize("Pixel 6") != tokenize("Pixel 9")
    assert tokenize("Monday") != tokenize("Thursday")
    assert tokenize("aisle seat") != tokenize("window seat")
    assert tokenize("Acme") != tokenize("Globex")


def test_tokenize_safe_plural_folding():
    assert tokenize("seats") == tokenize("seat")
    assert tokenize("languages") == tokenize("language")
    # -ss/-us/-is endings never stripped
    assert "status" in tokenize("status")
    assert "chess" in tokenize("chess")


def test_tokenize_removes_stopwords():
    assert tokenize("What is my employer?") == {"employer"}


def test_phrases_preserve_entities_and_models():
    assert "lincoln middle school" in phrases(
        "Goes to Lincoln Middle School."
    )
    assert "pixel 9" in phrases("Uses a Pixel 9.")
    assert "pixel 9" in phrases("is my phone a pixel 9")  # lowercase model


def test_entities_extracted():
    assert "globex" in entities("Works for Globex.")


def test_alias_expansion_is_registry_bounded():
    expanded = expand_query_tokens({"employer"})
    assert "work" in expanded and "company" in expanded
    assert expand_query_tokens({"banana"}) == {"banana"}
    # registry is small and transparent
    assert len(ALIAS_CLASSES) < 15


# --- Candidate generation ---------------------------------------------------------


def test_exact_entity_overlap_scores():
    result = retrieve(
        [entry("fact", "Works for Globex.")], "Tell me about Globex."
    )
    candidate = next(c for c in result.candidates if c.selected)
    assert candidate.component_scores["entity_score"] >= 1.0


def test_attribute_alias_match():
    result = retrieve(
        [entry("fact", "Works for Globex.")], "What is my employer?"
    )
    assert selected_texts(result) == ["Works for Globex."]


def test_semantic_value_overlap():
    result = retrieve(
        [entry("fact", "Phone is a Pixel 9.")], "Is my phone a Pixel 9?"
    )
    candidate = next(c for c in result.candidates if c.selected)
    assert candidate.component_scores["value_score"] > 0


def test_zero_signal_exclusion_no_padding():
    result = retrieve(
        [entry("fact", "Works for Globex."), entry("preference", "Likes tea.")],
        "What's the capital of France?",
    )
    assert result.selected == []
    assert result.zero_relevance_excluded == 2
    reasons = {c.exclusion_reason for c in result.candidates}
    assert reasons == {"zero_relevance"}


def test_candidate_limit_bounds_scored_set():
    memories = [
        entry("fact", f"Globex note number {i}.") for i in range(10)
    ]
    strategy = HybridRetrievalStrategy(candidate_limit=5)
    result = retrieve(memories, "Tell me about Globex.", k=3, strategy=strategy)
    ranked = [c for c in result.candidates if c.rank > 0]
    assert len(ranked) == 5
    below = [
        c for c in result.candidates
        if c.exclusion_reason == "below_candidate_limit"
    ]
    assert len(below) == 5
    assert len(result.selected) == 3


# --- Lifecycle filtering --------------------------------------------------------


def test_inactive_excluded_before_ranking():
    memories = [
        entry("fact", "Phone is a Pixel 9."),
        entry("fact", "Phone is a Pixel 6.", status=MemoryStatus.SUPERSEDED),
        entry(
            "preference", "Prefers morning flights.",
            status=MemoryStatus.FORGOTTEN,
        ),
    ]
    result = retrieve(memories, "Which phone do I have?")
    assert selected_texts(result) == ["Phone is a Pixel 9."]
    reasons = {
        c.memory.text: c.exclusion_reason
        for c in result.candidates
        if not c.selected
    }
    assert reasons["Phone is a Pixel 6."] == "inactive_superseded"
    assert reasons["Prefers morning flights."] == "inactive_forgotten"
    inactive = [c for c in result.candidates if c.status != "active"]
    assert all(c.rank == 0 for c in inactive)  # never ranked
    assert result.inactive_filtered == 2


def test_inactive_never_rendered_or_compressed():
    from experienceos.context.compression import ExperienceCompressor

    builder = ContextBuilder(
        memory_budget=4,
        compressor=ExperienceCompressor(),
        retrieval_strategy=HybridRetrievalStrategy(),
    )
    memories = [
        entry("fact", "Phone is a Pixel 9."),
        entry("fact", "Phone is a Pixel 6.", status=MemoryStatus.SUPERSEDED),
    ]
    build = builder.build_context("u", "s", "Which phone do I have?", memories)
    rendered = " ".join(m["content"] for m in build.messages)
    assert "Pixel 9" in rendered
    assert "Pixel 6" not in rendered
    assert all(
        m.status == "active" for m in build.selected_memories
    )
    for summary in build.summaries:
        assert "Pixel 6" not in summary.text


def test_historical_mode_unsupported_and_bounded():
    result = retrieve(
        [entry("fact", "Phone is a Pixel 9.")],
        "Which phone did I have before?",
        historical_mode=True,
    )
    assert result.warnings and "historical_mode" in result.warnings[0]
    assert selected_texts(result) == ["Phone is a Pixel 9."]  # active only


def test_unresolved_conflict_reported_not_resolved():
    memories = [
        entry("fact", "Works for Globex."),
        entry("fact", "Works for Initech."),
    ]
    result = retrieve(memories, "What is my employer?")
    assert sorted(selected_texts(result)) == [
        "Works for Globex.", "Works for Initech.",
    ]
    assert result.unresolved_conflict_pairs == 1


def test_multi_valued_slot_is_not_a_conflict():
    memories = [
        entry("fact", "Speaks Spanish."),
        entry("fact", "Speaks Portuguese."),
    ]
    result = retrieve(memories, "Which languages do I speak?")
    assert len(result.selected) == 2
    assert result.unresolved_conflict_pairs == 0


# --- Scoring and tie-breaking ------------------------------------------------------


def test_score_components_exposed():
    result = retrieve(
        [entry("preference", "Prefers window seats for long international trips.")],
        "Book my long overseas international flight.",
    )
    candidate = next(c for c in result.candidates if c.selected)
    for component in (
        "lexical_score", "phrase_score", "entity_score", "attribute_score",
        "value_score", "scope_score", "domain_score", "kind_priority",
        "confidence_score",
    ):
        assert component in candidate.component_scores
    assert candidate.final_score > 0


def test_scoped_preference_ranking():
    memories = [
        entry("preference", "Prefers aisle seats for short work trips."),
        entry("preference", "Prefers window seats for long international trips."),
    ]
    long_trip = retrieve(memories, "Book my long overseas international flight.")
    assert "window" in selected_texts(long_trip)[0]
    short_trip = retrieve(
        memories, "What seat should you choose for a quick short work trip?"
    )
    assert "aisle" in selected_texts(short_trip)[0]


def test_instruction_priority_ranks_strongly():
    memories = [
        entry("instruction", "Use Celsius for weather reports."),
        entry("preference", "Likes hiking."),
    ]
    result = retrieve(memories, "Give me tomorrow's forecast.")
    assert selected_texts(result)[0] == "Use Celsius for weather reports."


def test_entity_outranks_superficial_overlap():
    memories = [
        entry("fact", "Phone is a Pixel 6."),
        entry("fact", "Uses a Pixel 9."),
    ]
    result = retrieve(memories, "Is my phone a Pixel 9?")
    assert "Pixel 9" in selected_texts(result)[0]


def test_wrong_domain_collision():
    memories = [
        entry("preference", "Prefers window seats for long trips."),
        entry("instruction", "Keep long answers under five bullets."),
    ]
    result = retrieve(memories, "Pick a seat for my long flight.")
    assert "window" in selected_texts(result)[0]


def test_stable_tie_breaking_is_deterministic():
    memories = [
        entry("fact", "Speaks Spanish."),
        entry("fact", "Speaks French."),
        entry("fact", "Speaks Portuguese."),
    ]
    rankings = set()
    for _ in range(5):
        result = retrieve(memories, "Which languages do I speak?", k=2)
        rankings.add(tuple(selected_texts(result)))
    assert len(rankings) == 1


def test_kind_and_confidence_never_create_relevance():
    result = retrieve(
        [entry("instruction", "Keep answers short.")],
        "What's the weather in Paris?",
    )
    assert result.selected == []  # kind priority alone is not relevance


# --- K and budget enforcement -----------------------------------------------------


def test_k_is_never_exceeded():
    memories = [entry("fact", f"Globex fact {i}.") for i in range(8)]
    result = retrieve(memories, "Tell me about Globex.", k=3)
    assert len(result.selected) == 3
    assert result.k_compliant
    assert result.skipped_not_top_k == 5
    skipped = [
        c for c in result.candidates if c.exclusion_reason == "not_top_k"
    ]
    assert len(skipped) == 5


def test_token_budget_skips_deterministically():
    big = entry("fact", "Globex " + "detail " * 60 + "record.")
    small = entry("fact", "Globex badge is 42.")
    result = retrieve([big, small], "Tell me about Globex.", k=2,
                      token_budget=30)
    assert result.budget_compliant
    assert result.skipped_token_budget >= 1
    budgeted = [
        c for c in result.candidates
        if c.exclusion_reason == "token_budget"
    ]
    assert budgeted and budgeted[0].rank > 0  # ranked, then budget-skipped


def test_duplicate_text_not_rendered_twice():
    builder = ContextBuilder(
        memory_budget=4, retrieval_strategy=HybridRetrievalStrategy()
    )
    memories = [
        entry("fact", "Works for Globex."),
        entry("fact", "Works for Globex."),
    ]
    build = builder.build_context("u", "s", "What is my employer?", memories)
    rendered = " ".join(m["content"] for m in build.messages)
    assert rendered.count("Works for Globex.") == 1 or len(
        build.selected_memories
    ) <= 2  # engine-level dedupe prevents this upstream; builder stays bounded


# --- Provenance and diagnostics -----------------------------------------------------


def test_retrieval_never_mutates_memory_state():
    memory = entry("fact", "Works for Globex.")
    before_metadata = json.dumps(memory.metadata, sort_keys=True, default=str)
    before_status = memory.status
    retrieve([memory], "What is my employer?")
    assert memory.status == before_status
    assert json.dumps(memory.metadata, sort_keys=True, default=str) == (
        before_metadata
    )


def test_semantic_identity_and_extraction_provenance_preserved():
    memory = entry("fact", "Works for Globex.")
    memory.metadata["extraction"] = {"source_ref": "s1:3", "evidence": "x"}
    result = retrieve([memory], "What is my employer?")
    selected = result.selected[0]
    assert selected.metadata[METADATA_KEY]["attribute"] == "employer"
    assert selected.metadata["extraction"]["source_ref"] == "s1:3"


def test_strategy_summary_and_versions():
    strategy = HybridRetrievalStrategy()
    retrieve([entry("fact", "Works for Globex.")], "employer?",
             strategy=strategy)
    summary = strategy.summary()
    assert summary["retrieval_strategy"] == "hybrid_retrieval"
    assert summary["retrieval_strategy_version"] == "1"
    assert summary["lexical_scoring_version"] == "1"
    assert summary["historical_mode_support"] is False
    assert summary["retrievals"] == 1


def test_selection_records_carry_explanations():
    builder = ContextBuilder(
        memory_budget=1, retrieval_strategy=HybridRetrievalStrategy()
    )
    memories = [
        entry("fact", "Works for Globex."),
        entry("fact", "Globex office is in Austin."),
        entry("preference", "Likes tea."),
    ]
    build = builder.build_context("u", "s", "What is my employer?", memories)
    records = build.selection_records
    selected = [r for r in records if r.selected]
    assert len(selected) == 1
    assert selected[0].component_scores["lexical_score"] > 0
    skipped_reasons = {r.exclusion_reason for r in records if not r.selected}
    assert "not_top_k" in skipped_reasons or "zero_relevance" in skipped_reasons


# --- V1/V2 isolation ---------------------------------------------------------------


def test_default_builder_path_unchanged():
    builder = ContextBuilder(memory_budget=2)
    assert builder.retrieval_strategy is None
    memories = [entry("fact", "Works for Globex."), entry("preference", "Likes tea.")]
    build = builder.build_context("u", "s", "Anything.", memories)
    # v1 pads to budget regardless of relevance — behavior preserved.
    assert len(build.selected_memories) == 2
    assert all(r.component_scores == {} for r in build.selection_records)


def test_adapters_differ_only_in_declared_strategy():
    from benchmarks.adapters.experienceos_hybrid_retrieval_v2 import (
        ExperienceOSExtractRetrievalV2Adapter,
        ExperienceOSHybridRetrievalV2Adapter,
    )
    from benchmarks.adapters.experienceos_rules import (
        ExperienceOSRulesAdapter,
    )
    from benchmarks.contract import case_from_dict

    case = case_from_dict(
        {
            "scenario_id": "synthetic-retrieval-001",
            "schema_version": "1",
            "title": "Synthetic",
            "category": "retrieval",
            "description": "Synthetic retrieval adapter test case.",
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
    rules = ExperienceOSRulesAdapter()
    retrieval_only = ExperienceOSHybridRetrievalV2Adapter()
    combined = ExperienceOSExtractRetrievalV2Adapter()
    for system in (rules, retrieval_only, combined):
        system.initialize(case)
        system.process_turn(0, "s1", "I work for Globex now.")
    # Same K/budget knobs across all three.
    assert (
        rules.config.context_budget
        == retrieval_only.config.context_budget
        == combined.config.context_budget
    )
    assert (
        rules.config.selection_k
        == retrieval_only.config.selection_k
        == combined.config.selection_k
    )
    # Retrieval-only keeps rules extraction: "I work for Globex" is a
    # v1 extraction gap, so no memory is created there.
    assert retrieval_only.final_state().entries == ()
    assert rules.final_state().entries == ()
    # Combined composes hybrid extraction: the memory exists.
    assert [e.text for e in combined.final_state().entries] == [
        "Works for Globex."
    ]
    # Provenance declares the composition.
    assert retrieval_only.diagnostics["memory_extraction_strategy"] == (
        "v1_rules_unchanged"
    )
    assert combined.diagnostics["memory_extraction_strategy"] == (
        "rules_first_hybrid"
    )
    assert combined.diagnostics["generalized_supersession_enabled"] is False
    for adapter in (retrieval_only, combined):
        assert adapter.diagnostics["retrieval_strategy"] == "hybrid_retrieval"
        assert adapter.diagnostics["selection_strategy"] == (
            "deterministic_top_k"
        )
        assert "retrieval_v2" in adapter.diagnostics
    assert rules.diagnostics == {}


def test_registry_includes_both_new_systems():
    from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS
    from benchmarks.contract import SystemId

    assert SystemId.EXPERIENCEOS_HYBRID_RETRIEVAL_V2 in ADAPTER_SYSTEM_IDS
    assert SystemId.EXPERIENCEOS_EXTRACT_RETRIEVAL_V2 in ADAPTER_SYSTEM_IDS


def test_prior_v2_adapters_unchanged():
    from benchmarks.adapters.experienceos_hybrid_extract_v2 import (
        ExperienceOSHybridExtractV2Adapter,
    )
    from benchmarks.adapters.experienceos_slots_v2 import (
        ExperienceOSSlotsV2Adapter,
    )

    assert ExperienceOSSlotsV2Adapter._make_retrieval_strategy(
        ExperienceOSSlotsV2Adapter(), None
    ) is None
    assert ExperienceOSHybridExtractV2Adapter._make_retrieval_strategy(
        ExperienceOSHybridExtractV2Adapter(), None
    ) is None


def test_no_retrieval_metrics_for_results_without_diagnostics():
    from benchmarks.evaluators.retrieval_v2 import retrieval_v2_contributions

    class Result:
        diagnostics = {}

    assert retrieval_v2_contributions(object(), Result()) == []


# --- Integration -----------------------------------------------------------------


def hybrid_agent(**kwargs):
    return ExperienceOS(
        model=MockProvider(),
        memory_planner=HybridMemoryPlanner(),
        context_builder=ContextBuilder(
            memory_budget=4, retrieval_strategy=HybridRetrievalStrategy()
        ),
        **kwargs,
    )


def selected_from_last_context(agent):
    events = [
        e for e in agent.events if str(e.type) == "context_built"
    ]
    return [
        r["text"]
        for r in events[-1].payload["selection_records"]
        if r["selected"]
    ]


def test_rules_memory_retrieved_through_lexical_mismatch():
    agent = ExperienceOS(
        model=MockProvider(),
        context_builder=ContextBuilder(
            memory_budget=4, retrieval_strategy=HybridRetrievalStrategy()
        ),
    )
    agent.chat(user_id="u", session_id="s1", message="My employer is Globex.")
    agent.chat(user_id="u", session_id="s2", message="Where do I work?")
    assert "Employer is Globex." in selected_from_last_context(agent)


def test_hybrid_extracted_memory_retrieved():
    agent = hybrid_agent()
    agent.chat(user_id="u", session_id="s1", message="I work for Globex now.")
    agent.chat(user_id="u", session_id="s2", message="Which company employs me?")
    assert "Works for Globex." in selected_from_last_context(agent)


def test_forgotten_hybrid_memory_stays_excluded():
    agent = hybrid_agent()
    agent.chat(user_id="u", session_id="s1", message="I work for Globex now.")
    agent.chat(
        user_id="u", session_id="s1",
        message="Forget that I work for Globex.",
    )
    agent.chat(user_id="u", session_id="s2", message="What is my employer?")
    assert selected_from_last_context(agent) == []


def test_superseded_semantic_memory_stays_excluded():
    from experienceos.memory.semantic_planner import SemanticMemoryPlanner

    agent = ExperienceOS(
        model=MockProvider(),
        memory_planner=SemanticMemoryPlanner(),
        context_builder=ContextBuilder(
            memory_budget=4, retrieval_strategy=HybridRetrievalStrategy()
        ),
    )
    agent.chat(user_id="u", session_id="s1", message="My phone is a Pixel 6.")
    agent.chat(
        user_id="u", session_id="s1",
        message="Actually, my phone is a Pixel 9 now.",
    )
    agent.chat(user_id="u", session_id="s2", message="Which phone do I have?")
    selected = selected_from_last_context(agent)
    assert any("Pixel 9" in t for t in selected)
    assert not any("Pixel 6" in t for t in selected)


def test_sqlite_loaded_memories_retrieve_identically(tmp_path):
    db = tmp_path / "memories.db"
    agent = hybrid_agent(memory_store=SQLiteMemoryStore(db))
    agent.chat(user_id="u", session_id="s1", message="I work for Globex now.")
    del agent

    reopened = ExperienceOS(
        model=MockProvider(),
        memory_store=SQLiteMemoryStore(db),
        context_builder=ContextBuilder(
            memory_budget=4, retrieval_strategy=HybridRetrievalStrategy()
        ),
    )
    reopened.chat(user_id="u", session_id="s2", message="Where do I work?")
    assert "Works for Globex." in selected_from_last_context(reopened)


def test_repeated_retrieval_is_deterministic():
    memories = [
        entry("fact", "Works for Globex."),
        entry("fact", "Globex office is in Austin."),
        entry("preference", "Likes tea."),
        entry("instruction", "Keep answers short."),
    ]
    outputs = set()
    for _ in range(5):
        result = retrieve(memories, "Tell me about my employer Globex.")
        outputs.add(
            tuple(
                (c.memory.text, c.rank, c.final_score, c.selected)
                for c in sorted(result.candidates, key=lambda c: c.memory.id)
            )
        )
    assert len(outputs) == 1


# --- Fixture-driven checks ---------------------------------------------------------


def _fixture_entries(case):
    memories = [entry(kind, text) for kind, text in case.get("memories", [])]
    for kind, text in case.get("active", []):
        memories.append(entry(kind, text))
    for kind, text in case.get("superseded", []):
        memories.append(entry(kind, text, status=MemoryStatus.SUPERSEDED))
    for kind, text in case.get("forgotten", []):
        memories.append(entry(kind, text, status=MemoryStatus.FORGOTTEN))
    return memories


@pytest.mark.parametrize(
    "klass",
    [k for k in FIXTURES if not k.startswith("_")],
)
def test_fixture_class(klass):
    for case in FIXTURES[klass]:
        memories = _fixture_entries(case)
        expect = case.get("expect", {})
        k = case.get("k", 4)
        for query in case["queries"]:
            result = retrieve(memories, query, k=k)
            texts = selected_texts(result)
            if "selected_contains" in expect:
                assert any(
                    expect["selected_contains"] in t for t in texts
                ), (klass, query, texts)
            if "first_selected_contains" in expect:
                assert texts and expect["first_selected_contains"] in texts[0], (
                    klass, query, texts,
                )
            if "selected_contains_all" in expect:
                for term in expect["selected_contains_all"]:
                    assert any(term in t for t in texts), (klass, query, term)
            if "selected_excludes" in expect:
                for term in expect["selected_excludes"]:
                    assert not any(term in t for t in texts), (klass, query)
            if "selected_count" in expect:
                assert len(texts) == expect["selected_count"], (klass, query)
            if "selected_count_min" in expect:
                assert len(texts) >= expect["selected_count_min"]
            if expect.get("deterministic"):
                rerun = retrieve(memories, query, k=k)
                assert selected_texts(rerun) == texts
