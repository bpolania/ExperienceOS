"""Dashboard visibility for governed action replacement.

Fast unit tests over the read-only diagnostics source, plus a render-level
AppTest. They prove the replacement lifecycle, benchmark comparison, gate
results, residuals, classification, old-event compatibility, and
artifact-failure handling are all visible and honest — and that rendering
mutates nothing and changes no classification.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest

from demo import transition_diagnostics as td

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FROZEN = REPO_ROOT / "benchmarks/results/committed/report-transition-verification"
REPLACEMENT = REPO_ROOT / "benchmarks/results/committed/action-replacement"


@pytest.fixture(autouse=True)
def _fresh_cache():
    td.reload_artifacts()
    yield
    td.reload_artifacts()


# --- benchmark comparison ---------------------------------------------------


def test_summary_reports_10_to_4_and_class_elimination() -> None:
    s = td.replacement_summary()
    assert s["available"] is True
    assert s["reference_duplicates"] == 0
    assert s["append_duplicates"] == 10
    assert s["replacement_duplicates"] == 4
    assert s["supersede_bearing_append"] == 6
    assert s["supersede_bearing_replacement"] == 0
    assert s["pure_create_residual"] == 4
    assert s["replacements_applied"] == 6
    assert s["lineage_correct"] == 6 and s["lineage_broken"] == 0
    assert s["seeded_memories_lost"] == 0
    assert s["stale_reference"] == 6 and s["stale_replacement"] == 1


# --- gate visibility --------------------------------------------------------


def test_all_twenty_gates_visible_with_fail_and_inconclusive() -> None:
    rows = td.replacement_gate_rows()
    assert len(rows) == 20
    assert sorted(r["gate"] for r in rows) == list(range(1, 21))
    gate1 = next(r for r in rows if r["gate"] == 1)
    gate6 = next(r for r in rows if r["gate"] == 6)
    assert gate1["replacement_decision"] == "fail"
    assert gate6["replacement_decision"] == "inconclusive"
    blocking = [r for r in rows if r["blocking"]]
    assert sorted(r["gate"] for r in blocking) == [4, 5, 8, 9, 10, 11, 12, 19, 20]
    assert all(r["replacement_decision"] == "pass" for r in blocking)


def test_summary_tally_and_conditions() -> None:
    s = td.replacement_summary()
    assert s["tally"] == {"passed": 18, "failed": 1, "inconclusive": 1}
    assert s["blocking_all_pass"] is True
    assert s["conditions_pass"] == 22 and s["conditions_total"] == 22


def test_conditions_all_pass() -> None:
    conditions = td.replacement_conditions()
    assert len(conditions) == 22
    assert all(v == "pass" for v in conditions.values())


# --- classification ---------------------------------------------------------


def test_classification_is_candidate_only() -> None:
    s = td.replacement_summary()
    assert s["classification"] == "TRANSITION_PATH_CANDIDATE_ONLY"
    assert s["runtime_default"] == "disabled"
    assert s["canonical_controller"] == "none"


# --- pure-create residuals --------------------------------------------------


def test_four_pure_create_residuals_visible() -> None:
    rows = td.pure_create_residual_rows()
    assert len(rows) == 4
    ids = " ".join(r["case_id"] for r in rows)
    for needle in td.PURE_CREATE_RESIDUAL_IDS:
        assert needle in ids
    for r in rows:
        assert r["transition_class"] == "pure_create"
        assert r["replacement_duplicate_pairs"] > 0
        assert "does not apply" in r["reason"]


# --- historical example -----------------------------------------------------


def test_historical_example_shows_before_and_after() -> None:
    ex = td.historical_replacement_example()
    assert ex["available"] is True
    assert "updates_001" in ex["case_id"]
    assert ex["append_duplicate_pairs"] == 1
    assert ex["replacement_duplicate_pairs"] == 0
    assert ex["canonical_effect"] == "action_replaced"
    assert ex["planner_suppressed"] is True
    assert ex["lineage_ok"] is True


# --- live replacement record ------------------------------------------------


def test_applied_replacement_record_is_readable_and_safe() -> None:
    record = td.replacement_record({
        "attempted": True, "applied": True,
        "matcher_decision": "replacement_ready",
        "plan_status": "replacement_plan_ready",
        "canonical_effect": "action_replacement_candidate",
        "plan_digest": "0123456789abcdef0123",
        "authorization_status": {"authorized": True},
        "suppressed_occurrence_index": 0, "final_action_count": 3,
    })
    assert record["available"] is True
    assert record["applied"] is True
    assert record["authorization_status"] == "accepted"
    # Digest is shortened, never the full value.
    assert record["plan_digest"] == "0123456789ab…"


def test_rejected_replacement_record_shows_fallback() -> None:
    record = td.replacement_record({
        "attempted": True, "applied": False,
        "matcher_decision": "replacement_ready",
        "plan_status": "replacement_plan_ready",
        "canonical_effect": "authorization_denied",
        "authorization_status": {"authorized": False,
                                 "mismatched_fields": ["plan_digest"]},
        "fallback_used": True, "fallback_reason": "authorization_mismatch",
    })
    assert record["applied"] is False
    assert record["authorization_status"] == "rejected"
    assert record["authorization_mismatched_fields"] == ["plan_digest"]
    assert record["fallback_used"] is True


def test_old_event_without_replacement_renders_unavailable() -> None:
    # A transition event with no replacement sub-record.
    normalized = td.normalize_transition_event({
        "effective_mode": "shadow", "canonical_action_effect": "diagnostics_only",
    })
    assert normalized["malformed"] is False
    assert normalized["replacement"] == {"available": False}
    # And a bare/None replacement value is unavailable, never a crash.
    assert td.replacement_record(None) == {"available": False}
    assert td.replacement_record("nonsense") == {"available": False}


# --- artifact-failure handling ----------------------------------------------


def test_missing_artifacts_handled_gracefully(monkeypatch) -> None:
    monkeypatch.setattr(td, "REPLACEMENT_ADOPTION_DIR", REPO_ROOT / "no" / "such")
    td.reload_artifacts()
    assert td.replacement_available() is False
    assert td.replacement_summary() == {"available": False}
    assert td.replacement_gate_rows() == []
    assert td.pure_create_residual_rows() == []
    assert td.historical_replacement_example() == {"available": False}


# --- no mutation ------------------------------------------------------------


def _tree_digest(directory: pathlib.Path) -> str:
    h = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            h.update(path.name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def test_reading_diagnostics_mutates_no_committed_file() -> None:
    before_frozen = _tree_digest(FROZEN)
    before_repl = _tree_digest(REPLACEMENT)
    # Exercise every reader.
    td.replacement_summary()
    td.replacement_gate_rows()
    td.replacement_gate_detail()
    td.replacement_conditions()
    td.pure_create_residual_rows()
    td.replacement_systems()
    td.historical_replacement_example()
    assert _tree_digest(FROZEN) == before_frozen
    assert _tree_digest(REPLACEMENT) == before_repl


# --- render-level ------------------------------------------------------------

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402


def _app_text() -> str:
    at = AppTest.from_file("demo/app.py", default_timeout=120)
    at.run()
    assert not at.exception
    parts = []
    for group in (at.markdown, at.caption, at.warning, at.info, at.success):
        parts.extend(str(e.value) for e in group)
    return " ".join(parts)


def test_dashboard_renders_replacement_evidence_and_classification() -> None:
    text = _app_text()
    assert "TRANSITION_PATH_CANDIDATE_ONLY" in text
    # The honest benchmark story and the refusal are both visible.
    assert "pure-create duplicates remain" in text
    assert "refused canonical adoption" in text.lower()
    assert "benchmark/test-only" in text
    # Gate 1 failure and the class-elimination context are shown.
    assert "supersede-bearing class is\neliminated" in text or "6 → 0" in text
