"""AdmissionController contract (Phase 11, Prompt 6; interface-only).

Question answered: should this interaction enter the memory-processing
pipeline for further deterministic validation? The controller never
creates memory and never decides durability — canonical admission
today is the deterministic planner/policy path, which this contract
does not touch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from experienceos.controllers.base import (
    ControllerProposalError,
    bounded_text,
    validate_common_proposal,
    validate_metadata,
)

ADMISSION_RECOMMENDATIONS = ("admit", "reject", "abstain")


@dataclass(frozen=True)
class AdmissionEvidence:
    """Bounded snapshot of one interaction."""

    user_message: str
    assistant_message: str = ""
    session_ref: str = ""
    source_type: str = "user_turn"
    active_memory_count: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(
            self, "user_message", bounded_text(self.user_message)
        )
        object.__setattr__(
            self, "assistant_message",
            bounded_text(self.assistant_message),
        )
        if (
            not isinstance(self.active_memory_count, int)
            or self.active_memory_count < 0
        ):
            from experienceos.controllers.base import ControllerInputError

            raise ControllerInputError(
                "active_memory_count must be an int >= 0"
            )
        object.__setattr__(
            self, "metadata", validate_metadata("metadata", self.metadata)
        )


@dataclass(frozen=True)
class AdmissionProposal:
    """Proposal only — never an applied admission decision."""

    recommendation: str
    score: float
    confidence: float
    reason: str
    controller_id: str
    diagnostics: dict = field(default_factory=dict)
    proposal_only: bool = True

    def __post_init__(self):
        if self.recommendation not in ADMISSION_RECOMMENDATIONS:
            raise ControllerProposalError(
                f"recommendation must be one of "
                f"{ADMISSION_RECOMMENDATIONS}"
            )
        validate_common_proposal(self)


class AdmissionController(Protocol):
    """Proposal-only seam; no apply/commit/persist surface exists."""

    @property
    def controller_id(self) -> str:
        ...

    def evaluate(self, evidence: AdmissionEvidence) -> AdmissionProposal:
        ...


class AbstainingAdmissionController:
    """Interface-only deterministic default: always abstains, leaving
    canonical deterministic admission entirely authoritative."""

    controller_id = "admission_abstain-1"

    def evaluate(self, evidence: AdmissionEvidence) -> AdmissionProposal:
        return AdmissionProposal(
            recommendation="abstain",
            score=0.0,
            confidence=0.0,
            reason="interface-only default: no admission opinion",
            controller_id=self.controller_id,
            diagnostics={"rule": "abstain_default"},
        )
