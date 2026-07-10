"""Runner behavior tests: ordering, isolation, failure handling,
profiles, and full-dataset compatibility. All offline."""

import json

import pytest

from benchmarks.contract import SystemId
from benchmarks.runner.cli import main as cli_main
from benchmarks.runner.config import (
    QUICK_PROFILE_SCENARIOS,
    RunConfig,
    profile_config,
)
from benchmarks.runner.execute import build_provenance, execute_run
from benchmarks.scenarios.loader import load_manifest

MANIFEST_HASH = (
    "0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb"
)

ALL_SYSTEMS = (
    SystemId.STATELESS,
    SystemId.FULL_HISTORY,
    SystemId.APPEND_ONLY,
    SystemId.NAIVE_TOP_K,
    SystemId.EXPERIENCEOS_RULES,
    SystemId.EXPERIENCEOS_LOCAL,
)


@pytest.fixture(scope="module")
def quick_output(tmp_path_factory):
    config = profile_config(
        "quick", str(tmp_path_factory.mktemp("quick") / "run")
    )
    return execute_run(config)


@pytest.fixture(scope="module")
def full_output(tmp_path_factory):
    config = profile_config(
        "full-offline", str(tmp_path_factory.mktemp("full") / "run")
    )
    return execute_run(config)


def test_quick_profile_is_committed_and_ordered(quick_output):
    assert len(QUICK_PROFILE_SCENARIOS) == 14
    executed = [
        e["scenario_id"]
        for e in quick_output.execution_order
        if e["system_id"] == SystemId.STATELESS
    ]
    assert executed == list(QUICK_PROFILE_SCENARIOS)
    # Coverage groups present, including known hard cases.
    assert "creation_006_paraphrased_duplicate" in QUICK_PROFILE_SCENARIOS
    assert "retrieval_003_lexical_mismatch" in QUICK_PROFILE_SCENARIOS
    assert "context_003_redundant_compression" in QUICK_PROFILE_SCENARIOS


def test_full_profile_uses_manifest_order(full_output):
    manifest = load_manifest()
    assert manifest["manifest_hash"] == MANIFEST_HASH
    expected = [e["scenario_id"] for e in manifest["scenarios"]]
    for system in ALL_SYSTEMS:
        executed = [
            e["scenario_id"]
            for e in full_output.execution_order
            if e["system_id"] == system
        ]
        assert executed == expected


def test_all_six_systems_execute(full_output):
    systems = {e["system_id"] for e in full_output.execution_order}
    assert systems == set(ALL_SYSTEMS)
    assert len(full_output.execution_order) == 240


def test_full_run_counts(full_output):
    outcomes = {}
    for entry in full_output.execution_order:
        outcomes[entry["outcome"]] = outcomes.get(entry["outcome"], 0) + 1
    assert outcomes["skipped"] == 12  # 2 local cases x 6 systems
    assert outcomes.get("execution_failed", 0) == 0
    assert not full_output.failures["system_execution_failures"]
    assert not full_output.failures["evaluator_failures"]
    # Deferred evaluations are recorded, not hidden.
    assert len(full_output.failures["deferred_evaluations"]) == 12


def test_skips_and_deferrals_carry_reasons(full_output):
    for skip in full_output.failures["skipped_cases"]:
        assert "requires_local_model" in skip["reason"]
    for deferral in full_output.failures["deferred_evaluations"]:
        assert "deferred" in deferral["reason"]


def test_low_scores_do_not_fail_the_command(tmp_path):
    exit_code = cli_main(
        [
            "run",
            "--profile",
            "quick",
            "--output",
            str(tmp_path / "run"),
        ]
    )
    assert exit_code == 0  # plenty of failed cases, zero exec failures


def test_overwrite_protection(tmp_path):
    output = tmp_path / "run"
    assert cli_main(["run", "--profile", "quick", "--output", str(output)]) == 0
    with pytest.raises(FileExistsError):
        cli_main(["run", "--profile", "quick", "--output", str(output)])
    assert (
        cli_main(
            [
                "run",
                "--profile",
                "quick",
                "--output",
                str(output),
                "--overwrite",
            ]
        )
        == 0
    )


def test_optional_profiles_are_configuration_only(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        profile_config("qwen", str(tmp_path))
    assert "configuration-only" in str(excinfo.value)
    with pytest.raises(ValueError):
        profile_config("nonsense", str(tmp_path))


def test_unknown_scenario_in_config_rejected(tmp_path):
    config = RunConfig(
        profile="quick",
        output_dir=str(tmp_path),
        scenario_ids=("does_not_exist",),
    )
    with pytest.raises(ValueError) as excinfo:
        execute_run(config)
    assert "unknown scenarios" in str(excinfo.value)


def test_provenance_is_complete_and_safe(quick_output):
    provenance = build_provenance(quick_output)
    payload = provenance.to_payload()
    assert payload["manifest_hash"] == MANIFEST_HASH
    assert payload["used_real_provider"] is False
    assert payload["used_real_local_model"] is False
    assert payload["used_mock"] is True
    assert payload["used_fallback"] is True  # scripted/unavailable local
    assert payload["local_model_name"] == "scripted-local-proposals"
    assert payload["executed_cases"] == 84
    body = json.dumps(payload)
    assert "/Users/" not in body


def test_state_isolated_across_case_runs(quick_output):
    # No cross-scenario or cross-system leakage: stateless never holds
    # state; the non-durable scenario ends empty for every memory
    # system even though earlier scenarios created memories.
    for run in quick_output.case_runs:
        if run.system_id == "stateless":
            assert run.result.final_active == []
        if run.scenario_id == "creation_004_non_durable_statement":
            assert run.result.final_active == [], run.system_id
        if (
            run.scenario_id == "creation_001_explicit_scoped_preference"
            and run.system_id == "append_only"
        ):
            assert len(run.result.final_active) == 1


def test_contributions_reference_known_metrics(quick_output):
    from benchmarks.contract import metric

    for run in quick_output.case_runs:
        for c in run.evaluation.contributions:
            metric(c.metric)  # raises on unknown


def test_fail_fast_false_preserves_later_cases(monkeypatch, tmp_path):
    from benchmarks.runner import execute as execute_module

    real = execute_module._run_one
    calls = {"n": 0}

    def flaky(system_id, scenario, config):
        calls["n"] += 1
        result = real(system_id, scenario, config)
        if calls["n"] == 1:
            result.status = "partial"
            result.failure_reason = "injected failure"
            result.turns = []
        return result

    monkeypatch.setattr(execute_module, "_run_one", flaky)
    config = RunConfig(
        profile="quick",
        output_dir=str(tmp_path / "run"),
        scenario_ids=QUICK_PROFILE_SCENARIOS[:3],
        systems=(SystemId.STATELESS,),
    )
    output = execute_module.execute_run(config)
    assert len(output.execution_order) == 3  # later cases still ran
    assert output.execution_order[0]["outcome"] == "execution_failed"
    assert output.failures["system_execution_failures"]
