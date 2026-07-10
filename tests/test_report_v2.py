"""Phase 9 Prompt 9: comparative report generation and validation tests."""

import json
from pathlib import Path

from benchmarks.contract import canonical_json
from benchmarks.reporting.report_v2 import (
    build_failure_summary,
    build_report_data,
    build_tables,
    load_spec,
    report_data_digest,
    validate,
    verify_sources,
)

SPEC = load_spec()
REPORT_DATA = json.loads(
    Path(SPEC["outputs"]["report_data"]).read_text()
)
MARKDOWN = Path(SPEC["outputs"]["markdown"]).read_text()


def test_spec_locks_source_digests():
    assert SPEC["sources"]["lifecycle_v2"]["normalized_result_digest"] == (
        "ee437bb3e9fde909f343112e40aaa6ecf63155a07a81ad67e017e310"
        "fbefb547"
    )
    assert SPEC["sources"]["external_v2"]["normalized_result_digest"] == (
        "19b66cacb330e943b0460ccdb33e8cc6577fccb17621cb7a129f7420"
        "f5c7868f"
    )
    verify_sources(SPEC)  # raises on drift


def test_report_data_reconciles_with_artifacts():
    rebuilt = build_report_data(SPEC)
    assert canonical_json(rebuilt) == canonical_json(REPORT_DATA)


def test_lifecycle_headline_values():
    rules = REPORT_DATA["lifecycle"]["experienceos_rules"]
    full = REPORT_DATA["lifecycle"]["experienceos_hybrid_full_v2"]
    assert (rules["forget_detection_accuracy"]["numerator"],
            rules["forget_detection_accuracy"]["denominator"]) == (2, 4)
    assert (full["forget_detection_accuracy"]["numerator"],
            full["forget_detection_accuracy"]["denominator"]) == (4, 4)
    assert (full["recall_at_k"]["numerator"],
            full["recall_at_k"]["denominator"]) == (17, 17)
    assert (full["forgotten_exclusion_rate"]["numerator"],
            full["forgotten_exclusion_rate"]["denominator"]) == (2, 2)
    assert full["case_outcomes"]["passed"] == 21
    assert rules["case_outcomes"]["passed"] == 17


def test_external_headline_values_and_references():
    rules = REPORT_DATA["external"]["experienceos_rules"]
    full = REPORT_DATA["external"]["experienceos_hybrid_full_v2"]
    naive = REPORT_DATA["external"]["naive_top_k"]
    assert (rules["answer_session_selection_rate"]["numerator"],
            rules["answer_session_selection_rate"]["denominator"]) == (
        14, 50)
    assert (full["answer_session_candidate_rate"]["numerator"],
            full["answer_session_candidate_rate"]["denominator"]) == (
        31, 50)
    assert (full["answer_session_selection_rate"]["numerator"]) == 12
    assert round(full["answer_session_mrr"]["value"], 3) == 0.305
    assert (naive["answer_session_selection_rate"]["numerator"]) == 42
    assert rules["context_tokens_total"] == 10328
    assert full["context_tokens_total"] == 5527


def test_token_reduction_calculation():
    reduction = REPORT_DATA["derived"]["external_token_reduction"]
    assert reduction["absolute_reduction"] == 10328 - 5527 == 4801
    assert round(reduction["relative_reduction"], 3) == 0.465


def test_unsupported_slots_reason_present():
    assert "experienceos_slots_v2" in REPORT_DATA["external_unsupported"]
    assert "retrieval-only" in REPORT_DATA["external_unsupported"][
        "experienceos_slots_v2"
    ]


def test_required_disclosures_in_markdown():
    lowered = MARKDOWN.lower()
    for phrase in SPEC["required_disclosures"]:
        assert phrase.lower() in lowered, phrase
    # Selection trade-off, simulated labeling, official-score
    # disclaimer, and naive top-K advantage all disclosed.
    assert "not an official longmemeval score" in lowered
    assert "scripted-simulated" in lowered
    assert "14/50 to 12/50" in MARKDOWN or "14/50 → 12/50" in MARKDOWN \
        or "fell" in lowered
    assert "superior raw recall" in lowered


def test_markdown_has_no_personal_paths():
    assert "/Users/" not in MARKDOWN
    assert "/home/" not in MARKDOWN


def test_failure_summary_counts():
    failures = json.loads(
        Path(SPEC["outputs"]["failure_summary"]).read_text()
    )
    rebuilt = build_failure_summary(SPEC)
    assert canonical_json(rebuilt) == canonical_json(failures)
    external = failures["external_final_system"]
    assert external["candidate_absent_count"] == len(
        external["candidate_absent_cases"]
    )
    assert external["candidate_unselected_count"] == len(
        external["candidate_unselected_cases"]
    )
    assert external["abstention_deferrals"] == 10
    lifecycle = failures["lifecycle_non_passed_by_system"]
    assert "experienceos_hybrid_full_v2" in lifecycle


def test_comparison_tables_reconcile():
    tables = json.loads(
        Path(SPEC["outputs"]["comparison_tables"]).read_text()
    )
    rebuilt = build_tables(SPEC, REPORT_DATA)
    assert canonical_json(rebuilt) == canonical_json(tables)
    final_row = next(
        r for r in tables["external_headline"]
        if r["system"] == "experienceos_hybrid_full_v2"
    )
    assert final_row["candidate"] == "31/50"
    assert final_row["selection"] == "12/50"


def test_manifest_digest_locks():
    manifest = json.loads(Path(SPEC["outputs"]["manifest"]).read_text())
    assert manifest["report_data_digest"] == report_data_digest(
        REPORT_DATA
    )


def test_full_report_validation_passes():
    validate()  # raises on any drift, missing disclosure, or mismatch


def test_v1_report_untouched():
    v1 = Path("docs/benchmark_report.md").read_text()
    assert "Phase 9" not in v1.split("\n")[0]
    assert Path("benchmarks/results/committed/report-v1").is_dir()
    # v2 report lives at its own path.
    assert Path("docs/benchmark_report_v2.md").exists()
