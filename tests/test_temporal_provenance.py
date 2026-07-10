"""Phase 9 Prompt 6: temporal and provenance-aware experience tests.

All tests run offline and deterministically: reference dates are
explicit ISO strings, never wall clocks.
"""

import json

import pytest

from experienceos import ExperienceOS
from experienceos.context.builder import ContextBuilder
from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.context.selection import CoverageSelectionStrategy
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.memory.temporal import (
    PROVENANCE_KEY,
    TEMPORAL_KEY,
    ProvenanceMetadata,
    QueryMode,
    SourceType,
    TemporalMetadata,
    TemporalNormalizer,
    TemporalRetrievalPolicy,
    TemporalScope,
    TimePrecision,
    TRUST_ORDER,
    interpret_query_mode,
    not_yet_valid,
    resolve_validity,
)
from experienceos.memory.temporal_planner import TemporalMemoryPlanner
from experienceos.providers import MockProvider

NORMALIZER = TemporalNormalizer()
REF = "2026-07-10"


def temporal_agent(assistant_ingestion=True, planner=None, **kwargs):
    planner = planner or TemporalMemoryPlanner(
        assistant_ingestion=assistant_ingestion
    )
    policy = TemporalRetrievalPolicy(reference_time=REF)
    agent = ExperienceOS(
        model=MockProvider(),
        memory_planner=planner,
        context_builder=ContextBuilder(
            memory_budget=4,
            retrieval_strategy=HybridRetrievalStrategy(
                selection_strategy=CoverageSelectionStrategy(),
                temporal_policy=policy,
            ),
        ),
        **kwargs,
    )
    return agent, planner, policy


def selected_texts(agent):
    events = [e for e in agent.events if str(e.type) == "context_built"]
    return [
        r["text"]
        for r in events[-1].payload["selection_records"]
        if r["selected"]
    ]


def rendered_context(agent):
    events = [e for e in agent.events if str(e.type) == "context_built"]
    return " ".join(
        m["content"] for m in events[-1].payload["context_messages"]
    )


# --- Temporal parsing --------------------------------------------------------------


def test_explicit_iso_date():
    meta = NORMALIZER.normalize("My start date is 2025-06-03.", REF)
    assert meta.event_time == "2025-06-03"
    assert meta.time_precision == TimePrecision.DAY


def test_explicit_month_day_year():
    meta = NORMALIZER.normalize("I moved to Seattle on June 3, 2025.", REF)
    assert meta.event_time == "2025-06-03"
    assert meta.time_precision == TimePrecision.DAY


def test_month_year_gets_month_precision():
    meta = NORMALIZER.normalize("It happened in March 2024.", REF)
    assert meta.event_time == "2024-03"
    assert meta.time_precision == TimePrecision.MONTH


def test_relative_date_with_reference():
    meta = NORMALIZER.normalize("I moved here last month.", REF)
    assert meta.event_time == "2026-06"
    assert meta.time_precision == TimePrecision.MONTH  # no invented day


def test_relative_days_ago():
    meta = NORMALIZER.normalize("I arrived two days ago.", REF)
    assert meta.event_time == "2026-07-08"
    assert meta.time_precision == TimePrecision.DAY


def test_relative_date_without_reference_stays_unresolved():
    meta = NORMALIZER.normalize("I moved here last month.", None)
    assert meta.event_time is None
    assert meta.time_precision == TimePrecision.RELATIVE
    assert meta.uncertainty_reason


def test_no_year_no_invention():
    # "July 2" without a year and without safe resolution: nothing.
    meta = NORMALIZER.normalize("See you on July 2.", None)
    assert meta is None or meta.event_time is None


def test_approximate_historical_phrase():
    meta = NORMALIZER.normalize("A few years ago I worked at Acme.", REF)
    assert meta.temporal_scope == TemporalScope.HISTORICAL
    assert meta.time_precision == TimePrecision.APPROXIMATE
    assert meta.time_confidence < 1.0
    assert meta.event_time is None  # never fabricated


def test_future_expression():
    meta = NORMALIZER.normalize(
        "Starting next month, send reports there.", REF
    )
    assert meta.temporal_scope == TemporalScope.FUTURE


def test_recurring_expression():
    meta = NORMALIZER.normalize("Every Monday at 10 we have a review.", REF)
    assert meta.temporal_scope == TemporalScope.RECURRING


def test_year_range():
    meta = NORMALIZER.normalize("I lived there between 2024 and 2025.", REF)
    assert meta.valid_from == "2024"
    assert meta.valid_until == "2025"
    assert meta.time_precision == TimePrecision.RANGE


def test_deterministic_parsing():
    outputs = {
        json.dumps(
            NORMALIZER.normalize("I moved on June 3, 2025.", REF).to_metadata(),
            sort_keys=True,
        )
        for _ in range(5)
    }
    assert len(outputs) == 1


# --- Temporal and provenance models ---------------------------------------------------


def test_temporal_round_trip():
    meta = TemporalMetadata(
        event_time="2025-06-03", valid_from="2025-06-03",
        temporal_scope=TemporalScope.CURRENT,
        time_precision=TimePrecision.DAY, time_expression="June 3, 2025",
        source_session_date=REF, reference_time=REF,
    )
    assert TemporalMetadata.from_metadata(meta.to_metadata()) == meta


def test_provenance_round_trip_and_trust():
    prov = ProvenanceMetadata(
        source_type=SourceType.TOOL_VERIFIED, source_role="tool",
        source_tool="reservations", confirmed_by="tool",
        derivation_refs=("s1:1",),
    )
    restored = ProvenanceMetadata.from_metadata(prov.to_metadata())
    assert restored.source_type == SourceType.TOOL_VERIFIED
    assert restored.trust_level() == 5
    assert TRUST_ORDER[SourceType.TOOL_VERIFIED] > TRUST_ORDER[
        SourceType.USER_ASSERTED
    ] > TRUST_ORDER[SourceType.JOINTLY_CONFIRMED] > TRUST_ORDER[
        SourceType.SYSTEM_OBSERVED
    ] > TRUST_ORDER[SourceType.ASSISTANT_DERIVED]


def test_legacy_entry_without_temporal_metadata():
    entry = ExperienceEntry(user_id="u", text="Likes tea.", kind="preference")
    validity = resolve_validity(entry, {})
    assert validity.valid_from is None
    assert validity.valid_until is None
    assert validity.scope == TemporalScope.UNKNOWN  # no fabricated dates


# --- Validity transitions --------------------------------------------------------------


def correction_agent():
    agent, planner, policy = temporal_agent()
    planner.set_reference_time("2025-01-05")
    agent.chat(user_id="u", session_id="s1", message="My phone is a Pixel 6.")
    planner.set_reference_time(REF)
    agent.chat(
        user_id="u", session_id="s2",
        message="Actually, my phone is a Pixel 9 now.",
    )
    return agent, planner, policy


def test_supersession_derives_valid_until():
    agent, _, _ = correction_agent()
    superseded = agent.memories_for_user("u", status="superseded")
    assert [m.text for m in superseded] == ["Phone is a Pixel 6."]
    active = agent.memories_for_user("u")
    by_id = {m.id: m for m in [*superseded, *active]}
    validity = resolve_validity(superseded[0], by_id)
    # Derived from the superseder's session date — never invented
    # earlier than the evidence supports.
    assert validity.valid_until == REF
    assert validity.supersession_time is not None
    # Original observation preserved.
    temporal = superseded[0].metadata.get(TEMPORAL_KEY) or {}
    assert temporal.get("source_session_date") == "2025-01-05"


def test_historical_statement_does_not_replace_current():
    agent, planner, _ = temporal_agent()
    planner.set_reference_time(REF)
    agent.chat(user_id="u", session_id="s1",
               message="My home city is Seattle.")
    agent.chat(
        user_id="u", session_id="s1",
        message="My home city was Boston back in 2019.",
    )
    texts = sorted(m.text for m in agent.memories_for_user("u"))
    assert texts == ["Home city is Seattle.", "Home city was Boston."]
    assert agent.memories_for_user("u", status="superseded") == []
    boston = next(
        m for m in agent.memories_for_user("u") if "Boston" in m.text
    )
    assert boston.metadata[TEMPORAL_KEY]["temporal_scope"] == "historical"


def test_historical_supersede_veto_safety_net():
    """If a historical-scoped source message ever produces a paired
    supersede (semantic layer edge), the pairing is vetoed so both
    records coexist."""
    from experienceos.memory.planner import CREATE, SUPERSEDE, MemoryAction

    planner = TemporalMemoryPlanner()
    planner.set_reference_time(REF)
    actions = [
        MemoryAction(action=SUPERSEDE, kind="fact", memory_id="old-1",
                     text="Phone is a Pixel 9.", reason="conflict"),
        MemoryAction(action=CREATE, kind="fact",
                     text="Phone is a Pixel 6.", replaces="old-1"),
    ]
    result = planner._apply_temporal(
        actions, "Back in 2019 I used a Pixel 6.", "s1:1"
    )
    assert all(a.action == CREATE for a in result)
    create = result[0]
    assert create.replaces is None
    assert planner.counters["historical_supersede_vetoes"] == 1


def test_future_memory_not_current_before_activation():
    entry = ExperienceEntry(user_id="u", text="Report channel is #finance.",
                            kind="fact")
    entry.metadata[TEMPORAL_KEY] = TemporalMetadata(
        temporal_scope=TemporalScope.FUTURE, valid_from="2026-08",
    ).to_metadata()
    assert not_yet_valid(entry, "2026-07-15")
    assert not not_yet_valid(entry, "2026-08-05")
    # Unresolved future or missing runtime reference: held.
    entry.metadata[TEMPORAL_KEY] = TemporalMetadata(
        temporal_scope=TemporalScope.FUTURE,
    ).to_metadata()
    assert not_yet_valid(entry, "2026-08-05")


def test_old_age_alone_never_expires():
    entry = ExperienceEntry(user_id="u", text="Likes tea.", kind="preference")
    entry.metadata[TEMPORAL_KEY] = TemporalMetadata(
        source_session_date="2019-01-01",
        temporal_scope=TemporalScope.CURRENT,
    ).to_metadata()
    validity = resolve_validity(entry, {})
    assert validity.valid_until is None  # old does not mean obsolete


# --- Assistant, tool, and confirmation eligibility --------------------------------------


def test_jointly_confirmed_decision():
    agent, planner, _ = temporal_agent()
    planner.set_reference_time(REF)
    planner.note_assistant_message(
        "u", "s1", "We'll use the 9:00 AM flight to Denver."
    )
    agent.chat(user_id="u", session_id="s1", message="Yes, book that.")
    memories = agent.memories_for_user("u")
    assert len(memories) == 1
    assert "9:00 AM flight" in memories[0].text
    prov = memories[0].metadata[PROVENANCE_KEY]
    assert prov["source_type"] == SourceType.JOINTLY_CONFIRMED
    assert prov["confirmed_by"] == "user"
    assert len(prov["derivation_refs"]) == 2


def test_unconfirmed_assistant_suggestion_rejected():
    agent, planner, _ = temporal_agent()
    planner.note_assistant_message(
        "u", "s1", "You probably prefer window seats."
    )
    agent.chat(user_id="u", session_id="s1", message="Interesting.")
    assert agent.memories_for_user("u") == []


def test_ambiguous_confirmation_rejected():
    agent, planner, _ = temporal_agent()
    planner.note_assistant_message(
        "u", "s1",
        "We'll go with either the 9:00 AM flight or the noon option.",
    )
    agent.chat(user_id="u", session_id="s1", message="That works.")
    assert agent.memories_for_user("u") == []
    assert planner.counters["assistant_candidates_rejected"] == 1


def test_tool_verified_fact_accepted():
    agent, planner, _ = temporal_agent()
    planner.set_reference_time(REF)
    planner.queue_tool_result(
        "reservations",
        {"fact": "Reservation confirmed for 2026-07-18.",
         "confirmation": "reservation confirmed for 2026-07-18",
         "result_ref": "resv-42"},
    )
    agent.chat(user_id="u", session_id="s1", message="Anything else?")
    memories = agent.memories_for_user("u")
    assert [m.text for m in memories] == [
        "Reservation confirmed for 2026-07-18."
    ]
    prov = memories[0].metadata[PROVENANCE_KEY]
    assert prov["source_type"] == SourceType.TOOL_VERIFIED
    assert prov["source_tool"] == "reservations"
    assert prov["source_tool_result_ref"] == "resv-42"
    assert prov["trust_level"] == 5


def test_ungrounded_tool_fact_rejected():
    agent, planner, _ = temporal_agent()
    planner.queue_tool_result(
        "reservations",
        {"fact": "User loves skydiving adventures.", "status": "ok"},
    )
    agent.chat(user_id="u", session_id="s1", message="Anything else?")
    assert agent.memories_for_user("u") == []
    assert planner.counters["assistant_candidates_rejected"] == 1


def test_deterministic_derivation():
    agent, planner, _ = temporal_agent()
    planner.set_reference_time("2026-07-01")
    agent.chat(
        user_id="u", session_id="s1",
        message="My trip begins on July 10, 2026 and lasts five days.",
    )
    memories = agent.memories_for_user("u")
    derived = next(m for m in memories if "ends" in m.text)
    assert derived.text == "Trip ends on 2026-07-15."
    prov = derived.metadata[PROVENANCE_KEY]
    assert prov["source_type"] == SourceType.SYSTEM_OBSERVED
    assert prov["confirmation_status"] == "derived"
    assert prov["derivation_refs"]  # not mislabeled as user asserted


def test_assistant_path_disabled_by_default_flag():
    agent, planner, _ = temporal_agent(assistant_ingestion=False)
    planner.note_assistant_message(
        "u", "s1", "We'll use the 9:00 AM flight."
    )
    agent.chat(user_id="u", session_id="s1", message="Yes, book that.")
    assert agent.memories_for_user("u") == []
    planner.queue_tool_result("t", {"fact": "Confirmed for 2026-07-18."})
    agent.chat(user_id="u", session_id="s1", message="Ok.")
    assert agent.memories_for_user("u") == []


def test_assistant_hook_absent_in_prior_planners():
    from experienceos.memory.hybrid_planner import HybridMemoryPlanner
    from experienceos.memory.planner import MemoryPlanner
    from experienceos.memory.semantic_planner import SemanticMemoryPlanner

    for planner in (MemoryPlanner(), SemanticMemoryPlanner(),
                    HybridMemoryPlanner()):
        assert not hasattr(planner, "note_assistant_message")


# --- Query modes --------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,mode",
    [
        ("Which phone do I have?", QueryMode.CURRENT),
        ("What was my old phone?", QueryMode.HISTORICAL),
        ("What did I use before?", QueryMode.HISTORICAL),
        ("What phone did I use in 2025?", QueryMode.AS_OF),
        ("As of March 2024, where did I work?", QueryMode.AS_OF),
        ("How has my phone changed over time?", QueryMode.TIMELINE),
        ("Show my employment history.", QueryMode.TIMELINE),
        ("Book me a flight.", QueryMode.CURRENT),  # ambiguous → current
    ],
)
def test_query_mode_interpretation(query, mode):
    assert interpret_query_mode(query).mode == mode


def test_as_of_reference_extracted():
    intent = interpret_query_mode("As of March 2024, where did I work?")
    assert intent.reference == "2024-03"
    intent = interpret_query_mode("What phone did I use in 2025?")
    assert intent.reference == "2025"


def test_current_query_selects_only_current(agent=None):
    agent, _, _ = correction_agent()
    agent.chat(user_id="u", session_id="q", message="Which phone do I have?")
    assert selected_texts(agent) == ["Phone is a Pixel 9."]


def test_historical_query_includes_superseded_labeled():
    agent, _, _ = correction_agent()
    agent.chat(user_id="u", session_id="q", message="What was my old phone?")
    texts = selected_texts(agent)
    assert any("Pixel 6" in t for t in texts)
    rendered = rendered_context(agent)
    assert "superseded" in rendered  # labeled historical, never silent


def test_as_of_query_includes_period_valid_record():
    agent, _, _ = correction_agent()
    agent.chat(
        user_id="u", session_id="q",
        message="What phone did I use in 2025?",
    )
    assert any("Pixel 6" in t for t in selected_texts(agent))


def test_timeline_query_chronological_variants():
    agent, planner, _ = temporal_agent()
    planner.set_reference_time("2024-03-01")
    agent.chat(user_id="u", session_id="s1",
               message="My employer is Initech.")
    planner.set_reference_time(REF)
    agent.chat(user_id="u", session_id="s2",
               message="My employer is Globex now.")
    agent.chat(user_id="u", session_id="q",
               message="Show my employer history.")
    texts = selected_texts(agent)
    assert any("Initech" in t for t in texts)
    assert any("Globex" in t for t in texts)


def test_forgotten_excluded_from_all_modes():
    agent, planner, policy = temporal_agent()
    planner.set_reference_time(REF)
    agent.chat(user_id="u", session_id="s1",
               message="I prefer morning flights.")
    agent.chat(user_id="u", session_id="s1",
               message="Forget that I prefer morning flights.")
    for query in ("What do I prefer?", "What did I prefer before?",
                  "Show my preference history."):
        agent.chat(user_id="u", session_id="q", message=query)
        assert not any("morning" in t for t in selected_texts(agent)), query
    assert policy.counters["forgotten_excluded"] == 0  # engine never passes


# --- Retrieval integration -----------------------------------------------------------


def entry_with(text, kind="fact", status=MemoryStatus.ACTIVE,
               temporal=None, provenance=None):
    record = ExperienceEntry(user_id="u", text=text, kind=kind, status=status)
    if temporal is not None:
        record.metadata[TEMPORAL_KEY] = temporal.to_metadata()
    if provenance is not None:
        record.metadata[PROVENANCE_KEY] = provenance.to_metadata()
    return record


def retrieve(memories, query, reference=REF, k=4):
    strategy = HybridRetrievalStrategy(
        temporal_policy=TemporalRetrievalPolicy(reference_time=reference)
    )
    return strategy.retrieve(
        RetrievalRequest(query=query, memories=tuple(memories), k=k)
    )


def test_future_record_held_in_current_mode():
    future = entry_with(
        "Report channel is #finance.",
        temporal=TemporalMetadata(
            temporal_scope=TemporalScope.FUTURE, valid_from="2026-08",
        ),
    )
    result = retrieve([future], "Which channel gets my reports?")
    assert result.selected == []
    reasons = {c.exclusion_reason for c in result.candidates}
    assert "not_yet_valid" in reasons
    # After activation, the same record is current.
    later = retrieve([future], "Which channel gets my reports?",
                     reference="2026-08-05")
    assert [m.text for m in later.selected] == ["Report channel is #finance."]


def test_trust_refines_but_never_creates_relevance():
    trusted_irrelevant = entry_with(
        "Reservation confirmed for 2026-07-18.",
        provenance=ProvenanceMetadata(
            source_type=SourceType.TOOL_VERIFIED, source_role="tool",
        ),
    )
    result = retrieve([trusted_irrelevant], "What's the capital of France?")
    assert result.selected == []  # trust alone earns nothing
    relevant = retrieve([trusted_irrelevant], "When is my reservation?")
    candidate = next(c for c in relevant.candidates if c.selected)
    assert candidate.component_scores["trust_score"] == 5.0


def test_temporal_components_absent_without_policy():
    strategy = HybridRetrievalStrategy()
    result = strategy.retrieve(
        RetrievalRequest(
            query="When is my reservation?",
            memories=(entry_with("Reservation confirmed for 2026-07-18."),),
            k=4,
        )
    )
    candidate = next(c for c in result.candidates if c.selected)
    assert "trust_score" not in candidate.component_scores
    assert not strategy.includes_historical


def test_retrieval_never_mutates_state():
    memory = entry_with(
        "Phone is a Pixel 9.",
        temporal=TemporalMetadata(temporal_scope=TemporalScope.CURRENT),
    )
    before = json.dumps(memory.metadata, sort_keys=True, default=str)
    retrieve([memory], "Which phone do I have?")
    assert json.dumps(memory.metadata, sort_keys=True, default=str) == before
    assert memory.status == "active"


# --- Rendering ----------------------------------------------------------------------


def test_current_label_and_provenance_rendered():
    agent, planner, _ = temporal_agent()
    planner.set_reference_time(REF)
    agent.chat(user_id="u", session_id="s1",
               message="My phone is a Pixel 9 now.")
    agent.chat(user_id="u", session_id="q",
               message="Which phone do I have?")
    rendered = rendered_context(agent)
    assert "[user asserted, current]" in rendered


def test_approximate_time_labeled():
    memory = entry_with(
        "Worked at Acme.",
        temporal=TemporalMetadata(
            temporal_scope=TemporalScope.HISTORICAL,
            time_precision=TimePrecision.APPROXIMATE,
            time_confidence=0.5,
        ),
    )
    policy = TemporalRetrievalPolicy(reference_time=REF)
    label = policy.annotate(memory, {})
    assert "historical" in label
    assert "approximate time" in label


def test_v1_rendering_unchanged():
    builder = ContextBuilder(memory_budget=2)
    build = builder.build_context(
        "u", "s", "Anything.",
        [ExperienceEntry(user_id="u", text="Likes tea.", kind="preference")],
    )
    rendered = " ".join(m["content"] for m in build.messages)
    assert "- Likes tea." in rendered
    assert "[" not in rendered.split("Likes tea.")[1][:5]


# --- V1/V2 isolation ------------------------------------------------------------------


def test_prior_adapters_unchanged():
    from benchmarks.adapters.experienceos_coverage_v2 import (
        ExperienceOSCoverageV2Adapter,
    )
    from benchmarks.adapters.experienceos_hybrid_retrieval_v2 import (
        ExperienceOSHybridRetrievalV2Adapter,
    )

    from benchmarks.contract import case_from_dict

    case = case_from_dict(
        {
            "scenario_id": "synthetic-isolation-001",
            "schema_version": "1",
            "title": "Synthetic",
            "category": "retrieval",
            "description": "Isolation probe.",
            "tags": ["domain:test"],
            "seed": 7,
            "context_budget": 4,
            "selection_k": 4,
            "turns": [],
            "current_message": "Anything.",
            "current_session_id": "s1",
            "expected": {"memory_actions": []},
            "evaluation_mode": "deterministic",
        }
    )
    for adapter_cls in (
        ExperienceOSCoverageV2Adapter, ExperienceOSHybridRetrievalV2Adapter,
    ):
        adapter = adapter_cls()
        strategy = adapter._make_retrieval_strategy(case)
        assert strategy.temporal_policy is None
        assert not strategy.includes_historical


def test_temporal_adapter_registration_and_provenance():
    from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
    from benchmarks.contract import SystemId, case_from_dict

    assert SystemId.EXPERIENCEOS_TEMPORAL_V2 in ADAPTER_SYSTEM_IDS
    system = create_system(SystemId.EXPERIENCEOS_TEMPORAL_V2)
    case = case_from_dict(
        {
            "scenario_id": "synthetic-temporal-001",
            "schema_version": "1",
            "title": "Synthetic",
            "category": "retrieval",
            "description": "Synthetic temporal adapter test case.",
            "tags": ["domain:test"],
            "seed": 7,
            "context_budget": 4,
            "selection_k": 4,
            "turns": [],
            "current_message": "Which phone do I have?",
            "current_session_id": "s1",
            "expected": {"memory_actions": []},
            "evaluation_mode": "deterministic",
        }
    )
    system.initialize(case)
    system.process_turn(0, "s1", "My phone is a Pixel 9 now.")
    diagnostics = system.diagnostics
    assert diagnostics["temporal_metadata_version"] == "1"
    assert diagnostics["provenance_version"] == "1"
    assert diagnostics["assistant_ingestion_enabled"] is True
    assert diagnostics["forgotten_history_policy"] == (
        "always_excluded_user_facing"
    )
    assert diagnostics["generalized_supersession_enabled"] is True
    assert "temporal_v2" in diagnostics
    assert "coverage_v2" in diagnostics


def test_dev_composition_labeled_not_registered():
    from benchmarks.adapters.experienceos_temporal_v2 import (
        ExperienceOSTemporalV2Adapter,
    )
    from benchmarks.contract import KNOWN_SYSTEM_IDS

    dev = ExperienceOSTemporalV2Adapter(dev_composition=True)
    assert dev.system_id == "dev_full_temporal"
    assert dev.system_id not in KNOWN_SYSTEM_IDS


def test_no_temporal_metrics_without_diagnostics():
    from benchmarks.evaluators.temporal_v2 import temporal_v2_contributions

    class Result:
        diagnostics = {}

    assert temporal_v2_contributions(object(), Result()) == []


# --- Integration -----------------------------------------------------------------------


def test_sqlite_round_trip_preserves_temporal_and_provenance(tmp_path):
    db = tmp_path / "memories.db"
    agent, planner, _ = temporal_agent(memory_store=SQLiteMemoryStore(db))
    planner.set_reference_time(REF)
    agent.chat(
        user_id="u", session_id="s1",
        message="My start date is June 3, 2025.",
    )
    del agent

    reopened = ExperienceOS(
        model=MockProvider(), memory_store=SQLiteMemoryStore(db)
    )
    memories = reopened.memories_for_user("u")
    assert memories
    temporal = memories[0].metadata[TEMPORAL_KEY]
    assert temporal["event_time"] == "2025-06-03"
    provenance = memories[0].metadata[PROVENANCE_KEY]
    assert provenance["source_type"] == SourceType.USER_ASSERTED


def test_legacy_sqlite_rows_stay_readable(tmp_path):
    db = tmp_path / "memories.db"
    plain = ExperienceOS(model=MockProvider(),
                         memory_store=SQLiteMemoryStore(db))
    plain.chat(user_id="u", session_id="s1", message="I prefer aisle seats.")
    del plain

    agent, _, _ = temporal_agent(memory_store=SQLiteMemoryStore(db))
    agent.chat(user_id="u", session_id="q", message="Which seat do I prefer?")
    assert "Prefers aisle seats." in selected_texts(agent)


def test_repeated_temporal_run_is_deterministic():
    outputs = set()
    for _ in range(3):
        agent, _, _ = correction_agent()
        agent.chat(user_id="u", session_id="q",
                   message="What was my old phone?")
        outputs.add(tuple(selected_texts(agent)))
        outputs.add(
            rendered_context(agent).replace(" ", "")[:400]
        )
    assert len(outputs) == 2  # one selection tuple + one rendering string
