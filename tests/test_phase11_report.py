"""Phase 11 Prompt 7: report generation and adoption-gate tests."""

import json
from pathlib import Path

from benchmarks.contract import canonical_json
from benchmarks.reporting.report_phase11 import (
    build_report_data,
    evaluate_adoption_gates,
    load_spec,
    validate,
    verify_sources,
)

SPEC = load_spec()
REPORT_DATA = json.loads(
    Path(SPEC["outputs"]["report_data"]).read_text()
)
GATES = json.loads(Path(SPEC["outputs"]["adoption_gates"]).read_text())
MARKDOWN = Path(SPEC["outputs"]["markdown"]).read_text()


def test_spec_locks_all_source_digests():
    verify_sources(SPEC)  # raises on drift
    assert SPEC["sources"]["lifecycle_v2_reference"][
        "normalized_result_digest"
    ].startswith("ee437bb3")
    assert SPEC["sources"]["external_v2_reference"][
        "normalized_result_digest"
    ].startswith("19b66cac")


def test_report_data_reconciles_with_artifacts():
    rebuilt = build_report_data(SPEC)
    assert canonical_json(rebuilt) == canonical_json(REPORT_DATA)


def test_adoption_gates_reconcile():
    rebuilt = evaluate_adoption_gates(SPEC, REPORT_DATA)
    assert canonical_json(rebuilt) == canonical_json(GATES)


def test_reference_lock_recorded_true():
    lock = REPORT_DATA["reference_lock"]
    assert lock["lifecycle_metrics_equal"] is True
    assert lock["external_metrics_equal"] is True
    assert lock["excluded_metrics"] == [
        "external_token_reduction_vs_full_history"
    ]


def test_headline_values():
    reference = REPORT_DATA["external"][
        "experienceos_hybrid_full_v2_reference"
    ]
    fused = REPORT_DATA["external"]["experienceos_fused_retrieval_v1"]
    embedding = REPORT_DATA["external"]["experienceos_embedding_only_v1"]
    assert reference["answer_session_selection_rate"]["numerator"] == 12
    assert reference["context_tokens_total"] == 5527
    assert fused["answer_session_selection_rate"]["numerator"] == 13
    assert round(fused["answer_session_mrr"]["value"], 4) == 0.2931
    assert embedding["answer_session_selection_rate"]["numerator"] == 2
    lifecycle_embedding = REPORT_DATA["lifecycle"][
        "experienceos_embedding_only_v1"
    ]
    assert lifecycle_embedding["recall_at_k"]["numerator"] == 2


def test_materiality_threshold_ratified():
    assert GATES["threshold"] == {"absolute_cases": 1, "relative": 0.02}


def test_classifications():
    assert GATES["experienceos_embedding_only_v1"][
        "classification"
    ] == "not_adopted"
    assert GATES["experienceos_fused_retrieval_v1"][
        "classification"
    ] == "experimental"
    assert GATES["experienceos_gate_shadow_v1"][
        "classification"
    ] == "experimental"


def test_gate_shadow_summary_zero_affected():
    for scope in ("external", "lifecycle"):
        summary = REPORT_DATA["gate_shadow"][scope]
        assert summary["gate_affected_selection"] == 0
        assert summary["gate_failures"] == 0
        assert summary["gate_evaluated"] == (
            summary["gate_admit"] + summary["gate_reject"]
            + summary["gate_abstain"]
        )


def test_required_disclosures_present():
    lowered = MARKDOWN.lower()
    for phrase in SPEC["required_disclosures"]:
        assert phrase.lower() in lowered, phrase
    assert "not an official longmemeval score" in lowered
    assert "material" in lowered  # the MRR regression is disclosed
    assert "recommended_candidate" not in lowered.replace(
        "cannot justify recommended_candidate", ""
    )


def test_markdown_has_no_personal_paths():
    assert "/Users/" not in MARKDOWN
    assert "/home/" not in MARKDOWN


def test_full_report_validation_passes():
    validate()  # raises on drift, hash mismatch, missing disclosure


def test_provider_evidence_class_recorded():
    provider = REPORT_DATA["provider"]
    assert provider["provider_id"] == "deterministic"
    assert provider["provider_class"] == "deterministic_test_embeddings"
    assert provider["optional_local_provider"] == (
        "skipped: dependency_missing"
    )
    assert provider["fallback_count"] == 0
