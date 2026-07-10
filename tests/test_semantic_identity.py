"""Phase 9 Prompt 2 tests: semantic identity, conservative conflict
detection, lifecycle integration, persistence, and v1/v2 isolation.
All deterministic and offline."""

import json
from pathlib import Path

import pytest

from experienceos import ExperienceOS
from experienceos.memory import ExperienceEntry, MemoryKind, MemoryStatus
from experienceos.memory.planner import MemoryPlanner
from experienceos.memory.semantic import (
    Cardinality,
    Decision,
    SemanticIdentity,
    SemanticNormalizer,
    evaluate_pair,
    identity_of,
    resolve_conflicts,
)
from experienceos.memory.semantic_planner import SemanticMemoryPlanner
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.providers import MockProvider

FIXTURES = json.loads(
    Path("benchmarks/fixtures/phase9_dev/semantic_identity/cases.json")
    .read_text()
)


def v2_agent(**kwargs):
    return ExperienceOS(
        model=MockProvider(),
        memory_planner=SemanticMemoryPlanner(),
        **kwargs,
    )


def chat_all(agent, messages, user="u"):
    for message in messages:
        agent.chat(user_id=user, session_id="s", message=message)
    return agent


def texts(agent, status=MemoryStatus.ACTIVE, user="u"):
    return [m.text for m in agent.memories_for_user(user, status=status)]


def entry(kind, text, **metadata):
    e = ExperienceEntry(user_id="u", text=text, kind=kind)
    e.metadata.update(metadata)
    return e


NORMALIZER = SemanticNormalizer()


# --- Normalization -------------------------------------------------------------


def test_fact_attribute_aliases_normalize():
    for text, attribute, value in (
        ("Phone is a Pixel 6.", "current_phone", "pixel 6"),
        ("Current phone is Pixel 9.", "current_phone", "pixel 9"),
        ("Device is a Pixel 9.", "current_phone", "pixel 9"),
        ("Lives in San Jose.", "residence", "san jose"),
        ("Employer is Acme.", "employer", "acme"),
        ("Works for Globex.", "employer", "globex"),
    ):
        identity = NORMALIZER.normalize(MemoryKind.FACT, text)
        assert identity is not None, text
        assert identity.subject == "user"
        assert identity.attribute == attribute
        assert identity.value == value
        assert identity.cardinality == Cardinality.SINGLE


def test_generic_possessive_fact_gets_slug_attribute():
    identity = NORMALIZER.normalize(
        MemoryKind.FACT, "Daughter's soccer practice is on Tuesdays."
    )
    assert identity.attribute == "daughters_soccer_practice"
    assert identity.value == "on tuesdays"


def test_preference_classes_and_scopes():
    aisle = NORMALIZER.normalize(
        MemoryKind.PREFERENCE, "Prefers aisle seats for short work trips."
    )
    assert (aisle.attribute, aisle.scope, aisle.value) == (
        "preferred_seat", "short_work_trip", "aisle",
    )
    window = NORMALIZER.normalize(
        MemoryKind.PREFERENCE, "Prefers window seats."
    )
    assert (window.attribute, window.scope) == ("preferred_seat", "global")
    tea = NORMALIZER.normalize(
        MemoryKind.PREFERENCE, "Prefers tea in the morning."
    )
    assert (tea.attribute, tea.scope, tea.value) == (
        "preferred_drink", "morning", "tea",
    )
    study = NORMALIZER.normalize(
        MemoryKind.PREFERENCE, "Prefers studying in the evening."
    )
    assert (study.attribute, study.scope, study.value) == (
        "study_time", "global", "evening",
    )


def test_unknown_identity_is_none_not_guessed():
    assert NORMALIZER.normalize(MemoryKind.PREFERENCE, "Dislikes cilantro.") is None
    assert NORMALIZER.normalize(
        MemoryKind.INSTRUCTION, "Include airport transfer time when planning."
    ) is None
    assert NORMALIZER.normalize(MemoryKind.PREFERENCE, "Prefers studying.") is None


def test_historical_wording_flagged():
    identity = NORMALIZER.normalize(
        MemoryKind.FACT, "Phone is a Pixel 6 back in 2024."
    )
    assert identity is not None and identity.is_historical()


def test_multi_valued_language():
    identity = NORMALIZER.normalize(MemoryKind.FACT, "Speaks Spanish.")
    assert identity.attribute == "speaks_language"
    assert identity.cardinality == Cardinality.MULTI


def test_routing_instruction_with_trailing_modifier():
    identity = NORMALIZER.normalize(
        MemoryKind.INSTRUCTION,
        "Send my daily status summary to the #eng-standup channel instead.",
    )
    assert identity.attribute == "routing:daily_status_summary"
    assert identity.value == "#eng-standup"


def test_identity_metadata_round_trip():
    identity = NORMALIZER.normalize(MemoryKind.FACT, "Phone is a Pixel 9.")
    restored = SemanticIdentity.from_metadata(identity.to_metadata())
    assert restored == identity


# --- Conflict detection ------------------------------------------------------------


def make_identity(**overrides):
    base = dict(
        subject="user", attribute="current_phone", value="pixel 6",
        display_value="Pixel 6", scope="global", qualifiers={},
        cardinality=Cardinality.SINGLE,
    )
    base.update(overrides)
    return SemanticIdentity(**base)


def test_single_valued_incompatible_values_supersede():
    old_entry = entry(MemoryKind.FACT, "Phone is a Pixel 6.")
    decision = evaluate_pair(
        make_identity(value="pixel 9"), make_identity(), old_entry
    )
    assert decision.decision == Decision.SUPERSEDE
    assert "pixel 6" in decision.reason


def test_distinct_subject_or_attribute_coexists():
    old_entry = entry(MemoryKind.FACT, "x")
    assert evaluate_pair(
        make_identity(subject="alice", value="pixel 9"),
        make_identity(), old_entry,
    ).decision == Decision.COEXIST
    assert evaluate_pair(
        make_identity(attribute="residence", value="seattle"),
        make_identity(), old_entry,
    ).decision == Decision.COEXIST


def test_distinct_explicit_scopes_coexist():
    decision = evaluate_pair(
        make_identity(attribute="preferred_seat", value="window",
                      scope="long_international_trip"),
        make_identity(attribute="preferred_seat", value="aisle",
                      scope="short_work_trip"),
        entry(MemoryKind.PREFERENCE, "x"),
    )
    assert decision.decision == Decision.COEXIST
    assert "scope" in decision.reason


def test_default_vs_explicit_scope_coexists():
    decision = evaluate_pair(
        make_identity(attribute="preferred_seat", value="window"),
        make_identity(attribute="preferred_seat", value="aisle",
                      scope="short_work_trip"),
        entry(MemoryKind.PREFERENCE, "x"),
    )
    assert decision.decision == Decision.COEXIST


def test_equivalent_value_is_duplicate_not_conflict():
    decision = evaluate_pair(
        make_identity(value="pixel 9"),
        make_identity(value="pixel 9"),
        entry(MemoryKind.FACT, "Phone is a Pixel 9."),
    )
    assert decision.decision == Decision.DUPLICATE


def test_multi_valued_coexists():
    decision = evaluate_pair(
        make_identity(attribute="speaks_language", value="spanish",
                      cardinality=Cardinality.MULTI),
        make_identity(attribute="speaks_language", value="english",
                      cardinality=Cardinality.MULTI),
        entry(MemoryKind.FACT, "Speaks English."),
    )
    assert decision.decision == Decision.COEXIST


def test_unknown_cardinality_coexists():
    decision = evaluate_pair(
        make_identity(cardinality=Cardinality.UNKNOWN, value="pixel 9"),
        make_identity(cardinality=Cardinality.UNKNOWN),
        entry(MemoryKind.FACT, "x"),
    )
    assert decision.decision == Decision.COEXIST


def test_low_confidence_coexists():
    decision = evaluate_pair(
        make_identity(value="pixel 9", confidence=0.6),
        make_identity(),
        entry(MemoryKind.FACT, "x"),
    )
    assert decision.decision == Decision.COEXIST


def test_historical_never_supersedes():
    decision = evaluate_pair(
        make_identity(value="pixel 6", qualifiers={"historical": True}),
        make_identity(value="pixel 9"),
        entry(MemoryKind.FACT, "Phone is a Pixel 9."),
    )
    assert decision.decision == Decision.COEXIST


def test_forgotten_and_superseded_never_targets():
    # resolve_conflicts receives ACTIVE entries only by contract; the
    # planner filters, and this guards the helper's usage pattern.
    active = [entry(MemoryKind.FACT, "Phone is a Pixel 6.")]
    decisions = resolve_conflicts(
        NORMALIZER.normalize(MemoryKind.FACT, "Phone is a Pixel 9."),
        active, NORMALIZER,
    )
    assert [d.decision for d in decisions] == [Decision.SUPERSEDE]


# --- Lifecycle integration --------------------------------------------------------


def test_pixel_supersession_end_to_end():
    agent = chat_all(v2_agent(), [
        "My phone is a Pixel 6.",
        "I upgraded — my phone is a Pixel 9 now.",
    ])
    active = agent.memories_for_user("u")
    superseded = agent.memories_for_user("u", status=MemoryStatus.SUPERSEDED)
    assert [m.text for m in active] == ["Phone is a Pixel 9."]
    assert [m.text for m in superseded] == ["Phone is a Pixel 6."]
    # Bidirectional linkage.
    assert superseded[0].metadata["superseded_by"] == active[0].id
    assert active[0].metadata["replaces"] == superseded[0].id
    # Identity metadata persisted on the new record.
    identity = active[0].metadata["semantic_identity"]
    assert identity["attribute"] == "current_phone"
    assert identity["version"] == "1"
    # Audit events emitted through the existing channel.
    superseded_events = [
        e for e in agent.events if str(e.type) == "memory_superseded"
    ]
    assert len(superseded_events) == 1
    assert "semantic identity v1" in superseded_events[0].payload["reason"]


def test_residence_and_employer_updates():
    agent = chat_all(v2_agent(), [
        "I live in San Jose.",
        "I live in Seattle now.",
    ])
    assert texts(agent) == ["Lives in Seattle."]
    assert texts(agent, MemoryStatus.SUPERSEDED) == ["Lives in San Jose."]


def test_scoped_seat_coexistence_preserved():
    agent = chat_all(v2_agent(), [
        "I prefer aisle seats for short work trips.",
        "For long international trips, I prefer window seats.",
    ])
    active = texts(agent)
    assert len(active) == 2
    assert any("aisle" in t for t in active)
    assert any("window" in t for t in active)
    assert texts(agent, MemoryStatus.SUPERSEDED) == []


def test_different_attributes_never_conflict():
    agent = chat_all(v2_agent(), [
        "I prefer aisle seats for work trips.",
        "I prefer morning flights.",
    ])
    assert len(texts(agent)) == 2
    assert texts(agent, MemoryStatus.SUPERSEDED) == []


def test_duplicate_paraphrase_creates_nothing():
    agent = chat_all(v2_agent(), [
        "My phone is a Pixel 9.",
        "My current phone is Pixel 9.",
    ])
    assert texts(agent) == ["Phone is a Pixel 9."]
    assert texts(agent, MemoryStatus.SUPERSEDED) == []


def test_unrelated_memories_survive_supersession():
    agent = chat_all(v2_agent(), [
        "I don't like cilantro.",
        "My phone is a Pixel 6.",
        "My phone is a Pixel 9.",
    ])
    active = texts(agent)
    assert "Dislikes cilantro." in active
    assert "Phone is a Pixel 9." in active
    assert len(active) == 2


def test_current_retrieval_excludes_superseded():
    agent = chat_all(v2_agent(), [
        "My phone is a Pixel 6.",
        "My phone is a Pixel 9.",
        "Which charger should I buy for my phone?",
    ])
    context_event = [
        e for e in agent.events if str(e.type) == "context_built"
    ][-1]
    contents = " ".join(
        m["content"] for m in context_event.payload["context_messages"]
    )
    assert "Pixel 6" not in contents
    assert "Pixel 9" in contents


def test_forgotten_memories_stay_excluded():
    agent = chat_all(v2_agent(), [
        "I prefer tea in the morning.",
        "Forget that I prefer tea in the morning.",
        "I prefer coffee in the morning.",
    ])
    assert texts(agent) == ["Prefers coffee in the morning."]
    forgotten = texts(agent, MemoryStatus.FORGOTTEN)
    assert forgotten == ["Prefers tea in the morning."]
    # The forgotten record was never a conflict target (no resurrection,
    # no supersession of a forgotten record).
    assert texts(agent, MemoryStatus.SUPERSEDED) == []


def test_multiple_same_slot_conflicts_all_superseded():
    # Two legacy same-slot actives (as if created before v2), one new
    # value: both retire only because each is independently confident.
    agent = v2_agent()
    store = agent.memory_store
    store.add(entry(MemoryKind.FACT, "Phone is a Pixel 6."))
    store.add(entry(MemoryKind.FACT, "Phone is a Pixel 7."))
    agent.chat(user_id="u", session_id="s", message="My phone is a Pixel 9.")
    assert texts(agent) == ["Phone is a Pixel 9."]
    assert sorted(texts(agent, MemoryStatus.SUPERSEDED)) == [
        "Phone is a Pixel 6.", "Phone is a Pixel 7.",
    ]


# --- Persistence ---------------------------------------------------------------------


def test_semantic_identity_survives_sqlite_restart(tmp_path):
    db = str(tmp_path / "p9.sqlite3")
    agent = ExperienceOS(
        model=MockProvider(),
        memory_planner=SemanticMemoryPlanner(),
        memory_store=SQLiteMemoryStore(db),
    )
    chat_all(agent, ["My phone is a Pixel 6.", "My phone is a Pixel 9."])
    reopened = ExperienceOS(
        model=MockProvider(),
        memory_planner=SemanticMemoryPlanner(),
        memory_store=SQLiteMemoryStore(db),
    )
    active = reopened.memories_for_user("u")
    superseded = reopened.memories_for_user(
        "u", status=MemoryStatus.SUPERSEDED
    )
    assert [m.text for m in active] == ["Phone is a Pixel 9."]
    assert active[0].metadata["semantic_identity"]["attribute"] == (
        "current_phone"
    )
    assert superseded[0].metadata["superseded_by"] == active[0].id


def test_legacy_rows_without_identity_remain_valid(tmp_path):
    db = str(tmp_path / "legacy.sqlite3")
    # Pre-change database: plain v1 agent writes rows with no identity.
    v1 = ExperienceOS(model=MockProvider(), memory_store=SQLiteMemoryStore(db))
    v1.chat(user_id="u", session_id="s", message="My phone is a Pixel 6.")
    # Reopened under the v2 planner: legacy row readable, and lazily
    # normalized identity still drives supersession.
    v2 = ExperienceOS(
        model=MockProvider(),
        memory_planner=SemanticMemoryPlanner(),
        memory_store=SQLiteMemoryStore(db),
    )
    legacy = v2.memories_for_user("u")[0]
    assert "semantic_identity" not in legacy.metadata
    assert identity_of(legacy, NORMALIZER).attribute == "current_phone"
    v2.chat(user_id="u", session_id="s", message="My phone is a Pixel 9.")
    assert [m.text for m in v2.memories_for_user("u")] == [
        "Phone is a Pixel 9."
    ]


# --- V1/V2 isolation -----------------------------------------------------------------


def test_v1_planner_behavior_unchanged():
    v1 = ExperienceOS(model=MockProvider())  # default MemoryPlanner
    chat_all(v1, ["My phone is a Pixel 6.", "My phone is a Pixel 9."])
    # Historical v1 behavior: unkeyed facts accumulate (no supersession)
    # and carry no semantic identity metadata.
    active = v1.memories_for_user("u")
    assert sorted(m.text for m in active) == [
        "Phone is a Pixel 6.", "Phone is a Pixel 9.",
    ]
    assert all("semantic_identity" not in m.metadata for m in active)
    assert isinstance(v1.engine.memory_planner, MemoryPlanner)
    assert not isinstance(v1.engine.memory_planner, SemanticMemoryPlanner)


def test_v2_system_registered_and_isolated():
    from benchmarks.adapters.factory import create_system
    from benchmarks.contract import KNOWN_SYSTEM_IDS

    assert "experienceos_slots_v2" in KNOWN_SYSTEM_IDS
    slots = create_system("experienceos_slots_v2")
    rules = create_system("experienceos_rules")
    assert slots.system_id != rules.system_id
    assert "semantic_identity" in slots.memory_policy_label
    assert slots.memory_policy_label != rules.memory_policy_label


def test_v2_adapter_provenance_and_behavior(tmp_path):
    from benchmarks.adapters.common import run_adapter_case
    from benchmarks.adapters.factory import create_system
    from benchmarks.scenarios.loader import load_dataset

    scenario = next(
        s for s in load_dataset()
        if s.case.scenario_id == "retrieval_008_stale_would_mislead"
    )
    result = run_adapter_case(
        create_system("experienceos_slots_v2"), scenario
    )
    assert result.diagnostics["semantic_identity_enabled"] is True
    assert result.diagnostics["conflict_strategy"] == "conservative-1"
    # The generalized update fires on the frozen scenario: Pixel 6 is
    # superseded, not co-active.
    assert [e.text for e in result.final_superseded] == [
        "Phone is a Pixel 6."
    ]
    assert [e.text for e in result.final_active] == ["Phone is a Pixel 9."]


# --- Fixture-driven checks ------------------------------------------------------------


def test_dev_fixture_classes_hold():
    for case in FIXTURES["direct_update"]:
        agent = chat_all(v2_agent(), case["messages"])
        active = " ".join(texts(agent))
        superseded = " ".join(texts(agent, MemoryStatus.SUPERSEDED))
        for term in case["expect"]["active_contains"]:
            assert term in active
        for term in case["expect"]["superseded_contains"]:
            assert term in superseded
    for case in FIXTURES["duplicate_paraphrase"]:
        agent = chat_all(v2_agent(), case["messages"])
        assert len(texts(agent)) == case["expect"]["active_count"]


def test_fixture_multi_valued_and_historical():
    languages = [
        entry(MemoryKind.FACT, "Speaks English."),
        entry(MemoryKind.FACT, "Speaks Spanish."),
    ]
    new = NORMALIZER.normalize(MemoryKind.FACT, "Speaks Spanish.")
    decisions = resolve_conflicts(new, [languages[0]], NORMALIZER)
    assert decisions == []  # coexist: multi-valued

    historical = NORMALIZER.normalize(
        MemoryKind.FACT, "Phone is a Pixel 6 back in 2024."
    )
    current = [entry(MemoryKind.FACT, "Phone is a Pixel 9.")]
    decisions = resolve_conflicts(historical, current, NORMALIZER)
    assert decisions == []  # historical never conflicts with current
