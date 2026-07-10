"""Phase 9 experiment-contract integrity tests.

Narrow protections for the frozen Phase 8 boundary: immutable paths
exist, recorded hashes match, v1 system IDs remain registered, v2 IDs
cannot collide with v1, and v2 output roots cannot resolve into v1
artifact roots. Heavy digest verification stays with the existing
artifact validators (exercised by validate_demo.sh); these tests
guard the contract's declarations."""

import json
from pathlib import Path

from benchmarks.contract import KNOWN_SYSTEM_IDS, metric

CONTRACT_PATH = Path("benchmarks/contract/phase9_v2.json")


def contract():
    return json.loads(CONTRACT_PATH.read_text())


def test_contract_loads_with_version():
    data = contract()
    assert data["contract_version"] == "phase9-v2.1"
    assert data["verified_baseline"]["phase8_closure_commit"].startswith(
        "13ca2e8"
    )


def test_immutable_v1_paths_exist():
    data = contract()["frozen_v1"]
    for path in (
        data["lifecycle_dataset"]["scenario_root"],
        data["lifecycle_dataset"]["manifest"],
        data["external_subset"]["manifest"],
        data["artifacts"]["lifecycle"]["path"],
        data["artifacts"]["external"]["path"],
        data["artifacts"]["report"]["path"],
        data["artifacts"]["report"]["markdown"],
        data["report_spec"],
    ):
        assert Path(path).exists(), f"immutable v1 path missing: {path}"


def test_lifecycle_manifest_hash_matches_contract():
    data = contract()["frozen_v1"]["lifecycle_dataset"]
    manifest = json.loads(Path(data["manifest"]).read_text())
    assert manifest["manifest_hash"] == data["manifest_hash"]
    assert manifest["scenario_count"] == data["scenario_count"]


def test_external_manifest_hash_matches_contract():
    data = contract()["frozen_v1"]["external_subset"]
    manifest = json.loads(Path(data["manifest"]).read_text())
    assert manifest["manifest_hash"] == data["manifest_hash"]
    assert manifest["display_label"] == data["display_label"]
    assert manifest["source_revision"] == data["source_revision"]
    assert len(manifest["selected"]) == data["subset_size"]


def test_v1_artifact_digests_match_contract():
    data = contract()["frozen_v1"]["artifacts"]
    lifecycle = json.loads(
        (Path(data["lifecycle"]["path"]) / "artifact_manifest.json")
        .read_text()
    )
    assert lifecycle["normalized_result_digest"] == (
        data["lifecycle"]["normalized_digest"]
    )
    external = json.loads(
        (Path(data["external"]["path"]) / "artifact_manifest.json")
        .read_text()
    )
    assert external["normalized_result_digest"] == (
        data["external"]["normalized_digest"]
    )
    report = json.loads(
        (Path(data["report"]["path"]) / "artifact_manifest.json")
        .read_text()
    )
    assert report["report_data_digest"] == (
        data["report"]["report_data_digest"]
    )


def test_v1_system_ids_remain_registered():
    data = contract()["frozen_v1"]
    for system_id in data["system_ids"]:
        assert system_id in KNOWN_SYSTEM_IDS


def test_v2_ids_do_not_collide_with_v1():
    data = contract()
    v1 = set(data["frozen_v1"]["system_ids"])
    v2 = set(data["v2_system_ids"])
    assert not (v1 & v2)
    assert len(data["v2_system_ids"]) == len(v2)  # no duplicates
    assert all(system_id.endswith("_v2") for system_id in v2)


def test_v2_output_roots_disjoint_from_v1():
    data = contract()
    v1_roots = {
        Path(a["path"]).resolve()
        for a in data["frozen_v1"]["artifacts"].values()
    }
    for root in data["v2_output_roots"].values():
        resolved = Path(root).resolve()
        assert resolved not in v1_roots
        assert not any(
            v1_root == resolved or v1_root in resolved.parents
            for v1_root in v1_roots
        ), f"v2 root {root} resolves into a v1 artifact root"


def test_dev_fixture_root_separate_from_frozen_paths():
    data = contract()
    dev_root = Path(data["development_fixture_root"]).resolve()
    frozen = [
        Path(data["frozen_v1"]["lifecycle_dataset"]["scenario_root"]),
        Path("benchmarks/fixtures/contract"),
        *(Path(a["path"]) for a in data["frozen_v1"]["artifacts"].values()),
    ]
    for path in frozen:
        resolved = path.resolve()
        assert resolved != dev_root
        assert dev_root not in resolved.parents
        assert resolved not in dev_root.parents


def test_contract_v1_metric_references_are_valid():
    data = contract()
    lifecycle_metric_names = {
        "supersession_accuracy",
        "old_value_deactivation_rate",
        "conflicting_active_memory_rate",
        "stale_context_leakage_rate",
        "memory_creation_precision",
        "memory_creation_recall",
        "memory_creation_f1",
        "non_durable_rejection_rate",
        "recall_at_k",
        "mean_reciprocal_rank",
        "answers_per_1k_memory_tokens",
        "local_valid_proposal_rate",
        "local_correct_action_type_rate",
        "local_correct_target_rate",
        "fallback_rate",
        "local_applied_action_accuracy",
        "local_state_corruption_rate",
        "unrelated_preservation_rate",
        "selection_budget_adherence",
        "forget_detection_accuracy",
    }
    for name in lifecycle_metric_names:
        metric(name)  # raises on unknown / renamed v1 metric
    from benchmarks.external.longmemeval.evaluate import external_metric

    for name in (
        "answer_session_candidate_rate",
        "answer_session_selection_rate",
        "answer_session_mrr",
        "answer_context_presence_rate",
    ):
        external_metric(name)


def test_targets_carry_v1_raw_values():
    for target in contract()["targets"].values():
        assert "v1" in target and "direction" in target
        assert "/" in target["v1"] or "." in target["v1"]  # raw n/d kept
