"""TransitionVerifier contract (interface-only).

Question answered: is this proposed lifecycle transition supported by
the supplied evidence and allowed by the lifecycle rules? The verifier
reviews and proposes; applying transitions remains exclusively
``ExperienceEngine._apply_memory_actions`` after kernel validation.
The default verifier ABSTAINS — chosen over pass-through so that
"approve" can never be mistaken for "transition applied" or for
granted lifecycle authority. Canonical transition validation is
untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from experienceos.controllers.base import (
    ControllerInputError,
    ControllerProposalError,
    LIFECYCLE_STATUSES,
    MemorySnapshot,
    validate_common_proposal,
    validate_metadata,
)
from experienceos.controllers.extraction import ProposedMemoryCandidate

TRANSITION_RECOMMENDATIONS = ("approve", "reject", "abstain")

# Mirrors the engine's action vocabulary (CREATE/SUPERSEDE/FORGET),
# duplicated as literals for structural isolation.
TRANSITION_TYPES = ("create", "supersede", "forget")
_TYPES_REQUIRING_MEMORY = ("supersede", "forget")


@dataclass(frozen=True)
class TransitionEvidence:
    """One proposed lifecycle transition, snapshotted."""

    transition_type: str
    target_state: str
    memory: MemorySnapshot | None = None
    candidate: ProposedMemoryCandidate | None = None
    proposal_source: str = ""
    policy_results: dict = field(default_factory=dict)
    related_memory_ids: tuple = ()
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.transition_type not in TRANSITION_TYPES:
            raise ControllerInputError(
                f"transition_type must be one of {TRANSITION_TYPES}"
            )
        if self.target_state not in LIFECYCLE_STATUSES:
            raise ControllerInputError(
                f"target_state must be one of {LIFECYCLE_STATUSES}"
            )
        if self.transition_type in _TYPES_REQUIRING_MEMORY and (
            self.memory is None
        ):
            raise ControllerInputError(
                f"{self.transition_type!r} requires a memory snapshot"
            )
        if self.memory is not None and not isinstance(
            self.memory, MemorySnapshot
        ):
            raise ControllerInputError("memory must be a MemorySnapshot")
        if self.candidate is not None and not isinstance(
            self.candidate, ProposedMemoryCandidate
        ):
            raise ControllerInputError(
                "candidate must be a ProposedMemoryCandidate"
            )
        object.__setattr__(
            self, "policy_results",
            validate_metadata("policy_results", self.policy_results),
        )
        object.__setattr__(
            self, "related_memory_ids",
            tuple(str(m) for m in self.related_memory_ids),
        )
        object.__setattr__(
            self, "metadata", validate_metadata("metadata", self.metadata)
        )


@dataclass(frozen=True)
class TransitionProposal:
    """Verification proposal — never an applied transition."""

    recommendation: str
    score: float
    confidence: float
    reason: str
    controller_id: str
    rule_ids: tuple = ()
    diagnostics: dict = field(default_factory=dict)
    proposal_only: bool = True

    def __post_init__(self):
        if self.recommendation not in TRANSITION_RECOMMENDATIONS:
            raise ControllerProposalError(
                f"recommendation must be one of "
                f"{TRANSITION_RECOMMENDATIONS}"
            )
        object.__setattr__(
            self, "rule_ids", tuple(str(r) for r in self.rule_ids)
        )
        validate_common_proposal(self)


class TransitionVerifier(Protocol):
    @property
    def controller_id(self) -> str:
        ...

    def verify(self, evidence: TransitionEvidence) -> TransitionProposal:
        ...


class AbstainingTransitionVerifier:
    """Interface-only deterministic default: abstains on every
    transition — explicitly meaning "no controller-level opinion",
    never "no objection" and never "approved". Kernel validation
    remains the only transition authority."""

    controller_id = "transition_abstain-1"

    def verify(self, evidence: TransitionEvidence) -> TransitionProposal:
        return TransitionProposal(
            recommendation="abstain",
            score=0.0,
            confidence=0.0,
            reason=(
                "interface-only default: kernel validation remains "
                "authoritative"
            ),
            controller_id=self.controller_id,
            diagnostics={"rule": "abstain_default"},
        )
