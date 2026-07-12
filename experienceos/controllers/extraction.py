"""ExtractionController contract (Phase 11, Prompt 6; interface-only).

Question answered: what candidate memory, if any, appears grounded in
this interaction? The contract can represent exactly one grounded
candidate or none — the likely Phase 12 direction — with optional
evidence spans. Nothing here persists anything: a proposed candidate
has no durable ID, no lifecycle status, and no supersession links, and
canonical extraction behavior is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from experienceos.controllers.base import (
    ControllerInputError,
    ControllerProposalError,
    EvidenceSpan,
    MEMORY_KINDS,
    bounded_text,
    validate_common_proposal,
    validate_metadata,
    validate_unit,
)

EXTRACTION_RECOMMENDATIONS = ("candidate", "none", "abstain")


@dataclass(frozen=True)
class ExtractionEvidence:
    """Bounded interaction snapshot for grounded extraction."""

    user_text: str
    assistant_text: str = ""
    source_role: str = "user"
    temporal_reference: str = ""
    provenance_label: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "user_text", bounded_text(self.user_text))
        object.__setattr__(
            self, "assistant_text", bounded_text(self.assistant_text)
        )
        if self.source_role not in ("user", "assistant"):
            raise ControllerInputError(
                "source_role must be 'user' or 'assistant'"
            )
        object.__setattr__(
            self, "metadata", validate_metadata("metadata", self.metadata)
        )


@dataclass(frozen=True)
class ProposedMemoryCandidate:
    """A proposal-shaped candidate — deliberately NOT a memory record.

    No durable ID, no lifecycle status, no supersession links, no
    timestamps: those exist only after the deterministic kernel
    validates and applies a creation through the engine.
    """

    kind: str
    text: str
    tags: tuple = ()
    evidence_spans: tuple = ()
    source_digest: str | None = None
    grounded: bool = False
    confidence: float = 0.0

    def __post_init__(self):
        if self.kind not in MEMORY_KINDS:
            raise ControllerInputError(
                f"kind must be one of {MEMORY_KINDS}, got {self.kind!r}"
            )
        if not isinstance(self.text, str) or not self.text.strip():
            raise ControllerInputError("candidate text must be non-empty")
        object.__setattr__(self, "text", bounded_text(self.text))
        object.__setattr__(self, "tags", tuple(self.tags))
        spans = tuple(self.evidence_spans)
        if not all(isinstance(span, EvidenceSpan) for span in spans):
            raise ControllerInputError(
                "evidence_spans must contain EvidenceSpan values"
            )
        object.__setattr__(self, "evidence_spans", spans)
        validate_unit("candidate confidence", self.confidence)


@dataclass(frozen=True)
class ExtractionProposal:
    """One grounded candidate, or none — never a persisted memory."""

    recommendation: str
    candidate: ProposedMemoryCandidate | None
    score: float
    confidence: float
    reason: str
    controller_id: str
    diagnostics: dict = field(default_factory=dict)
    proposal_only: bool = True

    def __post_init__(self):
        if self.recommendation not in EXTRACTION_RECOMMENDATIONS:
            raise ControllerProposalError(
                f"recommendation must be one of "
                f"{EXTRACTION_RECOMMENDATIONS}"
            )
        if self.recommendation == "candidate" and self.candidate is None:
            raise ControllerProposalError(
                "'candidate' recommendation requires a candidate"
            )
        if self.recommendation != "candidate" and (
            self.candidate is not None
        ):
            raise ControllerProposalError(
                f"{self.recommendation!r} must not carry a candidate"
            )
        validate_common_proposal(self)


class ExtractionController(Protocol):
    @property
    def controller_id(self) -> str:
        ...

    def extract(self, evidence: ExtractionEvidence) -> ExtractionProposal:
        ...


class NoOpExtractionController:
    """Interface-only deterministic default: never proposes a
    candidate; canonical extraction remains authoritative."""

    controller_id = "extraction_noop-1"

    def extract(self, evidence: ExtractionEvidence) -> ExtractionProposal:
        return ExtractionProposal(
            recommendation="none",
            candidate=None,
            score=0.0,
            confidence=0.0,
            reason="interface-only default: no extraction performed",
            controller_id=self.controller_id,
            diagnostics={"rule": "noop_default"},
        )
