"""Phase 9 Prompt 8: final composition and v2 artifact tests."""

import json
from pathlib import Path

import pytest

from benchmarks.adapters.experienceos_hybrid_full_v2 import (
    ExperienceOSHybridFullV2Adapter,
)
from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
from benchmarks.contract import KNOWN_SYSTEM_IDS, SystemId, case_from_dict
from benchmarks.validation_v2 import (
    EXTERNAL_V2_SYSTEMS,
    LIFECYCLE_V2_SYSTEMS,
    validate_cross_consistency,
    validate_external_v2,
    validate_lifecycle_v2,
)

LIFECYCLE_V2_DIR = Path("benchmarks/results/committed/lifecycle-v2-ablation")
EXTERNAL_V2_DIR = Path(
    "benchmarks/results/committed/longmemeval-50-subset-v2"
)


def synthetic_case(message="x", category="creation"):
    return case_from_dict(
        {
            "scenario_id": "synthetic-fullv2-001",
            "schema_version": "1",
            "title": "Synthetic",
            "category": category,
            "description": "Full-v2 composition probe.",
            "tags": ["domain:test"],
            "seed": 7,
            "context_budget": 4,
            "selection_k": 4,
            "turns": [],
            "current_message": message,
            "current_session_id": "s1",
            "expected": {"memory_actions": []},
            "evaluation_mode": "deterministic",
        }
    )


def driven_adapter(turns):
    adapter = ExperienceOSHybridFullV2Adapter()
    adapter.initialize(synthetic_case())
    for index, message in enumerate(turns):
        adapter.process_turn(index, "s1", message)
    return adapter


# --- Registration and provenance ---------------------------------------------------


def test_full_v2_registered_with_unique_id():
    assert SystemId.EXPERIENCEOS_HYBRID_FULL_V2 in ADAPTER_SYSTEM_IDS
    assert SystemId.EXPERIENCEOS_HYBRID_FULL_V2 in KNOWN_SYSTEM_IDS
    system = create_system(SystemId.EXPERIENCEOS_HYBRID_FULL_V2)
    assert system.system_id == "experienceos_hybrid_full_v2"
    assert len(set(ADAPTER_SYSTEM_IDS)) == len(ADAPTER_SYSTEM_IDS)


def test_final_system_provenance_labels():
    adapter = driven_adapter(["I work for Globex now."])
    diagnostics = adapter.diagnostics
    assert diagnostics["final_system_version"] == "1"
    assert diagnostics["local_model_mode"] == "scripted"
    assert diagnostics["model_identity"] == "scripted-simulated-proposals"
    assert diagnostics["simulated_proposal"] is True
    assert diagnostics["direct_model_inference"] is False
    assert diagnostics["proposal_source"] == (
        "deterministic_plan_serialized_through_local_v2_pipeline"
    )
    assert diagnostics["generalized_supersession_enabled"] is True
    assert diagnostics["assistant_ingestion_enabled"] is False
    assert diagnostics["zero_value_padding"] is False
    assert diagnostics["forgotten_history_policy"] == (
        "always_excluded_user_facing"
    )
    # Explicitly distinct from local_v2 provenance.
    local = create_system(SystemId.EXPERIENCEOS_LOCAL_V2)
    assert local.memory_policy_label != adapter.memory_policy_label


def test_real_local_mode_is_non_canonical():
    real = ExperienceOSHybridFullV2Adapter(mode="real")
    assert real.mode == "real"
    canonical = ExperienceOSHybridFullV2Adapter()
    assert canonical.mode == "scripted"


# --- Composition correctness --------------------------------------------------------


def test_lifecycle_composition_end_to_end():
    adapter = driven_adapter(
        [
            "I work for Globex now.",                 # hybrid extraction
            "My phone is a Pixel 6.",                 # rules extraction
            "Actually, my phone is a Pixel 9 now.",   # semantic supersession
            "I prefer aisle seats for short work trips.",
            "For long international trips, I prefer window seats.",  # coexist
            "Forget my aisle seat preference.",       # forget resolver
            "Don't forget my window preference.",     # negation guard
        ]
    )
    snapshot = adapter.final_state()
    by_status = {}
    for entry in snapshot.entries:
        by_status.setdefault(entry.status, []).append(entry.text)
    assert "Works for Globex." in by_status["active"]
    assert "Phone is a Pixel 9." in by_status["active"]
    # v1-matched wording keeps v1's stored text (the leading-clause
    # scope loss is the documented Prompt 2/3 boundary); the semantic
    # cross-scope veto still prevents it superseding the aisle memory.
    assert "Prefers window seats." in by_status["active"]
    assert by_status["superseded"] == ["Phone is a Pixel 6."]
    assert by_status["forgotten"] == [
        "Prefers aisle seats for short work trips."
    ]


def test_pipeline_runs_once_per_turn_no_counter_overwrite():
    adapter = driven_adapter(
        ["I work for Globex now.", "What time is it?"]
    )
    counters = adapter.diagnostics["forget_policy_v2"]
    # One policy decision per turn.
    assert counters["decisions"] == 2
    # Hybrid extraction counters survived the mixin composition
    # (Prompt 3/6 counter-overwrite regressions stay fixed) and the
    # extractor ran exactly once (only one turn was eligible).
    assert counters["extractor_invocations"] == 1
    assert counters["structural_valid"] == 2
    assert counters["fallbacks_total"] == 0


def test_forget_clause_not_reextracted_as_memory():
    adapter = driven_adapter(
        ["Erase the fact that I work for Globex."]
    )
    snapshot = adapter.final_state()
    assert snapshot.entries == ()  # no memory created from forget phrasing


def test_temporal_metadata_attaches_and_no_duplicate_actions():
    adapter = driven_adapter(["My start date is June 3, 2025."])
    entries = adapter.final_state().entries
    assert len(entries) == 1  # exactly one create, no duplicates
    planner = adapter._planner
    assert planner.counters["creates_with_provenance"] >= 1


def test_retrieval_and_coverage_single_pass():
    adapter = driven_adapter(
        ["I work for Globex now.", "What is my employer?"]
    )
    retrieval = adapter.diagnostics["retrieval_v2"]
    # One retrieval per turn (2 turns) — no duplicate passes.
    assert retrieval["retrievals"] == 2
    coverage = adapter.diagnostics["coverage_v2"]
    assert coverage["selections"] == 2


def test_safety_invariants_hold():
    adapter = driven_adapter(
        [
            "I prefer tea in the morning.",
            "Actually, I prefer coffee in the morning.",
            "Forget everything.",  # bulk → contained, no mass action
        ]
    )
    snapshot = adapter.final_state()
    by_status = {}
    for entry in snapshot.entries:
        by_status.setdefault(entry.status, []).append(entry.text)
    # Bulk forget was rejected: the active memory survived.
    assert by_status["active"] == ["Prefers coffee in the morning."]
    assert by_status["superseded"] == ["Prefers tea in the morning."]
    counters = adapter.diagnostics["forget_policy_v2"]
    assert counters.get("forget_bulk_rejected", 0) == 1
    assert adapter.config.context_budget == 4  # K unchanged
    assert adapter.config.selection_k == 4


# --- Prior-system isolation ---------------------------------------------------------


def test_prior_v2_systems_unchanged_by_full_v2():
    for system_id, expected_label_part in (
        (SystemId.EXPERIENCEOS_SLOTS_V2, "semantic_identity"),
        (SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2, "hybrid_extraction"),
        (SystemId.EXPERIENCEOS_HYBRID_RETRIEVAL_V2, "hybrid_retrieval"),
        (SystemId.EXPERIENCEOS_COVERAGE_V2, "coverage_selection"),
        (SystemId.EXPERIENCEOS_TEMPORAL_V2, "temporal"),
        (SystemId.EXPERIENCEOS_LOCAL_V2, "local_policy"),
    ):
        system = create_system(system_id)
        assert expected_label_part in system.memory_policy_label, system_id


# --- Committed v2 artifacts (present after generation) ------------------------------


needs_artifacts = pytest.mark.skipif(
    not LIFECYCLE_V2_DIR.exists() or not EXTERNAL_V2_DIR.exists(),
    reason="v2 artifacts not generated yet",
)


@needs_artifacts
def test_lifecycle_v2_artifact_validates():
    report = validate_lifecycle_v2(LIFECYCLE_V2_DIR)
    assert report is not None
    config = json.loads((LIFECYCLE_V2_DIR / "run_config.json").read_text())
    assert tuple(config["systems"]) == LIFECYCLE_V2_SYSTEMS
    assert config["run_id"] == "lifecycle-v2-ablation"


@needs_artifacts
def test_external_v2_artifact_validates():
    validate_external_v2(EXTERNAL_V2_DIR)
    config = json.loads(
        (EXTERNAL_V2_DIR / "external_run_config.json").read_text()
    )
    assert tuple(config["systems"]) == EXTERNAL_V2_SYSTEMS


@needs_artifacts
def test_cross_artifact_consistency():
    validate_cross_consistency(LIFECYCLE_V2_DIR, EXTERNAL_V2_DIR)


@needs_artifacts
def test_artifacts_have_no_personal_paths_or_source_data():
    for directory in (LIFECYCLE_V2_DIR, EXTERNAL_V2_DIR):
        for artifact in directory.iterdir():
            content = artifact.read_text(errors="ignore")
            assert "/Users/" not in content, artifact
            assert "/home/" not in content, artifact
    # External artifact stores context as bounded digests/previews,
    # never full official session payloads.
    first_case = json.loads(
        (EXTERNAL_V2_DIR / "cases.jsonl").read_text().splitlines()[0]
    )
    assert "context_message_digests" in first_case
    for digest_entry in first_case["context_message_digests"]:
        assert len(digest_entry.get("preview", "")) <= 120


@needs_artifacts
def test_failure_evidence_retained():
    aggregate = json.loads(
        (LIFECYCLE_V2_DIR / "aggregate.json").read_text()
    )
    outcomes = aggregate["case_outcomes"]
    for system, cells in outcomes.items():
        assert "failed" in cells or "passed" in cells, system
    failures = json.loads((LIFECYCLE_V2_DIR / "failures.json").read_text())
    assert "skipped_cases" in failures
