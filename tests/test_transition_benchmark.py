"""Transition benchmark: registry, isolation, metrics, gates, artifacts.

All deterministic and offline: mock provider only, no model, no network,
no credentials, and no change to any runtime default.
"""

import json
from pathlib import Path

import pytest

from benchmarks.annotations import transition_verification as tv
from benchmarks.transition_benchmark import artifacts as artifact_module
from benchmarks.transition_benchmark import gates as gate_module
from benchmarks.transition_benchmark.runner import evaluate, run
from benchmarks.transition_benchmark.systems import (
    ADOPTED_ID,
    CANDIDATE_ID,
    LEARNED_ID,
    QWEN_ID,
    REFERENCE_ID,
    RULES_ID,
    SHADOW_ID,
    registry,
    run_case,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def benchmark():
    data = run(include_ablations=True)
    return data, evaluate(data)


def _record(source_case_id):
    corpus = tv.load_corpus()
    for partition in ("historical_scored", "development_fixtures"):
        for record in corpus[partition]:
            if record["source_case_id"] == source_case_id:
                return record
    raise AssertionError(source_case_id)


# --- Registry -----------------------------------------------------------------


def test_registry_contains_every_reserved_system_id():
    ids = [s.system_id for s in registry()]
    assert set(ids) == {
        REFERENCE_ID, SHADOW_ID, CANDIDATE_ID, RULES_ID, ADOPTED_ID,
        LEARNED_ID, QWEN_ID,
    }
    assert len(ids) == len(set(ids))


def test_adopted_system_is_not_a_default_anywhere():
    from experienceos import ExperienceOS
    from experienceos.memory.transition_integration import (
        TransitionIntegrationConfig,
    )
    from experienceos.providers import MockProvider

    assert TransitionIntegrationConfig().mode == "disabled"
    assert ExperienceOS(model=MockProvider()).transition_coordinator is None
    adopted = next(s for s in registry() if s.system_id == ADOPTED_ID)
    assert adopted.mode == "adopted"
    # Reachable only from the benchmark, never from default construction.
    assert adopted.kind == "transition"


def test_optional_systems_report_unavailable_with_a_reason():
    optional = [s for s in registry() if s.kind == "optional"]
    assert len(optional) == 2
    for system in optional:
        assert system.available is False
        assert system.unavailable_reason


# --- Corpus and isolation -----------------------------------------------------


def test_partitions_are_loaded_separately_and_completely(benchmark):
    data, _ = benchmark
    assert data["partitions"]["historical_scored"]["records"] == 28
    assert data["partitions"]["development_fixtures"]["records"] == 27
    assert len(data["unresolved"]) == 13


def test_corpus_manifest_unchanged_by_the_benchmark(benchmark):
    assert tv.verify_manifest() is True


def test_each_system_runs_against_an_isolated_store():
    record = _record("direct_replacement-01")
    systems = [s for s in registry() if s.available]
    first = run_case(systems[0], record)
    second = run_case(systems[0], record)
    # A repeated run cannot see the previous run's state.
    assert first.active_ids == second.active_ids
    assert first.created_count == second.created_count


def test_reference_and_transition_systems_see_the_same_before_state():
    record = _record("direct_replacement-01")
    seeded = {
        m["memory_ref"]["logical_id"] for m in record["before_state"]
    }
    for system in registry():
        if not system.available or system.system_id == RULES_ID:
            continue
        observation = run_case(system, record)
        assert set(observation.seeded_ids) == seeded


def test_the_oracle_never_reaches_the_controller():
    import inspect

    from benchmarks.transition_benchmark import systems

    source = inspect.getsource(systems)
    # The runner may score with the oracle; the system adapters must not
    # read it when producing output.
    assert "expected_transition" not in source


def test_reference_level_is_labelled():
    levels = {s.system_id: s.reference_level for s in registry()}
    assert levels[REFERENCE_ID] == "full_composition"
    assert levels[RULES_ID] == "proposal_only"


# --- Measured results ---------------------------------------------------------


def test_reference_leaves_stale_active_pairs(benchmark):
    data, _ = benchmark
    reference = data["systems"][REFERENCE_ID]
    assert reference["lifecycle_actual"]["stale_pairs"] > 0
    assert reference["target"]["correct"] == 0


def test_transition_systems_classify_and_target_correctly(benchmark):
    data, _ = benchmark
    for system_id in (SHADOW_ID, CANDIDATE_ID, RULES_ID):
        metrics = data["systems"][system_id]
        assert metrics["classification"]["correct"] == 28
        assert metrics["target"]["wrong"] == 0


def test_non_mutating_systems_match_the_reference_state(benchmark):
    data, _ = benchmark
    reference = data["systems"][REFERENCE_ID]["lifecycle_actual"]
    for system_id in (SHADOW_ID, CANDIDATE_ID):
        actual = data["systems"][system_id]["lifecycle_actual"]
        assert actual["duplicate_pairs"] == reference["duplicate_pairs"]
        assert actual["stale_pairs"] == reference["stale_pairs"]
        assert actual["created"] == reference["created"]
        assert data["systems"][system_id]["actions_applied"] == 0


def test_adopted_reduces_stale_pairs_but_adds_duplicates(benchmark):
    # The decisive measured finding, pinned so it cannot regress silently.
    data, _ = benchmark
    reference = data["systems"][REFERENCE_ID]["lifecycle_actual"]
    adopted = data["systems"][ADOPTED_ID]["lifecycle_actual"]
    assert adopted["stale_pairs"] < reference["stale_pairs"]
    assert adopted["duplicate_pairs"] > reference["duplicate_pairs"]


def test_zero_tolerance_safety_metrics_are_all_zero(benchmark):
    data, _ = benchmark
    for key, value in data["safety"].items():
        assert value == 0, f"{key}={value}"


# --- Gates --------------------------------------------------------------------


def test_all_twenty_gates_are_evaluated(benchmark):
    _, result = benchmark
    numbers = [g["gate"] for g in result["gates"]]
    assert numbers == list(range(1, 21))


def test_every_gate_has_a_written_justification(benchmark):
    _, result = benchmark
    for gate in result["gates"]:
        assert gate["justification"].strip(), gate["gate"]
        assert gate["decision"] in (
            "pass", "fail", "inconclusive", "unavailable", "not_applicable"
        )
        assert gate["evidence"]


def test_deferred_and_fixed_gate_sets_match_the_contract():
    assert gate_module.DEFERRED_GATES == (1, 2, 3, 6, 13, 14)
    assert gate_module.FIXED_THRESHOLD_GATES == (
        4, 5, 8, 9, 10, 11, 15, 17, 18, 19, 20
    )
    assert gate_module.MATERIALITY_CASES == 1
    assert gate_module.MATERIALITY_RELATIVE == 0.02


def test_blocking_safety_gates_all_pass(benchmark):
    _, result = benchmark
    blocking = [g for g in result["gates"] if g["blocking"]]
    assert blocking
    for gate in blocking:
        assert gate["decision"] == "pass", gate["gate"]


def test_gate_one_fails_on_the_measured_duplicate_increase(benchmark):
    _, result = benchmark
    gate = result["gates"][0]
    assert gate["gate"] == 1
    assert gate["decision"] == "fail"
    assert "duplicate" in gate["justification"].lower()


def test_gate_six_is_inconclusive_rather_than_passed(benchmark):
    # Both reference and candidate already create 0 positive memories from
    # forget directives, so there is no reduction to demonstrate. The gate
    # asks for improvement, and absence of harm is not improvement.
    _, result = benchmark
    gate = result["gates"][5]
    assert gate["gate"] == 6
    assert gate["decision"] == "inconclusive"


def test_classification_is_deterministic_and_conservative(benchmark):
    _, result = benchmark
    assert result["classification"] == "TRANSITION_PATH_CANDIDATE_ONLY"
    assert result["rationale"]


def test_a_blocking_failure_would_disable_the_path():
    gates = [
        gate_module.GateResult(
            4, "Scoped coexistence is preserved", "gate", "0", gate_module.FAIL,
            blocking=True,
        )
    ]
    classification, _ = gate_module.classify(gates)
    assert classification == "TRANSITION_PATH_DISABLED"


def test_all_gates_passing_yields_eligible_but_not_enabled():
    gates = [
        gate_module.GateResult(n, f"g{n}", "gate", "0", gate_module.PASS)
        for n in range(1, 21)
    ]
    classification, rationale = gate_module.classify(gates)
    assert classification == "TRANSITION_PATH_ELIGIBLE_FOR_ADOPTION"
    assert "does not make" in rationale


# --- Ablations ----------------------------------------------------------------


def test_every_required_ablation_runs(benchmark):
    data, _ = benchmark
    ids = {a["ablation_id"] for a in data["ablations"]["ablations"]}
    assert {
        "exact_text_duplicate_only", "no_scope_awareness", "no_identity_layer",
        "proposal_without_verifier", "verifier_with_oracle_proposals",
        "update_only", "forget_only", "no_exact_authorization",
        "reference_planner_component", "full_transition_stack",
    } <= ids


def test_no_ablation_is_runtime_eligible_or_applies_actions(benchmark):
    data, _ = benchmark
    for ablation in data["ablations"]["ablations"]:
        assert ablation["runtime_eligible"] is False, ablation["ablation_id"]
        assert ablation["action_applied"] is False, ablation["ablation_id"]
    assert data["ablations"]["safety"]["runtime_eligible_ablations"] == 0
    assert data["ablations"]["safety"]["ablations_applying_actions"] == 0


def test_identity_ablation_shows_the_largest_contribution(benchmark):
    data, _ = benchmark
    by_id = {a["ablation_id"]: a for a in data["ablations"]["ablations"]}
    full = by_id["full_transition_stack"]["metrics"]["classification_correct"]
    no_identity = by_id["no_identity_layer"]["metrics"]["classification_correct"]
    no_scope = by_id["no_scope_awareness"]["metrics"]["classification_correct"]
    assert no_identity < no_scope < full


def test_authorization_ablation_rejects_every_mismatch(benchmark):
    data, _ = benchmark
    by_id = {a["ablation_id"]: a for a in data["ablations"]["ablations"]}
    ablation = by_id["no_exact_authorization"]
    assert ablation["metrics"]["rejected"] == ablation["metrics"]["attempted"]
    assert ablation["safety_failures"] == 0


def test_every_bound_authorization_field_fails_closed(benchmark):
    data, _ = benchmark
    authorization = data["authorization"]
    assert authorization["bound_fields"] == 20
    assert authorization["mismatches_rejected"] == authorization["mismatches_tested"]
    assert authorization["exact_match_accepted"] is True
    assert authorization["unauthorized_applications"] == 0


# --- Lifecycle and downstream -------------------------------------------------


def test_lifecycle_chain_is_evaluated_for_both_systems(benchmark):
    data, _ = benchmark
    lifecycle = data["lifecycle"]
    assert lifecycle["turns"] == 10
    assert set(lifecycle["systems"]) == {REFERENCE_ID, CANDIDATE_ID}
    for chain in lifecycle["systems"].values():
        assert len(chain["turns"]) == 10


def test_downstream_reports_unavailable_metrics_honestly(benchmark):
    data, _ = benchmark
    downstream = data["downstream"]
    for side in ("reference", "adopted"):
        assert downstream[side]["recall_at_1"] is None
        assert downstream[side]["mrr"] is None
        assert downstream[side]["unavailable_reason"]
        # No inactive memory reaches retrieval or selection.
        assert downstream[side]["inactive_retrieved"] == 0
        assert downstream[side]["inactive_selected"] == 0


# --- Artifacts ----------------------------------------------------------------


@pytest.mark.parametrize(
    "directory,required",
    [
        (
            "transition-verification",
            ("per-case.jsonl", "aggregate.json", "systems.json",
             "lifecycle-chains.jsonl", "downstream.json", "comparison.csv",
             "comparison.md", "adoption-gates.json", "manifest.json", "README.md"),
        ),
        (
            "transition-ablation",
            ("per-case.jsonl", "aggregate.json", "ablations.json",
             "contribution.csv", "contribution.md", "safety.json",
             "manifest.json", "README.md"),
        ),
        (
            "report-transition-verification",
            ("report_data.json", "headline_metrics.json", "gate_summary.json",
             "claims.json", "limitations.json", "artifact_index.json",
             "manifest.json", "README.md"),
        ),
    ],
)
def test_committed_artifact_families_are_complete(directory, required):
    path = REPO_ROOT / "benchmarks/results/committed" / directory
    assert path.is_dir()
    for name in required:
        assert (path / name).is_file(), f"{directory}/{name}"


@pytest.mark.parametrize(
    "directory",
    ["transition-verification", "transition-ablation", "report-transition-verification"],
)
def test_committed_artifacts_validate(directory):
    assert artifact_module.validate(
        REPO_ROOT / "benchmarks/results/committed" / directory
    )


def test_manifests_record_provenance_and_commands():
    for directory in (
        "transition-verification", "transition-ablation",
        "report-transition-verification",
    ):
        manifest = json.loads(
            (
                REPO_ROOT / "benchmarks/results/committed" / directory
                / "manifest.json"
            ).read_text()
        )
        assert manifest["schema_version"]
        assert manifest["benchmark_version"]
        assert manifest["contract_commit"]
        assert manifest["corpus_commit"]
        assert manifest["regeneration_command"]
        assert manifest["verification_command"]
        assert manifest["content_digest"]
        assert manifest["file_digests"]


def test_latency_is_excluded_from_committed_digests():
    directory = REPO_ROOT / "benchmarks/results/committed/transition-verification"
    manifest = json.loads((directory / "manifest.json").read_text())
    assert "latency.json" not in manifest["file_digests"]
    assert manifest["nondeterministic_files"] == ["latency.json"]
    assert (directory / "latency.json").is_file()
    # No deterministic artifact carries measured milliseconds.
    aggregate = json.loads((directory / "aggregate.json").read_text())
    for metrics in aggregate["systems"].values():
        assert "latency" not in metrics


def test_report_records_the_classification_and_the_failed_gate():
    report = (REPO_ROOT / "docs/transition_verification_report.md").read_text()
    assert "TRANSITION_PATH_CANDIDATE_ONLY" in report
    assert "does not change the runtime default" in report
    assert "Gate 1" in report
    # The decisive finding must be visible, not buried.
    assert "duplicate" in report.lower()


def test_claims_artifact_separates_supported_from_refuted():
    claims = json.loads(
        (
            REPO_ROOT
            / "benchmarks/results/committed/report-transition-verification/claims.json"
        ).read_text()
    )
    supported = {c["claim"] for c in claims["supported"]}
    unsupported = {c["claim"] for c in claims["unsupported"]}
    assert "canonical adoption" in unsupported
    assert "improved final answer quality" in unsupported
    assert any("duplicate prevention" in c for c in unsupported)
    assert supported


def test_limitations_artifact_names_the_real_limits():
    limitations = json.loads(
        (
            REPO_ROOT
            / "benchmarks/results/committed/report-transition-verification"
            / "limitations.json"
        ).read_text()
    )
    text = " ".join(limitations["limitations"])
    assert "corpus" in text
    assert "share domains" in text
    assert "Recall@K" in text


# --- Reproducibility and safety -----------------------------------------------


def test_benchmark_content_is_deterministic():
    first = run(include_ablations=False)
    second = run(include_ablations=False)
    assert artifact_module._digest(
        {"cases": first["per_case"], "aggregate": first["systems"]}
    ) == artifact_module._digest(
        {"cases": second["per_case"], "aggregate": second["systems"]}
    )


def test_per_case_records_carry_no_runtime_uuids(benchmark):
    data, _ = benchmark
    for row in data["per_case"]:
        for memory_id in row["observation"]["active_ids"]:
            # Created memories are labelled stably; a raw UUID would make
            # committed artifacts differ byte-for-byte between runs.
            assert "-" not in memory_id or memory_id.startswith("created:") or (
                memory_id.count("-") < 4
            )


def test_benchmark_constructs_no_provider_beyond_the_mock():
    import inspect

    from benchmarks.transition_benchmark import systems

    source = inspect.getsource(systems)
    assert "QwenCloud" not in source
    assert "LocalModel" not in source
    assert "MockProvider" in source


def test_benchmark_performs_no_network_access(monkeypatch):
    import socket

    def deny(*args, **kwargs):
        raise AssertionError("benchmark attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    record = _record("direct_replacement-01")
    system = next(s for s in registry() if s.system_id == CANDIDATE_ID)
    assert run_case(system, record).proposal_type == "supersede_existing"


def test_historical_committed_result_directories_are_untouched():
    # The three new families are additive; every pre-existing directory
    # must still exist unmodified (verified byte-wise in validation).
    committed = REPO_ROOT / "benchmarks/results/committed"
    for legacy in (
        "grounded-extraction", "grounded-extraction-ablation",
        "lifecycle-offline-v1", "lifecycle-v2-ablation",
        "longmemeval-50-subset-v1", "longmemeval-50-subset-v2",
        "phase11-retrieval-ablation", "phase11-semantic-retrieval",
        "report-grounded-extraction", "report-phase11", "report-v1", "report-v2",
    ):
        assert (committed / legacy).is_dir()
