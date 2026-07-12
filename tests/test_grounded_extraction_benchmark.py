"""Grounded-extraction benchmark: systems, scoring, artifacts, isolation."""

import json

import pytest

from benchmarks.artifacts.writer import normalized_digest
from benchmarks.grounded_extraction import artifacts as artifact_mod
from benchmarks.grounded_extraction.annotations import load_lifecycle_annotations
from benchmarks.grounded_extraction.evaluation import evaluate_case
from benchmarks.grounded_extraction.gates import evaluate_gates
from benchmarks.grounded_extraction.report import (
    build_report_data,
    comparison_csv,
    comparison_markdown,
    render_report,
)
from benchmarks.grounded_extraction.runner import run_all, run_lifecycle
from benchmarks.grounded_extraction.systems import (
    GROUNDED_RULES,
    REFERENCE,
    REGISTRY,
    get_system,
)

ANNS = {a.case_id: a for a in load_lifecycle_annotations()}
RESULT = run_all()
AGGS = {a["system_id"]: a for a in RESULT["aggregates"]}


# ---- system configuration ------------------------------------------------

def test_reference_disables_grounded_extraction():
    ref = get_system(REFERENCE)
    assert ref.controller_type == "none"
    assert ref.controller_id is None


def test_grounded_rules_configuration():
    grd = get_system(GROUNDED_RULES)
    assert grd.controller_type == "deterministic"
    assert grd.controller_id == "grounded_rules-1"
    assert grd.fallback_mode == "none"


def test_config_digest_is_deterministic():
    for definition in REGISTRY.values():
        assert definition.config_digest() == definition.config_digest()


def test_system_ids_are_distinct():
    ids = [d.system_id for d in REGISTRY.values()]
    assert len(ids) == len(set(ids))


def test_unknown_system_rejected():
    with pytest.raises(KeyError):
        get_system("nope")


# ---- proposal / grounding / lifecycle scoring ----------------------------

def test_true_positive_case():
    rec = evaluate_case(get_system(GROUNDED_RULES),
                        ANNS["creation_001_explicit_scoped_preference"])
    assert rec["proposal_present"] is True
    assert rec["proposal_score"] == "true_positive"
    assert rec["grounding_status"] is True


def test_false_negative_on_missed_fact():
    rec = evaluate_case(get_system(GROUNDED_RULES),
                        ANNS["creation_002_durable_user_fact"])
    assert rec["proposal_present"] is False
    assert rec["proposal_score"] == "false_negative"


def test_false_positive_on_forget_directive():
    rec = evaluate_case(get_system(GROUNDED_RULES),
                        ANNS["forgetting_003_forget_one_of_several"])
    assert rec["proposal_present"] is True
    assert rec["proposal_score"] == "false_positive"


def test_true_negative_on_question():
    rec = evaluate_case(get_system(GROUNDED_RULES),
                        ANNS["retrieval_006_no_memory_needed"])
    assert rec["proposal_present"] is False
    assert rec["proposal_score"] == "true_negative"


def test_duplicate_excluded_from_precision_recall():
    rec = evaluate_case(get_system(GROUNDED_RULES),
                        ANNS["creation_005_exact_duplicate_restatement"])
    assert rec["proposal_score"] == "duplicate"


def test_zero_denominator_reports_undefined_not_zero():
    ref = AGGS[REFERENCE]
    # reference has no grounded proposals; precision must be null, not 0.
    assert ref["creation_metrics"]["precision"] is None


def test_no_candidate_precision_and_recall_present():
    grd = AGGS[GROUNDED_RULES]
    nc = grd["no_candidate_metrics"]
    assert nc["no_candidate_recall"]["denominator"] == 24
    assert nc["no_candidate_precision"]["rate"] is not None


# ---- durable / safety layer ----------------------------------------------

def test_reference_and_adopted_creation_recall_measured():
    assert AGGS[REFERENCE]["creation_metrics"][
        "durable_creation_recall"]["denominator"] == 13
    assert AGGS[GROUNDED_RULES]["creation_metrics"][
        "durable_creation_recall"]["denominator"] == 13


def test_state_corruption_zero_for_both_systems():
    for agg in RESULT["aggregates"]:
        assert agg["safety_metrics"]["state_corruption"] == 0


def test_duplicate_active_leak_is_surfaced_not_hidden():
    # The semantic-dedup gap is real; the benchmark must report it.
    assert AGGS[GROUNDED_RULES]["safety_metrics"][
        "duplicate_active_memories"] >= 1


def test_stale_active_memory_kept_separate_from_corruption():
    for rec in RESULT["per_case"]:
        # a stale/leak signal never counts as direct corruption
        assert rec["state_corruption"] == 0


# ---- learned attribution / optional skips --------------------------------

def test_optional_systems_skip_cleanly_without_fabrication():
    for run in RESULT["optional_runs"]:
        assert run["executed"] is False
        assert run["metrics"] is None
        assert run["fallback_substituted"] is False
        assert run["skip_reason"]


def test_fixture_smoke_is_not_primary_evidence():
    fx = RESULT["fixture_smoke"]
    assert fx["is_primary_benchmark_evidence"] is False
    assert fx["fixture_count"] == 37


# ---- ablations -----------------------------------------------------------

def test_grounding_ablation_counts_reconcile():
    ga = RESULT["grounding_ablation"]
    assert ga["validated_proposals"] + ga["removed_by_grounding"] == (
        ga["raw_proposals"])


def test_lifecycle_ablation_reports_leaks():
    la = RESULT["lifecycle_ablation"]
    assert la["duplicate_active_leaks"] >= 1


# ---- gates ---------------------------------------------------------------

def test_gates_not_reinterpreted_and_recall_gate_fails():
    gates = evaluate_gates(RESULT["aggregates"])
    by_name = {g["gate"]: g for g in gates["gates"]}
    assert by_name["creation_recall_or_absence_improvement"]["status"] == (
        "fail")
    assert by_name["duplicate_active_memories"]["status"] == "fail"


def test_classification_is_shadow_only_not_adopted():
    classes = {c["system_id"]: c["classification"]
               for c in RESULT["classifications"]}
    assert classes[GROUNDED_RULES] == "shadow_only"
    assert "adopted" not in classes[GROUNDED_RULES]


# ---- artifact generation & determinism -----------------------------------

def test_two_run_digest_equality():
    a = run_all()
    b = run_all()

    def digest(result):
        return normalized_digest(result["per_case"], {
            "aggregates": result["aggregates"],
            "grounding_ablation": result["grounding_ablation"],
            "lifecycle_ablation": result["lifecycle_ablation"],
            "fixture_smoke": result["fixture_smoke"],
            "optional_runs": result["optional_runs"],
            "external": result["external"],
            "gates": result["gates"],
        })

    assert digest(a) == digest(b)


def test_comparison_table_deterministic():
    assert comparison_markdown(RESULT) == comparison_markdown(RESULT)
    assert comparison_csv(RESULT) == comparison_csv(RESULT)


def test_artifacts_write_validate_and_protect_overwrite(tmp_path):
    out = tmp_path / "grounded-extraction-ablation"
    artifact_mod.write_ablation_dir(RESULT, out)
    manifest = artifact_mod.validate_dir(out)
    assert manifest["normalized_result_digest"]
    # idempotent rewrite of identical content is allowed
    artifact_mod.write_ablation_dir(RESULT, out)
    # a genuinely different digest without overwrite is refused
    mutated = dict(RESULT)
    mutated["per_case"] = RESULT["per_case"][:1]
    with pytest.raises(artifact_mod.OverwriteError):
        artifact_mod.write_ablation_dir(mutated, out)


def test_report_data_and_render_are_stable():
    data = build_report_data(RESULT)
    assert json.dumps(data, sort_keys=True) == json.dumps(
        build_report_data(RESULT), sort_keys=True)
    report = render_report(RESULT)
    assert "shadow_only" in report
    assert "official LongMemEval" in report  # in the "not claimed" section


# ---- isolation -----------------------------------------------------------

def test_evaluation_uses_isolated_state_no_cross_case_leak():
    # Each case starts from a fresh store: a negative evaluated after a
    # positive still creates nothing.
    grd = get_system(GROUNDED_RULES)
    pos = evaluate_case(grd, ANNS["creation_001_explicit_scoped_preference"])
    neg = evaluate_case(grd, ANNS["retrieval_006_no_memory_needed"])
    assert pos["created_memory_count"] >= 1
    assert neg["created_memory_count"] == 0


def test_external_never_enters_primary_aggregates():
    assert RESULT["external"]["scorable_for_extraction"] == 0
    # aggregates only reference the lifecycle dataset
    for agg in RESULT["aggregates"]:
        assert agg["dataset_id"] == "experienceos-lifecycle-v1"


# ---- committed artifacts -------------------------------------------------

def test_committed_artifacts_validate():
    from pathlib import Path

    from benchmarks.grounded_extraction.annotations import REPO_ROOT

    root = REPO_ROOT / "benchmarks/results/committed"
    for name in ("grounded-extraction-ablation", "grounded-extraction",
                 "report-grounded-extraction"):
        directory = root / name
        assert directory.exists(), directory
        manifest = artifact_mod.validate_dir(directory)
        assert manifest["normalized_result_digest"]


def test_committed_digest_matches_fresh_run():
    from pathlib import Path

    from benchmarks.grounded_extraction.annotations import REPO_ROOT

    committed = json.loads(
        (REPO_ROOT / "benchmarks/results/committed"
         / "grounded-extraction-ablation" / "artifact_manifest.json"
         ).read_text())["normalized_result_digest"]
    fresh = artifact_mod._digest_payload(run_all())
    assert committed == fresh
