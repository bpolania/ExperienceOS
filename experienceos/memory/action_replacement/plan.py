"""Immutable, deterministic action-replacement plans.

A plan is a *projection*, never an applied rewrite. Given the original
canonical planner action list and a Prompt-3 ``ReplacementDecision``,
:class:`ReplacementPlanBuilder` produces one immutable
:class:`ActionReplacementPlan` describing exactly what action-list
transformation would occur *if* canonical replacement were later
authorized — which occurrence would be suppressed, what atomic sequence
would be inserted, what would be preserved, the projected list, and the
digests binding all of it.

The builder is pure: no store, engine, manager; no persistence,
mutation, authorization, verification, matching, ranking, model, or
network. It consumes the matcher decision unchanged — it never rematches
and never chooses a different action. It only validates the decision's
internal consistency against the supplied immutable inputs and projects
the rewrite. Expected failures are results, never exceptions.

Canonical-effect note: this module does not emit runtime
``ACTION_REPLACED``. A ready plan's effect is
``action_replacement_candidate`` (computed, not applied), matching the
contract's non-canonical vocabulary. These plan-effect constants are
defined here, in the replacement package, deliberately not by editing
the transition-integration enum.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from experienceos.memory.planner import CREATE, FORGET, SUPERSEDE, MemoryAction
from experienceos.memory.action_replacement.identity import (
    OccurrenceIdentity,
    action_content_digest,
    action_list_digest,
)
from experienceos.memory.action_replacement.planner import (
    NO_REPLACEMENT_NEEDED,
    REPLACEMENT_READY,
    ReplacementDecision,
)
from experienceos.memory.action_replacement.projection import (
    ActionListRewriteResult,
    project_rewrite,
)

PLAN_SCHEMA_VERSION = "1"

# --- Plan statuses -----------------------------------------------------------

PLAN_NO_REPLACEMENT_NEEDED = "no_replacement_needed"
PLAN_READY = "replacement_plan_ready"
PLAN_REJECTED_MATCHER = "replacement_plan_rejected_matcher"
PLAN_REJECTED_MISSING_CANDIDATE = "replacement_plan_rejected_missing_candidate"
PLAN_REJECTED_OCCURRENCE_NOT_FOUND = "replacement_plan_rejected_occurrence_not_found"
PLAN_REJECTED_OCCURRENCE_AMBIGUOUS = "replacement_plan_rejected_occurrence_ambiguous"
PLAN_REJECTED_ACTION_CHANGED = "replacement_plan_rejected_action_changed"
PLAN_REJECTED_BEFORE_STATE = "replacement_plan_rejected_before_state"
PLAN_REJECTED_INVALID_SEQUENCE = "replacement_plan_rejected_invalid_sequence"
PLAN_REJECTED_SCOPE_PRESERVATION = "replacement_plan_rejected_scope_preservation"
PLAN_REJECTED_UNRELATED_SUPPRESSION = "replacement_plan_rejected_unrelated_suppression"
PLAN_REJECTED_DUPLICATE_INSERTION = "replacement_plan_rejected_duplicate_insertion"
PLAN_REJECTED_INTERNAL = "replacement_plan_rejected_internal"

PLAN_STATUSES = frozenset(
    {
        PLAN_NO_REPLACEMENT_NEEDED,
        PLAN_READY,
        PLAN_REJECTED_MATCHER,
        PLAN_REJECTED_MISSING_CANDIDATE,
        PLAN_REJECTED_OCCURRENCE_NOT_FOUND,
        PLAN_REJECTED_OCCURRENCE_AMBIGUOUS,
        PLAN_REJECTED_ACTION_CHANGED,
        PLAN_REJECTED_BEFORE_STATE,
        PLAN_REJECTED_INVALID_SEQUENCE,
        PLAN_REJECTED_SCOPE_PRESERVATION,
        PLAN_REJECTED_UNRELATED_SUPPRESSION,
        PLAN_REJECTED_DUPLICATE_INSERTION,
        PLAN_REJECTED_INTERNAL,
    }
)

# --- Non-canonical plan effects (see module docstring) -----------------------

EFFECT_NONE = "action_none"
EFFECT_CANDIDATE = "action_replacement_candidate"
EFFECT_SHADOW = "action_replacement_shadow"
EFFECT_REJECTED = "action_replacement_rejected"

PLAN_EFFECTS = frozenset(
    {EFFECT_NONE, EFFECT_CANDIDATE, EFFECT_SHADOW, EFFECT_REJECTED}
)

# Projection contexts a caller may request. Adopted integration is NOT
# offered here: this prompt produces projections only.
CONTEXT_CANDIDATE = "candidate"
CONTEXT_SHADOW = "shadow"
_CONTEXT_EFFECT = {CONTEXT_CANDIDATE: EFFECT_CANDIDATE, CONTEXT_SHADOW: EFFECT_SHADOW}


# --- Diagnostics -------------------------------------------------------------


@dataclass(frozen=True)
class ReplacementPlanDiagnostic:
    """Deterministic explanation of one plan outcome."""

    matcher_decision: str
    candidate_present: bool
    occurrence_found: bool
    original_count: int
    preserved_count: int
    suppressed_count: int
    inserted_count: int
    projected_count: int | None
    original_digest: str | None
    projected_digest: str | None
    before_state_match: bool
    transition_sequence_valid: bool
    scope_preserved: bool
    unrelated_preserved: bool
    duplicate_insertion: bool
    status: str
    canonical_effect: str
    rejection_reason: str | None

    def to_record(self) -> dict:
        return {
            "matcher_decision": self.matcher_decision,
            "candidate_present": self.candidate_present,
            "occurrence_found": self.occurrence_found,
            "original_count": self.original_count,
            "preserved_count": self.preserved_count,
            "suppressed_count": self.suppressed_count,
            "inserted_count": self.inserted_count,
            "projected_count": self.projected_count,
            "original_digest": self.original_digest,
            "projected_digest": self.projected_digest,
            "before_state_match": self.before_state_match,
            "transition_sequence_valid": self.transition_sequence_valid,
            "scope_preserved": self.scope_preserved,
            "unrelated_preserved": self.unrelated_preserved,
            "duplicate_insertion": self.duplicate_insertion,
            "status": self.status,
            "canonical_effect": self.canonical_effect,
            "rejection_reason": self.rejection_reason,
        }


# --- Authorization binding (immutable input for later integration) -----------


@dataclass(frozen=True)
class ReplacementBinding:
    """The minimum exact material a later authorization may bind.

    This prompt issues and validates no authorization; the binding is
    only immutable data for later integration.
    """

    plan_digest: str
    before_state_digest: str
    original_action_list_digest: str
    matched_occurrence: OccurrenceIdentity
    replaced_action_digest: str
    preserved_occurrences_digest: str
    inserted_action_digests: tuple
    projected_action_list_digest: str
    decision_type: str
    verified_transition_id: str

    def to_record(self) -> dict:
        return {
            "plan_digest": self.plan_digest,
            "before_state_digest": self.before_state_digest,
            "original_action_list_digest": self.original_action_list_digest,
            "matched_occurrence": self.matched_occurrence.to_record(),
            "replaced_action_digest": self.replaced_action_digest,
            "preserved_occurrences_digest": self.preserved_occurrences_digest,
            "inserted_action_digests": list(self.inserted_action_digests),
            "projected_action_list_digest": self.projected_action_list_digest,
            "decision_type": self.decision_type,
            "verified_transition_id": self.verified_transition_id,
        }


# --- The plan ----------------------------------------------------------------


@dataclass(frozen=True)
class ActionReplacementPlan:
    """One immutable projected replacement plan. Never applied here."""

    plan_version: str
    status: str
    matcher_decision: str
    canonical_effect: str
    before_state_digest: str
    verified_transition_id: str
    original_action_list_digest: str | None = None
    matched_occurrence: OccurrenceIdentity | None = None
    matched_action_digest: str | None = None
    suppressed_occurrences: tuple = ()
    preserved_occurrences: tuple = ()
    inserted_action_digests: tuple = ()
    transition_sequence: tuple = ()
    projected_actions: tuple = ()
    projected_action_list_digest: str | None = None
    original_count: int = 0
    suppressed_count: int = 0
    inserted_count: int = 0
    projected_count: int = 0
    rewrite: ActionListRewriteResult | None = None
    diagnostic: ReplacementPlanDiagnostic | None = None
    rejection_reason: str | None = None
    plan_digest: str = ""

    @property
    def ready(self) -> bool:
        return self.status == PLAN_READY

    def binding(self) -> ReplacementBinding | None:
        """Immutable authorization-binding material, when ready."""
        if not self.ready or self.matched_occurrence is None:
            return None
        return ReplacementBinding(
            plan_digest=self.plan_digest,
            before_state_digest=self.before_state_digest,
            original_action_list_digest=self.original_action_list_digest,
            matched_occurrence=self.matched_occurrence,
            replaced_action_digest=self.matched_action_digest,
            preserved_occurrences_digest=_preserved_digest(self.preserved_occurrences),
            inserted_action_digests=self.inserted_action_digests,
            projected_action_list_digest=self.projected_action_list_digest,
            decision_type=self.matcher_decision,
            verified_transition_id=self.verified_transition_id,
        )

    def digest_payload(self) -> dict:
        """The exact, sorted, mutable-free material the plan digest binds."""
        return {
            "schema_version": self.plan_version,
            "matcher_decision": self.matcher_decision,
            "verified_transition_id": self.verified_transition_id,
            "before_state_digest": self.before_state_digest,
            "original_action_list_digest": self.original_action_list_digest,
            "matched_occurrence": (
                self.matched_occurrence.to_record()
                if self.matched_occurrence is not None
                else None
            ),
            "suppressed_occurrences": [
                o.to_record() for o in self.suppressed_occurrences
            ],
            "preserved_occurrences": [
                o.to_record() for o in self.preserved_occurrences
            ],
            "inserted_action_digests": list(self.inserted_action_digests),
            "projected_action_list_digest": self.projected_action_list_digest,
            "canonical_effect": self.canonical_effect,
            "status": self.status,
        }

    def to_record(self) -> dict:
        return {
            "plan_version": self.plan_version,
            "status": self.status,
            "matcher_decision": self.matcher_decision,
            "canonical_effect": self.canonical_effect,
            "before_state_digest": self.before_state_digest,
            "verified_transition_id": self.verified_transition_id,
            "original_action_list_digest": self.original_action_list_digest,
            "matched_occurrence": (
                self.matched_occurrence.to_record()
                if self.matched_occurrence is not None
                else None
            ),
            "matched_action_digest": self.matched_action_digest,
            "suppressed_occurrences": [
                o.to_record() for o in self.suppressed_occurrences
            ],
            "preserved_occurrences": [
                o.to_record() for o in self.preserved_occurrences
            ],
            "inserted_action_digests": list(self.inserted_action_digests),
            "projected_action_list_digest": self.projected_action_list_digest,
            "original_count": self.original_count,
            "suppressed_count": self.suppressed_count,
            "inserted_count": self.inserted_count,
            "projected_count": self.projected_count,
            "rejection_reason": self.rejection_reason,
            "diagnostic": (
                self.diagnostic.to_record() if self.diagnostic is not None else None
            ),
            "plan_digest": self.plan_digest,
        }


def _canonical_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _preserved_digest(occurrences) -> str:
    joined = "|".join(o.content_digest for o in occurrences)
    return hashlib.sha256(joined.encode()).hexdigest()


# --- The builder -------------------------------------------------------------


class ReplacementPlanBuilder:
    """Pure builder: projects a Prompt-3 decision into an immutable plan.

    Holds no store, engine, or manager; performs no matching, mutation,
    authorization, or persistence. Validates the decision's consistency
    with the supplied immutable inputs; never chooses a different action.
    """

    version = "1"

    def build(
        self,
        original_actions,
        decision: ReplacementDecision,
        *,
        before_state_digest: str,
        verified_transition_id: str,
        transition_sequence=None,
        context: str = CONTEXT_CANDIDATE,
    ) -> ActionReplacementPlan:
        try:
            return self._build(
                tuple(original_actions),
                decision,
                before_state_digest,
                verified_transition_id,
                transition_sequence,
                context,
            )
        except Exception as exc:  # noqa: BLE001 — results, never exceptions
            return self._finalize(
                _plan(
                    status=PLAN_REJECTED_INTERNAL,
                    matcher_decision=getattr(decision, "decision", "unknown"),
                    canonical_effect=EFFECT_REJECTED,
                    before_state_digest=before_state_digest,
                    verified_transition_id=verified_transition_id,
                    rejection_reason="internal_error",
                    diagnostic=_diag(
                        matcher_decision=getattr(decision, "decision", "unknown"),
                        status=PLAN_REJECTED_INTERNAL,
                        canonical_effect=EFFECT_REJECTED,
                        rejection_reason=type(exc).__name__,
                    ),
                )
            )

    # -- internals --

    def _build(
        self,
        original_actions,
        decision,
        before_state_digest,
        verified_transition_id,
        transition_sequence,
        context,
    ) -> ActionReplacementPlan:
        effect = _CONTEXT_EFFECT.get(context, EFFECT_CANDIDATE)
        matcher = decision.decision

        # No-op: the matcher decided nothing is to be replaced.
        if matcher == NO_REPLACEMENT_NEEDED:
            return self._finalize(
                _noop(matcher, before_state_digest, verified_transition_id)
            )

        # Any non-ready matcher decision projects to a rejected plan that
        # faithfully carries the matcher's reason. No suppression.
        if matcher != REPLACEMENT_READY:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_MATCHER,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    decision.rejection_reason or matcher,
                )
            )

        candidate = decision.candidate
        match = decision.match
        if candidate is None or match is None:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_MISSING_CANDIDATE,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "candidate_or_match_absent",
                )
            )

        # The candidate must belong to this decision (occurrence agrees).
        if match.identity.occurrence != candidate.planner_occurrence:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_OCCURRENCE_AMBIGUOUS,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "match_and_candidate_occurrence_disagree",
                )
            )

        occ = candidate.planner_occurrence
        original = tuple(original_actions)
        original_digest = action_list_digest(original)

        # Before-state binding: evaluate against the exact verified state.
        before_ok = (
            candidate.before_state_digest == before_state_digest
            and before_state_digest != ""
        )
        if not before_ok:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_BEFORE_STATE,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "before_state_digest_mismatch",
                    original_digest=original_digest,
                )
            )

        # The action list must not have changed since matching.
        if occ.action_list_digest != original_digest:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_ACTION_CHANGED,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "action_list_digest_changed",
                    original_digest=original_digest,
                )
            )

        # Locate the exact occurrence by index; never rematch semantically.
        index = occ.occurrence_index
        if not (0 <= index < len(original)):
            return self._finalize(
                _reject(
                    PLAN_REJECTED_OCCURRENCE_NOT_FOUND,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "occurrence_index_out_of_range",
                    original_digest=original_digest,
                )
            )
        matched = original[index]
        matched_digest = action_content_digest(matched)
        if matched_digest != occ.content_digest or matched_digest != candidate.planner_digest:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_ACTION_CHANGED,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "matched_action_content_changed",
                    original_digest=original_digest,
                )
            )
        if matched.action != CREATE:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_ACTION_CHANGED,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "matched_action_not_create_like",
                    original_digest=original_digest,
                )
            )

        # Resolve and validate the transition replacement sequence.
        sequence = (
            tuple(transition_sequence)
            if transition_sequence is not None
            else _default_sequence(candidate)
        )
        seq_reason = _validate_sequence(sequence, candidate)
        if seq_reason is not None:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_INVALID_SEQUENCE,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    seq_reason,
                    original_digest=original_digest,
                )
            )

        # Duplicate-insertion protection: the inserted create must not
        # already exist in the original list, and the sequence must not
        # repeat a create.
        inserted_create = next(a for a in sequence if a.action == CREATE)
        inserted_create_digest = action_content_digest(inserted_create)
        if any(
            action_content_digest(a) == inserted_create_digest for a in original
        ):
            return self._finalize(
                _reject(
                    PLAN_REJECTED_DUPLICATE_INSERTION,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "inserted_create_already_present",
                    original_digest=original_digest,
                )
            )

        # Project the rewrite (pure).
        rewrite = project_rewrite(original, index, sequence)

        # Count invariant: preserved + suppressed == original, exactly one
        # suppressed, projected == original - 1 + len(sequence).
        preserved_count = len(rewrite.preserved_occurrences)
        if (
            rewrite.suppressed_count != 1
            or preserved_count + rewrite.suppressed_count != rewrite.original_count
        ):
            return self._finalize(
                _reject(
                    PLAN_REJECTED_UNRELATED_SUPPRESSION,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "suppression_count_invariant_violated",
                    original_digest=original_digest,
                )
            )
        expected_projected = rewrite.original_count - 1 + rewrite.inserted_count
        if rewrite.projected_count != expected_projected:
            return self._finalize(
                _reject(
                    PLAN_REJECTED_INVALID_SEQUENCE,
                    matcher,
                    before_state_digest,
                    verified_transition_id,
                    "projected_count_mismatch",
                    original_digest=original_digest,
                )
            )

        diagnostic = _diag(
            matcher_decision=matcher,
            status=PLAN_READY,
            canonical_effect=effect,
            candidate_present=True,
            occurrence_found=True,
            original_count=rewrite.original_count,
            preserved_count=preserved_count,
            suppressed_count=rewrite.suppressed_count,
            inserted_count=rewrite.inserted_count,
            projected_count=rewrite.projected_count,
            original_digest=original_digest,
            projected_digest=rewrite.projection.projected_digest,
            before_state_match=True,
            transition_sequence_valid=True,
            scope_preserved=True,
            unrelated_preserved=True,
            duplicate_insertion=False,
            rejection_reason=None,
        )
        plan = _plan(
            status=PLAN_READY,
            matcher_decision=matcher,
            canonical_effect=effect,
            before_state_digest=before_state_digest,
            verified_transition_id=verified_transition_id,
            original_action_list_digest=original_digest,
            matched_occurrence=occ,
            matched_action_digest=matched_digest,
            suppressed_occurrences=(rewrite.suppressed_occurrence,),
            preserved_occurrences=rewrite.preserved_occurrences,
            inserted_action_digests=rewrite.projection.inserted_digests,
            transition_sequence=sequence,
            projected_actions=rewrite.projection.projected_actions,
            projected_action_list_digest=rewrite.projection.projected_digest,
            original_count=rewrite.original_count,
            suppressed_count=rewrite.suppressed_count,
            inserted_count=rewrite.inserted_count,
            projected_count=rewrite.projected_count,
            rewrite=rewrite,
            diagnostic=diagnostic,
        )
        return self._finalize(plan)

    @staticmethod
    def _finalize(plan: ActionReplacementPlan) -> ActionReplacementPlan:
        """Stamp the deterministic plan digest onto an otherwise-complete plan."""
        from dataclasses import replace

        digest = _canonical_digest(plan.digest_payload())
        return replace(plan, plan_digest=digest)


# --- helpers -----------------------------------------------------------------


def _default_sequence(candidate) -> tuple:
    parts = []
    if candidate.supersede_action is not None:
        parts.append(candidate.supersede_action)
    if candidate.replacement_create is not None:
        parts.append(candidate.replacement_create)
    return tuple(parts)


def _validate_sequence(sequence, candidate) -> str | None:
    """Structural validation of the transition replacement sequence.

    Returns a bounded reason string on rejection, or None when valid.
    """
    supersedes = [a for a in sequence if a.action == SUPERSEDE]
    creates = [a for a in sequence if a.action == CREATE]
    forgets = [a for a in sequence if a.action == FORGET]
    others = [
        a for a in sequence if a.action not in (SUPERSEDE, CREATE, FORGET)
    ]
    if forgets:
        return "sequence_contains_forget"
    if others:
        return "sequence_contains_unrelated_action"
    if len(supersedes) != 1:
        return "sequence_supersede_count"
    if len(creates) != 1:
        return "sequence_create_count"
    supersede = supersedes[0]
    create = creates[0]
    if create.replaces != supersede.memory_id:
        return "create_replaces_target_mismatch"
    if candidate.target_memory_ids and supersede.memory_id not in candidate.target_memory_ids:
        return "supersede_target_not_in_candidate"
    if candidate.supersede_action is not None and (
        supersede.memory_id != candidate.supersede_action.memory_id
    ):
        return "supersede_disagrees_with_candidate"
    if candidate.replacement_create is not None and (
        action_content_digest(create)
        != action_content_digest(candidate.replacement_create)
    ):
        return "create_disagrees_with_candidate"
    return None


def _plan(**kwargs) -> ActionReplacementPlan:
    kwargs.setdefault("plan_version", PLAN_SCHEMA_VERSION)
    return ActionReplacementPlan(**kwargs)


def _noop(matcher, before_state_digest, verified_transition_id) -> ActionReplacementPlan:
    diagnostic = _diag(
        matcher_decision=matcher,
        status=PLAN_NO_REPLACEMENT_NEEDED,
        canonical_effect=EFFECT_NONE,
        rejection_reason=None,
    )
    return _plan(
        status=PLAN_NO_REPLACEMENT_NEEDED,
        matcher_decision=matcher,
        canonical_effect=EFFECT_NONE,
        before_state_digest=before_state_digest,
        verified_transition_id=verified_transition_id,
        diagnostic=diagnostic,
    )


def _reject(
    status,
    matcher,
    before_state_digest,
    verified_transition_id,
    reason,
    *,
    original_digest=None,
) -> ActionReplacementPlan:
    diagnostic = _diag(
        matcher_decision=matcher,
        status=status,
        canonical_effect=EFFECT_REJECTED,
        original_digest=original_digest,
        rejection_reason=reason,
    )
    return _plan(
        status=status,
        matcher_decision=matcher,
        canonical_effect=EFFECT_REJECTED,
        before_state_digest=before_state_digest,
        verified_transition_id=verified_transition_id,
        original_action_list_digest=original_digest,
        rejection_reason=reason,
        diagnostic=diagnostic,
    )


def _diag(
    *,
    matcher_decision,
    status,
    canonical_effect,
    candidate_present=False,
    occurrence_found=False,
    original_count=0,
    preserved_count=0,
    suppressed_count=0,
    inserted_count=0,
    projected_count=None,
    original_digest=None,
    projected_digest=None,
    before_state_match=False,
    transition_sequence_valid=False,
    scope_preserved=False,
    unrelated_preserved=False,
    duplicate_insertion=False,
    rejection_reason=None,
) -> ReplacementPlanDiagnostic:
    return ReplacementPlanDiagnostic(
        matcher_decision=matcher_decision,
        candidate_present=candidate_present,
        occurrence_found=occurrence_found,
        original_count=original_count,
        preserved_count=preserved_count,
        suppressed_count=suppressed_count,
        inserted_count=inserted_count,
        projected_count=projected_count,
        original_digest=original_digest,
        projected_digest=projected_digest,
        before_state_match=before_state_match,
        transition_sequence_valid=transition_sequence_valid,
        scope_preserved=scope_preserved,
        unrelated_preserved=unrelated_preserved,
        duplicate_insertion=duplicate_insertion,
        status=status,
        canonical_effect=canonical_effect,
        rejection_reason=rejection_reason,
    )
