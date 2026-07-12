"""Orchestrate the grounded-extraction benchmark and its ablations.

Produces per-case records, per-system aggregates, the grounding and
lifecycle ablations, the development-fixture smoke (kept out of primary
aggregates), and clean skip evidence for the optional learned and Qwen
systems. Fully deterministic and offline: the default run constructs no
provider beyond the mock, loads no model, and reads no credentials.
"""

from __future__ import annotations

from benchmarks.grounded_extraction import RUN_SCHEMA_VERSION
from benchmarks.grounded_extraction.annotations import (
    load_external_annotations,
    load_lifecycle_annotations,
)
from benchmarks.grounded_extraction.evaluation import DATASET_ID, evaluate_case
from benchmarks.grounded_extraction.scoring import aggregate_system
from benchmarks.grounded_extraction.systems import (
    GROUNDED_RULES,
    LEARNED_CANDIDATE,
    LEARNED_SHADOW,
    QWEN_CEILING,
    REFERENCE,
    get_system,
)
from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.memory.grounded_extraction import (
    DeterministicGroundedExtractionController,
)
from experienceos.memory.grounding import ApprovedSource, GroundedCandidateValidator

OFFLINE_SYSTEMS = (REFERENCE, GROUNDED_RULES)
OPTIONAL_SYSTEMS = (LEARNED_SHADOW, LEARNED_CANDIDATE, QWEN_CEILING)


def run_lifecycle():
    """Evaluate the offline systems over the lifecycle annotations."""
    annotations = load_lifecycle_annotations()
    per_case = []
    aggregates = []
    for system_id in OFFLINE_SYSTEMS:
        definition = get_system(system_id)
        records = [evaluate_case(definition, ann) for ann in annotations]
        records.sort(key=lambda r: (r["system_id"], r["case_id"]))
        per_case.extend(records)
        aggregates.append(aggregate_system(system_id, records, definition))
    per_case.sort(key=lambda r: (r["system_id"], r["case_id"]))
    return annotations, per_case, aggregates


def grounding_ablation(annotations):
    """Raw controller proposals vs grounding-validated proposals.

    Benchmark-only instrumentation: it counts how the grounding
    validator filters raw deterministic proposals. It never applies an
    unsafe proposal — nothing is persisted here.
    """
    controller = DeterministicGroundedExtractionController()
    validator = GroundedCandidateValidator()
    raw = 0
    validated = 0
    removed_by_code = {}
    for ann in annotations:
        if not ann.scorable:
            continue
        proposal = controller.extract(
            ExtractionEvidence(user_text=ann.source_text,
                               provenance_label="user_asserted"))
        if proposal.recommendation != "candidate" or proposal.candidate is None:
            continue
        raw += 1
        grounding = validator.validate(
            proposal.candidate,
            ApprovedSource(source_id="bench", text=ann.source_text,
                           provenance="user_asserted"))
        if grounding.valid:
            validated += 1
        else:
            removed_by_code[grounding.code] = (
                removed_by_code.get(grounding.code, 0) + 1)
    return {
        "raw_proposals": raw,
        "validated_proposals": validated,
        "removed_by_grounding": raw - validated,
        "removed_by_code": dict(sorted(removed_by_code.items())),
    }


def lifecycle_ablation(per_case):
    """Grounded-valid vs lifecycle-eligible vs isolated-applied counts."""
    grounded = [r for r in per_case if r["system_id"] == GROUNDED_RULES]
    valid = [r for r in grounded if r["proposal_present"]]
    eligible = [r for r in valid
                if r["lifecycle_evaluation_status"] == "eligible"]
    applied_created = [r for r in grounded if r["created_memory_count"] > 0]
    downstream_selected = [r for r in grounded if r["downstream_selected"]]
    return {
        "grounded_valid_proposals": len(valid),
        "lifecycle_eligible": len(eligible),
        "isolated_applied_created_memories": sum(
            r["created_memory_count"] for r in grounded),
        "cases_with_created_memory": len(applied_created),
        "downstream_selected_cases": len(downstream_selected),
        "duplicate_active_leaks": sum(
            r["duplicate_active_leak"] for r in grounded),
    }


def fixture_smoke():
    """Development-fixture smoke: schema/rule/abstention coverage only.

    Kept entirely out of the primary benchmark aggregates. Uses the
    committed development fixtures via their existing loader.
    """
    from benchmarks.fixtures.grounded_extraction import (
        load_development_fixtures,
    )

    controller = DeterministicGroundedExtractionController()
    validator = GroundedCandidateValidator()
    fixtures = load_development_fixtures()
    positive = [f for f in fixtures if f["candidate_expected"]]
    negative = [f for f in fixtures if not f["candidate_expected"]]
    pos_proposed = 0
    neg_abstained = 0
    for f in fixtures:
        proposal = controller.extract(
            ExtractionEvidence(user_text=f["user_message"],
                               provenance_label="user_asserted"))
        accepted = False
        if proposal.recommendation == "candidate" and proposal.candidate:
            grounding = validator.validate(
                proposal.candidate,
                ApprovedSource(source_id="fx", text=f["user_message"],
                               provenance="user_asserted"))
            accepted = grounding.valid
        if f["candidate_expected"] and accepted:
            pos_proposed += 1
        if not f["candidate_expected"] and not accepted:
            neg_abstained += 1
    return {
        "fixture_count": len(fixtures),
        "positive_fixtures": len(positive),
        "negative_fixtures": len(negative),
        "positive_accepted": pos_proposed,
        "negative_abstained": neg_abstained,
        "is_primary_benchmark_evidence": False,
        "note": (
            "Development-only smoke: rule/parser/abstention coverage over "
            "the committed development fixtures. Not held-out benchmark "
            "evidence; excluded from all primary aggregates."),
    }


def optional_runs():
    """Clean skip evidence for the optional learned and Qwen systems.

    No runner is configured and no credentials are read in the default
    run, so each optional system records an explicit, non-fabricated
    skip. Deterministic fallback results are never substituted for
    learned quality.
    """
    runs = []
    for system_id in OPTIONAL_SYSTEMS:
        definition = get_system(system_id)
        runs.append({
            "system_id": system_id,
            "controller_id": definition.controller_id,
            "controller_version": definition.controller_version,
            "runner_id": definition.runner_id,
            "requires_runner": definition.requires_runner,
            "requires_credentials": definition.requires_credentials,
            "executed": False,
            "skip_reason": (
                "no optional learned runtime configured (no credentials for "
                "the Qwen ceiling)" if definition.requires_credentials
                else "no configured local learned runner available"),
            "metrics": None,
            "fallback_substituted": False,
        })
    return runs


def external_classification():
    """Classification-only summary of the external subset."""
    annotations = load_external_annotations()
    by_class = {}
    for ann in annotations:
        by_class.setdefault(ann.classification, 0)
        by_class[ann.classification] += 1
    cases = [
        {
            "case_id": a.case_id,
            "category": a.category,
            "classification": a.classification,
            "scorable": a.scorable,
            "span_scoring_available": a.span_scoring_available,
            "answer_bearing_candidate_expected":
                a.answer_bearing_candidate_expected,
            "annotation_notes": a.annotation_notes,
        }
        for a in annotations
    ]
    cases.sort(key=lambda c: c["case_id"])
    return {
        "run_schema_version": RUN_SCHEMA_VERSION,
        "dataset_id": "longmemeval-50-subset-v1",
        "total_cases": len(annotations),
        "scorable_for_extraction": 0,
        "classification_counts": dict(sorted(by_class.items())),
        "note": (
            "The external subset is a multi-session retrieval benchmark. "
            "Frozen artifacts retain only digests/previews of source text, "
            "so no exact single-message extraction oracle can be built. "
            "Classification-only; not part of the primary extraction "
            "aggregates and never an official LongMemEval score."),
        "cases": cases,
    }


def run_all():
    """Full offline run: everything needed for artifacts and the report."""
    from benchmarks.grounded_extraction.gates import (
        classify_controllers,
        evaluate_gates,
    )

    annotations, per_case, aggregates = run_lifecycle()
    optional = optional_runs()
    gates = evaluate_gates(aggregates)
    return {
        "run_schema_version": RUN_SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "systems": list(OFFLINE_SYSTEMS),
        "per_case": per_case,
        "aggregates": aggregates,
        "grounding_ablation": grounding_ablation(annotations),
        "lifecycle_ablation": lifecycle_ablation(per_case),
        "fixture_smoke": fixture_smoke(),
        "optional_runs": optional,
        "external": external_classification(),
        "gates": gates,
        "classifications": classify_controllers(gates, optional),
    }
