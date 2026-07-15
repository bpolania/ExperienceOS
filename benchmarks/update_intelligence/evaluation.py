"""Measure deterministic update intelligence on the frozen corpus.

The controller receives only the source statement, its evidence, and the
before-state. It independently chooses intent, transition type, target,
created value, scope, and preservation set; the verifier then judges the
proposal. Nothing here reads the expected transition into the
controller's input.

Two boundaries are kept explicit:

- **Forget cases are scored on the forget boundary, not on transition
  classification.** Formal forget targeting is a separate concern, so an
  affirmative forget directive is expected to hand off. What is measured
  is that it creates nothing positive.
- **Duplicate labels follow the frozen convention.** `duplicate_noop`
  without the `exact_duplicate` category asserts only "this duplicates
  existing experience" — either duplicate form satisfies it, exactly as
  the identity and verification layers already treat it. Strict
  label-equality accuracy is reported alongside so the convention hides
  nothing.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from benchmarks.annotations import transition_verification as tv
from benchmarks.transition_verification.proposal_fixtures import (
    before_state_for,
    evidence_for,
)
from benchmarks.update_intelligence.reference import (
    build_planner,
    oracle_effect,
    proposal_effect,
    reference_effect,
)
from experienceos.memory.transition_verification import TransitionStatus
from experienceos.memory.update_intelligence import (
    UPDATE_CONTROLLER_ID,
    DeterministicUpdateController,
    UpdateIntentType,
)

#: Cases whose source is an affirmative forget directive. Scored on the
#: forget boundary; formal forget targeting is out of scope here.
FORGET_BOUNDARY_CASES = frozenset(
    {
        "forgetting_001_exact_forget",
        "forgetting_002_paraphrased_forget",
        "forgetting_003_forget_one_of_several",
        "forgetting_004_forget_after_supersession",
        "forget_directive-01",
        "ambiguous_forget-01",
        "broad_forget-01",
    }
)

_DUPLICATE_TYPES = ("duplicate_noop", "semantic_duplicate_noop")
_REJECTION_TYPES = frozenset(
    {
        "reject_temporary",
        "reject_question",
        "reject_hypothetical",
        "reject_ambiguous",
        "reject_unsupported",
        "reject_forget_directive_as_creation",
        "reject_unrelated",
    }
)


def expected_types(record) -> frozenset:
    """Transition labels that satisfy the committed oracle."""
    transition = record["expected_transition"]
    primary = transition["primary_type"]
    categories = set(record.get("scoring_categories") or ())
    if primary == "duplicate_noop" and "exact_duplicate" not in categories:
        return frozenset(_DUPLICATE_TYPES)
    return frozenset({primary})


def is_forget_boundary(record) -> bool:
    return record["source_case_id"] in FORGET_BOUNDARY_CASES


def is_classification_applicable(record) -> bool:
    return (
        record.get("expected_transition") is not None
        and not is_forget_boundary(record)
    )


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    source_case_id: str
    partition: str
    expected: tuple
    strict_expected: str
    observed: str | None
    intent: str
    abstained: bool
    correct: bool
    strict_correct: bool
    target_expected: tuple
    target_observed: tuple
    target_correct: bool
    verifier_status: str | None
    verifier_reason: str | None
    canonical_effect_eligible: bool
    effect_matches_oracle: bool
    stale_active: int
    latency_ms: float

    def to_record(self) -> dict:
        return {
            "case_id": self.case_id,
            "source_case_id": self.source_case_id,
            "partition": self.partition,
            "expected_types": sorted(self.expected),
            "observed_type": self.observed,
            "intent": self.intent,
            "correct": self.correct,
            "strict_correct": self.strict_correct,
            "target_expected": sorted(self.target_expected),
            "target_observed": sorted(self.target_observed),
            "target_correct": self.target_correct,
            "verifier_status": self.verifier_status,
            "verifier_reason": self.verifier_reason,
            "canonical_effect_eligible": self.canonical_effect_eligible,
            "effect_matches_oracle": self.effect_matches_oracle,
            "abstained": self.abstained,
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
        r["logical_id"] for r in transition["superseded_refs"]
    ) | frozenset(r["logical_id"] for r in transition["forgotten_refs"])
    got_targets = (
        frozenset(result.proposal.superseded_ids)
        | frozenset(result.proposal.forgotten_ids)
        if result.proposal
        else frozenset()
    )
    verification = result.verification
    projected = verification.projected_after_state if verification else None
    outcome = CaseOutcome(
        case_id=record["case_id"],
        source_case_id=record["source_case_id"],
        partition=record["annotation_classification"],
        expected=tuple(sorted(expected)),
        strict_expected=transition["primary_type"],
        observed=observed,
        intent=result.intent.intent_type,
        abstained=result.abstained,
        correct=observed in expected,
        strict_correct=observed == transition["primary_type"],
        target_expected=tuple(sorted(want_targets)),
        target_observed=tuple(sorted(got_targets)),
        target_correct=want_targets == got_targets,
        verifier_status=verification.status if verification else None,
        verifier_reason=verification.rejection_reason if verification else None,
        canonical_effect_eligible=result.canonical_effect_eligible,
        effect_matches_oracle=(
            proposal_effect(result.proposal).to_record()
            == oracle_effect(record).to_record()
        ),
        stale_active=projected.stale_active_count if projected else 0,
        latency_ms=elapsed,
    )
    return outcome, result


def _prf(outcomes, label) -> dict:
    """Precision/recall/F1 for one transition label."""
    tp = sum(1 for o in outcomes if o.observed == label and o.correct)
    fp = sum(1 for o in outcomes if o.observed == label and not o.correct)
    fn = sum(
        1 for o in outcomes if label in o.expected and o.observed != label
        and not (o.correct and o.observed in _DUPLICATE_TYPES
                 and label in _DUPLICATE_TYPES)
    )
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _confusion(outcomes) -> dict:
    matrix = {}
    for outcome in outcomes:
        key = outcome.strict_expected
        observed = outcome.observed or "abstain"
        matrix.setdefault(key, {})
        matrix[key][observed] = matrix[key].get(observed, 0) + 1
    return matrix


def _forget_boundary(records, controller) -> dict:
    total = created = handed_off = 0
    for record in records:
        if not is_forget_boundary(record):
            continue
        total += 1
        result = controller.propose(
            record.get("source_statement") or "",
            evidence_for(record),
            before_state_for(record),
        )
        if result.proposal and result.proposal.created:
            created += 1
        if (
            result.intent.intent_type == UpdateIntentType.FORGET_DIRECTIVE
            and result.abstained
        ):
            handed_off += 1
    return {
        "cases": total,
        "handed_off": handed_off,
        "positive_creations": created,
    }


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
    """Pay the one-time costs before measuring steady state.

    The first call in a process compiles this module's regexes and fills
    import caches — roughly 1.9 ms that has nothing to do with per-case
    work. Timing it would report initialization as if it were the cost of
    proposing a transition. The warm-up result is discarded.
    """
    for record in records:
        if is_classification_applicable(record):
            controller.propose(
                record.get("source_statement") or "",
                evidence_for(record),
                before_state_for(record),
            )
            return


def evaluate_partition(records, controller, planner) -> dict:
    applicable = [r for r in records if is_classification_applicable(r)]
    _warm_up(applicable, controller)
    outcomes = []
    results = []
    for record in applicable:
        outcome, result = evaluate_record(record, controller)
        outcomes.append(outcome)
        results.append(result)

    proposals = [o for o in outcomes if o.observed is not None]
    rejections = [o for o in proposals if o.observed in _REJECTION_TYPES]
    abstentions = [o for o in outcomes if o.abstained]

    target_cases = [o for o in outcomes if o.target_expected]
    supersessions = [o for o in outcomes if "supersede_existing" in o.expected]
    duplicates = [
        o for o in outcomes
        if set(o.expected) & set(_DUPLICATE_TYPES)
    ]
    coexistence = [o for o in outcomes if "scoped_coexistence" in o.expected]

    labels = sorted({o.strict_expected for o in outcomes} | {
        o.observed for o in outcomes if o.observed
    })
    per_label = {label: _prf(outcomes, label) for label in labels}
    macro_f1 = (
        round(statistics.fmean([v["f1"] for v in per_label.values()]), 4)
        if per_label
        else 0.0
    )

    # Reference comparison on lifecycle effect over the same records.
    reference_matches = 0
    controller_matches = 0
    for record, outcome in zip(applicable, outcomes):
        if reference_effect(record, planner).to_record() == (
            oracle_effect(record).to_record()
        ):
            reference_matches += 1
        if outcome.effect_matches_oracle:
            controller_matches += 1

    return {
        "records": len(records),
        "applicable": len(applicable),
        "forget_boundary_cases": sum(1 for r in records if is_forget_boundary(r)),
        "coverage": {
            "proposals": len(proposals),
            "rejection_proposals": len(rejections),
            "abstentions": len(abstentions),
            "total": len(outcomes),
        },
        "transition_accuracy": {
            "correct": sum(1 for o in outcomes if o.correct),
            "total": len(outcomes),
        },
        "transition_accuracy_strict": {
            "correct": sum(1 for o in outcomes if o.strict_correct),
            "total": len(outcomes),
        },
        "per_label": per_label,
        "macro_f1": macro_f1,
        "confusion": _confusion(outcomes),
        "target": {
            "cases_requiring_target": len(target_cases),
            "correct": sum(1 for o in target_cases if o.target_correct),
            "wrong": sum(1 for o in target_cases if not o.target_correct),
            "spurious_targets": sum(
                1 for o in outcomes if not o.target_expected and o.target_observed
            ),
        },
        "duplicates": {
            "cases": len(duplicates),
            "correct": sum(1 for o in duplicates if o.correct),
            "created_instead": sum(
                1 for o in duplicates if o.observed == "create_new"
            ),
        },
        "supersession": {
            "cases": len(supersessions),
            "correct": sum(1 for o in supersessions if o.correct),
            "correct_target": sum(1 for o in supersessions if o.target_correct),
            "false_supersessions": sum(
                1 for o in outcomes
                if o.observed == "supersede_existing" and not o.correct
            ),
        },
        "coexistence": {
            "cases": len(coexistence),
            "correct": sum(1 for o in coexistence if o.correct),
            "false_coexistence": sum(
                1 for o in outcomes
                if o.observed == "scoped_coexistence" and not o.correct
            ),
        },
        "verification": {
            "verified": sum(1 for o in outcomes if o.verifier_status),
            "accepted": sum(
                1 for o in outcomes if o.verifier_status == TransitionStatus.ACCEPTED
            ),
            "rejected": sum(
                1 for o in outcomes
                if o.verifier_status and o.verifier_status != TransitionStatus.ACCEPTED
            ),
            "rejection_causes": _causes(outcomes),
            "canonical_effect_eligible": sum(
                1 for o in outcomes if o.canonical_effect_eligible
            ),
            "action_applied": 0,
        },
        "safety": _safety(outcomes),
        "effect_vs_oracle": {
            "controller": {"correct": controller_matches, "total": len(applicable)},
            "reference": {"correct": reference_matches, "total": len(applicable)},
        },
        "forget_boundary": _forget_boundary(records, controller),
        "latency": _latency([o.latency_ms for o in outcomes]),
        "stage_latency": _stage_latency(results),
        "outcomes": outcomes,
    }


def _causes(outcomes) -> dict:
    causes = {}
    for outcome in outcomes:
        if outcome.verifier_reason:
            causes[outcome.verifier_reason] = causes.get(outcome.verifier_reason, 0) + 1
    return causes


def _safety(outcomes) -> dict:
    """Zero-tolerance tallies.

    Each counts a *confident wrong action*, never an abstention: failing
    closed is the safe direction and is reported as coverage, not risk.
    """
    def mutating(outcome):
        return outcome.observed in (
            "supersede_existing", "create_new", "scoped_coexistence",
            "forget_existing",
        )

    return {
        "wrong_target": sum(
            1 for o in outcomes if o.target_expected and not o.target_correct
        ),
        "spurious_target": sum(
            1 for o in outcomes if not o.target_expected and o.target_observed
        ),
        "temporary_as_durable": sum(
            1 for o in outcomes
            if "reject_temporary" in o.expected and mutating(o)
        ),
        "historical_as_current": sum(
            1 for o in outcomes
            if o.strict_expected == "reject_unsupported" and mutating(o)
        ),
        "hypothetical_as_durable": sum(
            1 for o in outcomes
            if "reject_hypothetical" in o.expected and mutating(o)
        ),
        "question_as_mutation": sum(
            1 for o in outcomes if "reject_question" in o.expected and mutating(o)
        ),
        "ambiguous_guessed": sum(
            1 for o in outcomes if "reject_ambiguous" in o.expected and mutating(o)
        ),
        "unsafe_verified": sum(
            1 for o in outcomes
            if o.verifier_status == TransitionStatus.ACCEPTED and not o.correct
        ),
        "stale_active_projections": sum(o.stale_active for o in outcomes),
        "action_applied": 0,
    }


def evaluate_corpus() -> dict:
    corpus = tv.load_corpus()
    controller = DeterministicUpdateController()
    planner = build_planner()
    return {
        "evaluation_version": "1",
        "controller_id": UPDATE_CONTROLLER_ID,
        "controller_version": controller.version,
        "reference_id": "experienceos_hybrid_full_v2_reference",
        "historical_scored": evaluate_partition(
            corpus["historical_scored"], controller, planner
        ),
        "development_only": evaluate_partition(
            corpus["development_fixtures"], controller, planner
        ),
        "excluded_records": sum(
            1
            for r in corpus["unresolved_candidates"]
            if r["annotation_classification"] == "excluded"
        ),
        "unresolved_records": sum(
            1
            for r in corpus["unresolved_candidates"]
            if r["annotation_classification"] == "historical_unresolved"
        ),
    }


def proposal_signature() -> tuple:
    """Ordered (case_id, transition type) pairs — a repeatability check."""
    corpus = tv.load_corpus()
    controller = DeterministicUpdateController()
    signature = []
    for partition in ("historical_scored", "development_fixtures"):
        for record in corpus[partition]:
            if not is_classification_applicable(record):
                continue
            outcome, _ = evaluate_record(record, controller)
            signature.append((outcome.case_id, outcome.observed))
    return tuple(signature)
