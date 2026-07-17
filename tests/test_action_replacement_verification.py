"""Applied-state verification of governed replacement over the corpus.

These tests assert the *measured* duplicate reduction and preservation
properties, that the committed artifacts reproduce, and that the frozen
corpus is untouched. Failure paths (missing/mismatched authorization,
manager rejection, atomic sequence rejection, planner fallback) are
covered behaviorally in ``tests/test_action_replacement_integration.py``.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from benchmarks.action_replacement import artifacts
from benchmarks.action_replacement.verification import (
    PURE_CREATE,
    SUPERSEDE_BEARING,
    verify_all,
)
from benchmarks.contract.serialization import canonical_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "benchmarks/results/committed/action-replacement"
REPORT_DIR = ROOT / "benchmarks/results/committed/report-action-replacement"


@pytest.fixture(scope="module")
def data():
    return verify_all()


# --- measured duplicate reduction -------------------------------------------


def test_duplicate_pairs_reduced_10_to_4(data) -> None:
    s = data["summary"]
    assert s["append_duplicate_pairs_total"] == 10
    assert s["replacement_duplicate_pairs_total"] == 4
    assert s["duplicate_reduction"] == 6


def test_supersede_bearing_duplicates_eliminated(data) -> None:
    s = data["summary"]
    assert s["supersede_bearing_append_duplicates"] == 6
    assert s["supersede_bearing_replacement_duplicates"] == 0


def test_pure_create_residual_is_separate_and_unchanged(data) -> None:
    s = data["summary"]
    # The pure-create redundant class is out of scope and still present.
    assert s["pure_create_residual_duplicates"] == 4
    residual = [
        r for r in data["cases"]
        if r["transition_class"] == PURE_CREATE
        and r["replacement_duplicate_pairs"] > 0
    ]
    assert len(residual) == 4
    for r in residual:
        assert r["append_duplicate_pairs"] == r["replacement_duplicate_pairs"]


# --- applied-replacement correctness ----------------------------------------


def test_six_replacements_applied_with_lineage_and_no_loss(data) -> None:
    s = data["summary"]
    assert s["replacements_applied"] == 6
    assert s["planner_creates_suppressed"] == 6
    assert s["applied_lineage_correct"] == 6
    assert s["applied_lineage_broken"] == 0
    assert s["applied_seeded_memories_lost"] == 0
    assert s["applied_transition_create_present_once"] == 6


def test_every_applied_case_reports_action_replaced(data) -> None:
    applied = [r for r in data["cases"] if r["planner_suppressed"]]
    assert applied
    for r in applied:
        assert r["canonical_effect"] == "action_replaced"
        assert r["append_duplicate_pairs"] == 1
        assert r["replacement_duplicate_pairs"] == 0
        assert r["transition_create_count"] == 1
        assert r["lineage_ok"] is True
        assert r["seeded_non_target_lost"] == []


def test_no_applied_replacement_loses_a_seeded_memory(data) -> None:
    for r in data["cases"]:
        if r["planner_suppressed"]:
            assert r["seeded_non_target_lost"] == []


# --- artifact integrity ------------------------------------------------------


def test_committed_summary_matches_live_run(data) -> None:
    committed = json.loads((RESULT_DIR / "summary.json").read_text())
    assert committed == data["summary"]


def test_committed_results_match_live_run(data) -> None:
    committed = json.loads((RESULT_DIR / "results.json").read_text())
    assert committed == {"cases": data["cases"]}


def test_artifacts_validate() -> None:
    assert artifacts.validate(RESULT_DIR)
    assert artifacts.validate(REPORT_DIR)


def test_verification_is_deterministic() -> None:
    assert canonical_json(verify_all()) == canonical_json(verify_all())


def test_report_headline_carries_the_measured_reduction() -> None:
    report = json.loads((REPORT_DIR / "report.json").read_text())
    headline = report["headline"]
    assert headline["append_duplicate_pairs_total"] == 10
    assert headline["replacement_duplicate_pairs_total"] == 4
    readme = (REPORT_DIR / "README.md").read_text()
    assert "10" in readme and "4" in readme and "no adoption decision" in readme.lower()
