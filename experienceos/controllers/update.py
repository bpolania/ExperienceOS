"""UpdateController contract (interface-only).

Question answered: does this candidate appear to modify or replace
existing experience? The proposal names a relationship; applying any
update, supersession, or merge remains exclusively the deterministic
kernel's job (planner semantics + engine validation + engine
application). Canonical update/supersession behavior is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from experienceos.controllers.base import (
    ControllerInputError,
    ControllerProposalError,
    MemorySnapshot,
    bounded_text,
    validate_common_proposal,
    validate_metadata,
)
from experienceos.controllers.extraction import ProposedMemoryCandidate

UPDATE_RELATIONSHIPS = (
    "no_relation", "duplicate", "reinforce", "supersede", "correct",
    "merge_candidate", "abstain",
)
RELATIONSHIPS_REQUIRING_TARGET = (
    "duplicate", "reinforce", "supersede", "correct", "merge_candidate",
)
_RELATIONSHIPS_ALLOWING_TEXT = ("supersede", "correct", "merge_candidate")


@dataclass(frozen=True)
class UpdateEvidence:
    """One candidate against one existing memory snapshot."""

    candidate: ProposedMemoryCandidate
    existing: MemorySnapshot
    similarity_signals: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.candidate, ProposedMemoryCandidate):
            raise ControllerInputError(
                "candidate must be a ProposedMemoryCandidate"
            )
        if not isinstance(self.existing, MemorySnapshot):
            raise ControllerInputError(
                "existing must be a MemorySnapshot"
            )
        signals = validate_metadata(
            "similarity_signals", self.similarity_signals
        )
        import math

        for name, value in signals.items():
            if isinstance(value, bool) or not isinstance(
                value, (int, float)
            ) or not math.isfinite(float(value)):
                raise ControllerInputError(
                    f"similarity signal {name!r} must be finite numeric"
                )
        object.__setattr__(self, "similarity_signals", signals)
        object.__setattr__(
            self, "metadata", validate_metadata("metadata", self.metadata)
        )


@dataclass(frozen=True)
class UpdateProposal:
    """Relationship proposal — never an applied update."""

    relationship: str
    target_memory_id: str | None
    score: float
    confidence: float
    reason: str
    controller_id: str
    diagnostics: dict = field(default_factory=dict)
    proposed_text: str | None = None
    proposal_only: bool = True

    def __post_init__(self):
        if self.relationship not in UPDATE_RELATIONSHIPS:
            raise ControllerProposalError(
                f"relationship must be one of {UPDATE_RELATIONSHIPS}"
            )
        requires_target = (
            self.relationship in RELATIONSHIPS_REQUIRING_TARGET
        )
        if requires_target and not self.target_memory_id:
            raise ControllerProposalError(
                f"{self.relationship!r} requires target_memory_id"
            )
        if not requires_target and self.target_memory_id is not None:
            raise ControllerProposalError(
                f"{self.relationship!r} must not carry a target"
            )
        if self.proposed_text is not None:
            if self.relationship not in _RELATIONSHIPS_ALLOWING_TEXT:
                raise ControllerProposalError(
                    "proposed_text is only valid for "
                    f"{_RELATIONSHIPS_ALLOWING_TEXT}"
                )
            object.__setattr__(
                self, "proposed_text", bounded_text(self.proposed_text)
            )
        validate_common_proposal(self)


class UpdateController(Protocol):
    @property
    def controller_id(self) -> str:
        ...

    def evaluate(self, evidence: UpdateEvidence) -> UpdateProposal:
        ...


class AbstainingUpdateController:
    """Interface-only deterministic default: always abstains; the
    kernel's semantic-identity supersession logic stays authoritative."""

    controller_id = "update_abstain-1"

    def evaluate(self, evidence: UpdateEvidence) -> UpdateProposal:
        return UpdateProposal(
            relationship="abstain",
            target_memory_id=None,
            score=0.0,
            confidence=0.0,
            reason="interface-only default: no relation opinion",
            controller_id=self.controller_id,
            diagnostics={"rule": "abstain_default"},
        )
