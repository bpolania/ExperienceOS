"""Bounded runtime authority for canonical lifecycle transitions.

Closes the exact blocker identified upstream: adopted-mode transition
integration needs a `TransitionAuthorization` bound to the runtime
request, before-state, proposal, verification, and translation — which a
static configuration cannot precompute. This authority issues that exact
receipt, but only for one verified, canonical-effect-eligible, single
active-target supersede or forget produced by an allowlisted deterministic
controller. It is not a general adoption policy.

Deliberate boundaries (enforced by structure):

- it is data-only: no store handle, no engine or manager reference, no
  mutation method, no persistence, no network, no model inference;
- it authorizes only the two allowlisted deterministic controllers and
  the two supported transition types — never learned/experimental
  controllers and never ordinary creation;
- it reuses the existing exact authorization binding (`build_authorization`)
  without omitting, wildcarding, or normalizing away any bound field;
- it fails closed with a stable, machine-testable reason for every
  ineligible input, and never raises on ordinary ineligible source input;
- it issues the receipt; the existing exact `_authorize` comparison still
  consumes and validates it. The authority never approves generated
  actions and never applies anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from experienceos.memory.forget_intelligence import (
    FORGET_CONTROLLER_ID,
    FORGET_CONTROLLER_VERSION,
)
from experienceos.memory.planner import CREATE, FORGET, SUPERSEDE
from experienceos.memory.transition_verification import (
    TRANSITION_VERIFIER_ID,
)
from experienceos.memory.update_intelligence import (
    UPDATE_CONTROLLER_ID,
    UPDATE_CONTROLLER_VERSION,
)

AUTHORITY_ID = "experienceos_bounded_runtime_transition_authority_v1"

SUPERSEDE_EXISTING = "supersede_existing"
FORGET_EXISTING = "forget_existing"
SUPPORTED_TRANSITION_TYPES = (SUPERSEDE_EXISTING, FORGET_EXISTING)

# Immutable (controller_id, controller_version) allowlists per route. Only
# the canonical deterministic controllers. Never a learned/experimental
# controller (grounded_qwen_shadow-1, qwen_update-1) and never a bare
# controller with a merely compatible output shape.
ALLOWED_UPDATE_CONTROLLERS = frozenset({
    (UPDATE_CONTROLLER_ID, UPDATE_CONTROLLER_VERSION),
})
ALLOWED_FORGET_CONTROLLERS = frozenset({
    (FORGET_CONTROLLER_ID, FORGET_CONTROLLER_VERSION),
})
ALLOWED_VERIFIER_IDS = frozenset({TRANSITION_VERIFIER_ID})


# -- stable denial reasons ----------------------------------------------------

MODE_NOT_ADOPTED = "mode_not_adopted"
PROPOSAL_MISSING = "proposal_missing"
CONTROLLER_MISSING = "controller_missing"
CONTROLLER_NOT_ALLOWLISTED = "controller_not_allowlisted"
CONTROLLER_VERSION_NOT_ALLOWLISTED = "controller_version_not_allowlisted"
TRANSITION_TYPE_UNSUPPORTED = "transition_type_unsupported"
VERIFICATION_MISSING = "verification_missing"
VERIFICATION_REJECTED = "verification_rejected"
CANONICAL_EFFECT_INELIGIBLE = "canonical_effect_ineligible"
VERIFIER_NOT_ALLOWLISTED = "verifier_not_allowlisted"
VERIFICATION_PROPOSAL_MISMATCH = "verification_proposal_mismatch"
VERIFICATION_BEFORE_STATE_MISMATCH = "verification_before_state_mismatch"
TRANSLATION_MISSING = "translation_missing"
TRANSLATION_FAILED = "translation_failed"
TRANSLATION_MISMATCH = "translation_mismatch"
TARGET_MISSING = "target_missing"
MULTIPLE_TARGETS = "multiple_targets"
TARGET_CONFLICT = "target_conflict"
TARGET_NOT_ACTIVE = "target_not_active"
TARGET_NOT_IN_BEFORE_STATE = "target_not_in_before_state"
TARGET_SCOPE_MISMATCH = "target_scope_mismatch"
WRONG_ACTION_TYPE = "wrong_action_type"
WRONG_ACTION_COUNT = "wrong_action_count"
SUPERSEDE_LINEAGE_MISSING = "supersede_lineage_missing"
SUPERSEDE_HAS_FORGET_EFFECT = "supersede_has_forget_effect"
FORGET_HAS_SUPERSEDE_EFFECT = "forget_has_supersede_effect"
FORGET_CREATES_MEMORY = "forget_creates_memory"
BINDING_CONSTRUCTION_FAILED = "binding_construction_failed"
MALFORMED_INPUT = "malformed_input"

AUTHORIZED = "authorized"


@dataclass(frozen=True)
class RuntimeAuthorityDecision:
    """Immutable authority decision. ``receipt`` is the existing frozen
    ``TransitionAuthorization`` on success, else None."""

    authorized: bool
    reason: str
    receipt: object = None  # TransitionAuthorization | None
    checked: bool = True
    diagnostics: tuple = ()

    def to_record(self) -> dict:
        return {
            "authorized": self.authorized,
            "reason": self.reason,
            "checked": self.checked,
            "receipt_digest": (
                self.receipt.digest() if self.receipt is not None else None
            ),
            "diagnostics": list(self.diagnostics),
        }


def _deny(reason: str, *diagnostics) -> RuntimeAuthorityDecision:
    return RuntimeAuthorityDecision(
        authorized=False, reason=reason, receipt=None, checked=True,
        diagnostics=tuple(diagnostics),
    )


@dataclass(frozen=True)
class BoundedRuntimeTransitionAuthority:
    """Deterministic, data-only issuer of one exact transition receipt."""

    allowed_update_controllers: frozenset = ALLOWED_UPDATE_CONTROLLERS
    allowed_forget_controllers: frozenset = ALLOWED_FORGET_CONTROLLERS
    allowed_verifier_ids: frozenset = ALLOWED_VERIFIER_IDS
    authority_id: str = AUTHORITY_ID

    # -- transition receipt ----------------------------------------------------

    def authorize_transition(
        self, *, coordinator, request, proposal, verification, translation,
    ) -> RuntimeAuthorityDecision:
        """Issue an exact TransitionAuthorization receipt, or fail closed.

        Every ineligible case returns a denial (never raises); an
        unexpected internal error is contained as ``malformed_input`` with
        only the exception type name. No raw source text or memory content
        enters a diagnostic.
        """
        try:
            return self._authorize_transition(
                coordinator, request, proposal, verification, translation
            )
        except Exception as exc:  # noqa: BLE001 — contained, type-name only
            return _deny(MALFORMED_INPUT, type(exc).__name__)

    def _authorize_transition(
        self, coordinator, request, proposal, verification, translation,
    ) -> RuntimeAuthorityDecision:
        from experienceos.memory.transition_integration import (
            TransitionIntegrationMode,
        )

        # 7.1 mode — adopted only.
        mode = getattr(getattr(coordinator, "config", None), "mode", None)
        if mode != TransitionIntegrationMode.ADOPTED:
            return _deny(MODE_NOT_ADOPTED)

        # 7.2 proposal + controller allowlist.
        if proposal is None:
            return _deny(PROPOSAL_MISSING)
        controller_id = getattr(proposal, "proposer_id", "") or ""
        if not controller_id:
            return _deny(CONTROLLER_MISSING)
        ttype = getattr(proposal, "transition_type", "") or ""
        if ttype not in SUPPORTED_TRANSITION_TYPES:
            return _deny(TRANSITION_TYPE_UNSUPPORTED, ttype)
        version = _controller_version(controller_id)
        allowed = (
            self.allowed_update_controllers
            if ttype == SUPERSEDE_EXISTING
            else self.allowed_forget_controllers
        )
        allowed_ids = {cid for cid, _ in allowed}
        if controller_id not in allowed_ids:
            return _deny(CONTROLLER_NOT_ALLOWLISTED, controller_id)
        if (controller_id, version) not in allowed:
            return _deny(CONTROLLER_VERSION_NOT_ALLOWLISTED, controller_id)

        # 7.3 verification.
        if verification is None:
            return _deny(VERIFICATION_MISSING)
        if not getattr(verification, "accepted", False):
            return _deny(VERIFICATION_REJECTED)
        if not getattr(verification, "canonical_effect_eligible", False):
            return _deny(CANONICAL_EFFECT_INELIGIBLE)
        if getattr(verification, "verifier_id", "") not in self.allowed_verifier_ids:
            return _deny(VERIFIER_NOT_ALLOWLISTED)
        before_digest = request.before_state.digest()
        # The verification refers to the exact proposal (and its type).
        if getattr(verification, "proposal_id", None) != proposal.proposal_id:
            return _deny(VERIFICATION_PROPOSAL_MISMATCH)
        if getattr(verification, "transition_type", None) != ttype:
            return _deny(VERIFICATION_PROPOSAL_MISMATCH)
        # The proposal was built for this exact before-state; a before-state
        # changed after proposal generation fails closed here (and again at
        # the receipt's before_state_digest binding).
        if getattr(proposal, "before_state_digest", "") != before_digest:
            return _deny(VERIFICATION_BEFORE_STATE_MISMATCH)

        # 7.4 translation.
        if translation is None:
            return _deny(TRANSLATION_MISSING)
        if not getattr(translation, "succeeded", False):
            return _deny(TRANSLATION_FAILED)
        actions = tuple(getattr(translation, "actions", ()) or ())
        action_type = getattr(translation, "action_type", "")

        superseded = tuple(getattr(proposal, "superseded_ids", ()) or ())
        forgotten = tuple(getattr(proposal, "forgotten_ids", ()) or ())
        if superseded and forgotten:
            return _deny(TARGET_CONFLICT)

        # 7.5–7.7 target cardinality and per-type action shape.
        if ttype == SUPERSEDE_EXISTING:
            targets, other = superseded, forgotten
            if other:
                return _deny(SUPERSEDE_HAS_FORGET_EFFECT)
            if len(targets) == 0:
                return _deny(TARGET_MISSING)
            if len(targets) > 1:
                return _deny(MULTIPLE_TARGETS)
            if action_type != SUPERSEDE:
                return _deny(WRONG_ACTION_TYPE, action_type)
            supersedes = [a for a in actions if a.action == SUPERSEDE]
            creates = [a for a in actions if a.action == CREATE]
            forgets = [a for a in actions if a.action == FORGET]
            if forgets:
                return _deny(SUPERSEDE_HAS_FORGET_EFFECT)
            if len(actions) != 2 or len(supersedes) != 1 or len(creates) != 1:
                return _deny(WRONG_ACTION_COUNT, str(len(actions)))
            if creates[0].replaces != targets[0]:
                return _deny(SUPERSEDE_LINEAGE_MISSING)
            target = targets[0]
        else:  # FORGET_EXISTING
            targets, other = forgotten, superseded
            if other:
                return _deny(FORGET_HAS_SUPERSEDE_EFFECT)
            if len(targets) == 0:
                return _deny(TARGET_MISSING)
            if len(targets) > 1:
                return _deny(MULTIPLE_TARGETS)
            if getattr(proposal, "created", ()):
                return _deny(FORGET_CREATES_MEMORY)
            if action_type != FORGET:
                return _deny(WRONG_ACTION_TYPE, action_type)
            if len(actions) != 1 or actions[0].action != FORGET:
                return _deny(WRONG_ACTION_COUNT, str(len(actions)))
            if any(a.action in (SUPERSEDE, CREATE) for a in actions):
                return _deny(FORGET_HAS_SUPERSEDE_EFFECT)
            target = targets[0]

        # target must be present and active in the exact before-state (the
        # before-state is already scoped to this request's user).
        known = {m.memory_id for m in request.before_state.memories}
        if target not in known:
            return _deny(TARGET_NOT_IN_BEFORE_STATE, target)
        if target not in request.before_state.active_ids():
            return _deny(TARGET_NOT_ACTIVE, target)

        # 7.8 issue the exact receipt via the existing binding machinery.
        from experienceos.memory.transition_integration import build_authorization

        try:
            receipt = build_authorization(
                coordinator, request, proposal, verification, translation
            )
        except Exception as exc:  # noqa: BLE001 — contained, type-name only
            return _deny(BINDING_CONSTRUCTION_FAILED, type(exc).__name__)
        return RuntimeAuthorityDecision(
            authorized=True, reason=AUTHORIZED, receipt=receipt, checked=True,
            diagnostics=(ttype,),
        )

    # -- replacement receipt (supersede only) ---------------------------------

    def authorize_replacement(self, plan):
        """Issue the plan-bound ReplacementAuthorization for a ready
        supersede replacement plan, or None.

        Data-only: it consumes no plan, applies nothing, and touches no
        engine. It issues the receipt only for a `PLAN_READY` plan with a
        binding; the transition-eligibility linkage (that the plan derives
        from an authorized deterministic supersede) is enforced by the
        integration order — the engine builds this plan only after an
        authorized supersede.
        """
        from experienceos.memory.action_replacement import (
            authorization_from_plan,
        )

        if plan is None or not getattr(plan, "ready", False):
            return None
        if plan.binding() is None:
            return None
        return authorization_from_plan(plan)


def _controller_version(controller_id: str) -> str:
    """The controller version implied by an allowlisted controller id."""
    if controller_id == FORGET_CONTROLLER_ID:
        return FORGET_CONTROLLER_VERSION
    return UPDATE_CONTROLLER_VERSION
