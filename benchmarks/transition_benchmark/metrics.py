"""Per-case scoring and aggregation for the transition benchmark.

Two lifecycle views are kept apart on purpose:

- **actual** — what a system really did to memory through the real
  manager and engine;
- **projected** — what a transition proposal *would* do if it alone
  governed state.

Non-mutating modes leave those deliberately different, and collapsing
them would report an improvement that never happens. Adoption gates are
decided on the actual adopted outcome, because that is what adoption
would do.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

_DUPLICATE_TYPES = ("duplicate_noop", "semantic_duplicate_noop")


def expected_types(record) -> frozenset:
    """Transition labels satisfying the committed oracle.

    Reuses the frozen convention every prior layer applies: a
    `duplicate_noop` without the `exact_duplicate` category asserts only
    that the source duplicates existing experience.
    """
    transition = record["expected_transition"]
    primary = transition["primary_type"]
    categories = set(record.get("scoring_categories") or ())
    if primary == "duplicate_noop" and "exact_duplicate" not in categories:
        return frozenset(_DUPLICATE_TYPES)
    return frozenset({primary})


def oracle_targets(record) -> frozenset:
    transition = record["expected_transition"]
    return frozenset(
        r["logical_id"] for r in transition["superseded_refs"]
    ) | frozenset(r["logical_id"] for r in transition["forgotten_refs"])


def oracle_unchanged(record) -> frozenset:
    return frozenset(
        r["logical_id"] for r in record["expected_transition"]["unchanged_refs"]
    )


def oracle_preserved_active(record) -> frozenset:
    """Before-state actives the oracle expects to still be active after."""
    after = record.get("after_state") or {}
    seeded = {
        m["memory_ref"]["logical_id"]
        for m in record["before_state"]
        if m["lifecycle_state"] == "active"
    }
    return frozenset(
        r["logical_id"] for r in (after.get("active") or [])
    ) & seeded


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    source_case_id: str
    partition: str
    system_id: str
    reference_level: str
    expected_types: tuple
    observed_type: str | None
    classification_correct: bool
    target_expected: tuple
    target_observed: tuple
    target_correct: bool
    target_required: bool
    # Actual lifecycle outcome.
    active_count: int
    created_count: int
    duplicate_pairs: int
    stale_pairs: int
    targets_deactivated: bool
    unrelated_preserved: bool
    # Projected outcome of the proposal, when the system produced one.
    projected_available: bool
    projected_duplicate_pairs: int
    projected_stale_pairs: int
    verifier_status: str | None
    action_applied: bool
    has_diagnostics: bool
    latency_ms: float

    def to_record(self) -> dict:
        return {
            "case_id": self.case_id,
            "source_case_id": self.source_case_id,
            "partition": self.partition,
            "system_id": self.system_id,
            "reference_level": self.reference_level,
            "expected_types": sorted(self.expected_types),
            "observed_type": self.observed_type,
            "classification_correct": self.classification_correct,
            "target_expected": sorted(self.target_expected),
            "target_observed": sorted(self.target_observed),
            "target_correct": self.target_correct,
            "target_required": self.target_required,
            "active_count": self.active_count,
            "created_count": self.created_count,
            "duplicate_pairs": self.duplicate_pairs,
            "stale_pairs": self.stale_pairs,
            "targets_deactivated": self.targets_deactivated,
            "unrelated_preserved": self.unrelated_preserved,
            "projected_available": self.projected_available,
            "projected_duplicate_pairs": self.projected_duplicate_pairs,
            "projected_stale_pairs": self.projected_stale_pairs,
            "verifier_status": self.verifier_status,
            "action_applied": self.action_applied,
            "has_diagnostics": self.has_diagnostics,
        }


def score_case(record, observation) -> CaseScore:
    expected = expected_types(record)
    targets = oracle_targets(record)
    observed_targets = frozenset(observation.proposal_targets)
    deactivated = set(observation.superseded_ids) | set(observation.forgotten_ids)
    preserved = oracle_preserved_active(record)
    annotation = observation.annotation or {}
    return CaseScore(
        case_id=record["case_id"],
        source_case_id=record["source_case_id"],
        partition=record["annotation_classification"],
        system_id=observation.system_id,
        reference_level=observation.reference_level,
        expected_types=tuple(sorted(expected)),
        observed_type=observation.proposal_type,
        classification_correct=observation.proposal_type in expected,
        target_expected=tuple(sorted(targets)),
        target_observed=tuple(sorted(observed_targets)),
        target_correct=targets == observed_targets,
        target_required=bool(targets),
        active_count=len(observation.active_ids),
        created_count=observation.created_count,
        duplicate_pairs=observation.semantic_duplicate_pairs,
        stale_pairs=observation.stale_active_pairs,
        # Did the memories the oracle says must go actually go?
        targets_deactivated=bool(targets) and targets <= deactivated,
        # Did every memory the oracle says must stay actually stay?
        unrelated_preserved=preserved <= set(observation.active_ids),
        projected_available=observation.projected_available,
        projected_duplicate_pairs=observation.projected_duplicate_pairs,
        projected_stale_pairs=observation.projected_stale_pairs,
        verifier_status=observation.verifier_status,
        action_applied=observation.action_applied,
        has_diagnostics=bool(annotation.get("diagnostics")),
        latency_ms=observation.latency_ms,
    )


def _ratio(correct, total) -> dict:
    return {
        "correct": correct,
        "total": total,
        "rate": round(correct / total, 4) if total else None,
    }


def _prf(scores, label) -> dict:
    tp = sum(
        1 for s in scores if s.observed_type == label and s.classification_correct
    )
    fp = sum(
        1 for s in scores
        if s.observed_type == label and not s.classification_correct
    )
    fn = sum(
        1 for s in scores
        if label in s.expected_types and s.observed_type != label
        and not (
            s.classification_correct
            and s.observed_type in _DUPLICATE_TYPES
            and label in _DUPLICATE_TYPES
        )
    )
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )
    return {
        "tp": tp, "fp": fp, "fn": fn, "support": tp + fp + fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def latency(values) -> dict:
    if not values:
        return {"count": 0}
    values = sorted(values)
    index = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 4),
        "median_ms": round(statistics.median(values), 4),
        "p95_ms": round(values[index], 4),
        "max_ms": round(values[-1], 4),
    }


def aggregate(scores) -> dict:
    """Aggregate one system's scores over one partition."""
    if not scores:
        return {"cases": 0}
    classified = [s for s in scores if s.observed_type is not None]
    target_cases = [s for s in scores if s.target_required]
    labels = sorted(
        {t for s in scores for t in s.expected_types}
        | {s.observed_type for s in classified}
    )
    per_label = {label: _prf(scores, label) for label in labels}
    scored = [v["f1"] for v in per_label.values() if v["support"]]
    projected = [s for s in scores if s.projected_available]
    return {
        "cases": len(scores),
        "classification": _ratio(
            sum(1 for s in scores if s.classification_correct), len(scores)
        ),
        "proposals": len(classified),
        "abstentions": len(scores) - len(classified),
        "per_label": per_label,
        "macro_f1": round(statistics.fmean(scored), 4) if scored else None,
        "micro_f1": round(
            sum(1 for s in scores if s.classification_correct) / len(scores), 4
        ),
        "target": {
            **_ratio(
                sum(1 for s in target_cases if s.target_correct), len(target_cases)
            ),
            "wrong": sum(1 for s in target_cases if not s.target_correct),
            "spurious": sum(
                1 for s in scores if not s.target_required and s.target_observed
            ),
        },
        "lifecycle_actual": {
            "duplicate_pairs": sum(s.duplicate_pairs for s in scores),
            "stale_pairs": sum(s.stale_pairs for s in scores),
            "created": sum(s.created_count for s in scores),
            "targets_deactivated": _ratio(
                sum(1 for s in target_cases if s.targets_deactivated),
                len(target_cases),
            ),
            "preservation": _ratio(
                sum(1 for s in scores if s.unrelated_preserved), len(scores)
            ),
        },
        "lifecycle_projected": {
            "available": len(projected),
            "duplicate_pairs": sum(s.projected_duplicate_pairs for s in projected),
            "stale_pairs": sum(s.projected_stale_pairs for s in projected),
        },
        "verifier": {
            "accepted": sum(1 for s in scores if s.verifier_status == "accepted"),
            "evaluated": sum(1 for s in scores if s.verifier_status),
        },
        "diagnostics_complete": _ratio(
            sum(1 for s in classified if s.has_diagnostics), len(classified)
        ),
        "actions_applied": sum(1 for s in scores if s.action_applied),
        "latency": latency([s.latency_ms for s in scores]),
    }
