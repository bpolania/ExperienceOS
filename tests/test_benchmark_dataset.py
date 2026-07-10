"""Lifecycle benchmark dataset tests: coverage and validator behavior.

Everything here runs offline: no network, no credentials, no local
model, no downloads. The committed dataset and manifest are the
objects under test.
"""

import copy
import json

import pytest

from benchmarks.contract import InvalidBenchmarkCase, case_from_dict
from benchmarks.scenarios.loader import (
    DATASET_VERSION,
    GROUP_ALLOCATION,
    GROUP_ORDER,
    DatasetError,
    LoadedScenario,
    canonical_scenario_files,
    load_dataset,
    load_manifest,
)
from benchmarks.scenarios.validate import (
    validate_dataset,
    validate_group_allocation,
    validate_hashes,
    validate_manifest_structure,
    validate_oracle,
)

EXPECTED_TOTAL = 40


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def scenarios(manifest):
    return load_dataset(manifest)


@pytest.fixture(scope="module")
def summary():
    return validate_dataset()


def mutated(scenario, **case_overrides):
    """Rebuild a LoadedScenario from mutated raw case data."""
    data = json.loads(scenario.path.read_text())
    data.update(case_overrides)
    return LoadedScenario(
        case=case_from_dict(data),
        group=scenario.group,
        path=scenario.path,
        entry=scenario.entry,
    )


def by_id(scenarios, scenario_id):
    return next(
        s for s in scenarios if s.case.scenario_id == scenario_id
    )


# --- Dataset coverage ---------------------------------------------------------


def test_full_dataset_validates(summary):
    assert summary["total_scenarios"] == EXPECTED_TOTAL
    assert summary["dataset_version"] == DATASET_VERSION


def test_all_manifest_scenarios_load(scenarios):
    assert len(scenarios) == EXPECTED_TOTAL
    for scenario in scenarios:
        assert scenario.case.scenario_id


def test_manifest_hash_and_order_are_stable(manifest, scenarios):
    # Re-loading and re-validating reproduces the committed hash.
    validate_hashes(manifest, scenarios)
    ids = [s.case.scenario_id for s in scenarios]
    assert ids == sorted(
        ids,
        key=lambda i: (
            GROUP_ORDER.index(by_id(scenarios, i).group),
            i,
        ),
    )


def test_scenario_ids_and_paths_unique(manifest):
    ids = [e["scenario_id"] for e in manifest["scenarios"]]
    paths = [e["path"] for e in manifest["scenarios"]]
    assert len(set(ids)) == EXPECTED_TOTAL
    assert len(set(paths)) == EXPECTED_TOTAL


def test_group_allocation_matches_committed_target(summary):
    assert summary["group_counts"] == GROUP_ALLOCATION


def test_no_canonical_file_missing_from_manifest(manifest):
    on_disk = len(canonical_scenario_files())
    assert on_disk == len(manifest["scenarios"]) == EXPECTED_TOTAL


def test_required_scenario_patterns_present(scenarios):
    all_tags = {t for s in scenarios for t in s.case.tags}
    for required in (
        "duplicate",
        "paraphrase",
        "supersession",
        "scope",
        "chain",
        "distractor",
        "forget",
        "preservation",
        "resurrection",
        "stale-leakage",
        "forgotten-leakage",
        "abstention",
        "lexical-mismatch",
        "no-memory-needed",
        "budget",
        "compression",
        "efficiency",
        "containment",
        "fallback",
        "vague-reference",
        "one-sentence-supersession",
        "phase7",
    ):
        assert required in all_tags, f"missing required pattern tag {required}"


def test_domain_diversity_and_travel_share(scenarios):
    domains = {}
    for scenario in scenarios:
        domain = next(
            t.removeprefix("domain:")
            for t in scenario.case.tags
            if t.startswith("domain:")
        )
        domains.setdefault(domain, []).append(scenario.case.scenario_id)
    travel = len(domains.get("travel", []))
    assert travel <= EXPECTED_TOTAL // 3, (
        f"too travel-centered: {travel}/{EXPECTED_TOTAL}"
    )
    non_travel_domains = set(domains) - {"travel"}
    assert len(non_travel_domains) >= 5, sorted(non_travel_domains)


def test_every_scenario_declares_mode_seed_and_budget(scenarios):
    seeds = set()
    for scenario in scenarios:
        case = scenario.case
        assert case.evaluation_mode in ("deterministic", "model_scored")
        assert isinstance(case.seed, int)
        assert case.context_budget > 0
        seeds.add(case.seed)
    assert len(seeds) == EXPECTED_TOTAL  # fixed, distinct seeds


def test_optional_modes_are_explicit_and_bounded(scenarios):
    local = [s for s in scenarios if s.case.requires_local_model]
    provider = [s for s in scenarios if s.case.requires_provider]
    scored = [s for s in scenarios if s.case.evaluation_mode == "model_scored"]
    assert 1 <= len(local) <= 4
    assert 1 <= len(provider) <= 4
    assert all("local-model-behavior" in s.case.tags for s in local)
    assert all(s.case.requires_provider for s in scored)
    deterministic = EXPECTED_TOTAL - len(scored)
    assert deterministic >= 35  # the default dataset is offline-capable


def test_create_oracles_declare_kind(scenarios):
    for scenario in scenarios:
        for action in scenario.case.expected.memory_actions:
            if action.action == "create":
                assert action.kind is not None, scenario.case.scenario_id


def test_update_and_forget_oracles_declare_targets(scenarios):
    for scenario in scenarios:
        for action in scenario.case.expected.memory_actions:
            if action.action in ("supersede", "forget"):
                assert action.target is not None, scenario.case.scenario_id


def test_leakage_scenarios_carry_forbidden_constraints(scenarios):
    flagged = [
        s
        for s in scenarios
        if {"stale-leakage", "forgotten-leakage"} & set(s.case.tags)
    ]
    assert flagged
    for scenario in flagged:
        response = scenario.case.expected.response
        assert response is not None and response.must_exclude, (
            scenario.case.scenario_id
        )


def test_abstention_scenarios_declare_abstention(scenarios):
    abstentions = [s for s in scenarios if s.case.category == "abstention"]
    assert abstentions
    for scenario in abstentions:
        assert scenario.case.expected.response.expect_abstention


def test_duplicate_cases_reference_existing_logical_memory(scenarios):
    for sid in (
        "creation_005_exact_duplicate_restatement",
        "creation_006_paraphrased_duplicate",
    ):
        scenario = by_id(scenarios, sid)
        expected = scenario.case.expected
        assert expected.final_state_exact
        assert len(expected.active) == 1  # exactly one memory for the slot


def test_containment_cases_separate_proposal_from_state(scenarios):
    contained = [s for s in scenarios if s.group == "containment"]
    assert len(contained) == 6
    rejections = [
        s for s in contained if s.case.expected.rejection_reasons
    ]
    # Rejection cases assert a CLEAN final state alongside the rejection.
    for scenario in rejections:
        assert scenario.case.expected.active, scenario.case.scenario_id
        assert scenario.case.expected.final_state_exact
    fallback = by_id(contained, "containment_004_malformed_proposal_fallback")
    assert fallback.case.expected.fallback_expected
    assert fallback.case.expected.active  # fallback still ends correct


def test_phase7_findings_are_encoded(scenarios):
    tagged = {
        s.case.scenario_id for s in scenarios if "phase7" in s.case.tags
    }
    assert {
        "creation_001_explicit_scoped_preference",
        "updates_004_now_prefer_wording",
        "updates_005_instead_of_wording",
        "forgetting_001_exact_forget",
        "containment_001_duplicate_create_contained",
        "containment_005_one_sentence_supersession_local",
        "containment_006_vague_forget_safe",
    } <= tagged


def test_no_scenario_contains_secrets_or_personal_paths(scenarios):
    for scenario in scenarios:
        body = scenario.path.read_text()
        for marker in ("/Users/", "/home/", "api_key", "sk-", "Bearer "):
            assert marker not in body, (
                f"{scenario.case.scenario_id} contains {marker!r}"
            )


# --- Validator failure modes ---------------------------------------------------


def test_duplicate_scenario_id_rejected(manifest):
    broken = copy.deepcopy(manifest)
    broken["scenarios"][1]["scenario_id"] = broken["scenarios"][0][
        "scenario_id"
    ]
    with pytest.raises(DatasetError) as excinfo:
        validate_manifest_structure(broken)
    assert "duplicate scenario IDs" in str(excinfo.value)


def test_unstable_manifest_order_rejected(manifest):
    broken = copy.deepcopy(manifest)
    broken["scenarios"][0], broken["scenarios"][-1] = (
        broken["scenarios"][-1],
        broken["scenarios"][0],
    )
    with pytest.raises(DatasetError) as excinfo:
        validate_manifest_structure(broken)
    assert "order" in str(excinfo.value)


def test_category_count_drift_rejected(manifest):
    broken = copy.deepcopy(manifest)
    broken["group_allocation"] = dict(
        broken["group_allocation"], creation=7
    )
    with pytest.raises(DatasetError) as excinfo:
        validate_manifest_structure(broken)
    assert "allocation" in str(excinfo.value)


def test_malformed_manifest_rejected(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text('{"suite_name": "x"}')
    with pytest.raises(DatasetError) as excinfo:
        load_manifest(bad)
    assert "missing required field" in str(excinfo.value)


def test_hash_mismatch_rejected(manifest, scenarios):
    broken = copy.deepcopy(manifest)
    broken["scenarios"][0]["content_hash"] = "0" * 64
    broken_scenarios = [
        LoadedScenario(s.case, s.group, s.path, e)
        for s, e in zip(scenarios, broken["scenarios"])
    ]
    with pytest.raises(DatasetError) as excinfo:
        validate_hashes(broken, broken_scenarios)
    assert "hash mismatch" in str(excinfo.value)
    assert broken["scenarios"][0]["scenario_id"] in str(excinfo.value)


def test_group_category_mismatch_rejected(scenarios):
    scenario = by_id(scenarios, "creation_001_explicit_scoped_preference")
    broken = mutated(scenario, category="retrieval")
    with pytest.raises(DatasetError) as excinfo:
        validate_group_allocation(
            [broken if s is scenario else s for s in scenarios]
        )
    assert "not allowed in group" in str(excinfo.value)


def test_active_and_forgotten_overlap_rejected(scenarios):
    scenario = by_id(scenarios, "forgetting_001_exact_forget")
    data = json.loads(scenario.path.read_text())
    data["expected"]["active"] = data["expected"]["forgotten"]
    broken = LoadedScenario(
        case_from_dict(data), scenario.group, scenario.path, scenario.entry
    )
    with pytest.raises(DatasetError) as excinfo:
        validate_oracle(broken)
    assert "both active and forgotten" in str(excinfo.value)


def test_selected_absent_from_candidates_rejected(scenarios):
    scenario = by_id(scenarios, "context_005_active_and_inactive_versions")
    data = json.loads(scenario.path.read_text())
    data["expected"]["selected"] = [
        {"logical_id": "not.a.candidate", "match_terms": ["x"], "memory_id": None}
    ]
    broken = LoadedScenario(
        case_from_dict(data), scenario.group, scenario.path, scenario.entry
    )
    with pytest.raises(DatasetError) as excinfo:
        validate_oracle(broken)
    assert "missing from retrieval candidates" in str(excinfo.value)


def test_leakage_case_without_forbidden_constraint_rejected(scenarios):
    scenario = by_id(scenarios, "retrieval_008_stale_would_mislead")
    data = json.loads(scenario.path.read_text())
    data["expected"]["response"] = None
    broken = LoadedScenario(
        case_from_dict(data), scenario.group, scenario.path, scenario.entry
    )
    with pytest.raises(DatasetError) as excinfo:
        validate_oracle(broken)
    assert "forbidden response constraints" in str(excinfo.value)


def test_local_model_case_without_flag_rejected(scenarios):
    scenario = by_id(scenarios, "containment_006_vague_forget_safe")
    broken = mutated(scenario, requires_local_model=False)
    with pytest.raises(DatasetError) as excinfo:
        validate_oracle(broken)
    assert "requires_local_model" in str(excinfo.value)


def test_model_scored_without_provider_rejected(scenarios):
    scenario = by_id(scenarios, "retrieval_007_correct_abstention")
    broken = mutated(scenario, requires_provider=False)
    with pytest.raises(DatasetError) as excinfo:
        validate_oracle(broken)
    assert "requires_provider" in str(excinfo.value)


def test_selection_k_exceeding_budget_rejected(scenarios):
    scenario = by_id(scenarios, "creation_001_explicit_scoped_preference")
    broken = mutated(scenario, selection_k=9)
    with pytest.raises(DatasetError) as excinfo:
        validate_oracle(broken)
    assert "exceeds context_budget" in str(excinfo.value)


def test_zero_or_negative_context_budget_rejected(scenarios):
    scenario = by_id(scenarios, "creation_001_explicit_scoped_preference")
    data = json.loads(scenario.path.read_text())
    data["context_budget"] = 0
    with pytest.raises(InvalidBenchmarkCase):
        case_from_dict(data)


def test_missing_supersede_target_rejected(scenarios):
    scenario = by_id(scenarios, "updates_001_preference_replacement_cross_session")
    data = json.loads(scenario.path.read_text())
    data["expected"]["memory_actions"][0]["target"] = None
    with pytest.raises(InvalidBenchmarkCase):
        case_from_dict(data)


def test_unresolved_logical_reference_rejected(scenarios):
    scenario = by_id(scenarios, "creation_001_explicit_scoped_preference")
    data = json.loads(scenario.path.read_text())
    data["expected"]["active"] = [
        {"logical_id": "dangling", "match_terms": [], "memory_id": None}
    ]
    with pytest.raises(InvalidBenchmarkCase):
        case_from_dict(data)
