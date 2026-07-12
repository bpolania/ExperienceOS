"""Grounded extraction integration coordinator.

One bounded seam that makes the grounded-extraction controllers
observable in the execution pipeline through four explicit effect
modes — disabled, shadow, candidate, adopted — without creating a
second memory-mutation path. The coordinator invokes the selected
controller, revalidates its proposal at the integration boundary
(defense in depth), checks adoption authorization, and translates a
valid+authorized proposal into the existing ``MemoryAction`` shape. It
returns a bounded decision; it never applies anything, holds no store,
and has no mutation method.

Authority is preserved exactly: the ``ExperienceEngine`` remains the
sole durable-mutation boundary, ``ExperienceManager`` remains lifecycle
policy authority, and an adopted controller action is merged into the
same action list the engine already validates and applies. Disabled is
the default; learned extraction begins shadow-only; candidate mode is
non-mutating; adopted mode fails closed without explicit authorization;
no controller is adopted by evidence. ``canonical_effect`` is decided
by the engine and is true only when a controller-originated action
actually changes durable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experienceos.controllers.extraction import (
    ExtractionEvidence,
    ProposedMemoryCandidate,
)
from experienceos.memory.grounding import (
    ApprovedSource,
    GroundedCandidateValidator,
)
from experienceos.memory.planner import CREATE, MemoryAction
from experienceos.memory.schema import MemoryKind

INTEGRATION_ID = "extraction_integration"
INTEGRATION_VERSION = "1"

# Closed effect-mode vocabulary.
MODE_DISABLED = "disabled"
MODE_SHADOW = "shadow"
MODE_CANDIDATE = "candidate"
MODE_ADOPTED = "adopted"
EFFECT_MODES = (MODE_DISABLED, MODE_SHADOW, MODE_CANDIDATE, MODE_ADOPTED)

# Controller-selection vocabulary (never provider names).
CONTROLLER_DETERMINISTIC = "deterministic"
CONTROLLER_LEARNED = "learned"
CONTROLLER_TYPES = (CONTROLLER_DETERMINISTIC, CONTROLLER_LEARNED)

# Bounded integration status vocabulary.
STATUS_NO_CANDIDATE = "no_candidate"
STATUS_GROUNDING_REJECTED = "grounding_rejected"
STATUS_INTEGRATION_REJECTED = "integration_rejected"
STATUS_AUTHORIZATION_MISSING = "authorization_missing"
STATUS_AUTHORIZATION_MISMATCH = "authorization_mismatch"
STATUS_PROPOSED = "proposed"  # valid; shadow/candidate (never applied)
STATUS_AUTHORIZED = "authorized"  # valid + authorized (adopted merge)
STATUS_CONTROLLER_ERROR = "controller_error"

_CANONICAL_KINDS = frozenset(
    {MemoryKind.PREFERENCE, MemoryKind.FACT, MemoryKind.INSTRUCTION}
)


class ExtractionIntegrationError(ValueError):
    """Invalid integration configuration."""


@dataclass(frozen=True)
class AdoptionAuthorization:
    """Configuration evidence that a specific controller+source is
    permitted to affect canonical state in adopted mode. NOT lifecycle
    authority: it cannot bypass grounding, manager validation, or the
    engine's application rules, and carries no store or credentials."""

    controller_id: str
    controller_version: str
    final_proposal_source: str
    authorized: bool = True
    authorized_system_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionIntegrationConfig:
    """Immutable integration configuration. Default is fully disabled:
    no controller runs, nothing is constructed, canonical behavior is
    unchanged."""

    effect_mode: str = MODE_DISABLED
    controller_type: str = CONTROLLER_DETERMINISTIC
    deterministic_controller: object | None = None
    learned_controller: object | None = None
    authorizations: tuple = ()

    def __post_init__(self):
        if self.effect_mode not in EFFECT_MODES:
            raise ExtractionIntegrationError(
                f"unknown effect_mode {self.effect_mode!r}; expected "
                f"one of {EFFECT_MODES}"
            )
        if self.controller_type not in CONTROLLER_TYPES:
            raise ExtractionIntegrationError(
                f"unknown controller_type {self.controller_type!r}; "
                f"expected one of {CONTROLLER_TYPES}"
            )
        for auth in self.authorizations:
            if not isinstance(auth, AdoptionAuthorization):
                raise ExtractionIntegrationError(
                    "authorizations must be AdoptionAuthorization values"
                )


@dataclass
class IntegrationOutcome:
    """Bounded coordinator decision handed back to the engine. Carries
    no store handle and no applied state — the engine decides
    canonical_effect and performs any application."""

    effect_mode: str
    controller_type: str
    proposal: object  # ExtractionProposal
    translated_action: MemoryAction | None = None
    authorized: bool = False
    status: str = STATUS_NO_CANDIDATE
    final_proposal_source: str | None = None
    diagnostics: dict = field(default_factory=dict)


class ExtractionIntegrationCoordinator:
    """Runs the selected controller and returns a bounded decision.

    No store, engine, manager, bus, credentials, model path, retrieval
    state, or mutation callback — a translated action is only ever a
    proposal for the engine's existing authority to accept or reject.
    """

    integration_id = INTEGRATION_ID
    integration_version = INTEGRATION_VERSION

    def __init__(self, config: ExtractionIntegrationConfig,
                 validator: GroundedCandidateValidator | None = None):
        if not isinstance(config, ExtractionIntegrationConfig):
            raise ExtractionIntegrationError(
                "config must be an ExtractionIntegrationConfig"
            )
        self.config = config
        self.validator = validator or GroundedCandidateValidator()

    @property
    def enabled(self) -> bool:
        return self.config.effect_mode != MODE_DISABLED

    def _controller(self):
        if self.config.controller_type == CONTROLLER_LEARNED:
            controller = self.config.learned_controller
            if controller is None:
                raise ExtractionIntegrationError(
                    "learned controller_type requires a learned "
                    "controller instance"
                )
            return controller
        controller = self.config.deterministic_controller
        if controller is None:
            # Lazy default: the deterministic controller is dependency-
            # free and safe to construct on demand.
            from experienceos.memory.grounded_extraction import (
                DeterministicGroundedExtractionController,
            )

            controller = DeterministicGroundedExtractionController(
                validator=self.validator
            )
        return controller

    def evaluate(
        self, evidence: ExtractionEvidence, source_id: str,
        provenance: str,
    ) -> IntegrationOutcome:
        """Invoke the controller and return a bounded decision. Never
        mutates; ``translated_action`` is populated only in candidate/
        adopted mode for a fully validated proposal."""
        mode = self.config.effect_mode
        controller = self._controller()
        try:
            proposal = controller.extract(evidence)
        except Exception as exc:  # contained: never crash the run
            outcome = IntegrationOutcome(
                effect_mode=mode,
                controller_type=self.config.controller_type,
                proposal=None,
                status=STATUS_CONTROLLER_ERROR,
            )
            outcome.diagnostics = {
                "integration_id": self.integration_id,
                "integration_version": self.integration_version,
                "effect_mode": mode,
                "controller_type": self.config.controller_type,
                "source_id": source_id,
                "source_provenance": provenance,
                "proposal_present": False,
                "integration_status": STATUS_CONTROLLER_ERROR,
                "error_class": type(exc).__name__,
                "canonical_effect": False,
                "action_generated": False,
                "action_applied": False,
            }
            return outcome
        final_source = (
            (proposal.diagnostics or {}).get(
                "final_proposal_source", "controller"
            )
        )
        outcome = IntegrationOutcome(
            effect_mode=mode,
            controller_type=self.config.controller_type,
            proposal=proposal,
            final_proposal_source=final_source,
        )

        if proposal.recommendation != "candidate" or (
            proposal.candidate is None
        ):
            outcome.status = STATUS_NO_CANDIDATE
            outcome.diagnostics = self._diagnostics(
                outcome, source_id, provenance, grounding=None
            )
            return outcome

        # Defense in depth: never trust the controller's own claim.
        grounding = self._revalidate(
            proposal.candidate, source_id, evidence.user_text or "",
            provenance,
        )
        if grounding is None:
            outcome.status = STATUS_INTEGRATION_REJECTED
        elif not grounding.valid:
            outcome.status = STATUS_GROUNDING_REJECTED
        else:
            action = self._translate(
                proposal.candidate, source_id, provenance,
                proposal.controller_id, final_source, grounding.code,
            )
            if mode == MODE_ADOPTED:
                if self._authorized(proposal.controller_id, final_source):
                    outcome.translated_action = action
                    outcome.authorized = True
                    outcome.status = STATUS_AUTHORIZED
                else:
                    outcome.status = self._authorization_reject_reason(
                        proposal.controller_id, final_source
                    )
            else:  # shadow / candidate: translated but never applied
                outcome.translated_action = (
                    action if mode == MODE_CANDIDATE else None
                )
                outcome.status = STATUS_PROPOSED

        outcome.diagnostics = self._diagnostics(
            outcome, source_id, provenance,
            grounding=grounding.diagnostics if grounding else None,
        )
        return outcome

    # -- defense-in-depth --------------------------------------------------------

    def _revalidate(self, candidate, source_id, source_text,
                    provenance):
        if not isinstance(candidate, ProposedMemoryCandidate):
            return None
        if candidate.kind not in _CANONICAL_KINDS:
            return None
        if len(candidate.evidence_spans) != 1:
            return None
        return self.validator.validate(
            candidate,
            ApprovedSource(source_id=source_id, text=source_text,
                           provenance=provenance),
        )

    # -- translation (no persisted record; lifecycle stays with kernel) ----------

    @staticmethod
    def _translate(candidate, source_id, provenance, controller_id,
                   final_source, grounding_code) -> MemoryAction:
        span = candidate.evidence_spans[0]
        metadata = {
            "extraction_origin": {
                "controller_id": controller_id,
                "final_proposal_source": final_source,
                "source_id": source_id,
                "source_provenance": provenance,
                "grounding_code": grounding_code,
                "confidence": candidate.confidence,
                "evidence_start": span.start,
                "evidence_end": span.end,
            }
        }
        # A CREATE only: no memory ID, lifecycle status, supersede/forget
        # target, or replaces link — those remain the kernel's to decide.
        return MemoryAction(
            action=CREATE,
            kind=candidate.kind,
            text=candidate.text,
            reason="grounded_extraction",
            metadata=metadata,
        )

    # -- authorization -----------------------------------------------------------

    def _authorized(self, controller_id, final_source) -> bool:
        return any(
            auth.authorized
            and auth.controller_id == controller_id
            and auth.final_proposal_source == final_source
            for auth in self.config.authorizations
        )

    def _authorization_reject_reason(self, controller_id, final_source):
        if not self.config.authorizations:
            return STATUS_AUTHORIZATION_MISSING
        # A matching controller with a different final source (e.g. a
        # deterministic fallback under a learned-only authorization) is
        # a mismatch, not merely missing.
        return STATUS_AUTHORIZATION_MISMATCH

    # -- diagnostics -------------------------------------------------------------

    def _diagnostics(self, outcome, source_id, provenance, grounding):
        proposal = outcome.proposal
        candidate = getattr(proposal, "candidate", None)
        span = (
            candidate.evidence_spans[0]
            if candidate is not None and candidate.evidence_spans
            else None
        )
        proposal_diag = proposal.diagnostics or {}
        return {
            "integration_id": self.integration_id,
            "integration_version": self.integration_version,
            "effect_mode": outcome.effect_mode,
            "controller_type": outcome.controller_type,
            "controller_id": proposal.controller_id,
            "source_id": source_id,
            "source_provenance": provenance,
            "proposal_present": candidate is not None,
            "proposed_kind": candidate.kind if candidate else None,
            "normalized_text": (
                str(candidate.text)[:240] if candidate else None
            ),
            "evidence_start": span.start if span else None,
            "evidence_end": span.end if span else None,
            "evidence_length": (
                span.end - span.start if span else None
            ),
            "controller_outcome": proposal_diag.get(
                "outcome", proposal.recommendation
            ),
            "grounding_status": (
                grounding.get("valid") if grounding else None
            ),
            "grounding_code": (
                grounding.get("code") if grounding else None
            ),
            "runner_status": proposal_diag.get("runner_status"),
            "parser_status": proposal_diag.get("parser_status"),
            "fallback_mode": proposal_diag.get("fallback_mode"),
            "fallback_used": proposal_diag.get("fallback_used"),
            "fallback_reason": proposal_diag.get("fallback_reason"),
            "final_proposal_source": outcome.final_proposal_source,
            "integration_status": outcome.status,
            "adoption_authorized": outcome.authorized,
            # Lifecycle evaluation, action generation, action applied,
            # and canonical_effect are filled by the engine, which owns
            # them. Defaults keep the payload self-describing.
            "lifecycle_evaluation": None,
            "lifecycle_rejection_reason": None,
            "duplicate_or_conflict": None,
            "action_generated": outcome.translated_action is not None,
            "action_applied": False,
            "canonical_effect": False,
        }
