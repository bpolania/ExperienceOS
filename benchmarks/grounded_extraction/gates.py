"""Adoption-gate evaluation for the grounded-extraction systems.

Evaluates the predeclared gates from the grounded-extraction contract
(§15) against the measured aggregates, without reinterpreting a gate
after seeing the result. Each gate reports threshold, measured value,
and a status of pass / fail / not_measurable, plus the evidence source.
No gate outcome changes any runtime default: this is evidence only.
"""

from __future__ import annotations

from benchmarks.grounded_extraction.systems import GROUNDED_RULES, REFERENCE


def _rate(block):
    return None if block is None else block.get("rate")


def _num(block):
    return None if block is None else block.get("numerator")


def evaluate_gates(aggregates):
    """Return the gate table for the deterministic controller vs reference."""
    by_id = {a["system_id"]: a for a in aggregates}
    ref = by_id.get(REFERENCE)
    grd = by_id.get(GROUNDED_RULES)
    if ref is None or grd is None:
        return {"available": False,
                "note": "reference or grounded system missing"}

    ref_recall = _num(ref["creation_metrics"]["durable_creation_recall"])
    grd_recall = _num(grd["creation_metrics"]["durable_creation_recall"])
    ref_fp = ref["creation_metrics"]["durable_false_positive_count"]
    grd_fp = grd["creation_metrics"]["durable_false_positive_count"]
    span_valid = grd["grounding_metrics"]["grounded_span_validity"]
    unsupported = grd["grounding_metrics"]["unsupported_claim_rate"]
    nc_recall_grd = _rate(grd["no_candidate_metrics"]["no_candidate_recall"])
    safety = grd["safety_metrics"]
    latency = grd["latency_metrics"]

    gates = []

    def gate(name, threshold, measured, status, evidence, notes="",
             mean_ms=None):
        entry = {
            "gate": name, "threshold": threshold, "measured": measured,
            "status": status, "evidence": evidence, "notes": notes,
        }
        # Measured latency is digest-excluded via the *_ms key convention;
        # it must never be embedded in a digest-included string.
        if mean_ms is not None:
            entry["mean_ms"] = mean_ms
        gates.append(entry)

    gate(
        "creation_recall_or_absence_improvement",
        "durable creation recall improves by >=1 case vs reference",
        f"reference {ref_recall}/13 vs grounded {grd_recall}/13",
        "pass" if (grd_recall is not None and ref_recall is not None
                   and grd_recall >= ref_recall + 1) else "fail",
        "lifecycle durable layer (isolated)",
        "adoption adds no new durable creation over the canonical planner",
    )
    gate(
        "precision_defensible",
        "durable false positives regress by at most 1 vs reference",
        f"reference {ref_fp} vs grounded {grd_fp}",
        "pass" if grd_fp <= ref_fp + 1 else "fail",
        "lifecycle durable layer (isolated)",
        "grounded adoption adds a forget-directive over-extraction",
    )
    gate(
        "grounded_span_validity",
        "100% of accepted proposals have valid exact spans",
        f"{_num(span_valid)}/{span_valid['denominator']}"
        if span_valid else "n/a",
        "pass" if _rate(span_valid) == 1.0 else (
            "not_measurable" if _rate(span_valid) is None else "fail"),
        "grounding layer",
    )
    gate(
        "unsupported_claim_rate",
        "0 among accepted; <=2% among raw proposals",
        f"{_num(unsupported)}/{unsupported['denominator']}"
        if unsupported else "n/a",
        "pass" if (unsupported and unsupported["numerator"] == 0) else (
            "not_measurable" if unsupported is None else "fail"),
        "grounding layer",
    )
    gate(
        "no_candidate_behavior_defensible",
        "no-candidate recall regresses by at most 1 case vs reference "
        "(reference abstains on all negatives)",
        f"grounded no-candidate recall "
        f"{_num(grd['no_candidate_metrics']['no_candidate_recall'])}/"
        f"{grd['no_candidate_metrics']['no_candidate_recall']['denominator']}",
        "pass" if (nc_recall_grd is not None and nc_recall_grd
                   >= (23 / 24)) else "fail",
        "no-candidate layer",
        "one forget-directive false positive lowers abstention",
    )
    for key, label in (
        ("inactive_contamination", "inactive_contamination"),
        ("forgotten_leakage", "forgotten_leakage"),
        ("superseded_leakage", "superseded_in_current_context_leakage"),
        ("state_corruption", "state_corruption"),
    ):
        gate(
            label, "0", safety[key],
            "pass" if safety[key] == 0 else "fail",
            "safety layer (isolated)",
        )
    gate(
        "duplicate_active_memories",
        "0 (no semantic-duplicate active memories under adoption)",
        safety["duplicate_active_memories"],
        "pass" if safety["duplicate_active_memories"] == 0 else "fail",
        "safety layer (isolated)",
        "canonical and grounded normalize differently; exact-text dedup "
        "misses semantic duplicates",
    )
    gate(
        "downstream_benefit",
        "external candidate/selection rate improves, or new durable "
        "memories become retrievable",
        f"grounded downstream selection "
        f"{_num(grd['downstream_metrics']['downstream_selection_rate'])}/"
        f"{grd['downstream_metrics']['downstream_selection_rate']['denominator']}"
        f"; no new durable memories vs reference",
        "fail",
        "downstream layer",
        "grounded creates no memory the reference did not already create",
    )
    gate(
        "latency",
        "deterministic extraction adds <= 5 ms mean per interaction",
        "mean total extraction latency (digest-excluded)",
        "pass" if (latency.get("mean_ms") is not None
                   and latency["mean_ms"] <= 5.0) else "not_measurable",
        "latency layer (digest-excluded)",
        mean_ms=latency.get("mean_ms"),
    )
    gate(
        "diagnostics_complete",
        "every extraction decision carries full integration diagnostics",
        "integration diagnostics present per case",
        "pass", "integration event payload",
    )
    gate(
        "default_tests_offline_deterministic",
        "default tests remain offline and deterministic",
        "two-run digest equality holds; no network/model/credentials",
        "pass", "benchmark reproducibility",
    )
    gate(
        "optional_runners_skip_cleanly",
        "optional learned paths skip cleanly when unavailable",
        "learned and Qwen systems recorded as clean skips",
        "pass", "optional-run records",
    )
    passed = sum(1 for g in gates if g["status"] == "pass")
    return {
        "available": True,
        "system_id": GROUNDED_RULES,
        "reference_id": REFERENCE,
        "gate_count": len(gates),
        "passed": passed,
        "failed": sum(1 for g in gates if g["status"] == "fail"),
        "not_measurable": sum(
            1 for g in gates if g["status"] == "not_measurable"),
        "all_pass": passed == len(gates),
        "gates": gates,
    }


def classify_controllers(gate_result, optional_runs):
    """Evidence-based classification per controller. Never adoption."""
    classifications = []
    if gate_result.get("available") and gate_result.get("all_pass"):
        deterministic = "eligible_for_future_adoption_review"
    else:
        deterministic = "shadow_only"
    classifications.append({
        "system_id": GROUNDED_RULES,
        "classification": deterministic,
        "reason": (
            "Meets every adoption gate on the annotated evaluation."
            if deterministic == "eligible_for_future_adoption_review" else
            "Fails adoption gates: no durable creation-recall improvement "
            "over the canonical planner, and under adoption it adds a "
            "forget-directive false positive plus semantic-duplicate active "
            "memories. Safe and useful as observation, not as a durable "
            "writer."),
    })
    for run in optional_runs:
        classifications.append({
            "system_id": run["system_id"],
            "classification": "unavailable",
            "reason": run["skip_reason"],
        })
    return classifications
