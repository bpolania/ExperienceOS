"""Deterministic replacement intent and conflict matching.

The :class:`ActionReplacementPlanner` answers one question and only one:

    If replacement were allowed, which planner action would be replaced?

It never answers "apply the replacement." It is a pure decision engine:
it holds no store, no engine, no manager; performs no mutation, no
authorization, and no persistence; reads only immutable inputs; and
returns one immutable :class:`ReplacementDecision` with complete
diagnostics. Expected matching failures are decisions, never exceptions.

The rules are the contract's, not invented here: `docs/action_replacement_contract.md`
§9 (conflict), §10 (rejection), §11 (preservation), and the seam audit's
matching checklist (`docs/action_replacement_seam_audit.md` §16.14).
Matching finds a candidate by **semantic identity** and binds the exact
action by **occurrence identity**; the two are never conflated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experienceos.memory.identity import (
    IdentityProjector,
    IdentityRelation,
    compare_memory_identity,
)
from experienceos.memory.planner import CREATE, MemoryAction
from experienceos.memory.action_replacement.identity import (
    CANDIDATE_EXTRACTION,
    CANDIDATE_PLANNER,
    OccurrenceIdentity,
    PlannerActionIdentity,
    action_content_digest,
    action_list_digest,
    planner_action_identity,
)

# --- Decisions ---------------------------------------------------------------

NO_REPLACEMENT_NEEDED = "no_replacement_needed"
REPLACEMENT_READY = "replacement_ready"
REJECTED_NO_MATCH = "replacement_rejected_no_match"
REJECTED_MULTIPLE_MATCHES = "replacement_rejected_multiple_matches"
REJECTED_SCOPE_CONFLICT = "replacement_rejected_scope_conflict"
REJECTED_UNRELATED_ACTION = "replacement_rejected_unrelated_action"
REJECTED_BEFORE_STATE = "replacement_rejected_before_state"
REJECTED_VERIFICATION = "replacement_rejected_verification"
REJECTED_UNSUPPORTED = "replacement_rejected_unsupported"
REJECTED_INTERNAL = "replacement_rejected_internal"

REPLACEMENT_DECISIONS = frozenset(
    {
        NO_REPLACEMENT_NEEDED,
        REPLACEMENT_READY,
        REJECTED_NO_MATCH,
        REJECTED_MULTIPLE_MATCHES,
        REJECTED_SCOPE_CONFLICT,
        REJECTED_UNRELATED_ACTION,
        REJECTED_BEFORE_STATE,
        REJECTED_VERIFICATION,
        REJECTED_UNSUPPORTED,
        REJECTED_INTERNAL,
    }
)

#: Relations that mean "same intended memory effect".
_DUPLICATE_RELATIONS = frozenset(
    {IdentityRelation.EXACT_DUPLICATE, IdentityRelation.SEMANTIC_DUPLICATE}
)


# --- Immutable inputs and outputs --------------------------------------------


@dataclass(frozen=True)
class VerifiedTransition:
    """Immutable transition evidence the planner may consult.

    The caller builds this from the verified proposal; the planner never
    reaches into runtime state to get it. ``requests_replacement`` is
    true only for a supersession that emits a paired supersede + create.
    ``source_digest`` is the grounded-source identity; an empty value
    means the evidence is not grounded and no replacement may proceed.
    """

    accepted: bool
    transition_type: str
    supersede_action: MemoryAction | None
    replacement_create: MemoryAction | None
    target_memory_ids: tuple[str, ...] = ()
    source_digest: str = ""
    before_state_digest: str = ""

    @property
    def requests_replacement(self) -> bool:
        return (
            self.supersede_action is not None
            and self.replacement_create is not None
        )


@dataclass(frozen=True)
class ReplacementDiagnostic:
    """Deterministic per-action (or per-decision) diagnostic."""

    candidate_type: str
    occurrence_identity: OccurrenceIdentity | None = None
    semantic_key: str | None = None
    content_digest: str | None = None
    semantic_relation: str | None = None
    scope: str | None = None
    grounded: bool = False
    eligible: bool = False
    rejection_reason: str | None = None
    detail: str = ""

    def to_record(self) -> dict:
        return {
            "candidate_type": self.candidate_type,
            "occurrence_identity": (
                self.occurrence_identity.to_record()
                if self.occurrence_identity is not None
                else None
            ),
            "semantic_key": self.semantic_key,
            "content_digest": self.content_digest,
            "semantic_relation": self.semantic_relation,
            "scope": self.scope,
            "grounded": self.grounded,
            "eligible": self.eligible,
            "rejection_reason": self.rejection_reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReplacementMatch:
    """One planner action bound as the replacement target."""

    identity: PlannerActionIdentity
    action: MemoryAction

    def to_record(self) -> dict:
        return {
            "identity": self.identity.to_record(),
            "action": {
                "action": self.action.action,
                "kind": self.action.kind,
                "text": self.action.text,
                "replaces": self.action.replaces,
            },
        }


@dataclass(frozen=True)
class ReplacementCandidate:
    """A fully-described, deterministic replacement candidate.

    Carries no runtime objects, no store, and no callback — only immutable
    values a later step can bind to an authorization.
    """

    planner_occurrence: OccurrenceIdentity
    planner_digest: str
    semantic_key: str | None
    replacement_create: MemoryAction
    supersede_action: MemoryAction | None
    before_state_digest: str
    target_memory_ids: tuple[str, ...]
    source_digest: str
    scope: str | None
    decision: str

    def to_record(self) -> dict:
        return {
            "planner_occurrence": self.planner_occurrence.to_record(),
            "planner_digest": self.planner_digest,
            "semantic_key": self.semantic_key,
            "replacement_create_digest": action_content_digest(
                self.replacement_create
            ),
            "supersede_target": (
                self.supersede_action.memory_id
                if self.supersede_action is not None
                else None
            ),
            "before_state_digest": self.before_state_digest,
            "target_memory_ids": list(self.target_memory_ids),
            "source_digest": self.source_digest,
            "scope": self.scope,
            "decision": self.decision,
        }


@dataclass(frozen=True)
class ReplacementDecision:
    """Exactly one deterministic outcome. No partial success, no score."""

    decision: str
    candidate: ReplacementCandidate | None = None
    match: ReplacementMatch | None = None
    rejection_reason: str | None = None
    diagnostics: tuple[ReplacementDiagnostic, ...] = ()

    @property
    def ready(self) -> bool:
        return self.decision == REPLACEMENT_READY

    def to_record(self) -> dict:
        return {
            "decision": self.decision,
            "candidate": (
                self.candidate.to_record() if self.candidate is not None else None
            ),
            "match": self.match.to_record() if self.match is not None else None,
            "rejection_reason": self.rejection_reason,
            "diagnostics": [d.to_record() for d in self.diagnostics],
        }


# --- The planner -------------------------------------------------------------


class ActionReplacementPlanner:
    """Pure, deterministic replacement-intent and conflict matcher.

    Has no store, engine, or manager reference and no mutation method.
    Its only collaborator is the read-only identity projector.
    """

    version = "1"

    def __init__(self, projector: IdentityProjector | None = None):
        self._projector = projector or IdentityProjector()

    # -- public API --

    def plan(
        self,
        planner_actions,
        transition: VerifiedTransition,
        before_state_digest: str,
        *,
        extraction_actions=(),
    ) -> ReplacementDecision:
        """Decide which planner action, if any, a verified replacement
        would replace. Never mutates, never applies, never raises for an
        expected matching failure."""
        try:
            return self._plan(
                tuple(planner_actions),
                transition,
                before_state_digest,
                tuple(extraction_actions),
            )
        except Exception as exc:  # noqa: BLE001 — decisions, never exceptions
            return ReplacementDecision(
                decision=REJECTED_INTERNAL,
                rejection_reason="internal_error",
                diagnostics=(
                    ReplacementDiagnostic(
                        candidate_type=CANDIDATE_PLANNER,
                        rejection_reason="internal_error",
                        detail=type(exc).__name__,
                    ),
                ),
            )

    # -- internals --

    def _plan(
        self,
        planner_actions: tuple,
        transition: VerifiedTransition,
        before_state_digest: str,
        extraction_actions: tuple,
    ) -> ReplacementDecision:
        # 1. Verification must have accepted, on grounded evidence.
        if not transition.accepted:
            return self._reject(
                REJECTED_VERIFICATION, "transition_not_accepted"
            )
        if not transition.source_digest:
            return self._reject(
                REJECTED_VERIFICATION, "source_not_grounded"
            )

        # 2. Replacement-requiring type: a supersede paired with a create.
        supersede = transition.supersede_action
        create = transition.replacement_create
        if supersede is None and create is None:
            return self._none("transition_generated_no_actions")
        if supersede is None:
            # A pure create (create-new class) is not a replacement.
            return self._none("transition_not_replacement_type")
        if create is None:
            return self._reject(
                REJECTED_UNSUPPORTED, "replacement_missing_create"
            )
        if create.action != CREATE:
            return self._reject(
                REJECTED_INTERNAL, "replacement_create_not_create_like"
            )

        # 3. Before-state binding: the plan must evaluate against the very
        # state the transition was verified against.
        if transition.before_state_digest != before_state_digest:
            return self._reject(
                REJECTED_BEFORE_STATE, "before_state_digest_mismatch"
            )

        list_digest = action_list_digest(planner_actions)
        target_identity = self._projector.project_text(
            create.text, kind=create.kind
        )
        target_scope = _scope_of(target_identity)

        diagnostics: list[ReplacementDiagnostic] = []

        # Extraction actions are explicitly not replacement candidates.
        for index, action in enumerate(extraction_actions):
            if action.action != CREATE:
                continue
            relation = self._relation(action, target_identity)
            if relation in _DUPLICATE_RELATIONS:
                diagnostics.append(
                    ReplacementDiagnostic(
                        candidate_type=CANDIDATE_EXTRACTION,
                        content_digest=action_content_digest(action),
                        semantic_relation=relation,
                        grounded=True,
                        eligible=False,
                        rejection_reason="extraction_not_supported",
                    )
                )

        # Planner scan: classify every action by its relation to the
        # replacement create.
        matches: list[tuple[int, MemoryAction, PlannerActionIdentity]] = []
        scope_conflicts = 0
        unsupported = 0
        for index, action in enumerate(planner_actions):
            identity = self._identity(action, index, list_digest)
            relation = self._relation(action, target_identity)
            reason = None
            eligible = False
            if relation in _DUPLICATE_RELATIONS:
                if action.action == CREATE:
                    matches.append((index, action, identity))
                    eligible = True
                else:
                    unsupported += 1
                    reason = "unsupported_planner_type"
            elif relation == IdentityRelation.SCOPED_COEXISTENCE:
                scope_conflicts += 1
                reason = "scope_coexistence"
            else:
                reason = "unrelated_action"
            diagnostics.append(
                ReplacementDiagnostic(
                    candidate_type=CANDIDATE_PLANNER,
                    occurrence_identity=identity.occurrence,
                    semantic_key=identity.semantic_key,
                    content_digest=identity.content_digest,
                    semantic_relation=relation,
                    scope=_scope_of(
                        self._projector.project_text(action.text, kind=action.kind)
                    ),
                    grounded=True,
                    eligible=eligible,
                    rejection_reason=reason,
                )
            )

        # Decide -- exactly one outcome, fail closed on any ambiguity.
        if len(matches) > 1:
            return self._reject(
                REJECTED_MULTIPLE_MATCHES,
                f"{len(matches)}_planner_creates_match",
                diagnostics,
            )
        if len(matches) == 1:
            index, action, identity = matches[0]
            # Suppression must affect only this planner create: a create
            # that itself replaces a *different* target is not ours.
            if (
                action.replaces
                and supersede is not None
                and action.replaces != supersede.memory_id
            ):
                return self._reject(
                    REJECTED_UNRELATED_ACTION,
                    "planner_create_replaces_other_target",
                    diagnostics,
                )
            candidate = ReplacementCandidate(
                planner_occurrence=identity.occurrence,
                planner_digest=identity.content_digest,
                semantic_key=identity.semantic_key,
                replacement_create=create,
                supersede_action=supersede,
                before_state_digest=before_state_digest,
                target_memory_ids=transition.target_memory_ids,
                source_digest=transition.source_digest,
                scope=target_scope,
                decision=REPLACEMENT_READY,
            )
            return ReplacementDecision(
                decision=REPLACEMENT_READY,
                candidate=candidate,
                match=ReplacementMatch(identity=identity, action=action),
                diagnostics=tuple(diagnostics),
            )

        # No planner create matched. Prefer the most specific reason.
        if scope_conflicts:
            return self._reject(
                REJECTED_SCOPE_CONFLICT, "scoped_coexistence_only", diagnostics
            )
        if unsupported:
            return self._reject(
                REJECTED_UNSUPPORTED, "no_create_like_match", diagnostics
            )
        return self._reject(REJECTED_NO_MATCH, "no_planner_match", diagnostics)

    def _identity(self, action, index, list_digest) -> PlannerActionIdentity:
        identity = self._projector.project_text(action.text, kind=action.kind)
        return planner_action_identity(
            action, index, list_digest, semantic_key=identity.semantic_key()
        )

    def _relation(self, action, target_identity) -> str:
        action_identity = self._projector.project_text(
            action.text, kind=action.kind
        )
        return compare_memory_identity(action_identity, target_identity).relation

    @staticmethod
    def _reject(decision, reason, diagnostics=None) -> ReplacementDecision:
        return ReplacementDecision(
            decision=decision,
            rejection_reason=reason,
            diagnostics=tuple(diagnostics or ()),
        )

    @staticmethod
    def _none(reason) -> ReplacementDecision:
        return ReplacementDecision(
            decision=NO_REPLACEMENT_NEEDED, rejection_reason=reason
        )


def _scope_of(identity) -> str | None:
    scope = getattr(identity, "scope", None)
    if scope is not None and getattr(scope, "known", False):
        return scope.value
    return None
