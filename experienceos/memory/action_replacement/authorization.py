"""Exact authorization for one action-replacement plan.

This reuses the established exact-binding authorization pattern (a frozen
permission whose every bound field must match, any difference failing
closed) and scopes it to a single :class:`ActionReplacementPlan`. It is
not a parallel authorization subsystem: it binds the immutable
`ReplacementBinding` the plan already produced, and it authorizes *that
exact plan*, never a general right to replace an action.

It carries no store and no credentials, performs no mutation, and makes
no lifecycle decision. The engine consults it; the engine — the sole
durable mutation boundary — still admits and applies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experienceos.memory.action_replacement.plan import (
    ActionReplacementPlan,
    ReplacementBinding,
)

REPLACEMENT_AUTHORIZATION_VERSION = "1"


def _occurrence_triple(occurrence) -> list:
    return [
        occurrence.content_digest,
        occurrence.occurrence_index,
        occurrence.action_list_digest,
    ]


def _binding_fields(
    *,
    plan_digest,
    before_state_digest,
    original_action_list_digest,
    matched_occurrence_triple,
    replaced_action_digest,
    preserved_occurrences_digest,
    inserted_action_digests,
    projected_action_list_digest,
    decision_type,
    verified_transition_id,
    authorization_version,
) -> dict:
    return {
        "authorization_version": authorization_version,
        "plan_digest": plan_digest,
        "before_state_digest": before_state_digest,
        "original_action_list_digest": original_action_list_digest,
        "matched_occurrence": list(matched_occurrence_triple),
        "replaced_action_digest": replaced_action_digest,
        "preserved_occurrences_digest": preserved_occurrences_digest,
        "inserted_action_digests": list(inserted_action_digests),
        "projected_action_list_digest": projected_action_list_digest,
        "decision_type": decision_type,
        "verified_transition_id": verified_transition_id,
    }


@dataclass(frozen=True)
class ReplacementAuthorizationDecision:
    """Result of matching an authorization to a plan binding."""

    authorized: bool
    reason: str = ""
    mismatched_fields: tuple = ()
    checked: bool = False

    def to_record(self) -> dict:
        return {
            "authorized": self.authorized,
            "checked": self.checked,
            "reason": self.reason,
            "mismatched_fields": list(self.mismatched_fields),
        }


@dataclass(frozen=True)
class ReplacementAuthorization:
    """Permission for one exact replacement plan to affect canonical state.

    Every bound field must match the plan's binding exactly; any
    difference fails closed. It cannot invent a plan, choose another
    occurrence, or weaken lifecycle checks.
    """

    plan_digest: str
    before_state_digest: str
    original_action_list_digest: str
    matched_occurrence: tuple  # (content_digest, occurrence_index, action_list_digest)
    replaced_action_digest: str
    preserved_occurrences_digest: str
    inserted_action_digests: tuple
    projected_action_list_digest: str
    decision_type: str
    verified_transition_id: str
    authorization_version: str = REPLACEMENT_AUTHORIZATION_VERSION
    single_use: bool = True
    metadata: dict = field(default_factory=dict)

    def binding(self) -> dict:
        return _binding_fields(
            plan_digest=self.plan_digest,
            before_state_digest=self.before_state_digest,
            original_action_list_digest=self.original_action_list_digest,
            matched_occurrence_triple=self.matched_occurrence,
            replaced_action_digest=self.replaced_action_digest,
            preserved_occurrences_digest=self.preserved_occurrences_digest,
            inserted_action_digests=self.inserted_action_digests,
            projected_action_list_digest=self.projected_action_list_digest,
            decision_type=self.decision_type,
            verified_transition_id=self.verified_transition_id,
            authorization_version=self.authorization_version,
        )

    def check(
        self, plan_binding: ReplacementBinding
    ) -> ReplacementAuthorizationDecision:
        """Exact-match the plan's binding. Any difference fails closed."""
        expected = _binding_fields(
            plan_digest=plan_binding.plan_digest,
            before_state_digest=plan_binding.before_state_digest,
            original_action_list_digest=plan_binding.original_action_list_digest,
            matched_occurrence_triple=_occurrence_triple(
                plan_binding.matched_occurrence
            ),
            replaced_action_digest=plan_binding.replaced_action_digest,
            preserved_occurrences_digest=plan_binding.preserved_occurrences_digest,
            inserted_action_digests=plan_binding.inserted_action_digests,
            projected_action_list_digest=plan_binding.projected_action_list_digest,
            decision_type=plan_binding.decision_type,
            verified_transition_id=plan_binding.verified_transition_id,
            authorization_version=self.authorization_version,
        )
        mine = self.binding()
        mismatched = tuple(
            sorted(key for key in expected if mine.get(key) != expected[key])
        )
        if mismatched:
            return ReplacementAuthorizationDecision(
                authorized=False,
                reason="authorization_mismatch",
                mismatched_fields=mismatched,
                checked=True,
            )
        return ReplacementAuthorizationDecision(
            authorized=True, reason="authorization_accepted", checked=True
        )


def authorization_from_binding(
    binding: ReplacementBinding,
) -> ReplacementAuthorization:
    """Build the exact authorization that permits a specific plan binding."""
    return ReplacementAuthorization(
        plan_digest=binding.plan_digest,
        before_state_digest=binding.before_state_digest,
        original_action_list_digest=binding.original_action_list_digest,
        matched_occurrence=tuple(_occurrence_triple(binding.matched_occurrence)),
        replaced_action_digest=binding.replaced_action_digest,
        preserved_occurrences_digest=binding.preserved_occurrences_digest,
        inserted_action_digests=tuple(binding.inserted_action_digests),
        projected_action_list_digest=binding.projected_action_list_digest,
        decision_type=binding.decision_type,
        verified_transition_id=binding.verified_transition_id,
    )


def authorization_from_plan(
    plan: ActionReplacementPlan,
) -> ReplacementAuthorization | None:
    """Build an authorization for a ready plan (None otherwise)."""
    binding = plan.binding()
    if binding is None:
        return None
    return authorization_from_binding(binding)


def authorize_replacement(
    plan: ActionReplacementPlan, authorizations
) -> ReplacementAuthorizationDecision:
    """Find an authorization that exactly permits this plan.

    Fails closed: no authorizations → missing; none match → mismatch.
    """
    binding = plan.binding()
    if binding is None:
        return ReplacementAuthorizationDecision(
            False, "no_plan_binding", checked=True
        )
    candidates = tuple(authorizations or ())
    if not candidates:
        return ReplacementAuthorizationDecision(
            False, "authorization_missing", checked=True
        )
    best = None
    for authorization in candidates:
        decision = authorization.check(binding)
        if decision.authorized:
            return decision
        if best is None or len(decision.mismatched_fields) < len(
            best.mismatched_fields
        ):
            best = decision
    return best
