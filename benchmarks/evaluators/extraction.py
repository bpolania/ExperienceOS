"""Phase 9 extraction evaluator: v2-only observational contributions.

Reads the hybrid-extraction diagnostics counters a v2 adapter records
per case (``result.diagnostics["extraction_v2"]``) and converts them
into raw metric contributions. Systems without extraction diagnostics
— every v1 system — contribute nothing, so Phase 8 evaluation output
is byte-identical for them.

All extraction_v2 metrics are neutral/observational: they never decide
case outcomes. Creation precision/recall and the other Phase 8 metrics
keep judging quality under their existing, unchanged definitions.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution


def extraction_contributions(case, result):
    counters = result.diagnostics.get("extraction_v2")
    if not isinstance(counters, dict):
        return []

    def count(key) -> float:
        value = counters.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    gated = count("gate_passed") + count("gate_rejected")
    proposed = count("candidates_proposed")
    invocations = count("extractor_invocations")
    evidence = {
        "scenario_id": case.scenario_id,
        "extraction_strategy": counters.get("extraction_strategy"),
        "candidate_extractor": counters.get("candidate_extractor"),
    }
    return [
        contribution(
            "durability_gate_pass_rate_v2",
            count("gate_passed"), gated, **evidence,
        ),
        contribution(
            "auxiliary_extractor_invocation_rate_v2",
            invocations, count("turns"), **evidence,
        ),
        contribution(
            "candidate_acceptance_rate_v2",
            count("candidates_accepted"), proposed, **evidence,
        ),
        contribution(
            "candidate_grounding_rejection_rate_v2",
            count("candidates_grounding_rejected"), proposed, **evidence,
        ),
        contribution(
            "candidate_schema_rejection_rate_v2",
            count("candidates_schema_rejected"), proposed, **evidence,
        ),
        contribution(
            "duplicate_candidate_rate_v2",
            count("candidates_duplicate"), proposed, **evidence,
        ),
        contribution(
            "extraction_failure_safe_rate_v2",
            count("extractor_failed_safe"), invocations, **evidence,
        ),
        contribution(
            "accepted_candidates_per_invocation_v2",
            count("candidates_accepted"), invocations, **evidence,
        ),
    ]
