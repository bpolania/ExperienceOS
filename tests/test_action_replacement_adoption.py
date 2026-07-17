"""Adoption gate re-evaluation bound to frozen definitions and evidence.

The classification must follow the frozen gate rules, not narrative:
Gate 1 uses the overall duplicate metric under its frozen threshold and
cannot pass from class-specific improvement alone; a failed quality gate
yields candidate-only, not adopted. Frozen gate definitions and evidence
are unchanged.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from benchmarks.action_replacement import artifacts
from benchmarks.action_replacement.adoption import (
    TRANSITION_PATH_CANDIDATE_ONLY,
    evaluate,
)
from benchmarks.contract.serialization import canonical_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
FROZEN = ROOT / "benchmarks/results/committed/report-transition-verification"
ADOPTION_DIR = ROOT / "benchmarks/results/committed/action-replacement-adoption"
ADOPTION_REPORT_DIR = (
    ROOT / "benchmarks/results/committed/report-action-replacement-adoption"
)


@pytest.fixture(scope="module")
def evaluation():
    return evaluate()


# --- Gate 1 -----------------------------------------------------------------


def test_gate1_uses_frozen_overall_metric_and_fails(evaluation) -> None:
    g1 = evaluation["gate1"]
    frozen = {g["gate"]: g for g in
              json.loads((FROZEN / "gate_summary.json").read_text())["gates"]}[1]
    # Bound to the frozen definition and threshold.
    assert g1["name"] == frozen["name"]
    assert g1["threshold"] == frozen["threshold"]
    assert g1["reference"] == int(frozen["reference"])  # 0
    # Overall replacement duplicate pairs = 4; not strictly fewer than 0.
    assert g1["replacement"] == 4
    assert g1["replacement_decision"] == "fail"


def test_gate1_reports_class_and_residual_separately(evaluation) -> None:
    g1 = evaluation["gate1"]
    # The supersede-bearing class is eliminated, reported separately, and
    # does NOT flip the overall gate.
    assert g1["supersede_bearing"]["append"] == 6
    assert g1["supersede_bearing"]["replacement"] == 0
    assert g1["supersede_bearing"]["eliminated_for_class"] is True
    assert g1["pure_create_residual"] == 4
    assert g1["replacement_decision"] == "fail"


def test_gate1_cannot_pass_from_class_improvement_alone(evaluation) -> None:
    # Even though the class is eliminated, the classification is not adopted.
    assert evaluation["classification_inputs"]["gate1_pass"] is False


# --- Gate 6 -----------------------------------------------------------------


def test_gate6_remains_inconclusive_non_blocking(evaluation) -> None:
    g6 = evaluation["gate6"]
    assert g6["blocking"] is False
    assert g6["replacement_decision"] == "inconclusive"


# --- twenty gates & blocking ------------------------------------------------


def test_all_twenty_gates_present_with_unchanged_numbering(evaluation) -> None:
    gates = evaluation["gates"]
    assert len(gates) == 20
    assert sorted(g["gate"] for g in gates) == list(range(1, 21))
    # Blocking flags unchanged from the frozen framework.
    frozen = {g["gate"]: g["blocking"]
              for g in json.loads((FROZEN / "gate_summary.json").read_text())["gates"]}
    for g in gates:
        assert g["blocking"] == frozen[g["gate"]]


def test_tally_matches_individual_results(evaluation) -> None:
    t = evaluation["tally"]
    gates = evaluation["gates"]
    assert t["passed"] == sum(1 for g in gates if g["replacement_decision"] == "pass")
    assert t["failed"] == sum(1 for g in gates if g["replacement_decision"] == "fail")
    assert t["inconclusive"] == sum(
        1 for g in gates if g["replacement_decision"] == "inconclusive"
    )
    assert (t["passed"], t["failed"], t["inconclusive"]) == (18, 1, 1)


def test_nine_blocking_gates_all_pass(evaluation) -> None:
    b = evaluation["blocking_gates"]
    assert b["numbers"] == [4, 5, 8, 9, 10, 11, 12, 19, 20]
    assert b["all_pass"] is True
    assert b["any_inconclusive"] is False


# --- additional conditions --------------------------------------------------


def test_additional_conditions_all_pass(evaluation) -> None:
    conditions = evaluation["additional_conditions"]
    assert conditions  # non-empty
    assert all(v == "pass" for v in conditions.values())
    assert evaluation["additional_conditions_all_pass"] is True


# --- classification ---------------------------------------------------------


def test_classification_is_candidate_only(evaluation) -> None:
    assert evaluation["classification"] == TRANSITION_PATH_CANDIDATE_ONLY
    assert evaluation["canonical_controller"] == "none"
    assert evaluation["runtime_default"] == "disabled"


def test_adopted_requires_gate1_pass(evaluation) -> None:
    # The classification rule: gate1 fail -> not adopted, even with all
    # blocking gates and all conditions passing.
    ci = evaluation["classification_inputs"]
    assert ci["all_blocking_pass"] is True
    assert ci["all_conditions_pass"] is True
    assert ci["safety_regression"] is False
    assert ci["gate1_pass"] is False
    assert evaluation["classification"] == TRANSITION_PATH_CANDIDATE_ONLY


# --- artifacts & determinism ------------------------------------------------


def test_committed_classification_matches_live(evaluation) -> None:
    committed = json.loads((ADOPTION_DIR / "classification.json").read_text())
    assert committed["classification"] == evaluation["classification"]
    committed_report = json.loads((ADOPTION_REPORT_DIR / "report.json").read_text())
    assert committed_report["classification"] == evaluation["classification"]
    assert committed_report["tally"] == evaluation["tally"]


def test_adoption_artifacts_validate() -> None:
    assert artifacts.validate(ADOPTION_DIR)
    assert artifacts.validate(ADOPTION_REPORT_DIR)


def test_adoption_evaluation_is_deterministic() -> None:
    assert canonical_json(evaluate()) == canonical_json(evaluate())


def test_manifest_binds_frozen_references() -> None:
    manifest = json.loads((ADOPTION_DIR / "manifest.json").read_text())
    refs = manifest["frozen_references"]
    # The frozen gate summary is referenced by digest, never rewritten.
    frozen_digest = artifacts._file_digest(FROZEN / "gate_summary.json")
    assert refs["frozen_gate_summary_digest"] == frozen_digest


def test_systems_json_lists_reserved_ids(evaluation) -> None:
    systems = json.loads((ADOPTION_DIR / "systems.json").read_text())["systems"]
    ids = {s["system_id"] for s in systems}
    assert "experienceos_action_replacement_adopted_v1" in ids
    assert "experienceos_action_replacement_shadow_v1" in ids
    assert "experienceos_action_replacement_ablation_no_replacement_v1" in ids
    # The adopted-infrastructure system is labeled benchmark/test-only.
    adopted = next(
        s for s in systems
        if s["system_id"] == "experienceos_action_replacement_adopted_v1"
    )
    assert "infrastructure" in adopted["note"].lower()
