"""ForgetIntentController contract (Phase 11, Prompt 6;
interface-only).

Question answered: does this interaction appear to request that
specific experience stop being used? The proposal names candidate
targets; detecting, resolving, validating, and applying forgets
remains the deterministic kernel's job (the Phase 9 forget resolver
plus engine validation). Canonical forgetting behavior is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from experienceos.controllers.base import (
    ControllerInputError,
    ControllerProposalError,
    EvidenceSpan,
    MemorySnapshot,
    bounded_text,
    validate_common_proposal,
    validate_metadata,
)

FORGET_RECOMMENDATIONS = (
    "no_forget_intent", "forget_candidate", "ambiguous", "abstain",
)


@dataclass(frozen=True)
class ForgetIntentEvidence:
    """Bounded message plus candidate-target snapshots."""

    user_message: str
    candidate_memories: tuple = ()
    detected_phrases: tuple = ()
    session_ref: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self, "user_message", bounded_text(self.user_message)
        )
        candidates = tuple(self.candidate_memories)
        if not all(
            isinstance(memory, MemorySnapshot) for memory in candidates
        ):
            raise ControllerInputError(
                "candidate_memories must contain MemorySnapshot values"
            )
        object.__setattr__(self, "candidate_memories", candidates)
        object.__setattr__(
            self, "detected_phrases",
            tuple(str(phrase) for phrase in self.detected_phrases),
        )
        object.__setattr__(
            self, "metadata", validate_metadata("metadata", self.metadata)
        )


@dataclass(frozen=True)
class ForgetIntentProposal:
    """Forget-intent proposal — never a forget action.

    Target consistency: ``forget_candidate`` requires at least one
    proposed target; ``no_forget_intent`` and ``abstain`` must carry
    none; ``ambiguous`` may carry any number (the ambiguity may be
    about which target).
    """

    recommendation: str
    target_memory_ids: tuple = ()
    score: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    controller_id: str = ""
    diagnostics: dict = field(default_factory=dict)
    evidence_spans: tuple = ()
    proposal_only: bool = True

    def __post_init__(self):
        if self.recommendation not in FORGET_RECOMMENDATIONS:
            raise ControllerProposalError(
                f"recommendation must be one of {FORGET_RECOMMENDATIONS}"
            )
        targets = tuple(str(t) for t in self.target_memory_ids)
        object.__setattr__(self, "target_memory_ids", targets)
        if self.recommendation == "forget_candidate" and not targets:
            raise ControllerProposalError(
                "'forget_candidate' requires at least one target"
            )
        if self.recommendation in ("no_forget_intent", "abstain") and (
            targets
        ):
            raise ControllerProposalError(
                f"{self.recommendation!r} must not carry targets"
            )
        spans = tuple(self.evidence_spans)
        if not all(isinstance(span, EvidenceSpan) for span in spans):
            raise ControllerProposalError(
                "evidence_spans must contain EvidenceSpan values"
            )
        object.__setattr__(self, "evidence_spans", spans)
        validate_common_proposal(self)


class ForgetIntentController(Protocol):
    @property
    def controller_id(self) -> str:
        ...

    def evaluate(
        self, evidence: ForgetIntentEvidence
    ) -> ForgetIntentProposal:
        ...


class NoForgetIntentController:
    """Interface-only deterministic default: never proposes a forget;
    the kernel's forget resolver stays authoritative."""

    controller_id = "forget_intent_none-1"

    def evaluate(
        self, evidence: ForgetIntentEvidence
    ) -> ForgetIntentProposal:
        return ForgetIntentProposal(
            recommendation="no_forget_intent",
            target_memory_ids=(),
            score=0.0,
            confidence=0.0,
            reason="interface-only default: no forget-intent opinion",
            controller_id=self.controller_id,
            diagnostics={"rule": "no_forget_default"},
        )
