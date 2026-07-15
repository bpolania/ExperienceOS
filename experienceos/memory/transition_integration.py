"""Governed integration of transition intelligence.

One bounded seam decides whether transition controllers run at all, what
their proposals are allowed to influence, and whether a verified proposal
may become a canonical lifecycle action.

The coordinator orchestrates; it is not a lifecycle authority:

- it holds **no store** and has **no mutation method**;
- it never calls create, supersede, forget, or `_apply_memory_actions`;
- it returns *data* to the engine, which keeps every existing check;
- `ExperienceManager` remains lifecycle-policy authority and
  `ExperienceEngine._apply_memory_actions` remains the sole durable
  mutation boundary;
- it cannot authorize itself.

Three statements that are never interchangeable: a controller proposal,
a verifier acceptance, and an adoption authorization. None of them is an
application. Only the engine's existing path decides that.

Default mode is `disabled`: no controller is constructed, no verifier
runs, and canonical behavior is byte-for-byte unchanged.

This follows the grounded-extraction integration precedent — one
coordinator, explicit modes, controller output revalidated at the
boundary, exact authorization, no second action-application path — and
narrows it where transition semantics demand: routing is mutually
exclusive, and a verify-only mode inspects canonical planner actions
without changing them.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, replace

from experienceos.memory.planner import CREATE, FORGET, SUPERSEDE, MemoryAction
from experienceos.memory.schema import MemoryStatus

INTEGRATION_ID = "transition_integration"
INTEGRATION_VERSION = "1"
ANNOTATION_VERSION = "1"
AUTHORIZATION_VERSION = "1"


class TransitionIntegrationMode:
    """How far transition intelligence is allowed to reach."""

    DISABLED = "disabled"
    SHADOW = "shadow"
    CANDIDATE = "candidate"
    VERIFY_ONLY = "verify_only"
    ADOPTED = "adopted"


INTEGRATION_MODES = (
    TransitionIntegrationMode.DISABLED,
    TransitionIntegrationMode.SHADOW,
    TransitionIntegrationMode.CANDIDATE,
    TransitionIntegrationMode.VERIFY_ONLY,
    TransitionIntegrationMode.ADOPTED,
)

#: Modes that may never change the canonical action list.
NON_MUTATING_MODES = frozenset(
    {
        TransitionIntegrationMode.DISABLED,
        TransitionIntegrationMode.SHADOW,
        TransitionIntegrationMode.CANDIDATE,
        TransitionIntegrationMode.VERIFY_ONLY,
    }
)


class TransitionSystemId:
    """Feature-based ids reserved by the transition contract.

    A system id implies neither implementation nor adoption.
    """

    REFERENCE = "experienceos_hybrid_full_v2_reference"
    SHADOW = "experienceos_transition_shadow_v1"
    CANDIDATE = "experienceos_transition_candidate_v1"
    RULES = "experienceos_transition_rules_v1"
    ADOPTED = "experienceos_transition_adopted_v1"


_MODE_SYSTEM_ID = {
    TransitionIntegrationMode.SHADOW: TransitionSystemId.SHADOW,
    TransitionIntegrationMode.CANDIDATE: TransitionSystemId.CANDIDATE,
    TransitionIntegrationMode.VERIFY_ONLY: TransitionSystemId.SHADOW,
    TransitionIntegrationMode.ADOPTED: TransitionSystemId.ADOPTED,
}


class TransitionRoute:
    NOT_INVOKED = "not_invoked"
    UPDATE = "update_controller"
    FORGET = "forget_controller"
    ABSTAINED = "abstained"
    ERROR = "routing_error"


class CanonicalActionEffect:
    """What the integration did to the canonical action list."""

    UNCHANGED = "unchanged"
    DIAGNOSTICS_ONLY = "diagnostics_only"
    CANDIDATE_ONLY = "candidate_only"
    VERIFIED_EXISTING_ACTIONS = "verified_existing_actions"
    ACTION_ADDED = "action_added"
    ACTION_REPLACED = "action_replaced"
    ACTION_SUPPRESSED = "action_suppressed"
    AUTHORIZATION_DENIED = "authorization_denied"
    TRANSLATION_FAILED = "translation_failed"
    LIFECYCLE_REJECTED = "lifecycle_rejected"
    ENGINE_REJECTED = "engine_rejected"
    APPLIED = "applied"


class CanonicalEffectStatus:
    NONE = "none"
    SHADOW_ONLY = "shadow_only"
    CANDIDATE_ONLY = "candidate_only"
    ELIGIBLE_NOT_AUTHORIZED = "eligible_not_authorized"
    AUTHORIZED_NOT_APPLIED = "authorized_not_applied"
    APPLIED = "applied"


class ExistingActionStatus:
    VERIFIED = "verified"
    REJECTED = "rejected"
    UNVERIFIABLE = "unverifiable"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    NOT_TRANSITION_RELEVANT = "not_transition_relevant"


class TransitionFailureStage:
    NONE = "none"
    ROUTING = "routing"
    CONTROLLER = "controller"
    VERIFIER = "verifier"
    EVIDENCE = "evidence"
    BEFORE_STATE = "before_state"
    AUTHORIZATION = "authorization"
    TRANSLATION = "translation"
    LIFECYCLE = "lifecycle"


class TransitionIntegrationError(ValueError):
    """Configuration is invalid. Never raised for runtime source input."""


def _digest(value) -> str:
    """Deterministic short digest of any JSON-safe value."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class TransitionIntegrationDiagnostic:
    code: str
    category: str
    detail: str = ""

    def to_record(self) -> dict:
        return {"code": self.code, "category": self.category, "detail": self.detail}


@dataclass(frozen=True)
class TransitionAuthorization:
    """Permission for **one exact verified proposal** to affect canonical
    state in adopted mode.

    Not lifecycle authority: it cannot bypass grounding, verification,
    manager validation, or the engine's application rules, and it carries
    no store and no credentials. Every bound field must match exactly;
    any difference fails closed.
    """

    system_id: str
    controller_id: str
    controller_version: str
    request_id: str
    source_digest: str
    evidence_mode: str
    evidence_digest: str
    before_state_digest: str
    proposal_id: str
    proposal_digest: str
    transition_type: str
    target_ids: tuple
    created_digest: str
    verifier_id: str
    verifier_version: str
    verification_digest: str
    expected_action_type: str
    expected_action_count: int
    mode: str = TransitionIntegrationMode.ADOPTED
    authorization_version: str = AUTHORIZATION_VERSION
    scope: str = "single_proposal"
    single_use: bool = True
    metadata: dict = field(default_factory=dict)

    def binding(self) -> dict:
        """Every field authorization is bound to, for exact comparison."""
        return {
            "authorization_version": self.authorization_version,
            "mode": self.mode,
            "system_id": self.system_id,
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "request_id": self.request_id,
            "source_digest": self.source_digest,
            "evidence_mode": self.evidence_mode,
            "evidence_digest": self.evidence_digest,
            "before_state_digest": self.before_state_digest,
            "proposal_id": self.proposal_id,
            "proposal_digest": self.proposal_digest,
            "transition_type": self.transition_type,
            "target_ids": sorted(self.target_ids),
            "created_digest": self.created_digest,
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "verification_digest": self.verification_digest,
            "expected_action_type": self.expected_action_type,
            "expected_action_count": self.expected_action_count,
        }

    def digest(self) -> str:
        return _digest(self.binding())


@dataclass(frozen=True)
class TransitionAuthorizationDecision:
    authorized: bool
    reason: str = ""
    mismatched_fields: tuple = ()
    authorization_digest: str = ""
    checked: bool = False

    def to_record(self) -> dict:
        return {
            "authorized": self.authorized,
            "checked": self.checked,
            "reason": self.reason,
            "mismatched_fields": list(self.mismatched_fields),
            "authorization_digest": self.authorization_digest,
        }


@dataclass(frozen=True)
class TransitionIntegrationConfig:
    """Immutable integration configuration.

    The default is fully disabled: no controller is constructed, no
    verifier runs, and canonical behavior is unchanged. Adopted mode is
    never reachable from a mode string alone — it additionally requires
    an explicit structured authorization bound to the exact proposal.
    """

    mode: str = TransitionIntegrationMode.DISABLED
    update_controller: object | None = None
    forget_controller: object | None = None
    verifier: object | None = None
    authorizations: tuple = ()
    max_diagnostics: int = 12

    def __post_init__(self):
        if self.mode not in INTEGRATION_MODES:
            raise TransitionIntegrationError(
                f"unknown transition integration mode {self.mode!r}; "
                f"expected one of {INTEGRATION_MODES}"
            )
        for authorization in self.authorizations:
            if not isinstance(authorization, TransitionAuthorization):
                raise TransitionIntegrationError(
                    "authorizations must be TransitionAuthorization values"
                )

    @property
    def enabled(self) -> bool:
        return self.mode != TransitionIntegrationMode.DISABLED

    def to_record(self) -> dict:
        return {
            "mode": self.mode,
            "authorization_count": len(self.authorizations),
            "max_diagnostics": self.max_diagnostics,
        }


@dataclass(frozen=True)
class TransitionIntegrationRequest:
    """One bounded integration request. Carries no store handle."""

    statement: str
    evidence: object  # TransitionSourceEvidence
    before_state: object  # BeforeStateSnapshot
    request_id: str = ""
    user_id: str = ""
    existing_actions: tuple = ()
    authorization: TransitionAuthorization | None = None

    def source_digest(self) -> str:
        return _digest(self.statement)


@dataclass(frozen=True)
class ExistingActionVerification:
    """How one canonical planner action fared under verification.

    Diagnostic only: the action is never changed by this result.
    """

    action_type: str
    target_id: str | None
    inferred_transition: str | None
    status: str
    verifier_status: str | None = None
    reason: str = ""

    def to_record(self) -> dict:
        return {
            "action_type": self.action_type,
            "target_id": self.target_id,
            "inferred_transition": self.inferred_transition,
            "status": self.status,
            "verifier_status": self.verifier_status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TransitionTranslationResult:
    """Existing lifecycle actions a verified transition would need."""

    succeeded: bool
    actions: tuple = ()  # MemoryAction values; never applied here
    action_type: str = ""
    reason: str = ""

    def to_record(self) -> dict:
        return {
            "succeeded": self.succeeded,
            "action_type": self.action_type,
            "action_count": len(self.actions),
            "reason": self.reason,
        }


@dataclass
class TransitionIntegrationResult:
    """Bounded decision handed back to the engine.

    Carries no store handle and no applied state: `action_applied` is
    set only by the engine after its existing application path runs.
    """

    configured_mode: str
    effective_mode: str
    system_id: str | None = None
    route: str = TransitionRoute.NOT_INVOKED
    controller_id: str | None = None
    controller_version: str | None = None
    controller_invoked: bool = False
    verifier_invoked: bool = False
    authorization_checked: bool = False
    translation_attempted: bool = False
    controller_result: object | None = None
    proposal: object | None = None
    verification: object | None = None
    authorization_decision: TransitionAuthorizationDecision | None = None
    translation: TransitionTranslationResult | None = None
    existing_action_verifications: tuple = ()
    canonical_action_effect: str = CanonicalActionEffect.UNCHANGED
    canonical_effect_status: str = CanonicalEffectStatus.NONE
    canonical_effect_eligible: bool = False
    generated_actions: tuple = ()
    fallback_used: bool = False
    failure_stage: str = TransitionFailureStage.NONE
    failure_reason: str = ""
    diagnostics: tuple = ()
    latency_ms: float = 0.0
    stage_latency_ms: dict = field(default_factory=dict)
    integration_id: str = INTEGRATION_ID
    integration_version: str = INTEGRATION_VERSION
    action_applied: bool = False

    @property
    def transition_type(self) -> str | None:
        return getattr(self.proposal, "transition_type", None)

    def to_record(self) -> dict:
        """Deterministic annotation payload. Bounded and privacy-safe."""
        return {
            "annotation_version": ANNOTATION_VERSION,
            "integration_id": self.integration_id,
            "integration_version": self.integration_version,
            "configured_mode": self.configured_mode,
            "effective_mode": self.effective_mode,
            "system_id": self.system_id,
            "route": self.route,
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "controller_invoked": self.controller_invoked,
            "verifier_invoked": self.verifier_invoked,
            "authorization_checked": self.authorization_checked,
            "translation_attempted": self.translation_attempted,
            "transition_type": self.transition_type,
            "proposal_id": getattr(self.proposal, "proposal_id", None),
            "target_ids": sorted(
                getattr(self.proposal, "superseded_ids", ())
                + getattr(self.proposal, "forgotten_ids", ())
            ),
            "preserved_ids": sorted(getattr(self.proposal, "preserved_ids", ())),
            "verifier_status": getattr(self.verification, "status", None),
            "verifier_rejection_reason": getattr(
                self.verification, "rejection_reason", None
            ),
            "canonical_effect_eligible": self.canonical_effect_eligible,
            "authorization": (
                self.authorization_decision.to_record()
                if self.authorization_decision
                else None
            ),
            "translation": (
                self.translation.to_record() if self.translation else None
            ),
            "existing_action_verifications": [
                v.to_record() for v in self.existing_action_verifications
            ],
            "canonical_action_effect": self.canonical_action_effect,
            "canonical_effect_status": self.canonical_effect_status,
            "generated_action_types": [a.action for a in self.generated_actions],
            "fallback_used": self.fallback_used,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "diagnostics": [d.to_record() for d in self.diagnostics],
            "action_applied": self.action_applied,
        }


# --- Action translation -------------------------------------------------------


def _proposal_digest(proposal) -> str:
    return _digest(proposal.to_record()) if proposal is not None else ""


def _created_digest(proposal) -> str:
    if proposal is None or not getattr(proposal, "created", ()):
        return _digest([])
    return _digest([spec.to_record() for spec in proposal.created])


def _verification_digest(verification) -> str:
    return _digest(verification.to_record()) if verification is not None else ""


def _evidence_digest(evidence) -> str:
    return _digest(evidence.to_record()) if evidence is not None else ""


#: Transitions whose correct effect is no lifecycle action at all.
_NO_ACTION_TYPES = frozenset(
    {
        "duplicate_noop",
        "semantic_duplicate_noop",
        "shadow_only",
        "reject_forget_directive_as_creation",
        "reject_unsupported",
        "reject_ambiguous",
        "reject_temporary",
        "reject_question",
        "reject_hypothetical",
        "reject_unrelated",
    }
)


def translate_transition(proposal, verification, before_state):
    """Map a verified transition onto **existing** lifecycle actions.

    Returns data only: nothing here applies anything, and no new action
    type is invented. Supersession uses the repository's own canonical
    representation — a supersede action plus a replacement create
    carrying `replaces`, which the engine already links.

    Fails closed whenever existing action vocabulary cannot represent the
    transition safely.
    """
    transition_type = getattr(proposal, "transition_type", None)
    if transition_type in _NO_ACTION_TYPES:
        return TransitionTranslationResult(
            succeeded=True, actions=(), action_type="none",
            reason="transition requires no lifecycle action",
        )

    if verification is None or not getattr(verification, "accepted", False):
        return TransitionTranslationResult(
            succeeded=False, reason="unverified proposal cannot be translated"
        )

    specs = tuple(getattr(verification, "action_specs", ()))
    if not specs:
        return TransitionTranslationResult(
            succeeded=False, reason="verification produced no action specification"
        )

    if transition_type == "create_new" or transition_type == "scoped_coexistence":
        create = next((s for s in specs if s.action == "create"), None)
        if create is None:
            return TransitionTranslationResult(
                succeeded=False, reason="no create specification"
            )
        return TransitionTranslationResult(
            succeeded=True, action_type=CREATE,
            actions=(
                MemoryAction(
                    action=CREATE, kind=create.kind, text=create.text,
                    reason=f"{INTEGRATION_ID}: {transition_type}",
                    metadata={"provenance": "user_asserted"},
                ),
            ),
        )

    if transition_type == "supersede_existing":
        create = next((s for s in specs if s.action == "create"), None)
        supersede = next((s for s in specs if s.action == "supersede"), None)
        if create is None or supersede is None or not supersede.target_id:
            return TransitionTranslationResult(
                succeeded=False,
                reason="supersession requires a target and a replacement",
            )
        target = before_state.by_id(supersede.target_id)
        if target is None or target.status != MemoryStatus.ACTIVE:
            return TransitionTranslationResult(
                succeeded=False, reason="supersession target is not active"
            )
        return TransitionTranslationResult(
            succeeded=True, action_type=SUPERSEDE,
            actions=(
                MemoryAction(
                    action=SUPERSEDE, kind=target.kind,
                    memory_id=supersede.target_id, text=target.text,
                    reason=f"{INTEGRATION_ID}: supersede_existing",
                ),
                MemoryAction(
                    action=CREATE, kind=create.kind, text=create.text,
                    replaces=supersede.target_id,
                    reason=f"{INTEGRATION_ID}: supersede_existing replacement",
                    metadata={"provenance": "user_asserted"},
                ),
            ),
        )

    if transition_type == "forget_existing":
        forget = next((s for s in specs if s.action == "forget"), None)
        if forget is None or not forget.target_id:
            return TransitionTranslationResult(
                succeeded=False, reason="forget requires exactly one target"
            )
        if any(s.action == "create" for s in specs):
            return TransitionTranslationResult(
                succeeded=False,
                reason="a forget directive must not create a memory",
            )
        target = before_state.by_id(forget.target_id)
        if target is None or target.status != MemoryStatus.ACTIVE:
            return TransitionTranslationResult(
                succeeded=False, reason="forget target is not active"
            )
        return TransitionTranslationResult(
            succeeded=True, action_type=FORGET,
            actions=(
                MemoryAction(
                    action=FORGET, kind=target.kind,
                    memory_id=forget.target_id, text=target.text,
                    reason=f"{INTEGRATION_ID}: forget_existing",
                ),
            ),
        )

    return TransitionTranslationResult(
        succeeded=False,
        reason=f"no existing action mapping for {transition_type!r}",
    )


# --- Existing planner action verification ------------------------------------


def infer_existing_transition(actions) -> tuple:
    """Infer the transition an existing planner action batch represents.

    Returns (transition_type, target_id, create_action) or
    (None, None, None) when the batch is not transition-relevant.
    """
    creates = [a for a in actions if a.action == CREATE]
    supersedes = [a for a in actions if a.action == SUPERSEDE]
    forgets = [a for a in actions if a.action == FORGET]
    if forgets and not creates:
        return "forget_existing", forgets[0].memory_id, None
    if supersedes and creates:
        replacement = next(
            (c for c in creates if c.replaces == supersedes[0].memory_id), None
        )
        if replacement is not None:
            return "supersede_existing", supersedes[0].memory_id, replacement
        return "supersede_existing", supersedes[0].memory_id, creates[0]
    if creates and not supersedes and not forgets:
        return "create_new", None, creates[0]
    if not actions:
        return None, None, None
    return None, None, None


# --- Coordinator --------------------------------------------------------------


class TransitionIntegrationCoordinator:
    """Runs the configured mode and returns a bounded decision.

    Deliberately has **no store field and no mutation method**. It routes
    to at most one controller, verifies, checks authorization, and
    translates — then hands data back. The engine keeps every existing
    lifecycle check and performs any application.
    """

    integration_id = INTEGRATION_ID
    version = INTEGRATION_VERSION

    def __init__(self, config: TransitionIntegrationConfig):
        if not isinstance(config, TransitionIntegrationConfig):
            raise TransitionIntegrationError(
                "config must be a TransitionIntegrationConfig"
            )
        self.config = config
        self._update = config.update_controller
        self._forget = config.forget_controller
        self._verifier = config.verifier

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def mode(self) -> str:
        return self.config.mode

    # -- lazily constructed collaborators --------------------------------
    #
    # Nothing is constructed in disabled mode: `evaluate` returns before
    # reaching here, so a disabled coordinator builds no controller.

    def _update_controller(self):
        if self._update is None:
            from experienceos.memory.update_intelligence import (
                DeterministicUpdateController,
            )

            self._update = DeterministicUpdateController(verifier=self._verifier_impl())
        return self._update

    def _forget_controller(self):
        if self._forget is None:
            from experienceos.memory.forget_intelligence import (
                DeterministicForgetController,
            )

            self._forget = DeterministicForgetController(
                verifier=self._verifier_impl()
            )
        return self._forget

    def _verifier_impl(self):
        if self._verifier is None:
            from experienceos.memory.transition_verification import (
                TransitionVerifier,
            )

            self._verifier = TransitionVerifier()
        return self._verifier

    # -- public API ------------------------------------------------------

    def evaluate(self, request: TransitionIntegrationRequest):
        """Evaluate one request. Never mutates; never applies."""
        started = time.perf_counter()
        stages = {}
        diagnostics = []
        mode = self.config.mode

        if mode == TransitionIntegrationMode.DISABLED:
            diagnostics.append(
                TransitionIntegrationDiagnostic(
                    "transition_disabled", "mode",
                    "transition integration is disabled; no component ran",
                )
            )
            return TransitionIntegrationResult(
                configured_mode=mode, effective_mode=mode,
                canonical_action_effect=CanonicalActionEffect.UNCHANGED,
                canonical_effect_status=CanonicalEffectStatus.NONE,
                diagnostics=tuple(diagnostics),
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

        system_id = _MODE_SYSTEM_ID.get(mode)

        if mode == TransitionIntegrationMode.VERIFY_ONLY:
            return self._verify_only(request, started, stages, diagnostics, system_id)

        # -- route ----------------------------------------------------
        mark = time.perf_counter()
        try:
            route, controller_result = self._route(request)
        except Exception as exc:  # contained: never break the interaction
            return self._failure(
                mode, system_id, TransitionFailureStage.CONTROLLER,
                type(exc).__name__, diagnostics, started, stages,
                route=TransitionRoute.ERROR,
            )
        stages["routing_ms"] = (time.perf_counter() - mark) * 1000.0
        diagnostics.append(
            TransitionIntegrationDiagnostic(
                {
                    TransitionRoute.UPDATE: "update_controller_selected",
                    TransitionRoute.FORGET: "forget_controller_selected",
                }.get(route, "controller_not_invoked"),
                "routing", route,
            )
        )

        proposal = getattr(controller_result, "proposal", None)
        verification = getattr(controller_result, "verification", None)
        controller_id = getattr(controller_result, "controller_id", None)
        controller_version = getattr(controller_result, "controller_version", None)

        if proposal is None:
            diagnostics.append(
                TransitionIntegrationDiagnostic(
                    "controller_abstained", "controller",
                    getattr(controller_result, "abstention_reason", ""),
                )
            )
            return TransitionIntegrationResult(
                configured_mode=mode, effective_mode=mode, system_id=system_id,
                route=route, controller_id=controller_id,
                controller_version=controller_version, controller_invoked=True,
                controller_result=controller_result,
                canonical_action_effect=CanonicalActionEffect.DIAGNOSTICS_ONLY,
                canonical_effect_status=CanonicalEffectStatus.NONE,
                diagnostics=tuple(diagnostics),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                stage_latency_ms=dict(stages),
            )

        diagnostics.append(
            TransitionIntegrationDiagnostic(
                "proposal_generated", "controller", proposal.transition_type
            )
        )
        if verification is not None:
            diagnostics.append(
                TransitionIntegrationDiagnostic(
                    "verification_accepted"
                    if verification.accepted
                    else "verification_rejected",
                    "verifier",
                    verification.rejection_reason or verification.status,
                )
            )
        eligible = bool(
            verification is not None and verification.canonical_effect_eligible
        )
        if not eligible:
            diagnostics.append(
                TransitionIntegrationDiagnostic(
                    "canonical_effect_ineligible", "verifier",
                    getattr(verification, "canonical_effect_reason", ""),
                )
            )

        base = dict(
            configured_mode=mode, effective_mode=mode, system_id=system_id,
            route=route, controller_id=controller_id,
            controller_version=controller_version, controller_invoked=True,
            verifier_invoked=verification is not None,
            controller_result=controller_result, proposal=proposal,
            verification=verification, canonical_effect_eligible=eligible,
        )

        # -- shadow ---------------------------------------------------
        if mode == TransitionIntegrationMode.SHADOW:
            diagnostics.append(
                TransitionIntegrationDiagnostic(
                    "canonical_actions_unchanged", "mode",
                    "shadow records diagnostics only",
                )
            )
            return TransitionIntegrationResult(
                **base,
                canonical_action_effect=CanonicalActionEffect.DIAGNOSTICS_ONLY,
                canonical_effect_status=CanonicalEffectStatus.SHADOW_ONLY,
                diagnostics=tuple(diagnostics),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                stage_latency_ms=dict(stages),
            )

        # -- candidate: exercise translation, insert nothing ----------
        mark = time.perf_counter()
        translation = self._translate(proposal, verification, request)
        stages["translation_ms"] = (time.perf_counter() - mark) * 1000.0
        diagnostics.append(
            TransitionIntegrationDiagnostic(
                "translation_succeeded" if translation.succeeded
                else "translation_failed",
                "translation", translation.reason,
            )
        )
        if mode == TransitionIntegrationMode.CANDIDATE:
            diagnostics.append(
                TransitionIntegrationDiagnostic(
                    "candidate_action_not_inserted", "mode",
                    "candidate exercises translation without insertion",
                )
            )
            return TransitionIntegrationResult(
                **base, translation_attempted=True, translation=translation,
                generated_actions=(),
                canonical_action_effect=CanonicalActionEffect.CANDIDATE_ONLY,
                canonical_effect_status=CanonicalEffectStatus.CANDIDATE_ONLY,
                diagnostics=tuple(diagnostics),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                stage_latency_ms=dict(stages),
            )

        # -- adopted --------------------------------------------------
        mark = time.perf_counter()
        decision = self._authorize(request, proposal, verification, translation)
        stages["authorization_ms"] = (time.perf_counter() - mark) * 1000.0
        diagnostics.append(
            TransitionIntegrationDiagnostic(
                {
                    True: "authorization_accepted",
                }.get(
                    decision.authorized,
                    "authorization_missing"
                    if decision.reason == "authorization_missing"
                    else "authorization_mismatch",
                ),
                "authorization",
                decision.reason,
            )
        )
        if not decision.authorized:
            return TransitionIntegrationResult(
                **base, translation_attempted=True, translation=translation,
                authorization_checked=True, authorization_decision=decision,
                canonical_action_effect=CanonicalActionEffect.AUTHORIZATION_DENIED,
                canonical_effect_status=(
                    CanonicalEffectStatus.ELIGIBLE_NOT_AUTHORIZED
                    if eligible
                    else CanonicalEffectStatus.NONE
                ),
                fallback_used=True,
                failure_stage=TransitionFailureStage.AUTHORIZATION,
                failure_reason=decision.reason,
                diagnostics=tuple(diagnostics),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                stage_latency_ms=dict(stages),
            )
        if not translation.succeeded:
            return TransitionIntegrationResult(
                **base, translation_attempted=True, translation=translation,
                authorization_checked=True, authorization_decision=decision,
                canonical_action_effect=CanonicalActionEffect.TRANSLATION_FAILED,
                canonical_effect_status=CanonicalEffectStatus.AUTHORIZED_NOT_APPLIED,
                fallback_used=True,
                failure_stage=TransitionFailureStage.TRANSLATION,
                failure_reason=translation.reason,
                diagnostics=tuple(diagnostics),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                stage_latency_ms=dict(stages),
            )

        # Authorized and translated. The engine decides admission and
        # application; nothing is applied here.
        return TransitionIntegrationResult(
            **base, translation_attempted=True, translation=translation,
            authorization_checked=True, authorization_decision=decision,
            generated_actions=translation.actions,
            canonical_action_effect=CanonicalActionEffect.ACTION_ADDED,
            canonical_effect_status=CanonicalEffectStatus.AUTHORIZED_NOT_APPLIED,
            diagnostics=tuple(diagnostics),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            stage_latency_ms=dict(stages),
        )

    # -- routing ---------------------------------------------------------

    def _route(self, request) -> tuple:
        """Route to exactly one controller.

        Update classification runs first; only its explicit forget
        handoff sends the source to forget targeting. The two controllers
        never both produce a proposal for one statement, and nothing is
        ranked or merged.
        """
        from experienceos.memory.update_intelligence import AbstentionReason

        update = self._update_controller().propose(
            request.statement, request.evidence, request.before_state
        )
        if update.abstention_reason == AbstentionReason.FORGET_HANDOFF:
            forget = self._forget_controller().propose(
                request.statement, request.evidence, request.before_state
            )
            return TransitionRoute.FORGET, forget
        if update.abstained:
            return TransitionRoute.ABSTAINED, update
        return TransitionRoute.UPDATE, update

    # -- authorization ---------------------------------------------------

    def expected_binding(self, request, proposal, verification, translation) -> dict:
        """The binding an authorization must match exactly."""
        verifier_id = getattr(verification, "verifier_id", "")
        verifier_version = getattr(verification, "verifier_version", "")
        return {
            "authorization_version": AUTHORIZATION_VERSION,
            "mode": TransitionIntegrationMode.ADOPTED,
            "system_id": TransitionSystemId.ADOPTED,
            "controller_id": getattr(proposal, "proposer_id", ""),
            "controller_version": _controller_version(proposal),
            "request_id": request.request_id,
            "source_digest": request.source_digest(),
            "evidence_mode": getattr(request.evidence, "evidence_mode", ""),
            "evidence_digest": _evidence_digest(request.evidence),
            "before_state_digest": request.before_state.digest(),
            "proposal_id": proposal.proposal_id,
            "proposal_digest": _proposal_digest(proposal),
            "transition_type": proposal.transition_type,
            "target_ids": sorted(
                tuple(proposal.superseded_ids) + tuple(proposal.forgotten_ids)
            ),
            "created_digest": _created_digest(proposal),
            "verifier_id": verifier_id,
            "verifier_version": verifier_version,
            "verification_digest": _verification_digest(verification),
            "expected_action_type": translation.action_type,
            "expected_action_count": len(translation.actions),
        }

    def _authorize(self, request, proposal, verification, translation):
        """Exact-match authorization. Any difference fails closed."""
        # Authorization never substitutes for verification.
        if verification is None or not verification.accepted:
            return TransitionAuthorizationDecision(
                False, "proposal_not_verified", checked=True
            )
        if not verification.canonical_effect_eligible:
            return TransitionAuthorizationDecision(
                False, "canonical_effect_ineligible", checked=True
            )
        candidates = list(self.config.authorizations)
        if request.authorization is not None:
            candidates.append(request.authorization)
        if not candidates:
            return TransitionAuthorizationDecision(
                False, "authorization_missing", checked=True
            )
        expected = self.expected_binding(
            request, proposal, verification, translation
        )
        best_mismatch = None
        for authorization in candidates:
            binding = authorization.binding()
            mismatched = tuple(
                sorted(
                    key for key, value in expected.items()
                    if binding.get(key) != value
                )
            )
            if not mismatched:
                return TransitionAuthorizationDecision(
                    True, "exact_match", authorization_digest=authorization.digest(),
                    checked=True,
                )
            if best_mismatch is None or len(mismatched) < len(best_mismatch):
                best_mismatch = mismatched
        return TransitionAuthorizationDecision(
            False, "authorization_mismatch",
            mismatched_fields=best_mismatch or (), checked=True,
        )

    # -- translation ------------------------------------------------------

    def _translate(self, proposal, verification, request):
        try:
            return translate_transition(proposal, verification, request.before_state)
        except Exception as exc:  # contained
            return TransitionTranslationResult(
                succeeded=False, reason=f"translation_error:{type(exc).__name__}"
            )

    # -- verify-only ------------------------------------------------------

    def _verify_only(self, request, started, stages, diagnostics, system_id):
        """Inspect existing planner actions without changing them."""
        mark = time.perf_counter()
        verifications = []
        transition_type, target_id, create = infer_existing_transition(
            tuple(request.existing_actions)
        )
        if transition_type is None:
            for action in request.existing_actions:
                verifications.append(
                    ExistingActionVerification(
                        action_type=action.action, target_id=action.memory_id,
                        inferred_transition=None,
                        status=ExistingActionStatus.NOT_TRANSITION_RELEVANT,
                        reason="no transition inferred from this action batch",
                    )
                )
            if not request.existing_actions:
                diagnostics.append(
                    TransitionIntegrationDiagnostic(
                        "canonical_actions_unchanged", "mode",
                        "no canonical actions to verify",
                    )
                )
        else:
            verifications.append(
                self._verify_existing(
                    request, transition_type, target_id, create, diagnostics
                )
            )
        stages["existing_action_ms"] = (time.perf_counter() - mark) * 1000.0
        return TransitionIntegrationResult(
            configured_mode=self.config.mode,
            effective_mode=self.config.mode,
            system_id=system_id,
            route=TransitionRoute.NOT_INVOKED,
            verifier_invoked=bool(transition_type),
            existing_action_verifications=tuple(verifications),
            canonical_action_effect=(
                CanonicalActionEffect.VERIFIED_EXISTING_ACTIONS
                if verifications
                else CanonicalActionEffect.UNCHANGED
            ),
            canonical_effect_status=CanonicalEffectStatus.NONE,
            diagnostics=tuple(diagnostics),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            stage_latency_ms=dict(stages),
        )

    def _verify_existing(self, request, transition_type, target_id, create, diagnostics):
        """Verify one inferred existing transition. Never changes it."""
        from experienceos.controllers.extraction import ProposedMemoryCandidate
        from experienceos.memory.transition_verification import (
            CreatedMemorySpec,
            ProposedTransition,
        )

        action_type = (
            FORGET if transition_type == "forget_existing"
            else SUPERSEDE if transition_type == "supersede_existing"
            else CREATE
        )
        active_ids = [m.memory_id for m in request.before_state.active()]
        try:
            created = ()
            if create is not None:
                created = (
                    CreatedMemorySpec(
                        candidate=ProposedMemoryCandidate(
                            kind=create.kind, text=create.text or "x"
                        ),
                        local_ref="created:0",
                        replaces=target_id if transition_type == "supersede_existing"
                        else None,
                    ),
                )
            proposal = ProposedTransition(
                proposal_id=f"{INTEGRATION_ID}:existing:{request.request_id}",
                transition_type=transition_type,
                evidence=request.evidence,
                before_state_digest=request.before_state.digest(),
                target_ids=(target_id,) if target_id else (),
                created=created,
                superseded_ids=(
                    (target_id,) if transition_type == "supersede_existing" else ()
                ),
                forgotten_ids=(
                    (target_id,) if transition_type == "forget_existing" else ()
                ),
                preserved_ids=tuple(active_ids),
                unchanged_ids=tuple(
                    m for m in active_ids if m != target_id
                ),
                lineage_edges=(
                    ((target_id, "created:0"),)
                    if transition_type == "supersede_existing" and created
                    else ()
                ),
                proposer_id="canonical_planner",
                proposal_source="existing_action",
            )
            verification = self._verifier_impl().verify(proposal, request.before_state)
        except Exception as exc:  # contained
            diagnostics.append(
                TransitionIntegrationDiagnostic(
                    "existing_action_unverifiable", "verifier", type(exc).__name__
                )
            )
            return ExistingActionVerification(
                action_type=action_type, target_id=target_id,
                inferred_transition=transition_type,
                status=ExistingActionStatus.UNVERIFIABLE,
                reason=f"verifier_error:{type(exc).__name__}",
            )

        status = {
            "accepted": ExistingActionStatus.VERIFIED,
            "rejected": ExistingActionStatus.REJECTED,
            "ambiguous": ExistingActionStatus.AMBIGUOUS,
            "unsupported": ExistingActionStatus.UNSUPPORTED,
            "structurally_invalid": ExistingActionStatus.REJECTED,
            "shadow_only": ExistingActionStatus.UNVERIFIABLE,
        }.get(verification.status, ExistingActionStatus.UNVERIFIABLE)
        diagnostics.append(
            TransitionIntegrationDiagnostic(
                "existing_action_verified"
                if status == ExistingActionStatus.VERIFIED
                else "existing_action_rejected",
                "verifier",
                verification.rejection_reason or verification.status,
            )
        )
        diagnostics.append(
            TransitionIntegrationDiagnostic(
                "canonical_actions_unchanged", "mode",
                "verify-only never adds, removes, or rewrites an action",
            )
        )
        return ExistingActionVerification(
            action_type=action_type, target_id=target_id,
            inferred_transition=transition_type, status=status,
            verifier_status=verification.status,
            reason=verification.rejection_reason or "",
        )

    # -- failures ---------------------------------------------------------

    def _failure(
        self, mode, system_id, stage, exception_name, diagnostics, started,
        stages, route=TransitionRoute.NOT_INVOKED,
    ):
        """Bounded failure: baseline behavior continues unchanged."""
        diagnostics.append(
            TransitionIntegrationDiagnostic(
                "fallback_to_baseline", "fallback",
                f"{stage}:{exception_name}",
            )
        )
        return TransitionIntegrationResult(
            configured_mode=mode, effective_mode=mode, system_id=system_id,
            route=route,
            canonical_action_effect=CanonicalActionEffect.UNCHANGED,
            canonical_effect_status=CanonicalEffectStatus.NONE,
            fallback_used=True, failure_stage=stage,
            failure_reason=exception_name,
            diagnostics=tuple(diagnostics),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            stage_latency_ms=dict(stages),
        )


def _controller_version(proposal) -> str:
    from experienceos.memory.forget_intelligence import FORGET_CONTROLLER_VERSION
    from experienceos.memory.update_intelligence import UPDATE_CONTROLLER_VERSION

    proposer = getattr(proposal, "proposer_id", "")
    if proposer.startswith("experienceos_forget"):
        return FORGET_CONTROLLER_VERSION
    return UPDATE_CONTROLLER_VERSION


def build_authorization(
    coordinator: TransitionIntegrationCoordinator,
    request: TransitionIntegrationRequest,
    proposal,
    verification,
    translation,
    **overrides,
) -> TransitionAuthorization:
    """Build the exact authorization for one verified proposal.

    A deliberate convenience for tests and explicit operator tooling: it
    binds every field to the *actual* proposal, so an authorization can
    never be written by hand against a stale one. Overrides exist so a
    single field can be corrupted to prove the mismatch fails closed.
    """
    binding = coordinator.expected_binding(
        request, proposal, verification, translation
    )
    binding["target_ids"] = tuple(binding["target_ids"])
    binding.update(overrides)
    return TransitionAuthorization(**binding)
