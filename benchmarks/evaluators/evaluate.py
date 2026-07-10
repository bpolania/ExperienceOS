"""Per-case evaluation orchestrator.

Runs after execution only — the oracle never reaches a system. The
raw CaseResult is read, never mutated. Case outcome labels are a
navigation aid; the benchmark's conclusions come from the aggregate
metric table.
"""

from __future__ import annotations

from benchmarks.contract import CaseStatus
from benchmarks.evaluators.context import context_contributions
from benchmarks.evaluators.leakage import leakage_contributions
from benchmarks.evaluators.lifecycle import (
    forgetting_contributions,
    memory_write_contributions,
    update_contributions,
)
from benchmarks.evaluators.local_policy import local_policy_contributions
from benchmarks.evaluators.extraction import extraction_contributions
from benchmarks.evaluators.retrieval_v2 import retrieval_v2_contributions
from benchmarks.evaluators.records import CaseEvaluation, CaseOutcome
from benchmarks.evaluators.resolve import entries_of, resolve_ref
from benchmarks.evaluators.response import response_contributions
from benchmarks.evaluators.retrieval import retrieval_contributions
from benchmarks.evaluators.operational import operational_contributions


def _resolve_oracle(case, result) -> tuple[dict, list[dict]]:
    """Resolve every oracle reference; report problems explicitly."""
    resolution: dict = {}
    problems: list[dict] = []
    scopes = (
        ("active", case.expected.active, entries_of(result.final_active)),
        (
            "superseded",
            case.expected.superseded,
            entries_of(result.final_superseded),
        ),
        (
            "forgotten",
            case.expected.forgotten,
            entries_of(result.final_forgotten),
        ),
    )
    for scope, refs, entries in scopes:
        for ref in refs:
            resolved = resolve_ref(ref, entries)
            resolution[f"{scope}:{ref.logical_id}"] = resolved.to_payload()
            if resolved.status == "ambiguous":
                problems.append(
                    {
                        "type": "ambiguous_reference",
                        "scope": scope,
                        "logical_id": ref.logical_id,
                        "memory_ids": list(resolved.memory_ids),
                    }
                )
    return resolution, problems


def evaluate_case(case, result) -> CaseEvaluation:
    evaluation = CaseEvaluation(
        scenario_id=case.scenario_id,
        system_id=result.system_id,
        execution_status=result.status,
    )
    if result.status == CaseStatus.SKIPPED:
        evaluation.outcome = CaseOutcome.SKIPPED
        evaluation.eligible = False
        evaluation.notes.append(result.skip_reason or "skipped")
        return evaluation
    if result.status == CaseStatus.PARTIAL and not result.turns:
        evaluation.outcome = CaseOutcome.EXECUTION_FAILED
        evaluation.eligible = False
        evaluation.failures.append(
            {
                "type": "system_execution_failure",
                "reason": result.failure_reason,
            }
        )
        return evaluation

    try:
        resolution, problems = _resolve_oracle(case, result)
        evaluation.resolution = resolution
        evaluation.failures.extend(problems)

        evaluation.contributions.extend(
            memory_write_contributions(case, result)
        )
        evaluation.contributions.extend(update_contributions(case, result))
        evaluation.contributions.extend(
            forgetting_contributions(case, result)
        )
        evaluation.contributions.extend(
            retrieval_contributions(case, result)
        )
        evaluation.contributions.extend(leakage_contributions(case, result))
        response_out, constraints, deferred = response_contributions(
            case, result
        )
        evaluation.contributions.extend(response_out)
        evaluation.constraint_results = constraints
        evaluation.deferred.extend(deferred)
        evaluation.contributions.extend(context_contributions(case, result))
        evaluation.contributions.extend(
            operational_contributions(case, result)
        )
        if result.system_id == "experienceos_local":
            evaluation.contributions.extend(
                local_policy_contributions(case, result)
            )
        # v2-only: these yield nothing unless the result carries hybrid
        # extraction/retrieval diagnostics, so v1 evaluation stays
        # byte-identical.
        evaluation.contributions.extend(extraction_contributions(case, result))
        evaluation.contributions.extend(
            retrieval_v2_contributions(case, result)
        )
    except Exception as exc:  # noqa: BLE001 — evaluator failure is evidence
        evaluation.outcome = CaseOutcome.FAILED
        evaluation.failures.append(
            {
                "type": "evaluator_failure",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
        return evaluation

    if result.status == CaseStatus.PARTIAL:
        evaluation.outcome = CaseOutcome.PARTIAL
        evaluation.failures.append(
            {
                "type": "system_execution_failure",
                "reason": result.failure_reason,
            }
        )
    elif evaluation.deferred and not evaluation.contributions:
        evaluation.outcome = CaseOutcome.EVALUATION_DEFERRED
    else:
        applicable = [
            c for c in evaluation.contributions if c.applicable
        ]
        fully_met = all(
            c.numerator == c.denominator
            for c in applicable
            if _is_success_style(c.metric)
        )
        clean = not any(
            c.numerator > 0
            for c in applicable
            if _is_contamination_style(c.metric)
        )
        if evaluation.deferred:
            evaluation.outcome = CaseOutcome.PARTIAL
        elif fully_met and clean and not problems:
            evaluation.outcome = CaseOutcome.PASSED
        else:
            evaluation.outcome = CaseOutcome.FAILED
    return evaluation


_CONTAMINATION_METRICS = frozenset(
    (
        "duplicate_acceptance_rate",
        "conflicting_active_memory_rate",
        "stale_candidate_leakage_rate",
        "stale_selected_leakage_rate",
        "stale_context_leakage_rate",
        "stale_response_contamination_rate",
        "forgotten_response_contamination_rate",
        "memory_resurrection_rate",
        "inactive_contamination_rate",
        "local_state_corruption_rate",
        "duplicate_proposal_rate",
        "fallback_rate",
    )
)

_NEUTRAL_METRICS = frozenset(
    (
        "durability_gate_pass_rate_v2",
        "auxiliary_extractor_invocation_rate_v2",
        "candidate_acceptance_rate_v2",
        "candidate_grounding_rejection_rate_v2",
        "candidate_schema_rejection_rate_v2",
        "duplicate_candidate_rate_v2",
        "extraction_failure_safe_rate_v2",
        "accepted_candidates_per_invocation_v2",
        "retrieval_candidate_rate_v2",
        "zero_relevance_exclusion_v2",
        "inactive_candidate_filter_rate_v2",
        "retrieval_k_compliance_v2",
        "retrieval_budget_compliance_v2",
        "unresolved_conflict_selection_rate_v2",
        "memory_token_share",
        "relevant_token_share",
        "compression_ratio",
        "context_budget_utilization",
        "mean_reciprocal_rank",
        "experience_use_rate",
        "fallback_rate",
        "duplicate_proposal_rate",
        "local_valid_proposal_rate",
        "rejection_containment_rate",
    )
)


def _is_contamination_style(name: str) -> bool:
    return name in _CONTAMINATION_METRICS and name not in (
        "duplicate_proposal_rate",
        "fallback_rate",
    )


def _is_success_style(name: str) -> bool:
    return (
        name not in _CONTAMINATION_METRICS
        and name not in _NEUTRAL_METRICS
    )
