"""Phase 11 Prompt 7: committed artifact and validator tests."""

import json
import re
from pathlib import Path

import pytest

from benchmarks.validation_phase11 import (
    RUN_COMPOSITION_RELATIVE_METRICS,
    validate_cross_consistency_phase11,
    validate_phase11_external,
    validate_phase11_lifecycle,
)

LIFECYCLE_DIR = Path(
    "benchmarks/results/committed/phase11-retrieval-ablation"
)
EXTERNAL_DIR = Path(
    "benchmarks/results/committed/phase11-semantic-retrieval"
)
V2_LIFECYCLE = Path("benchmarks/results/committed/lifecycle-v2-ablation")
V2_EXTERNAL = Path(
    "benchmarks/results/committed/longmemeval-50-subset-v2"
)

PHASE11_IDS = (
    "experienceos_hybrid_full_v2_reference",
    "experienceos_embedding_only_v1",
    "experienceos_fused_retrieval_v1",
    "experienceos_gate_shadow_v1",
)


def _jsonl(path):
    for line in path.read_text().split("\n"):
        if line.strip():
            yield json.loads(line)


def test_committed_phase11_validators_pass():
    validate_phase11_lifecycle(str(LIFECYCLE_DIR))
    validate_phase11_external(str(EXTERNAL_DIR))
    validate_cross_consistency_phase11(
        str(LIFECYCLE_DIR), str(EXTERNAL_DIR)
    )


def test_reference_reproduces_phase9_behavioral_surface():
    p11 = json.loads((EXTERNAL_DIR / "aggregate.json").read_text())
    v2 = json.loads((V2_EXTERNAL / "aggregate.json").read_text())
    reference = p11["metrics"]["experienceos_hybrid_full_v2_reference"]
    historical = v2["metrics"]["experienceos_hybrid_full_v2"]
    for name, cell in historical.items():
        if name in RUN_COMPOSITION_RELATIVE_METRICS:
            continue
        assert reference[name] == cell, name
    # Headline values match the Phase 9 report exactly.
    assert reference["answer_session_candidate_rate"]["numerator"] == 31
    assert reference["answer_session_selection_rate"]["numerator"] == 12
    assert round(reference["answer_session_mrr"]["value"], 3) == 0.305


def test_reference_lifecycle_reproduces_phase9():
    p11 = json.loads((LIFECYCLE_DIR / "aggregate.json").read_text())
    v2 = json.loads((V2_LIFECYCLE / "aggregate.json").read_text())
    assert (
        p11["metrics"]["experienceos_hybrid_full_v2_reference"]
        == v2["metrics"]["experienceos_hybrid_full_v2"]
    )
    assert p11["case_outcomes"][
        "experienceos_hybrid_full_v2_reference"
    ] == v2["case_outcomes"]["experienceos_hybrid_full_v2"]


def test_gate_shadow_canonically_equal_to_fused():
    for directory in (LIFECYCLE_DIR, EXTERNAL_DIR):
        aggregate = json.loads(
            (directory / "aggregate.json").read_text()
        )
        assert (
            aggregate["metrics"]["experienceos_fused_retrieval_v1"]
            == aggregate["metrics"]["experienceos_gate_shadow_v1"]
        ), directory
    # Per-case retrieval decisions are identical too.
    def selections(system):
        return {
            record["question_id"]: (
                record["candidate_count"], record["selected_count"],
                record["context_tokens"],
            )
            for record in _jsonl(EXTERNAL_DIR / "cases.jsonl")
            if record["system_id"] == system
        }

    assert selections("experienceos_fused_retrieval_v1") == selections(
        "experienceos_gate_shadow_v1"
    )


def test_lifecycle_safety_zeros_hold():
    aggregate = json.loads((LIFECYCLE_DIR / "aggregate.json").read_text())
    for system in PHASE11_IDS:
        cells = aggregate["metrics"][system]
        assert cells["inactive_contamination_rate"]["numerator"] == 0
        assert cells["forgotten_response_contamination_rate"][
            "numerator"
        ] == 0


def test_gate_affected_selection_zero_everywhere():
    total = 0
    for record in _jsonl(LIFECYCLE_DIR / "cases.jsonl"):
        total += record["case"]["diagnostics"].get(
            "gate_shadow_v1", {}
        ).get("gate_affected_selection", 0)
    for record in _jsonl(EXTERNAL_DIR / "cases.jsonl"):
        total += (record.get("extraction") or {}).get(
            "gate_affected_selection", 0
        )
    assert total == 0


def test_gate_shadow_distributions_recorded():
    admits = rejects = evaluated = 0
    for record in _jsonl(EXTERNAL_DIR / "cases.jsonl"):
        extraction = record.get("extraction") or {}
        if record["system_id"] == "experienceos_gate_shadow_v1":
            evaluated += extraction.get("gate_evaluated", 0)
            admits += extraction.get("gate_admit", 0)
            rejects += extraction.get("gate_reject", 0)
    assert evaluated > 0
    assert admits + rejects <= evaluated


def test_artifact_digests_reproduce_declared_values():
    from benchmarks.reporting.report_phase11 import load_spec

    spec = load_spec()
    for name, source in spec["sources"].items():
        manifest = json.loads(
            (Path(source["path"]) / "artifact_manifest.json").read_text()
        )
        assert manifest["normalized_result_digest"] == (
            source["normalized_result_digest"]
        ), name


def test_case_counts_and_system_matrix():
    external_cases = {}
    for record in _jsonl(EXTERNAL_DIR / "cases.jsonl"):
        external_cases.setdefault(record["system_id"], set()).add(
            record["question_id"]
        )
    assert set(external_cases) == set(PHASE11_IDS)
    assert all(len(ids) == 50 for ids in external_cases.values())
    lifecycle_cases = {}
    for record in _jsonl(LIFECYCLE_DIR / "cases.jsonl"):
        lifecycle_cases.setdefault(
            record["case"]["system_id"], set()
        ).add(record["case"]["scenario_id"])
    assert set(lifecycle_cases) == set(PHASE11_IDS)
    assert all(len(ids) == 40 for ids in lifecycle_cases.values())


def test_no_vectors_or_personal_paths_in_artifacts():
    personal = re.compile(r"/Users/|/home/", re.IGNORECASE)
    for directory in (LIFECYCLE_DIR, EXTERNAL_DIR):
        for name in ("cases.jsonl", "aggregate.json"):
            text = (directory / name).read_text()
            assert not personal.search(text), f"{directory}/{name}"
            assert '"vector"' not in text
            assert '"embedding_vector"' not in text


def test_cache_evidence_present_for_semantic_systems():
    totals = {}
    for record in _jsonl(EXTERNAL_DIR / "cases.jsonl"):
        extraction = record.get("extraction") or {}
        lookups = extraction.get("semantic_cache_lookups")
        if lookups is not None:
            totals[record["system_id"]] = (
                totals.get(record["system_id"], 0) + lookups
            )
    assert set(totals) == {
        "experienceos_embedding_only_v1",
        "experienceos_fused_retrieval_v1",
        "experienceos_gate_shadow_v1",
    }
    assert all(value > 0 for value in totals.values())
    # The reference emits no semantic evidence at all.
    for record in _jsonl(EXTERNAL_DIR / "cases.jsonl"):
        if record["system_id"] == (
            "experienceos_hybrid_full_v2_reference"
        ):
            extraction = record.get("extraction") or {}
            assert "semantic_cache_lookups" not in extraction


def test_historical_artifacts_untouched_by_phase11_outputs():
    spec_paths = (
        "benchmarks/results/committed/phase11-retrieval-ablation",
        "benchmarks/results/committed/phase11-semantic-retrieval",
        "benchmarks/results/committed/report-phase11",
    )
    historical = (
        "benchmarks/results/committed/lifecycle-offline-v1",
        "benchmarks/results/committed/longmemeval-50-subset-v1",
        "benchmarks/results/committed/report-v1",
        "benchmarks/results/committed/lifecycle-v2-ablation",
        "benchmarks/results/committed/longmemeval-50-subset-v2",
        "benchmarks/results/committed/report-v2",
    )
    for new_path in spec_paths:
        assert new_path not in historical
        assert Path(new_path).is_dir()


def test_validator_fails_loudly_on_nonzero_leakage(tmp_path, monkeypatch):
    import shutil

    from benchmarks import validation_phase11

    corrupted = tmp_path / "lifecycle"
    shutil.copytree(LIFECYCLE_DIR, corrupted)
    aggregate_path = corrupted / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text())
    aggregate["metrics"]["experienceos_fused_retrieval_v1"][
        "inactive_contamination_rate"
    ]["numerator"] = 1.0
    aggregate_path.write_text(json.dumps(aggregate))
    # Bypass the structural hash check so the SAFETY check itself is
    # what trips (the hash check would also catch the tampering).
    monkeypatch.setattr(
        validation_phase11, "validate_artifact_dir", lambda path: None
    )
    with pytest.raises(
        validation_phase11.Phase11ValidationError,
        match="LIFECYCLE SAFETY FAILURE",
    ):
        validation_phase11.validate_phase11_lifecycle(str(corrupted))
