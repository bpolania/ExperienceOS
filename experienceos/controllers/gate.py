"""Shadow-mode MemoryGate: the first specialized controller seam.

MemoryGate proposes; ExperienceOS decides. A gate receives one bounded,
immutable evidence snapshot per lifecycle-eligible, canonically-ranked
candidate and returns an immutable proposal (admit / reject / abstain).
Every gate is shadow-only: ``shadow_mode`` is always true,
``affected_selection`` is always false, and no proposal can change
candidate eligibility, selection, ordering, token accounting, rendered
context, or memory state. There is no enforcement mode; canonical gate
enforcement requires benchmark evidence and explicit adoption in a
later phase.

Gates hold no store, engine, manager, bus, persistence, or mutation
handle — the interface is structurally incapable of applying anything.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Protocol

GATE_PROPOSALS = ("admit", "reject", "abstain")

_MAX_REASON_CHARS = 300
_MAX_EVIDENCE_TEXT_CHARS = 300


class GateError(RuntimeError):
    """Base for typed gate failures."""


class GateProposalError(GateError):
    """A gate produced an invalid proposal (bad value, NaN score,
    out-of-range confidence, non-serializable diagnostics)."""


class GateEvaluationError(GateError):
    """Raised in strict diagnostic mode when shadow evaluation fails.

    Canonical retrieval, selection, and budgets are already final
    before any gate runs, so even this error cannot alter them.
    """


@dataclass(frozen=True)
class GateCandidateEvidence:
    """Bounded, immutable snapshot of one canonically-ranked candidate.

    Contains primitives and small dict copies only — never the live
    memory record, a store, vectors, cache objects, or callbacks.
    ``memory_text`` is truncated to a documented bound so evidence
    stays serializable and cheap.
    """

    query: str
    memory_id: str
    memory_kind: str
    memory_text: str
    lifecycle_status: str
    canonical_selected: bool
    canonical_rank: int
    exclusion_reason: str | None
    token_estimate: int
    component_scores: dict = field(default_factory=dict)
    semantic: dict | None = None
    fusion: dict | None = None
    retrieval_mode: str = "disabled"
    fusion_profile_id: str | None = None

    def __post_init__(self):
        if len(self.memory_text) > _MAX_EVIDENCE_TEXT_CHARS:
            object.__setattr__(
                self,
                "memory_text",
                self.memory_text[:_MAX_EVIDENCE_TEXT_CHARS],
            )


@dataclass(frozen=True)
class GateProposal:
    """Immutable shadow proposal. Never an applied action.

    Validated at construction: unknown proposal values, non-finite or
    out-of-range scores/confidences, oversized reasons, attempts to
    leave shadow mode, and non-JSON-serializable diagnostics all raise
    ``GateProposalError``.
    """

    proposal: str
    score: float
    confidence: float
    reason: str
    controller_id: str
    diagnostics: dict = field(default_factory=dict)
    shadow_mode: bool = True
    affected_selection: bool = False

    def __post_init__(self):
        if self.proposal not in GATE_PROPOSALS:
            raise GateProposalError(
                f"unknown proposal {self.proposal!r}; expected one of "
                f"{GATE_PROPOSALS}"
            )
        for name, value, low, high in (
            ("score", self.score, 0.0, 1.0),
            ("confidence", self.confidence, 0.0, 1.0),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or not low <= float(value) <= high
            ):
                raise GateProposalError(
                    f"{name} must be finite in [{low}, {high}], got "
                    f"{value!r}"
                )
        if self.shadow_mode is not True:
            raise GateProposalError(
                "Gates are shadow-only: shadow_mode must be True"
            )
        if self.affected_selection is not False:
            raise GateProposalError(
                "gate proposals never affect selection: "
                "affected_selection must be False"
            )
        if not self.controller_id or not isinstance(self.controller_id, str):
            raise GateProposalError("controller_id must be a non-empty str")
        if not isinstance(self.reason, str) or len(
            self.reason
        ) > _MAX_REASON_CHARS:
            raise GateProposalError(
                f"reason must be a str of <= {_MAX_REASON_CHARS} chars"
            )
        try:
            json.dumps(self.diagnostics)
        except (TypeError, ValueError) as exc:
            raise GateProposalError(
                f"diagnostics not JSON-serializable: {type(exc).__name__}"
            ) from exc


class MemoryGate(Protocol):
    """Proposal-only controller seam.

    Deliberately absent: apply/admit_memory/reject_memory/update/
    delete/forget/select_context — a gate can only look and suggest.
    """

    @property
    def controller_id(self) -> str:
        ...

    def evaluate(self, evidence: GateCandidateEvidence) -> GateProposal:
        ...


class PassThroughMemoryGate:
    """Default deterministic shadow gate: admits everything it sees.

    Every input it receives is lifecycle-eligible and canonically
    ranked by construction, so pass-through means "no opinion beyond
    canonical selection". Dependency-free, offline, deterministic
    across runs and processes.
    """

    controller_id = "gate_pass_through-1"

    def evaluate(self, evidence: GateCandidateEvidence) -> GateProposal:
        return GateProposal(
            proposal="admit",
            score=1.0,
            confidence=1.0,
            reason=(
                "pass-through shadow gate: canonical selection stands"
            ),
            controller_id=self.controller_id,
            diagnostics={"rule": "pass_through"},
        )


class HeuristicShadowMemoryGate:
    """Deterministic, versioned heuristic shadow gate.

    Documented rules (``gate_shadow_heuristic-1``), evaluated in order
    on the supplied evidence only — never on benchmark labels, query
    special cases, or learned models:

    1. **admit** when high-precision lexical evidence exists
       (``phrase_score + entity_score >= 1``) or when the candidate
       carries both lexical and semantic evidence
       (``evidence_source == "lexical_and_semantic"``) or when its
       strength (below) is >= 0.35.
    2. **reject** when the candidate is semantic-only and its semantic
       score sits within 0.10 of the relevance floor recorded in its
       own evidence — near-floor semantic-only matches are the
       documented collision-noise risk.
    3. **abstain** otherwise (ambiguous evidence).

    Strength: the fused score when fusion evidence exists, else the
    semantic score when semantic evidence exists, else the bounded
    lexical transform ``lexical / (lexical + 3.0)`` mirroring the
    fusion normalization. Confidence is fixed per outcome: 0.9 admit,
    0.6 reject, 0.3 abstain.
    """

    controller_id = "gate_shadow_heuristic-1"

    _ADMIT_STRENGTH = 0.35
    _NEAR_FLOOR_MARGIN = 0.10

    def evaluate(self, evidence: GateCandidateEvidence) -> GateProposal:
        strength = self._strength(evidence)
        scores = evidence.component_scores
        precision = float(scores.get("phrase_score", 0.0)) + float(
            scores.get("entity_score", 0.0)
        )
        source = (
            evidence.fusion.get("evidence_source")
            if evidence.fusion
            else None
        )
        semantic_score = (
            float(evidence.semantic.get("score", 0.0))
            if evidence.semantic and evidence.semantic.get("considered")
            else None
        )
        floor = (
            float(evidence.semantic.get("relevance_floor", 0.0))
            if evidence.semantic and evidence.semantic.get("considered")
            else 0.0
        )
        diagnostics = {
            "rule_version": self.controller_id,
            "strength": round(strength, 6),
            "precision_evidence": round(precision, 6),
            "evidence_source": source,
        }
        if (
            precision >= 1.0
            or source == "lexical_and_semantic"
            or strength >= self._ADMIT_STRENGTH
        ):
            return GateProposal(
                proposal="admit",
                score=round(min(1.0, max(strength, 0.35)), 6),
                confidence=0.9,
                reason="strong multi-signal or high-precision evidence",
                controller_id=self.controller_id,
                diagnostics={**diagnostics, "rule": "strong_evidence"},
            )
        if (
            source == "semantic_only"
            and semantic_score is not None
            and semantic_score <= floor + self._NEAR_FLOOR_MARGIN
        ):
            return GateProposal(
                proposal="reject",
                score=round(strength, 6),
                confidence=0.6,
                reason="near-floor semantic-only evidence (noise risk)",
                controller_id=self.controller_id,
                diagnostics={**diagnostics, "rule": "near_floor_semantic"},
            )
        return GateProposal(
            proposal="abstain",
            score=round(strength, 6),
            confidence=0.3,
            reason="ambiguous evidence",
            controller_id=self.controller_id,
            diagnostics={**diagnostics, "rule": "ambiguous"},
        )

    @staticmethod
    def _strength(evidence: GateCandidateEvidence) -> float:
        if evidence.fusion is not None:
            return min(1.0, float(evidence.fusion.get("fused_score", 0.0)))
        if evidence.semantic and evidence.semantic.get("considered"):
            semantic = evidence.semantic.get("score")
            if semantic is not None and evidence.retrieval_mode == (
                "semantic_only"
            ):
                return min(1.0, float(semantic))
        lexical = float(
            evidence.component_scores.get("lexical_score", 0.0)
        )
        return lexical / (lexical + 3.0) if lexical > 0.0 else 0.0
