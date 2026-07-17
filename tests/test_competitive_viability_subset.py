"""Tests for the frozen viability subset and its manifest.

Offline and deterministic: the manifest derives from the frozen lifecycle
scenarios. These tests pin the selection (all scenarios, no cherry-pick),
the required per-case fields, determinism, and that no expected-answer
content leaks into the manifest.
"""

from __future__ import annotations

import json

from experiments.competitive_viability.cases import (
    EVIDENCE_FROZEN_HISTORICAL,
    SCORING_DETERMINISTIC,
    SCORING_MODEL_JUDGE,
)
from experiments.competitive_viability.viability_subset import (
    REQUIRED_SYSTEMS,
    build_viability_manifest,
    manifest_hash,
    viability_case_ids,
)

_REQUIRED_CASE_FIELDS = {
    "viability_case_id", "source_case_id", "source_dataset",
    "evidence_classification", "provenance", "lifecycle_category",
    "retrieval_category", "final_answer_category", "scoring_method",
    "scorable", "expected_answer_ref", "required_systems", "context_budget",
    "selection_k", "known_limitations", "dedup_lineage",
}


def test_manifest_selects_all_frozen_lifecycle_scenarios():
    manifest = build_viability_manifest()
    # Complete frozen lifecycle set — a bounded, defensible viability subset.
    assert manifest["summary"]["total_cases"] == 40
    assert set(manifest["summary"]["by_evidence_classification"]) == {
        EVIDENCE_FROZEN_HISTORICAL
    }
    assert "all frozen lifecycle scenarios" in manifest["selection_method"]


def test_every_case_has_the_required_fields():
    for case in build_viability_manifest()["cases"]:
        assert _REQUIRED_CASE_FIELDS <= set(case)
        assert case["required_systems"] == list(REQUIRED_SYSTEMS)


def test_manifest_carries_no_expected_answer_content():
    # Only references may appear — never expected-answer text.
    manifest = build_viability_manifest()
    for case in manifest["cases"]:
        assert case["expected_answer_ref"].startswith("scenario:")
        assert "expected_answer_ref" in case
        # No structured oracle keys are present in a case entry.
        for oracle_key in ("must_include_all", "must_include_any",
                           "response", "memory_actions", "answer"):
            assert oracle_key not in case


def test_manifest_is_deterministic_and_hashable():
    a = build_viability_manifest()
    b = build_viability_manifest()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert manifest_hash(a) == manifest_hash(b)


def test_summary_counts_are_consistent():
    manifest = build_viability_manifest()
    summary = manifest["summary"]
    assert summary["scorable_cases"] == sum(
        1 for c in manifest["cases"] if c["scorable"]
    )
    assert sum(summary["by_scoring_method"].values()) == summary["total_cases"]
    assert summary["by_scoring_method"].get(SCORING_DETERMINISTIC, 0) >= 1
    assert summary["by_scoring_method"].get(SCORING_MODEL_JUDGE, 0) >= 1


def test_local_model_cases_are_marked_not_scorable():
    # requires_local_model cases cannot be scored on Qwen systems; they are
    # marked not-scorable rather than counted as failures.
    manifest = build_viability_manifest()
    not_scorable = [c for c in manifest["cases"] if not c["scorable"]]
    for case in not_scorable:
        assert any("local_model" in lim for lim in case["known_limitations"])


def test_viability_case_ids_match_manifest_order():
    manifest = build_viability_manifest()
    assert viability_case_ids() == [
        c["source_case_id"] for c in manifest["cases"]
    ]


def test_longmemeval_limitation_is_recorded():
    manifest = build_viability_manifest()
    assert manifest["coverage_limitations"]
    assert any(
        "LongMemEval" in lim for lim in manifest["coverage_limitations"]
    )


# -- curated execution summary ------------------------------------------------


def test_curated_summary_reports_completeness_and_fairness_no_answers():
    from experiments.competitive_viability.summary import (
        curated_execution_summary,
    )

    records = [
        {"system_id": "a", "case_id": "c1", "status": "completed",
         "response_model": "qwen-plus", "execution_error": None},
        {"system_id": "a", "case_id": "c2", "status": "completed",
         "response_model": "qwen-plus", "execution_error": None},
        {"system_id": "b", "case_id": "c1", "status": "completed",
         "response_model": "qwen-plus", "execution_error": None},
        {"system_id": "b", "case_id": "c2", "status": "failed",
         "response_model": "qwen-plus", "execution_error": "X: boom"},
    ]
    summary = curated_execution_summary(
        records, run_id="r", execution_mode="live",
        viability_manifest_hash="h", git_commit="g",
    )
    assert summary["distinct_cases"] == 2
    assert summary["fairness"]["single_response_model"] is True
    assert summary["fairness"]["identical_case_set_per_system"] is True
    assert summary["provider_failures"] == 1
    # No answer/payload text is carried.
    import json
    assert "content" not in json.dumps(summary).lower()
