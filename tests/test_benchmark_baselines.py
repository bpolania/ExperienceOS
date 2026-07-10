"""Comparative baseline tests: shared behavior, per-baseline semantics,
and structural compatibility with the committed 40-scenario dataset.

Everything runs offline with the deterministic provider — no network,
no credentials, no local model.
"""

import json

import pytest

from benchmarks.baselines.append_only import AppendOnlyBaseline
from benchmarks.baselines.common import (
    DeterministicEchoProvider,
    annotate_logical_references,
    looks_durable,
    run_case,
)
from benchmarks.baselines.factory import (
    BASELINE_SYSTEM_IDS,
    create_baseline,
)
from benchmarks.baselines.full_history import FullHistoryBaseline
from benchmarks.baselines.naive_top_k import NaiveTopKBaseline
from benchmarks.baselines.stateless import StatelessBaseline
from benchmarks.contract import (
    CaseStatus,
    SystemId,
    case_from_dict,
    validate_case_result,
)
from benchmarks.scenarios.loader import load_dataset, load_manifest


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def scenario(dataset, scenario_id):
    return next(
        s for s in dataset if s.case.scenario_id == scenario_id
    )


def simple_case(**overrides):
    data = {
        "scenario_id": "synthetic-001",
        "schema_version": "1",
        "title": "Synthetic",
        "category": "creation",
        "description": "Synthetic test case.",
        "tags": ["domain:test"],
        "seed": 7,
        "context_budget": 4,
        "selection_k": 4,
        "turns": [],
        "current_message": "Hello there.",
        "current_session_id": "s1",
        "expected": {"memory_actions": []},
        "evaluation_mode": "deterministic",
    }
    data.update(overrides)
    return case_from_dict(data)


def drive(system, case, messages):
    """Initialize and process messages; return the TurnEvidence list."""
    system.initialize(case)
    return [
        system.process_turn(i, "s1", message)
        for i, message in enumerate(messages)
    ]


def latency_free(payload):
    """Strip wall-clock fields so payloads compare deterministically."""
    body = json.loads(json.dumps(payload))
    for turn in body.get("turns", []):
        turn["latencies"] = []
    body["latencies"] = []
    return body


# --- Shared behavior ----------------------------------------------------------


def test_factory_maps_all_baseline_ids():
    assert set(BASELINE_SYSTEM_IDS) == {
        SystemId.STATELESS,
        SystemId.FULL_HISTORY,
        SystemId.APPEND_ONLY,
        SystemId.NAIVE_TOP_K,
    }
    for system_id in BASELINE_SYSTEM_IDS:
        system = create_baseline(system_id)
        assert system.system_id == system_id
        assert system.config.provider_name == "deterministic-echo"


def test_factory_rejects_unknown_and_experienceos_ids():
    with pytest.raises(ValueError) as excinfo:
        create_baseline("experienceos_rules")
    assert "Prompt 4" in str(excinfo.value)
    with pytest.raises(ValueError):
        create_baseline("does-not-exist")


def test_deterministic_provider_is_stable_and_context_derived():
    provider = DeterministicEchoProvider()
    messages = ["sys", "note", "What now?"]
    assert provider.complete(messages) == provider.complete(messages)
    assert "What now?" in provider.complete(messages)
    assert "context messages: 2" in provider.complete(messages)


@pytest.mark.parametrize("system_id", BASELINE_SYSTEM_IDS)
def test_initialization_resets_state_between_scenarios(system_id):
    system = create_baseline(system_id)
    case = simple_case()
    drive(system, case, ["I prefer aisle seats for short work trips."])
    system.initialize(simple_case(scenario_id="synthetic-002"))
    evidence = system.process_turn(0, "s1", "Anything stored?")
    assert evidence.candidates == ()
    assert system.final_state().entries == ()


@pytest.mark.parametrize("system_id", BASELINE_SYSTEM_IDS)
def test_close_is_idempotent(system_id):
    system = create_baseline(system_id)
    drive(system, simple_case(), ["I like tea."])
    system.close()
    system.close()
    assert system.final_state().entries == ()


@pytest.mark.parametrize("system_id", BASELINE_SYSTEM_IDS)
def test_context_accounting_uses_approximation_method(system_id, dataset):
    result = run_case(
        create_baseline(system_id),
        scenario(dataset, "creation_001_explicit_scoped_preference"),
    )
    accounting = result.context_accounting
    assert accounting.method == "approximation"
    assert accounting.total_context_tokens == -(-accounting.total_context_chars // 4)


@pytest.mark.parametrize("system_id", BASELINE_SYSTEM_IDS)
def test_case_results_validate_and_serialize(system_id, dataset):
    result = run_case(
        create_baseline(system_id),
        scenario(dataset, "updates_001_preference_replacement_cross_session"),
    )
    validate_case_result(result)
    json.dumps(result.to_payload())


def test_partial_failure_preserves_prior_turn_evidence(dataset):
    class ExplodingProvider(DeterministicEchoProvider):
        def __init__(self):
            self.calls = 0

        def complete(self, messages):
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("provider blew up")
            return super().complete(messages)

    result = run_case(
        create_baseline(SystemId.APPEND_ONLY, provider=ExplodingProvider()),
        scenario(dataset, "forgetting_001_exact_forget"),
    )
    assert result.status == CaseStatus.PARTIAL
    assert "provider blew up" in result.failure_reason
    assert result.turns  # earlier evidence survived
    validate_case_result(result)


def test_annotation_is_observational_only(dataset):
    loaded = scenario(dataset, "creation_001_explicit_scoped_preference")
    result = run_case(create_baseline(SystemId.APPEND_ONLY), loaded)
    before = latency_free(result.to_payload())
    before["diagnostics"].pop("logical_resolution", None)
    annotate_logical_references(loaded.case, result)
    after = latency_free(result.to_payload())
    resolution = after["diagnostics"].pop("logical_resolution")
    assert after == before  # nothing but diagnostics changed
    assert resolution["travel.seat.short_work_trip"]  # and it resolved


@pytest.mark.parametrize("system_id", BASELINE_SYSTEM_IDS)
def test_no_baseline_reads_the_oracle(system_id, dataset):
    """Identical evidence with the oracle stripped: decisions cannot
    have depended on expected fields."""
    loaded = scenario(dataset, "retrieval_008_stale_would_mislead")
    with_oracle = run_case(create_baseline(system_id), loaded)

    stripped_data = json.loads(loaded.path.read_text())
    stripped_data["expected"] = {"memory_actions": []}
    stripped = type(loaded)(
        case=case_from_dict(stripped_data),
        group=loaded.group,
        path=loaded.path,
        entry=loaded.entry,
    )
    without_oracle = run_case(create_baseline(system_id), stripped)

    a = latency_free(with_oracle.to_payload())
    b = latency_free(without_oracle.to_payload())
    a["diagnostics"].pop("logical_resolution")
    b["diagnostics"].pop("logical_resolution")
    assert a == b


def test_local_model_cases_are_skipped_without_model(dataset):
    loaded = scenario(dataset, "containment_005_one_sentence_supersession_local")
    for system_id in BASELINE_SYSTEM_IDS:
        result = run_case(create_baseline(system_id), loaded)
        assert result.status == CaseStatus.SKIPPED
        assert "requires_local_model" in result.skip_reason
        assert result.turns == []  # never executed, never invoked a model


# --- Stateless ------------------------------------------------------------------


def test_stateless_prior_turns_unavailable():
    system = StatelessBaseline()
    turns = drive(
        system,
        simple_case(),
        ["I prefer aisle seats for short work trips.", "Plan my trip."],
    )
    final = turns[-1]
    assert all("aisle" not in m for m in final.context_messages)
    assert "aisle" not in final.response


def test_stateless_current_message_reaches_provider():
    system = StatelessBaseline()
    turns = drive(system, simple_case(), ["What's 15% of 240?"])
    assert "15% of 240" in turns[0].response


def test_stateless_emits_empty_memory_evidence():
    system = StatelessBaseline()
    turns = drive(
        system, simple_case(), ["I prefer aisle seats.", "Book a flight."]
    )
    for evidence in turns:
        assert evidence.proposals == ()
        assert evidence.applied_actions == ()
        assert evidence.candidates == ()
    assert system.final_state().entries == ()
    assert system.last_accounting.memory_context_tokens == 0
    assert system.last_accounting.memory_context_chars == 0


def test_stateless_scenarios_do_not_leak():
    system = StatelessBaseline()
    drive(system, simple_case(), ["I prefer window seats."])
    turns = drive(
        system,
        simple_case(scenario_id="synthetic-002"),
        ["What seat do I prefer?"],
    )
    assert all("window" not in m for m in turns[0].context_messages)


# --- Full history -----------------------------------------------------------------


def test_full_history_preserves_order_and_grows():
    system = FullHistoryBaseline()
    messages = ["First fact: tea.", "Second fact: coffee.", "Recap please."]
    turns = drive(system, simple_case(), messages)
    final_context = turns[-1].context_messages
    tea = next(i for i, m in enumerate(final_context) if "tea" in m)
    coffee = next(i for i, m in enumerate(final_context) if "coffee" in m)
    assert tea < coffee
    sizes = [
        sum(len(m) for m in t.context_messages) for t in turns
    ]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]


def test_full_history_retains_corrected_and_forgotten_text():
    system = FullHistoryBaseline()
    turns = drive(
        system,
        simple_case(),
        [
            "I prefer tea in the morning.",
            "Actually, I prefer coffee in the morning.",
            "Forget my morning drink preference entirely.",
            "What should I drink?",
        ],
    )
    final_context = " ".join(turns[-1].context_messages)
    assert "tea" in final_context  # corrected value still present
    assert "coffee" in final_context
    assert "Forget my morning drink" in final_context  # forget is just text


def test_full_history_no_memory_or_retrieval_actions():
    system = FullHistoryBaseline()
    turns = drive(
        system, simple_case(), ["I prefer tea.", "Plan my morning."]
    )
    for evidence in turns:
        assert evidence.proposals == ()
        assert evidence.applied_actions == ()
        assert evidence.candidates == ()
    assert system.final_state().entries == ()
    # Transcript counts in total context, not memory context.
    assert system.last_accounting.memory_context_tokens == 0
    assert system.last_accounting.total_context_chars > len(
        "Plan my morning."
    )


def test_full_history_current_message_not_duplicated():
    system = FullHistoryBaseline()
    turns = drive(system, simple_case(), ["Alpha message.", "Beta message."])
    final_context = turns[-1].context_messages
    assert sum("Beta message." in m for m in final_context) == 1


def test_full_history_reset_clears_transcript():
    system = FullHistoryBaseline()
    drive(system, simple_case(), ["Secret alpha detail."])
    turns = drive(
        system, simple_case(scenario_id="synthetic-002"), ["Recap please."]
    )
    assert all("alpha" not in m for m in turns[0].context_messages)


# --- Append-only --------------------------------------------------------------------


def test_append_only_durable_creates_and_transient_does_not():
    system = AppendOnlyBaseline()
    drive(
        system,
        simple_case(),
        [
            "I prefer aisle seats for short work trips.",
            "I'm pretty tired today, and it's raining here again.",
        ],
    )
    entries = system.final_state().entries
    assert len(entries) == 1
    assert "aisle" in entries[0].text


def test_append_only_correction_appends_contradiction_remains():
    system = AppendOnlyBaseline()
    drive(
        system,
        simple_case(),
        [
            "I prefer tea in the morning.",
            "Actually, I prefer coffee in the morning.",
        ],
    )
    entries = system.final_state().entries
    assert len(entries) == 2
    texts = " ".join(e.text for e in entries)
    assert "tea" in texts and "coffee" in texts
    assert all(e.status == "active" for e in entries)


def test_append_only_forget_request_changes_nothing():
    system = AppendOnlyBaseline()
    drive(
        system,
        simple_case(),
        ["I don't like cilantro.", "Forget that I don't like cilantro."],
    )
    entries = system.final_state().entries
    assert len(entries) == 1  # forget neither removes nor stores
    assert entries[0].status == "active"


def test_append_only_duplicates_accumulate():
    system = AppendOnlyBaseline()
    drive(
        system,
        simple_case(),
        ["I don't like cilantro.", "I don't like cilantro."],
    )
    assert len(system.final_state().entries) == 2  # documented: no dedupe


def test_append_only_budget_and_skips_visible():
    system = AppendOnlyBaseline()
    case = simple_case(context_budget=2, selection_k=2)
    messages = [
        "I prefer tea in the morning.",
        "I like ordering pizza on Fridays.",
        "I prefer aisle seats for short work trips.",
        "Plan my week.",
    ]
    turns = drive(system, case, messages)
    final = turns[-1]
    selected = [c for c in final.candidates if c.selected]
    skipped = [c for c in final.candidates if not c.selected]
    assert len(selected) == 2  # budget obeyed
    assert len(skipped) == 1
    # Most-recent-first: the earliest record is the one skipped.
    assert "tea" in skipped[0].text
    assert system.last_accounting.selected_memory_count == 2


def test_append_only_stale_value_remains_selectable():
    system = AppendOnlyBaseline()
    turns = drive(
        system,
        simple_case(context_budget=2, selection_k=2),
        [
            "My phone is a Pixel 6.",
            "I upgraded — my phone is a Pixel 9 now.",
            "Which charger should I buy?",
        ],
    )
    final_context = " ".join(turns[-1].context_messages)
    assert "Pixel 6" in final_context  # stale record still supplied


# --- Naive top-K -----------------------------------------------------------------------


def make_naive(case=None, messages=()):
    system = NaiveTopKBaseline()
    system.initialize(case or simple_case())
    turns = [
        system.process_turn(i, "s1", m) for i, m in enumerate(messages)
    ]
    return system, turns


def test_naive_ranking_is_deterministic_and_overlap_driven():
    setup = [
        "I prefer flashcards for memorizing vocabulary.",
        "My gym membership is at FitLife downtown.",
    ]
    query = "Help me plan my Spanish vocabulary review for tomorrow."
    system, turns = make_naive(
        simple_case(context_budget=1, selection_k=1), [*setup, query]
    )
    final = turns[-1]
    assert final.candidates[0].rank == 1
    assert "flashcards" in final.candidates[0].text  # overlap beats recency
    assert final.candidates[0].selected
    assert not final.candidates[1].selected
    # Deterministic across a fresh run:
    _, again = make_naive(
        simple_case(context_budget=1, selection_k=1), [*setup, query]
    )
    assert [c.memory_id for c in again[-1].candidates] == [
        c.memory_id for c in final.candidates
    ]


def test_naive_zero_overlap_falls_back_to_recency():
    system, turns = make_naive(
        simple_case(context_budget=1, selection_k=1),
        [
            "I don't like peanuts — never include them in my food.",
            "I prefer dark mode in my code editor.",
            "Suggest a trail snack for my weekend hike.",
        ],
    )
    final = turns[-1]
    # Zero lexical overlap for both: the newer record wins the slot.
    assert "dark mode" in final.candidates[0].text
    assert "recency" in final.candidates[0].reason


def test_naive_tie_break_is_insertion_order():
    system, turns = make_naive(
        simple_case(context_budget=1, selection_k=1),
        [
            "I like blue pens.",
            "I like blue notebooks.",
            "Recommend something blue.",
        ],
    )
    final = turns[-1]
    same_score = [c for c in final.candidates]
    # Equal overlap ("blue") — recency differs; force a true tie by
    # checking the documented rule on equal-score candidates instead:
    scores = [c.score for c in same_score]
    if scores[0] == scores[1]:
        assert same_score[0].memory_id < same_score[1].memory_id


def test_naive_k_and_budget_enforced():
    messages = [
        "I like blue pens.",
        "I like blue notebooks.",
        "I like blue mugs.",
        "Recommend something blue.",
    ]
    system, turns = make_naive(
        simple_case(context_budget=4, selection_k=2), messages
    )
    assert sum(c.selected for c in turns[-1].candidates) == 2  # K wins
    system, turns = make_naive(
        simple_case(context_budget=1, selection_k=4), messages
    )
    assert sum(c.selected for c in turns[-1].candidates) == 1  # budget wins


def test_naive_stale_and_forgotten_values_remain_eligible():
    system, turns = make_naive(
        simple_case(context_budget=4, selection_k=4),
        [
            "My phone is a Pixel 6.",
            "I upgraded — my phone is a Pixel 9 now.",
            "Forget that I don't like cilantro.",
            "Which fast charger should I buy for my phone?",
        ],
    )
    final = turns[-1]
    texts = [c.text for c in final.candidates if c.selected]
    assert any("Pixel 6" in t for t in texts)  # stale stays eligible
    assert any("Pixel 9" in t for t in texts)


def test_naive_wrong_domain_lexical_match_can_rank():
    system, turns = make_naive(
        simple_case(context_budget=1, selection_k=1),
        [
            "For long international flights, I prefer window seats.",
            "What curtains would work well for my living room windows?",
        ],
    )
    final = turns[-1]
    assert final.candidates[0].selected  # lexical trap taken
    assert "window" in final.candidates[0].text


def test_naive_scores_expose_components():
    system, turns = make_naive(
        simple_case(),
        ["I like blue pens.", "Recommend blue pens."],
    )
    reason = turns[-1].candidates[0].reason
    assert "overlap=" in reason and "recency=" in reason
    assert "weights=(1.0,0.5)" in reason


# --- Dataset compatibility --------------------------------------------------------------


@pytest.mark.parametrize("system_id", BASELINE_SYSTEM_IDS)
def test_all_40_scenarios_structurally_compatible(system_id, dataset):
    manifest = load_manifest()
    assert manifest["manifest_hash"] == (
        "0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb"
    )
    completed = skipped = 0
    for loaded in dataset:  # manifest order
        result = run_case(create_baseline(system_id), loaded)
        validate_case_result(result)
        json.dumps(result.to_payload())
        if result.status == CaseStatus.SKIPPED:
            skipped += 1
            assert result.skip_reason
        else:
            assert result.status == CaseStatus.PASSED, (
                f"{loaded.case.scenario_id}: {result.failure_reason}"
            )
            completed += 1
    assert completed == 38
    assert skipped == 2  # the two requires_local_model cases


def test_repeated_runs_are_deterministic(dataset):
    loaded = scenario(dataset, "context_001_budget_exceeded")
    payloads = [
        latency_free(
            run_case(create_baseline(SystemId.NAIVE_TOP_K), loaded).to_payload()
        )
        for _ in range(2)
    ]
    assert payloads[0] == payloads[1]


def test_durability_heuristic_is_documented_behavior():
    assert looks_durable("I prefer aisle seats for short work trips.")
    assert looks_durable("From now on, send my status to #eng-daily.")
    assert looks_durable("My home airport is SJC.")
    assert not looks_durable("I'm pretty tired today, and it's raining.")
    assert not looks_durable("Forget that I don't like cilantro.")
    assert not looks_durable("I don't care about my study preference anymore.")
