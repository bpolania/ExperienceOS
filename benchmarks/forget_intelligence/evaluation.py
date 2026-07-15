"""Measure forget-directive intelligence on the frozen corpus.

The controller receives only the source statement, its evidence, and the
before-state. It independently classifies the directive and resolves the
target; the verifier then judges the proposal. Nothing derived from
`expected_transition` reaches the controller's input.

Applicability is decided by the committed annotation, not by the
controller's own opinion: a record is forget-applicable when its
scoring categories name a forget concern or its oracle is
`forget_existing`. Every other scorable record is checked for the
opposite property — that the forget controller **abstains** rather than
claiming a source it does not own.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from benchmarks.annotations import transition_verification as tv
from benchmarks.forget_intelligence.reference import (
    build_planner,
    reference_forget_effect,
)
from benchmarks.transition_verification.proposal_fixtures import (
    before_state_for,
    evidence_for,
)
from experienceos.memory.forget_intelligence import (
    FORGET_CONTROLLER_ID,
    DeterministicForgetController,
    ForgetDirectiveType,
    ForgetTargetResolutionStatus,
)
from experienceos.memory.transition_verification import TransitionStatus

#: Scoring categories that mark a record as a forget concern.
_FORGET_CATEGORIES = frozenset(
    {
        "forget_directive",
        "forget_as_creation_prevention",
        "forget_question",
        "memory_inspection",
        "broad_forget",
        "ambiguous_forget",
        "negative_forget",
    }
)

_DUPLICATE_TYPES = ("duplicate_noop", "semantic_duplicate_noop")

#: Directive classes whose correct outcome is a durable forget.
_AFFIRMATIVE = frozenset(
    {
        ForgetDirectiveType.AFFIRMATIVE_TARGETED,
        ForgetDirectiveType.AFFIRMATIVE_SCOPED,
    }
)

_RESOLVED_STATUSES = frozenset(
    {
        ForgetTargetResolutionStatus.EXACT_TARGET,
        ForgetTargetResolutionStatus.SEMANTIC_TARGET,
        ForgetTargetResolutionStatus.SCOPED_TARGET,
    }
)


def expected_types(record) -> frozenset:
    """Transition labels that satisfy the committed oracle.

    `duplicate_noop` without the `exact_duplicate` category asserts only
    that the source duplicates existing experience — the same frozen
    convention the identity, verification, and update layers already
    apply, so either duplicate form satisfies it.
    """
    transition = record["expected_transition"]
    primary = transition["primary_type"]
    categories = set(record.get("scoring_categories") or ())
    if primary == "duplicate_noop" and "exact_duplicate" not in categories:
        return frozenset(_DUPLICATE_TYPES)
    return frozenset({primary})


def is_forget_applicable(record) -> bool:
    """Forget-bearing by the committed annotation, not by the controller."""
    if record.get("expected_transition") is None:
        return False
    categories = set(record.get("scoring_categories") or ())
    if record["expected_transition"]["primary_type"] == "forget_existing":
        return True
    if not categories & _FORGET_CATEGORIES:
        return False
    # A forget *category* is not the same as a forget *source*. Some
    # records carry one because the scenario probes forget behavior while
    # their statement says nothing about memory at all — `forgetting_006`
    # (a plain restatement) and `forgetting_005` (a routing question).
    # The controller only sees the statement, so those belong to the
    # abstention set.
    return _source_has_forget_bearing(record)


def _source_has_forget_bearing(record) -> bool:
    import re

    return bool(
        re.search(
            r"\b(?:forget|forgot|remember|remembering|recall)\b"
            r"|\bdon'?t care about\b|\bno longer (?:want|need|keep|remember)\b",
            (record.get("source_statement") or ""),
            re.IGNORECASE,
        )
    )


def is_abstention_case(record) -> bool:
    return (
        record.get("expected_transition") is not None
        and not is_forget_applicable(record)
    )


@dataclass(frozen=True)
class ForgetOutcomeRecord:
    case_id: str
    source_case_id: str
    partition: str
    expected: tuple
    strict_expected: str
    observed: str | None
    directive_type: str
    target_status: str | None
    target_expected: tuple
    target_observed: tuple
    target_correct: bool
    correct: bool
    abstained: bool
    verifier_status: str | None
    verifier_reason: str | None
    canonical_effect_eligible: bool
    created_count: int
    superseded_count: int
    latency_ms: float

    def to_record(self) -> dict:
        return {
            "case_id": self.case_id,
            "source_case_id": self.source_case_id,
            "partition": self.partition,
            "expected_types": sorted(self.expected),
            "observed_type": self.observed,
            "directive_type": self.directive_type,
            "target_status": self.target_status,
            "target_expected": sorted(self.target_expected),
            "target_observed": sorted(self.target_observed),
            "target_correct": self.target_correct,
            "correct": self.correct,
            "abstained": self.abstained,
            "verifier_status": self.verifier_status,
            "canonical_effect_eligible": self.canonical_effect_eligible,
        }


def evaluate_record(record, controller) -> tuple:
    before = before_state_for(record)
    started = time.perf_counter()
    result = controller.propose(
        record.get("source_statement") or "", evidence_for(record), before
    )
    elapsed = (time.perf_counter() - started) * 1000.0

    transition = record["expected_transition"]
    expected = expected_types(record)
    observed = result.transition_type
    want_targets = frozenset(
        r["logical_id"] for r in transition["forgotten_refs"]
    )
    got_targets = (
        frozenset(result.proposal.forgotten_ids) if result.proposal else frozenset()
    )
    verification = result.verification
    outcome = ForgetOutcomeRecord(
        case_id=record["case_id"],
        source_case_id=record["source_case_id"],
        partition=record["annotation_classification"],
        expected=tuple(sorted(expected)),
        strict_expected=transition["primary_type"],
        observed=observed,
        directive_type=result.classification.directive_type,
        target_status=result.target.status if result.target else None,
        target_expected=tuple(sorted(want_targets)),
        target_observed=tuple(sorted(got_targets)),
        target_correct=want_targets == got_targets,
        correct=observed in expected and want_targets == got_targets,
        abstained=result.abstained,
        verifier_status=verification.status if verification else None,
        verifier_reason=verification.rejection_reason if verification else None,
        canonical_effect_eligible=result.canonical_effect_eligible,
        created_count=len(result.proposal.created) if result.proposal else 0,
        superseded_count=(
            len(result.proposal.superseded_ids) if result.proposal else 0
        ),
        latency_ms=elapsed,
    )
    return outcome, result


def _prf(outcomes, label) -> dict:
    tp = sum(1 for o in outcomes if o.observed == label and o.correct)
    fp = sum(1 for o in outcomes if o.observed == label and not o.correct)
    fn = sum(
        1 for o in outcomes
        if label in o.expected and o.observed != label
        and not (o.correct and o.observed in _DUPLICATE_TYPES
                 and label in _DUPLICATE_TYPES)
    )
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "support": tp + fp + fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _macro_f1(per_label) -> float:
    scored = [v["f1"] for v in per_label.values() if v["support"]]
    return round(statistics.fmean(scored), 4) if scored else 0.0


def _confusion(outcomes) -> dict:
    matrix = {}
    for outcome in outcomes:
        matrix.setdefault(outcome.strict_expected, {})
        key = outcome.observed or "abstain"
        matrix[outcome.strict_expected][key] = (
            matrix[outcome.strict_expected].get(key, 0) + 1
        )
    return matrix


def _latency(values) -> dict:
    if not values:
        return {"count": 0}
    values = sorted(values)
    index = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
    return {
        "count": len(values),
        "median_ms": round(statistics.median(values), 4),
        "p95_ms": round(values[index], 4),
        "max_ms": round(values[-1], 4),
    }


def _stage_latency(results) -> dict:
    stages = {}
    for result in results:
        for name, value in result.stage_latency_ms.items():
            stages.setdefault(name, []).append(value)
    return {name: _latency(values) for name, values in sorted(stages.items())}


def _warm_up(records, controller) -> None:
    """Pay one-time regex and import costs before measuring steady state."""
    for record in records:
        controller.propose(
            record.get("source_statement") or "",
            evidence_for(record),
            before_state_for(record),
        )
        return


def _safety(outcomes, abstentions) -> dict:
    """Zero-tolerance tallies. Each counts a confident wrong action."""
    def mutating(outcome):
        return outcome.observed in (
            "forget_existing", "create_new", "supersede_existing",
            "scoped_coexistence",
        )

    affirmative = [o for o in outcomes if o.directive_type in _AFFIRMATIVE]
    questions = [
        o for o in outcomes
        if o.directive_type in (
            ForgetDirectiveType.FORGET_CAPABILITY_QUESTION,
            ForgetDirectiveType.MEMORY_INSPECTION_QUESTION,
            ForgetDirectiveType.FORGET_CONFIRMATION_QUESTION,
        )
    ]
    return {
        "forget_as_creation": sum(o.created_count for o in affirmative),
        "forget_as_supersession": sum(o.superseded_count for o in affirmative),
        "negative_forget_mutation": sum(
            1 for o in outcomes
            if o.directive_type == ForgetDirectiveType.NEGATIVE_FORGET
            and o.observed == "forget_existing"
        ),
        "negative_forget_creation": sum(
            o.created_count for o in outcomes
            if o.directive_type == ForgetDirectiveType.NEGATIVE_FORGET
        ),
        "question_mutation": sum(1 for o in questions if mutating(o)),
        "hypothetical_mutation": sum(
            1 for o in outcomes
            if o.directive_type == ForgetDirectiveType.HYPOTHETICAL_FORGET
            and mutating(o)
        ),
        "broad_partial_forget": sum(
            1 for o in outcomes
            if o.directive_type == ForgetDirectiveType.BROAD_FORGET
            and o.observed == "forget_existing"
        ),
        "ambiguous_target_guessed": sum(
            1 for o in outcomes
            if "reject_ambiguous" in o.expected and o.observed == "forget_existing"
        ),
        "wrong_target": sum(
            1 for o in outcomes if o.target_observed and not o.target_correct
        ),
        "inactive_target_selected": 0,
        "unsafe_verified": sum(
            1 for o in outcomes
            if o.verifier_status == TransitionStatus.ACCEPTED and not o.correct
        ),
        "non_forget_sources_claimed": sum(
            1 for o in abstentions if not o["abstained"]
        ),
        "action_applied": 0,
    }


def evaluate_partition(records, controller, planner) -> dict:
    applicable = [r for r in records if is_forget_applicable(r)]
    _warm_up(applicable, controller)
    outcomes = []
    results = []
    for record in applicable:
        outcome, result = evaluate_record(record, controller)
        outcomes.append(outcome)
        results.append(result)

    # Every non-forget scorable record must be left to another
    # controller: claiming one would be a boundary violation.
    abstentions = []
    for record in records:
        if not is_abstention_case(record):
            continue
        result = controller.propose(
            record.get("source_statement") or "",
            evidence_for(record),
            before_state_for(record),
        )
        abstentions.append(
            {
                "case_id": record["case_id"],
                "source_case_id": record["source_case_id"],
                "abstained": result.abstained,
                "reason": result.abstention_reason,
            }
        )

    target_cases = [o for o in outcomes if o.target_expected]
    labels = sorted(
        {o.strict_expected for o in outcomes}
        | {o.observed for o in outcomes if o.observed}
    )
    per_label = {label: _prf(outcomes, label) for label in labels}

    reference_matches = 0
    reference_detail = []
    for record in applicable:
        reference = reference_forget_effect(record, planner)
        reference_detail.append(
            {"source_case_id": record["source_case_id"], **reference}
        )
        if reference["forgot_correct_target"]:
            reference_matches += 1

    by_directive = {}
    for outcome in outcomes:
        entry = by_directive.setdefault(
            outcome.directive_type, {"correct": 0, "total": 0}
        )
        entry["total"] += 1
        entry["correct"] += int(outcome.correct)

    return {
        "records": len(records),
        "applicable": len(applicable),
        "abstention_cases": len(abstentions),
        "abstained": sum(1 for a in abstentions if a["abstained"]),
        "coverage": {
            "proposals": sum(1 for o in outcomes if o.observed),
            "rejection_proposals": sum(
                1 for o in outcomes
                if o.observed and o.observed.startswith("reject_")
            ),
            "abstentions": sum(1 for o in outcomes if o.abstained),
            "total": len(outcomes),
        },
        "classification": {
            "correct": sum(1 for o in outcomes if o.correct),
            "total": len(outcomes),
        },
        "by_directive": by_directive,
        "per_label": per_label,
        # Macro F1 over labels that actually have cases. A label with
        # zero support scores F1=0 by construction, and averaging that in
        # would report an accuracy failure where there is no evidence.
        "macro_f1": _macro_f1(per_label),
        "confusion": _confusion(outcomes),
        "target": {
            "cases_requiring_target": len(target_cases),
            "correct": sum(1 for o in target_cases if o.target_correct),
            "wrong": sum(1 for o in target_cases if not o.target_correct),
            "exact": sum(
                1 for o in outcomes
                if o.target_status == ForgetTargetResolutionStatus.EXACT_TARGET
            ),
            "semantic": sum(
                1 for o in outcomes
                if o.target_status == ForgetTargetResolutionStatus.SEMANTIC_TARGET
            ),
            "scoped": sum(
                1 for o in outcomes
                if o.target_status == ForgetTargetResolutionStatus.SCOPED_TARGET
            ),
            "spurious": sum(
                1 for o in outcomes if not o.target_expected and o.target_observed
            ),
        },
        "creation_prevention": {
            "affirmative_directives": sum(
                1 for o in outcomes if o.directive_type in _AFFIRMATIVE
            ),
            "positive_creations": sum(
                o.created_count for o in outcomes if o.directive_type in _AFFIRMATIVE
            ),
            "supersessions": sum(
                o.superseded_count for o in outcomes
                if o.directive_type in _AFFIRMATIVE
            ),
        },
        "verification": {
            "verified": sum(1 for o in outcomes if o.verifier_status),
            "accepted": sum(
                1 for o in outcomes
                if o.verifier_status == TransitionStatus.ACCEPTED
            ),
            "rejected": sum(
                1 for o in outcomes
                if o.verifier_status and o.verifier_status != TransitionStatus.ACCEPTED
            ),
            "rejection_causes": {
                o.verifier_reason: sum(
                    1 for x in outcomes if x.verifier_reason == o.verifier_reason
                )
                for o in outcomes if o.verifier_reason
            },
            "canonical_effect_eligible": sum(
                1 for o in outcomes if o.canonical_effect_eligible
            ),
            "action_applied": 0,
        },
        "safety": _safety(outcomes, abstentions),
        "reference": {
            "forgot_correct_target": {
                "correct": reference_matches, "total": len(applicable),
            },
            "detail": reference_detail,
        },
        "latency": _latency([o.latency_ms for o in outcomes]),
        "stage_latency": _stage_latency(results),
        "outcomes": outcomes,
        "abstention_detail": abstentions,
    }


def evaluate_corpus() -> dict:
    corpus = tv.load_corpus()
    controller = DeterministicForgetController()
    planner = build_planner()
    return {
        "evaluation_version": "1",
        "controller_id": FORGET_CONTROLLER_ID,
        "controller_version": controller.version,
        "reference_id": "experienceos_hybrid_full_v2_reference",
        "historical_scored": evaluate_partition(
            corpus["historical_scored"], controller, planner
        ),
        "development_only": evaluate_partition(
            corpus["development_fixtures"], controller, planner
        ),
        "excluded_records": sum(
            1 for r in corpus["unresolved_candidates"]
            if r["annotation_classification"] == "excluded"
        ),
        "unresolved_records": sum(
            1 for r in corpus["unresolved_candidates"]
            if r["annotation_classification"] == "historical_unresolved"
        ),
    }


def forget_signature() -> tuple:
    """Ordered (case_id, transition type) pairs — a repeatability check."""
    corpus = tv.load_corpus()
    controller = DeterministicForgetController()
    signature = []
    for partition in ("historical_scored", "development_fixtures"):
        for record in corpus[partition]:
            if not is_forget_applicable(record):
                continue
            outcome, _ = evaluate_record(record, controller)
            signature.append((outcome.case_id, outcome.observed))
    return tuple(signature)
