"""Measure the transition verifier against the frozen corpus.

Two separate measurements, never merged:

- **correct-proposal verification** — oracle-derived proposals must
  verify. This measures the verifier, not any controller: the proposals
  are built from the committed oracle, so acceptance here is not
  transition precision or recall.
- **adversarial rejection** — single-defect corruptions must be refused,
  each for its own cause.

Historical-scored and development-only partitions are reported
separately. Unresolved and excluded records are never scored.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from benchmarks.annotations import transition_verification as tv
from benchmarks.transition_verification.proposal_fixtures import (
    adversarial_variants,
    before_state_for,
    oracle_proposal,
)
from experienceos.memory.transition_verification import (
    TransitionRejectionReason,
    TransitionStatus,
    TransitionVerifier,
)

#: A correct proposal must reach one of these. `shadow_only` is a pass
#: for a deliberately partial snapshot; the corpus supplies complete
#: before-states, so it should not appear.
_CORRECT_PASS = frozenset({TransitionStatus.ACCEPTED})

#: Statuses that count as a refusal of a corrupted proposal.
_REJECTING = frozenset(
    {
        TransitionStatus.REJECTED,
        TransitionStatus.STRUCTURALLY_INVALID,
        TransitionStatus.AMBIGUOUS,
        TransitionStatus.UNSUPPORTED,
    }
)

#: Rejection reasons that legitimately explain each adversarial defect.
_EXPECTED_REASONS = {
    "invalid_target": {
        TransitionRejectionReason.TARGET_NOT_FOUND,
        TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR,
    },
    "inactive_target": {
        TransitionRejectionReason.TARGET_NOT_ACTIVE,
        TransitionRejectionReason.DOUBLE_SUPERSESSION,
        TransitionRejectionReason.DOUBLE_FORGET,
        TransitionRejectionReason.REACTIVATION_FORBIDDEN,
        TransitionRejectionReason.LINEAGE_INACTIVE_PREDECESSOR,
    },
    "unrelated_target": {
        TransitionRejectionReason.TARGET_UNRELATED,
        TransitionRejectionReason.LINEAGE_UNRELATED_PREDECESSOR,
        TransitionRejectionReason.UNRELATED_MEMORY_DEACTIVATED,
        TransitionRejectionReason.IDENTITY_RELATION_MISMATCH,
    },
    "unsupported_value": {TransitionRejectionReason.UNSUPPORTED_CREATED_VALUE},
    "unsupported_scope": {TransitionRejectionReason.UNSUPPORTED_SCOPE},
    "contradictory_structure": {
        TransitionRejectionReason.CONTRADICTORY_LIFECYCLE_SETS,
        TransitionRejectionReason.NOOP_WITH_CREATION,
        TransitionRejectionReason.COEXISTENCE_SUPERSEDES_SCOPE,
    },
    "invalid_lineage": {
        TransitionRejectionReason.LINEAGE_SELF_REFERENCE,
        TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR,
        TransitionRejectionReason.CREATED_REF_REUSED_AS_TARGET,
    },
    "ambiguous_target": {
        TransitionRejectionReason.TARGET_NOT_UNIQUE,
        TransitionRejectionReason.IDENTITY_RELATION_MISMATCH,
        TransitionRejectionReason.TARGET_UNRELATED,
    },
    "forget_as_creation": {
        TransitionRejectionReason.FORGET_WITH_CREATION,
        TransitionRejectionReason.FORGET_AS_CREATION,
    },
    "temporary_as_durable": {TransitionRejectionReason.TEMPORARY_NOT_DURABLE},
    "historical_as_current": {TransitionRejectionReason.HISTORICAL_NOT_CURRENT},
    "question_mutation": {TransitionRejectionReason.QUESTION_NOT_ASSERTED},
    "hypothetical_mutation": {
        TransitionRejectionReason.HYPOTHETICAL_NOT_ASSERTED
    },
    "missing_preservation": {
        TransitionRejectionReason.CONTRADICTORY_LIFECYCLE_SETS,
        TransitionRejectionReason.PRESERVATION_NOT_PROVEN,
    },
}


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    source_case_id: str
    partition: str
    transition_type: str
    status: str
    rejection_reason: str | None
    canonical_effect_eligible: bool
    latency_ms: float
    passed: bool
    category: str = "correct"

    def to_record(self) -> dict:
        return {
            "case_id": self.case_id,
            "source_case_id": self.source_case_id,
            "partition": self.partition,
            "transition_type": self.transition_type,
            "category": self.category,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "canonical_effect_eligible": self.canonical_effect_eligible,
            "passed": self.passed,
        }


def _scorable(record) -> bool:
    return record.get("expected_transition") is not None


def evaluate_partition(records, verifier) -> dict:
    correct = []
    adversarial = []
    checks = {
        "targets_valid": [0, 0],
        "lifecycle_legal": [0, 0],
        "identity_consistent": [0, 0],
        "preservation_safe": [0, 0],
        "lineage_valid": [0, 0],
        "after_state_consistent": [0, 0],
        "grounding_consistent": [0, 0],
        "structural_valid": [0, 0],
    }
    eligibility_correct = 0

    for record in records:
        if not _scorable(record):
            continue
        before = before_state_for(record)
        proposal = oracle_proposal(record, before)
        started = time.perf_counter()
        result = verifier.verify(proposal, before)
        elapsed = (time.perf_counter() - started) * 1000.0

        for name, counts in checks.items():
            if name in result.checks:
                counts[1] += 1
                counts[0] += int(bool(result.checks[name]))

        # No corpus evidence is production-grounded, so no correct
        # proposal may be canonical-eligible.
        if result.canonical_effect_eligible is False:
            eligibility_correct += 1

        correct.append(
            CaseOutcome(
                case_id=record["case_id"],
                source_case_id=record["source_case_id"],
                partition=record["annotation_classification"],
                transition_type=proposal.transition_type,
                status=result.status,
                rejection_reason=result.rejection_reason,
                canonical_effect_eligible=result.canonical_effect_eligible,
                latency_ms=elapsed,
                passed=result.status in _CORRECT_PASS,
            )
        )

        for category, corrupted in adversarial_variants(record, before, proposal):
            bad = verifier.verify(corrupted, before)
            expected = _EXPECTED_REASONS.get(category, set())
            adversarial.append(
                CaseOutcome(
                    case_id=corrupted.proposal_id,
                    source_case_id=record["source_case_id"],
                    partition=record["annotation_classification"],
                    transition_type=corrupted.transition_type,
                    status=bad.status,
                    rejection_reason=bad.rejection_reason,
                    canonical_effect_eligible=bad.canonical_effect_eligible,
                    latency_ms=bad.latency_ms,
                    category=category,
                    passed=(
                        bad.status in _REJECTING
                        and bad.rejection_reason in expected
                    ),
                )
            )

    latencies = sorted(c.latency_ms for c in correct)
    return {
        "records": len(records),
        "correct_evaluated": len(correct),
        "correct_accepted": sum(1 for c in correct if c.passed),
        "correct_rejected": sum(1 for c in correct if not c.passed),
        "adversarial_evaluated": len(adversarial),
        "adversarial_rejected": sum(1 for c in adversarial if c.passed),
        "adversarial_accepted": sum(1 for c in adversarial if not c.passed),
        "adversarial_by_category": _by_category(adversarial),
        "checks": {
            name: {"passed": passed, "total": total}
            for name, (passed, total) in checks.items()
        },
        "canonical_eligibility_correct": {
            "correct": eligibility_correct,
            "total": len(correct),
        },
        "latency": _latency(latencies),
        "correct_results": correct,
        "adversarial_results": adversarial,
    }


def _by_category(outcomes) -> dict:
    grouped = {}
    for outcome in outcomes:
        entry = grouped.setdefault(outcome.category, {"rejected": 0, "total": 0})
        entry["total"] += 1
        entry["rejected"] += int(outcome.passed)
    return grouped


def _latency(sorted_ms) -> dict:
    if not sorted_ms:
        return {"count": 0}
    index = min(len(sorted_ms) - 1, int(round(0.95 * (len(sorted_ms) - 1))))
    return {
        "count": len(sorted_ms),
        "median_ms": statistics.median(sorted_ms),
        "p95_ms": sorted_ms[index],
        "max_ms": sorted_ms[-1],
    }


def unresolved_diagnostics(records, verifier) -> dict:
    """Fail-closed diagnostics only — never scored.

    Unresolved records carry a null oracle, so no proposal can be built
    from them. That absence is the finding, and it is recorded rather
    than filled in with a guess.
    """
    return {
        record["case_id"]: {
            "oracle_available": record.get("expected_transition") is not None,
            "reason": (record.get("resolution") or {}).get("reason", ""),
        }
        for record in records
        if record["annotation_classification"] == "historical_unresolved"
    }


def evaluate_corpus() -> dict:
    corpus = tv.load_corpus()
    verifier = TransitionVerifier()
    return {
        "evaluation_version": "1",
        "verifier_id": verifier.verifier_id,
        "verifier_version": verifier.version,
        "proposal_source": "oracle_derived",
        "historical_scored": evaluate_partition(corpus["historical_scored"], verifier),
        "development_only": evaluate_partition(
            corpus["development_fixtures"], verifier
        ),
        "unresolved_diagnostics": unresolved_diagnostics(
            corpus["unresolved_candidates"], verifier
        ),
        "excluded_records": sum(
            1
            for r in corpus["unresolved_candidates"]
            if r["annotation_classification"] == "excluded"
        ),
    }


def verification_signature() -> tuple:
    """Ordered (proposal_id, status) pairs — a repeatability fingerprint."""
    data = evaluate_corpus()
    signature = []
    for partition in ("historical_scored", "development_only"):
        for group in ("correct_results", "adversarial_results"):
            for outcome in data[partition][group]:
                signature.append((outcome.case_id, outcome.status))
    return tuple(signature)
