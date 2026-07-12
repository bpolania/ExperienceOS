"""Shadow-gate integration helper (Phase 11, Prompt 5).

Runs strictly after canonical retrieval, selection, and token-budget
enforcement are final: it reads the completed ``RetrievalResult``,
builds bounded immutable evidence for each canonically-ranked
candidate, collects proposals, contains failures, and attaches
additive diagnostics. It never touches ``result.selected``, candidate
eligibility, ordering, scores, reasons, or token accounting — the gate
observes the canonical result; it does not participate in producing
it. Lifecycle-excluded and pre-ranking-excluded records are never sent
to the gate (``gate: {"considered": false}``).
"""

from __future__ import annotations

import time

from experienceos.controllers.gate import (
    GateCandidateEvidence,
    GateError,
    GateEvaluationError,
    GateProposal,
)


def evaluate_shadow_gate(
    gate,
    result,
    query: str,
    retrieval_mode: str,
    fusion_profile_id: str | None = None,
    strict: bool = False,
) -> None:
    """Attach shadow-gate diagnostics to a completed retrieval result.

    Failure containment (default): any typed gate error, runtime
    error, or invalid proposal from one candidate is recorded as a
    per-candidate failure (exception type name only — no stack traces,
    no paths) and evaluation continues; the canonical result is never
    altered and no proposal is fabricated. With ``strict=True`` a
    ``GateEvaluationError`` is raised after containment bookkeeping —
    selection is already final, so even strict mode cannot change it.
    """
    started = time.perf_counter()
    counters = {
        "evaluated": 0,
        "admit": 0,
        "reject": 0,
        "abstain": 0,
        "agreement": 0,
        "disagreement": 0,
        "neutral": 0,
        "selected_proposed_reject": 0,
        "skipped_proposed_admit": 0,
        "failures": 0,
        "affected_selection": 0,  # invariant: stays 0
    }
    first_failure: str | None = None
    for candidate in result.candidates:
        if candidate.rank <= 0:
            # Lifecycle-excluded and pre-ranking-excluded records are
            # never gate-evaluated; existing reasons stay authoritative.
            candidate.gate = {"considered": False}
            continue
        evidence = GateCandidateEvidence(
            query=query,
            memory_id=candidate.memory.id,
            memory_kind=candidate.memory.kind,
            memory_text=candidate.memory.text,
            lifecycle_status=candidate.status,
            canonical_selected=candidate.selected,
            canonical_rank=candidate.rank,
            exclusion_reason=candidate.exclusion_reason,
            token_estimate=candidate.token_estimate,
            component_scores=dict(candidate.component_scores),
            semantic=candidate.semantic,
            fusion=candidate.fusion,
            retrieval_mode=retrieval_mode,
            fusion_profile_id=fusion_profile_id,
        )
        try:
            proposal = gate.evaluate(evidence)
            if not isinstance(proposal, GateProposal):
                raise GateError(
                    "gate returned "
                    f"{type(proposal).__name__}, not GateProposal"
                )
        except Exception as exc:  # bounded: recorded, never silent
            counters["failures"] += 1
            failure = type(exc).__name__
            first_failure = first_failure or failure
            candidate.gate = {
                "considered": True,
                "controller_id": getattr(
                    gate, "controller_id", "unknown"
                ),
                "status": "failed",
                "failure": failure,
                "shadow_mode": True,
                "affected_selection": False,
                "canonical_selected": candidate.selected,
            }
            continue
        counters["evaluated"] += 1
        counters[proposal.proposal] += 1
        agreement = _agreement(candidate.selected, proposal.proposal)
        counters[agreement] += 1
        if candidate.selected and proposal.proposal == "reject":
            counters["selected_proposed_reject"] += 1
        if not candidate.selected and proposal.proposal == "admit":
            counters["skipped_proposed_admit"] += 1
        candidate.gate = {
            "considered": True,
            "controller_id": proposal.controller_id,
            "status": "evaluated",
            "proposal": proposal.proposal,
            "score": proposal.score,
            "confidence": proposal.confidence,
            "reason": proposal.reason,
            "shadow_mode": True,
            "affected_selection": False,
            "canonical_selected": candidate.selected,
            "agreement_with_selection": agreement,
            "diagnostics": proposal.diagnostics,
        }
    result.gate = {
        "enabled": True,
        "shadow_mode": True,
        "controller_id": getattr(gate, "controller_id", "unknown"),
        "retrieval_mode": retrieval_mode,
        **counters,
        "status": "failed" if counters["failures"] else "evaluated",
        "first_failure": first_failure,
        "evaluation": {
            "elapsed_ms": round(
                (time.perf_counter() - started) * 1000.0, 3
            )
        },
    }
    if strict and counters["failures"]:
        raise GateEvaluationError(
            f"shadow gate evaluation failed: {first_failure}"
        )


def _agreement(canonical_selected: bool, proposal: str) -> str:
    """Documented agreement rule: selected+admit and skipped+reject
    agree; abstain is neutral; the remaining pairs disagree.
    Disagreement is expected shadow evidence, never an error."""
    if proposal == "abstain":
        return "neutral"
    if canonical_selected == (proposal == "admit"):
        return "agreement"
    return "disagreement"
