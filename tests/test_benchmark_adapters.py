"""ExperienceOS benchmark adapter tests.

All tests run offline: deterministic provider, no network, no
credentials, no real local model (llama.cpp weights are never
loaded). Runtime memory IDs are UUIDs, so determinism comparisons use
a normalized view that maps IDs to first-seen placeholders and strips
measured latencies — behavioral differences still surface.
"""

import json
import re

import pytest

from benchmarks.adapters.common import run_adapter_case
from benchmarks.adapters.experienceos_local import ExperienceOSLocalAdapter
from benchmarks.adapters.experienceos_rules import ExperienceOSRulesAdapter
from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
from benchmarks.adapters.scripted_policy import (
    SCRIPTED_PROPOSALS,
    scripted_runner_for,
)
from benchmarks.contract import (
    CaseStatus,
    SystemId,
    case_from_dict,
    validate_case_result,
)
from benchmarks.scenarios.loader import load_dataset, load_manifest
from experienceos.providers import MockProvider

MANIFEST_HASH = (
    "0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb"
)

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def scenario(dataset, scenario_id):
    return next(s for s in dataset if s.case.scenario_id == scenario_id)


def simple_case(**overrides):
    data = {
        "scenario_id": "synthetic-001",
        "schema_version": "1",
        "title": "Synthetic",
        "category": "creation",
        "description": "Synthetic adapter test case.",
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
    system.initialize(case)
    return [
        system.process_turn(i, "s1", m) for i, m in enumerate(messages)
    ]


def normalized(payload):
    """Latency-free, UUID-stable view for determinism comparisons."""
    body = json.dumps(payload)
    seen: dict = {}

    def replace(match):
        return seen.setdefault(match.group(0), f"mem-{len(seen):04d}")

    body = _UUID.sub(replace, body)
    data = json.loads(body)
    for turn in data.get("turns", []):
        turn["latencies"] = []
    data["latencies"] = []
    return data


# --- Shared adapter behavior -----------------------------------------------------


def test_factory_resolves_all_six_systems():
    for system_id in (
        SystemId.STATELESS,
        SystemId.FULL_HISTORY,
        SystemId.APPEND_ONLY,
        SystemId.NAIVE_TOP_K,
        SystemId.EXPERIENCEOS_RULES,
        SystemId.EXPERIENCEOS_LOCAL,
    ):
        assert create_system(system_id).system_id == system_id
    assert {
        SystemId.EXPERIENCEOS_RULES,
        SystemId.EXPERIENCEOS_LOCAL,
    } <= set(ADAPTER_SYSTEM_IDS)  # v1 adapters always present; Phase 9
    # adds v2 adapter IDs additively (e.g. experienceos_slots_v2).


def test_factory_rejects_invalid_configuration():
    with pytest.raises(ValueError):
        create_system("nonsense")
    with pytest.raises(ValueError) as excinfo:
        create_system(SystemId.STATELESS, local_mode="real")
    assert "applies only" in str(excinfo.value)
    with pytest.raises(ValueError) as excinfo:
        create_system(SystemId.EXPERIENCEOS_RULES, local_mode="unavailable")
    assert "applies only" in str(excinfo.value)
    with pytest.raises(ValueError):
        ExperienceOSLocalAdapter(mode="bogus")


def test_scenario_storage_is_isolated():
    adapter = ExperienceOSRulesAdapter()
    drive(adapter, simple_case(), ["I prefer aisle seats for work trips."])
    assert adapter.final_state().entries
    drive(
        adapter,
        simple_case(scenario_id="synthetic-002"),
        ["What do you know about me?"],
    )
    assert adapter.final_state().entries == ()


def test_rules_and_local_adapters_do_not_share_state():
    rules = ExperienceOSRulesAdapter()
    local = ExperienceOSLocalAdapter()
    drive(rules, simple_case(), ["I prefer aisle seats for work trips."])
    drive(local, simple_case(), ["Anything stored for me?"])
    assert local.final_state().entries == ()


def test_close_is_idempotent():
    adapter = ExperienceOSRulesAdapter()
    drive(adapter, simple_case(), ["I like tea."])
    adapter.close()
    adapter.close()


def test_events_do_not_leak_across_turns():
    adapter = ExperienceOSRulesAdapter()
    turns = drive(
        adapter,
        simple_case(),
        ["I prefer aisle seats for work trips.", "What time is it?"],
    )
    # Turn 1's create must not reappear in turn 2's evidence.
    assert len(turns[0].applied_actions) == 1
    assert turns[1].applied_actions == ()
    assert len(turns[1].proposals) == 0


def test_exact_context_matches_provider_input():
    class RecordingProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.received = []

        def complete(self, messages):
            self.received.append([m["content"] for m in messages])
            return super().complete(messages)

    provider = RecordingProvider()
    adapter = ExperienceOSRulesAdapter(provider=provider)
    turns = drive(
        adapter,
        simple_case(),
        ["I prefer aisle seats for work trips.", "Plan a work trip."],
    )
    for evidence, received in zip(turns, provider.received):
        assert list(evidence.context_messages) == received


def test_final_snapshot_distinguishes_three_statuses():
    adapter = ExperienceOSRulesAdapter()
    drive(
        adapter,
        simple_case(),
        [
            "I prefer aisle seats for work trips.",
            "Actually, I now prefer window seats for work trips.",
            "I prefer morning flights.",
            "Forget that I prefer morning flights.",
        ],
    )
    entries = adapter.final_state().entries
    statuses = {e.status for e in entries}
    assert statuses == {"active", "superseded", "forgotten"}
    active = [e for e in entries if e.status == "active"]
    assert all("morning" not in e.text for e in active)
    assert all("aisle" not in e.text for e in active)


def test_case_result_validates_and_partial_failure_keeps_evidence(dataset):
    class ExplodingProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def complete(self, messages):
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("provider exploded")
            return super().complete(messages)

    loaded = scenario(dataset, "forgetting_001_exact_forget")
    result = run_adapter_case(
        ExperienceOSRulesAdapter(provider=ExplodingProvider()), loaded
    )
    assert result.status == CaseStatus.PARTIAL
    assert "provider exploded" in result.failure_reason
    assert result.turns and result.turns[0].applied_actions
    validate_case_result(result)


def test_annotation_is_post_run_and_covers_inactive(dataset):
    loaded = scenario(dataset, "retrieval_008_stale_would_mislead")
    result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
    resolution = result.diagnostics["logical_resolution"]
    # The superseded Pixel 6 record resolves through the inactive list.
    assert resolution["devices.phone_model"]


def test_oracle_firewall_holds(dataset):
    loaded = scenario(dataset, "retrieval_008_stale_would_mislead")
    with_oracle = run_adapter_case(ExperienceOSRulesAdapter(), loaded)

    stripped_data = json.loads(loaded.path.read_text())
    stripped_data["expected"] = {"memory_actions": []}
    stripped = type(loaded)(
        case=case_from_dict(stripped_data),
        group=loaded.group,
        path=loaded.path,
        entry=loaded.entry,
    )
    without_oracle = run_adapter_case(ExperienceOSRulesAdapter(), stripped)

    a = normalized(with_oracle.to_payload())
    b = normalized(without_oracle.to_payload())
    a["diagnostics"].pop("logical_resolution")
    b["diagnostics"].pop("logical_resolution")
    assert a == b


# --- Rule-based adapter ---------------------------------------------------------------


def test_rules_create_proposal_and_application(dataset):
    loaded = scenario(dataset, "creation_001_explicit_scoped_preference")
    result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
    turn = result.turns[-1]
    assert turn.proposals[0].action == "create"
    assert turn.proposals[0].decision_source == "rule_based"
    assert turn.proposals[0].confidence == 1
    assert turn.applied_actions[0].action == "create"
    assert "aisle" in result.final_active[0].text.lower()


def test_rules_non_durable_produces_nothing(dataset):
    loaded = scenario(dataset, "creation_004_non_durable_statement")
    result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
    assert result.turns[-1].proposals == ()
    assert result.turns[-1].applied_actions == ()
    assert result.final_active == []


def test_rules_exact_duplicate_leaves_single_active(dataset):
    loaded = scenario(dataset, "creation_005_exact_duplicate_restatement")
    result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
    cilantro = [
        e for e in result.final_active if "cilantro" in e.text.lower()
    ]
    assert len(cilantro) == 1


def test_rules_supersession_evidence(dataset):
    loaded = scenario(dataset, "updates_005_instead_of_wording")
    result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
    final_turn = result.turns[-1]
    actions = {a.action for a in final_turn.applied_actions}
    assert actions == {"supersede", "create"}
    assert [e.text for e in result.final_superseded] == [
        "Prefers aisle seats for work trips."
    ]
    assert "window" in result.final_active[0].text.lower()
    assert "aisle" not in result.final_active[0].text.lower()


def test_rules_forget_and_context_exclusion():
    adapter = ExperienceOSRulesAdapter()
    turns = drive(
        adapter,
        simple_case(),
        [
            "I prefer aisle seats for work trips.",
            "I prefer morning flights.",
            "Forget that I prefer morning flights.",
            "Help me plan a work trip to Boston.",
        ],
    )
    assert turns[2].applied_actions[0].action == "forget"
    final = turns[3]
    selected_texts = [c.text for c in final.candidates if c.selected]
    assert all("morning" not in t.lower() for t in selected_texts)
    assert all(
        "morning" not in m.lower() for m in final.context_messages[:-1]
    )
    entries = adapter.final_state().entries
    forgotten = [e for e in entries if e.status == "forgotten"]
    assert len(forgotten) == 1 and "morning" in forgotten[0].text.lower()
    # Unrelated active memory preserved.
    assert any(
        e.status == "active" and "aisle" in e.text.lower() for e in entries
    )


def test_rules_superseded_excluded_from_context():
    # Seat preferences are a keyed conflict domain, so the rules
    # policy genuinely supersedes here (unlike unkeyed device facts —
    # see retrieval_008, an honest hard case left unpatched).
    adapter = ExperienceOSRulesAdapter()
    turns = drive(
        adapter,
        simple_case(),
        [
            "I prefer aisle seats for work trips.",
            "Actually, I now prefer window seats for work trips.",
            "Plan a work trip to Boston.",
        ],
    )
    final = turns[-1]
    assert all("aisle" not in c.text.lower() for c in final.candidates)
    assert all(
        "aisle" not in m.lower() for m in final.context_messages[:-1]
    )
    entries = adapter.final_state().entries
    assert any(
        e.status == "superseded" and "aisle" in e.text.lower()
        for e in entries
    )


def test_rules_budget_and_selection_evidence(dataset):
    loaded = scenario(dataset, "context_001_budget_exceeded")
    result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
    final = result.turns[-1]
    selected = [c for c in final.candidates if c.selected]
    skipped = [c for c in final.candidates if not c.selected]
    assert len(selected) <= 2  # budget 2
    assert skipped  # overflow is visible
    assert result.context_accounting.context_budget == 2
    assert result.context_accounting.selected_memory_count == len(selected)


def test_rules_compression_evidence():
    # Uses the production compression trigger set (five diverse travel
    # memories); the committed context_003 scenario's three short
    # preferences legitimately do NOT compress under the engine's
    # genuinely-shrinks guard — an honest hard case left unpatched.
    adapter = ExperienceOSRulesAdapter()
    turns = drive(
        adapter,
        simple_case(context_budget=6, selection_k=6),
        [
            "I prefer aisle seats.",
            "I prefer evening flights.",
            "I don't like red-eye flights.",
            "My home airport is SFO.",
            "When planning work trips, include airport transfer time.",
            "Plan a work trip to Denver.",
        ],
    )
    accounting = adapter.last_accounting
    assert accounting.compressed_summary_count >= 1
    assert accounting.compression_saved_chars > 0
    # Compressed content actually entered the supplied context...
    memory_context = " ".join(turns[-1].context_messages[1:-1])
    assert "summary" in memory_context.lower()
    assert "aisle" in memory_context.lower()
    # ...while the source memories remain stored and auditable, and no
    # stored memory was created from the context-only summary.
    entries = adapter.final_state().entries
    assert sum(1 for e in entries if e.status == "active") == 5
    assert all("summary" not in e.text.lower() for e in entries)


def test_rules_final_state_matches_public_queries():
    adapter = ExperienceOSRulesAdapter()
    case = simple_case()
    drive(adapter, case, ["I prefer aisle seats for work trips."])
    snapshot = {e.memory_id for e in adapter.final_state().entries}
    store_ids = {
        m.id for m in adapter.agent.memories_for_user(adapter.user_id)
    }
    assert snapshot == store_ids


# --- Scripted local adapter ---------------------------------------------------------


@pytest.fixture(scope="module")
def scripted_results(dataset):
    return {
        sid: run_adapter_case(
            ExperienceOSLocalAdapter(mode="scripted"), scenario(dataset, sid)
        )
        for sid in SCRIPTED_PROPOSALS
    }


def test_scripted_valid_create_parsed_and_applied(scripted_results):
    result = scripted_results["containment_001_duplicate_create_contained"]
    first = result.turns[0]
    assert first.proposals[0].decision_source == "local_model"
    assert first.applied_actions[0].action == "create"


def test_scripted_duplicate_rejected_not_corruption(scripted_results):
    result = scripted_results["containment_001_duplicate_create_contained"]
    final = result.turns[-1]
    # Case 6: the duplicate proposal is visible AND rejected...
    assert final.proposals[0].text == (
        "Prefers aisle seats for short work trips."
    )
    assert final.rejected_actions[0].rejected_reason == "duplicate_of_active"
    assert final.applied_actions == ()
    assert final.fallbacks == ()
    # ...and the final state is containment, not corruption.
    assert len(result.final_active) == 1
    assert result.status == CaseStatus.PASSED


def test_scripted_inactive_target_rejected(scripted_results):
    result = scripted_results["containment_002_supersede_inactive_target"]
    final = result.turns[-1]
    reasons = {r.rejected_reason for r in final.rejected_actions}
    assert "target_not_active" in reasons
    assert final.applied_actions == ()
    assert [e.text for e in result.final_active] == [
        "Prefers coffee in the morning."
    ]
    assert [e.text for e in result.final_superseded] == [
        "Prefers tea in the morning."
    ]


def test_scripted_nonexistent_forget_rejected_unrelated_preserved(
    scripted_results,
):
    result = scripted_results["containment_003_forget_nonexistent_target"]
    final = result.turns[-1]
    assert final.proposals[0].action == "forget"
    assert final.proposals[0].target_memory_id == "nonexistent-memory-0000"
    assert final.rejected_actions[0].rejected_reason == "target_not_active"
    assert result.final_forgotten == []
    assert "pytest" in result.final_active[0].text  # unrelated preserved


def test_scripted_malformed_triggers_real_fallback(scripted_results):
    result = scripted_results["containment_004_malformed_proposal_fallback"]
    turn = result.turns[-1]
    # Case 3: fallback recorded with typed reason...
    assert turn.fallbacks[0].reason == "invalid_output"
    # ...and the applied action is visibly fallback-sourced, never
    # presented as local-model correctness.
    assert turn.proposals[0].decision_source == "fallback"
    assert turn.applied_actions[0].action == "create"
    assert "greeting" in result.final_active[0].text.lower()


def test_scripted_mode_provenance_and_invocations(scripted_results):
    for result in scripted_results.values():
        assert result.diagnostics["real_model_used"] is False
        assert result.diagnostics["local_mode"] == "scripted"
        assert result.diagnostics["local_model_name"] == (
            "scripted-local-proposals"
        )
        assert result.local_model_invocation_count >= 1


def test_fixture_registry_is_exact(dataset):
    scripted_tagged = {
        s.case.scenario_id
        for s in dataset
        if "scripted_local_proposals" in s.case.evaluator_requirements
    }
    assert scripted_tagged == set(SCRIPTED_PROPOSALS)
    assert scripted_runner_for("creation_001_explicit_scoped_preference") is None


# --- Local availability behavior ------------------------------------------------------


def test_unavailable_mode_falls_back_with_zero_invocations():
    adapter = ExperienceOSLocalAdapter(mode="unavailable")
    turns = drive(
        adapter, simple_case(), ["I prefer aisle seats for work trips."]
    )
    turn = turns[0]
    assert turn.fallbacks[0].reason == "model_unavailable"
    assert turn.proposals[0].decision_source == "fallback"
    assert adapter.local_model_invocation_count == 0
    assert adapter.diagnostics["real_model_used"] is False
    # Case 3/5 separation: the fallback still produced a correct create.
    assert turn.applied_actions[0].action == "create"


def test_requires_local_model_cases_skip_safely(dataset):
    for sid in (
        "containment_005_one_sentence_supersession_local",
        "containment_006_vague_forget_safe",
    ):
        result = run_adapter_case(
            ExperienceOSLocalAdapter(mode="scripted"), scenario(dataset, sid)
        )
        assert result.status == CaseStatus.SKIPPED
        assert "requires_local_model" in result.skip_reason
        assert result.local_model_invocation_count == 0
        assert result.turns == []


def test_real_mode_without_configuration_degrades_safely(monkeypatch):
    monkeypatch.delenv("EXPERIENCEOS_LOCAL_MODEL_PATH", raising=False)
    adapter = ExperienceOSLocalAdapter(mode="real")
    turns = drive(
        adapter, simple_case(), ["I prefer aisle seats for work trips."]
    )
    assert adapter.diagnostics["real_model_used"] is False
    assert adapter.diagnostics["local_model_name"] is None
    assert adapter.local_model_invocation_count == 0
    assert turns[0].fallbacks  # real fallback path, clearly recorded


def test_no_personal_paths_in_emitted_evidence(dataset, scripted_results):
    for result in scripted_results.values():
        body = json.dumps(result.to_payload())
        for marker in ("/Users/", "/home/", "\\Users\\"):
            assert marker not in body


# --- Dataset compatibility ---------------------------------------------------------


def test_rules_adapter_compatible_with_all_40(dataset):
    manifest = load_manifest()
    assert manifest["manifest_hash"] == MANIFEST_HASH
    completed = skipped = 0
    for loaded in dataset:
        result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
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
    assert (completed, skipped) == (38, 2)


def test_local_adapter_compatible_with_all_40(dataset):
    completed = skipped = 0
    for loaded in dataset:
        result = run_adapter_case(
            ExperienceOSLocalAdapter(mode="scripted"), loaded
        )
        validate_case_result(result)
        if result.status == CaseStatus.SKIPPED:
            skipped += 1
            continue
        completed += 1
        # Fallback output is never labeled local-model success.
        for turn in result.turns:
            for proposal in turn.proposals:
                assert proposal.decision_source in (
                    "local_model",
                    "fallback",
                    "rule_based",
                )
        if result.diagnostics["local_mode"] == "unavailable_fallback":
            for turn in result.turns:
                for proposal in turn.proposals:
                    assert proposal.decision_source == "fallback"
    assert (completed, skipped) == (38, 2)


def test_repeated_runs_structurally_deterministic(dataset):
    loaded = scenario(dataset, "updates_005_instead_of_wording")
    views = []
    for _ in range(2):
        result = run_adapter_case(ExperienceOSRulesAdapter(), loaded)
        views.append(normalized(result.to_payload()))
    assert views[0] == views[1]
