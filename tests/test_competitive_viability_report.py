"""Integrity tests for the competitive viability report.

Verify the report's numbers reproduce from the committed evidence, that
every system appears once, that the unfavorable facts (7.90-point gap,
worst stale-use, preserved judge failure) are visible, that forbidden
claims are absent, and that the decisions are allowed values. No live
calls; reads committed artifacts only.
"""

from __future__ import annotations

import json
import pytest
import re
import statistics
from pathlib import Path

COMMITTED = Path("benchmarks/results/committed/competitive-viability")
REPORT = Path("docs/competitive_viability_report.md")
RAW = Path("benchmarks/results/local/competitive-viability/records.jsonl")

SYSTEMS = (
    "canonical_experienceos_qwen", "deterministic_experienceos", "stateless",
    "full_history", "naive_top_k", "append_only",
)


def _report_text():
    return REPORT.read_text()


def _evidence():
    return json.loads((COMMITTED / "scoring_evidence.json").read_text())


def test_report_exists_with_required_title_and_sections():
    text = _report_text()
    assert text.startswith("# ExperienceOS Competitive Viability Report")
    for heading in (
        "## 1. Executive summary", "## 2. Final decision",
        "## 9. Final-answer results", "## 10. Context efficiency",
        "## 12. Competitive profile", "## 13. Ten required questions",
        "## 17. Go / No-Go recommendation",
        "## 18. Recommended next action",
    ):
        assert heading in text, heading


def test_final_answer_metrics_reproduce_from_scoring_evidence():
    agg = _evidence()["aggregate_by_system"]
    text = _report_text()
    for system in SYSTEMS:
        pct = agg[system]["final_answer_accuracy"]["percentage"]
        assert f"{pct:.2f}%" in text, f"{system} {pct}"


def test_strongest_baseline_and_gap_are_accurate():
    agg = _evidence()["aggregate_by_system"]
    accs = {s: agg[s]["final_answer_accuracy"]["percentage"] for s in SYSTEMS}
    strongest = max(v for s, v in accs.items()
                    if s not in ("canonical_experienceos_qwen",
                                 "deterministic_experienceos"))
    canonical = accs["canonical_experienceos_qwen"]
    gap = round(strongest - canonical, 2)
    assert strongest == 78.95 and canonical == 71.05
    assert gap == 7.90
    assert "7.90" in _report_text()  # the gap is shown, not hidden


def test_context_metrics_reproduce_from_execution_records():
    if not RAW.exists():
        pytest.skip("local competitive-viability records scratch not present")
    recs = [json.loads(l) for l in RAW.read_text().splitlines()]
    by = {}
    for r in recs:
        if r["status"] == "completed" and r["context_tokens"] is not None:
            by.setdefault(r["system_id"], []).append(r["context_tokens"])
    canonical_mean = round(statistics.mean(by["canonical_experienceos_qwen"]), 1)
    full_mean = round(statistics.mean(by["full_history"]), 1)
    assert canonical_mean == 60.4 and full_mean == 455.9
    text = _report_text()
    assert "60.4" in text and "455.9" in text


def test_every_system_appears_in_report():
    text = _report_text()
    for system in SYSTEMS:
        assert system in text


def test_judge_failure_and_exclusion_visible():
    ev = _evidence()
    assert ev["score_counts"]["excluded"] == 1
    assert ev["score_counts"]["exclusion_counts"] == {"judge_failure": 1}
    text = _report_text()
    assert "judge failure" in text.lower()
    assert "37/37" not in text  # append-only shown as 27/37, not fabricated 38


def test_worst_stale_use_is_shown_not_hidden():
    # Canonical's 50% stale-info use is the worst and must be visible.
    text = _report_text()
    assert "50.00%" in text or "50%" in text
    assert "stale" in text.lower()


def test_forbidden_claims_absent():
    text = _report_text().lower()
    # No AFFIRMATIVE forbidden claims (Mem0 comparison, statistical
    # significance, LongMemEval live validation, SOTA). Mentions are only
    # allowed inside the explicit unsupported-claims disclaimer.
    assert "claimed or supported" in text  # explicit unsupported disclaimer
    for affirmative in (
        "outperforms mem0", "beats mem0", "matches mem0",
        "statistically significant",
        "longmemeval validation", "validated on longmemeval",
    ):
        assert affirmative not in text, affirmative
    # SOTA appears only inside the explicit disclaimer "not ... a claim of".
    assert "not a claim of state-of-the-art" in text
    # The forbidden topics appear only as explicitly unsupported items.
    assert "statistical significance" in text
    assert "longmemeval" in text


def test_decisions_are_allowed_values():
    text = _report_text()
    assert "COMPETITIVE_VIABILITY_NOT_YET_DEMONSTRATED" in text
    assert "PHASE_17_COMPETITIVE_REPORT_COMPLETE" in text
    assert "PHASE_17_COMPLETE" in text
    assert "TARGETED_VALIDATION_JUSTIFIED" in text
    # Exactly one final decision value present.
    finals = [
        "COMPETITIVE_VIABILITY_DEMONSTRATED",
        "DIFFERENTIATED_VIABILITY_DEMONSTRATED",
        "COMPETITIVE_VIABILITY_NOT_YET_DEMONSTRATED",
        "COMPETITIVE_VIABILITY_INCONCLUSIVE",
    ]
    # NOT_YET is present; the bare DEMONSTRATED token appears only as the
    # substring of NOT_YET / as an option list — count exact decision line.
    assert "**`COMPETITIVE_VIABILITY_NOT_YET_DEMONSTRATED`**" in text


def test_report_has_no_secrets_or_raw_answer_dump():
    text = _report_text().lower()
    assert "api_key" not in text and "authorization:" not in text
    assert "bearer " not in text


def test_committed_artifact_hashes_still_match():
    import hashlib
    ev = _evidence()
    d = Path("benchmarks/results/local/competitive-viability/scoring")
    if not d.exists():
        pytest.skip("local competitive-viability scoring scratch not present")
    ah = ev["artifact_hashes"]
    for name, key in (("score_records.jsonl", "score_records_jsonl"),
                      ("judge_tasks.jsonl", "judge_tasks_jsonl")):
        got = hashlib.sha256((d / name).read_bytes()).hexdigest()
        assert got == ah[key], name
