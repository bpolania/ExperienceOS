"""Deterministic update and supersession proposal intelligence.

This controller answers one question and applies no answer:

> Given a source statement, its evidence, and the active memory state
> before it — which lifecycle transition should ExperienceOS *propose*?

It produces `ProposedTransition` values and submits them to the
transition verifier. It never mutates state, never authorizes anything,
and never applies anything. `ExperienceManager` remains lifecycle-policy
authority and `ExperienceEngine._apply_memory_actions` remains the sole
durable mutation boundary.

Its purpose is not to maximize mutation rate. It is to propose a safe,
explainable transition when the evidence supports one and to abstain or
reject when it does not.

Architecture (Option C — shared identity foundation, proposal-only):

- the canonical `SemanticMemoryPlanner` is **unchanged** and remains the
  only deterministic path with real lifecycle effect;
- this controller is proposal-only and is not wired into any runtime
  path, so two deterministic components can never issue contradictory
  lifecycle decisions — only one of them has authority, and it is not
  this one;
- both consume the same semantic identity layer, so identity semantics
  are shared rather than forked.

Identity projection, comparison, and resolution come from
`experienceos/memory/identity.py` and are consumed, never reimplemented.
Transition models and verification come from
`experienceos/memory/transition_verification.py`.

Forget boundary: this controller detects forget language only to keep it
out of update intelligence. Affirmative forget directives produce a
bounded handoff and never a positive creation. Formal forget-directive
targeting is a separate concern and is not implemented here.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from experienceos.memory.identity import (
    IdentityProjector,
    IdentityRelation,
    MemoryIdentity,
    TemporalStatus,
    canonical_value,
    normalize_text,
    resolve_identity,
)
from experienceos.memory.schema import MemoryStatus
from experienceos.memory.transition_verification import (
    AfterStateExpectation,
    CreatedMemorySpec,
    ProposedTransition,
    TransitionSourceEvidence,
    TransitionVerifier,
)
from experienceos.controllers.extraction import ProposedMemoryCandidate

#: Reserved by the transition contract for deterministic transition
#: intelligence. A reserved id implies neither adoption nor authority.
UPDATE_CONTROLLER_ID = "experienceos_transition_rules_v1"
UPDATE_CONTROLLER_VERSION = "1"


class UpdateIntentType:
    """Controller-internal source-intent classes.

    Internal on purpose: each maps onto the frozen transition taxonomy
    rather than replacing it.
    """

    DURABLE_ASSERTION = "durable_assertion"
    DIRECT_REPLACEMENT = "direct_replacement"
    INSTEAD_OF_REPLACEMENT = "instead_of_replacement"
    SWITCHED_FROM_TO = "switched_from_to"
    NO_LONGER_NOW = "no_longer_now"
    USED_TO_NOW = "used_to_now"
    CORRECTION = "correction"
    SEMANTIC_RESTATEMENT = "semantic_restatement"
    EXACT_RESTATEMENT = "exact_restatement"
    SCOPED_ADDITION = "scoped_addition"
    UNRELATED_ADDITION = "unrelated_addition"
    TEMPORARY_EXCEPTION = "temporary_exception"
    HISTORICAL_ONLY = "historical_only"
    HYPOTHETICAL = "hypothetical"
    QUESTION = "question"
    FORGET_DIRECTIVE = "forget_directive"
    NEGATIVE_FORGET = "negative_forget"
    VALUELESS_UPDATE_REQUEST = "valueless_update_request"
    TASK_REQUEST = "task_request"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class TargetResolutionStatus:
    NO_TARGET_REQUIRED = "no_target_required"
    EXACT_TARGET = "exact_target"
    SEMANTIC_TARGET = "semantic_target"
    CONFLICT_TARGET = "conflict_target"
    SCOPED_COEXISTENCE = "scoped_coexistence"
    NO_MATCHING_TARGET = "no_matching_target"
    MULTIPLE_TARGETS = "multiple_targets"
    INACTIVE_ONLY_MATCH = "inactive_only_match"
    OLD_VALUE_MISMATCH = "old_value_mismatch"
    IDENTITY_AMBIGUOUS = "identity_ambiguous"
    UNRELATED_ONLY = "unrelated_only"
    UNSUPPORTED = "unsupported"


class AbstentionReason:
    NOT_APPLICABLE = "not_applicable"
    FORGET_HANDOFF = "forget_directive_detected"
    NO_DURABLE_CONTENT = "no_durable_content"
    IDENTITY_INCOMPLETE = "identity_incomplete"
    EVIDENCE_UNUSABLE = "evidence_unusable"


@dataclass(frozen=True)
class UpdateControllerDiagnostic:
    code: str
    category: str
    detail: str = ""

    def to_record(self) -> dict:
        return {"code": self.code, "category": self.category, "detail": self.detail}


@dataclass(frozen=True)
class UpdatePatternMatch:
    """The bounded pattern that matched, and what it extracted."""

    pattern_id: str = ""
    old_value: str | None = None
    new_value: str | None = None
    topic: str = ""
    surface: str = ""

    def to_record(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "topic": self.topic,
            "surface": self.surface,
        }


@dataclass(frozen=True)
class UpdateIntent:
    """Classified source intent plus the markers that justified it."""

    intent_type: str
    pattern: UpdatePatternMatch = field(default_factory=UpdatePatternMatch)
    markers: tuple = ()
    durable: bool = False
    detail: str = ""

    def to_record(self) -> dict:
        return {
            "intent_type": self.intent_type,
            "pattern": self.pattern.to_record(),
            "markers": list(self.markers),
            "durable": self.durable,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TargetResolution:
    """Which active memory (if any) the proposal may act on."""

    status: str
    target_id: str | None = None
    relation: str | None = None
    candidates: tuple = ()
    detail: str = ""

    def to_record(self) -> dict:
        return {
            "status": self.status,
            "target_id": self.target_id,
            "relation": self.relation,
            "candidates": list(self.candidates),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class UpdateProposalResult:
    """Controller output. Never an authorized or applied action."""

    statement: str
    intent: UpdateIntent
    identity: MemoryIdentity | None = None
    target: TargetResolution | None = None
    proposal: ProposedTransition | None = None
    # Annotated so it is a real dataclass field and not a class
    # attribute: the verifier result must be constructible per call.
    verification: "object | None" = None
    abstained: bool = False
    abstention_reason: str = ""
    diagnostics: tuple = ()
    latency_ms: float = 0.0
    stage_latency_ms: dict = field(default_factory=dict)
    controller_id: str = UPDATE_CONTROLLER_ID
    controller_version: str = UPDATE_CONTROLLER_VERSION
    action_applied: bool = False

    @property
    def transition_type(self) -> str | None:
        return self.proposal.transition_type if self.proposal else None

    @property
    def canonical_effect_eligible(self) -> bool:
        return bool(
            self.verification and self.verification.canonical_effect_eligible
        )

    def to_record(self) -> dict:
        return {
            "intent": self.intent.to_record(),
            "identity": self.identity.to_record() if self.identity else None,
            "target": self.target.to_record() if self.target else None,
            "proposal": self.proposal.to_record() if self.proposal else None,
            "verification": (
                self.verification.to_record() if self.verification else None
            ),
            "transition_type": self.transition_type,
            "abstained": self.abstained,
            "abstention_reason": self.abstention_reason,
            "diagnostics": [d.to_record() for d in self.diagnostics],
            "canonical_effect_eligible": self.canonical_effect_eligible,
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "action_applied": self.action_applied,
        }


@dataclass(frozen=True)
class UpdateControllerConfig:
    """Deterministic configuration. No providers, no model, no network."""

    verify: bool = True
    max_candidate_diagnostics: int = 4
    request_canonical_effect: bool = False


# --- Bounded source patterns --------------------------------------------------

# A one-off task or request: it asks for work, it does not assert
# durable experience.
_TASK_OPENER = re.compile(
    r"^(?:please\s+)?(?:let'?s\s+)?"
    r"(?:plan|book|find|search|look up|check|fetch|tidy|clean|organi[sz]e"
    r"|review|set up|setup|schedule|arrange|help|show|tell|give)\b"
)

# An update request that names a topic but asserts no new value.
_UPDATE_REQUEST = re.compile(
    r"^(?:please\s+)?(?:change|update|modify|adjust|edit|switch|set)\s+"
    r"(?:my|the)\s+(?P<topic>[a-z' -]+?)(?:\s+(?:preference|setting|thing))?\s*[.!?]?$"
)

# Forget language. The negative form is checked first: "Don't forget
# that I prefer X" asserts X, it does not remove it.
_NEGATIVE_FORGET = re.compile(
    r"\b(?:do\s+not|don'?t|never)\s+forget\b|\bkeep\s+remembering\b"
)
_AFFIRMATIVE_FORGET = re.compile(
    r"\bforget\b|\bstop\s+remembering\b|\bremove\s+my\b|\bdelete\s+my\b"
    r"|\bno\s+longer\s+(?:want|need)\s+you\s+to\s+remember\b"
    r"|\bdon'?t\s+care\s+about\s+my\b|\bdoesn'?t\s+matter\s+anymore\b"
    r"|\bdon'?t\s+care\s+about\s+.*\banymore\b"
)

# Standing-scope cue: makes an imperative durable ("Always ...").
_STANDING_SCOPE = re.compile(
    r"\b(?:from now on|going forward|always|whenever|every time|for future)\b"
)

# Explicit replacement forms. Each yields an old value, a new value, or
# both; the new value always comes from the identity projection, never
# from the replaced clause.
_INSTEAD_OF_OLD = re.compile(
    r"\binstead of\s+(?P<old>[^.;]+?)(?=\s+for\b|[.;]|$)"
)
_SWITCHED_FROM_TO = re.compile(
    r"\b(?:switched|changed|moved|migrated)\s+from\s+(?P<old>[^.;]+?)\s+to\s+"
    r"(?P<new>[^.;]+?)(?=\s+for\b|[.;]|$)"
)
_NO_LONGER = re.compile(
    r"\bno longer\s+(?:prefer|use|like|want)\s+(?P<old>[^.;,]+)"
)
_USED_TO = re.compile(r"\bused to\b")
_DIRECT_NOW = re.compile(r"\b(?:now|these days)\b")
_CORRECTION_LEAD = re.compile(
    r"^(?:actually|correction|no,|nope,|sorry,|one more change|quick note)\b"
)

_CANDIDATE_DOMAIN_HINT = re.compile(r"[a-z]+")


class DeterministicUpdateController:
    """Converts supported update language into verifiable proposals.

    Stateless: every call takes an explicit before-state snapshot, so a
    correction chain is driven by the caller's snapshots rather than by
    hidden controller memory.
    """

    controller_id = UPDATE_CONTROLLER_ID
    version = UPDATE_CONTROLLER_VERSION

    def __init__(
        self,
        config: UpdateControllerConfig | None = None,
        projector: IdentityProjector | None = None,
        verifier: TransitionVerifier | None = None,
    ):
        self.config = config or UpdateControllerConfig()
        self._projector = projector or IdentityProjector()
        self._verifier = verifier or TransitionVerifier()

    # -- public API ------------------------------------------------------

    def propose(
        self, statement: str, evidence: TransitionSourceEvidence, before_state
    ) -> UpdateProposalResult:
        """Propose a transition for one statement. Mutates nothing."""
        started = time.perf_counter()
        stages = {}
        diagnostics = []

        if not evidence.usable:
            return self._abstain(
                statement,
                UpdateIntent(UpdateIntentType.UNSUPPORTED),
                AbstentionReason.EVIDENCE_UNUSABLE,
                diagnostics
                + [
                    UpdateControllerDiagnostic(
                        "evidence_unusable", "grounding",
                        f"evidence mode {evidence.evidence_mode}",
                    )
                ],
                started,
                stages,
            )

        mark = time.perf_counter()
        identity = self._projector.project_text(
            statement, kind=evidence.source_kind or None
        )
        stages["identity_ms"] = (time.perf_counter() - mark) * 1000.0

        mark = time.perf_counter()
        intent = self._classify(statement, identity, before_state)
        stages["intent_ms"] = (time.perf_counter() - mark) * 1000.0
        diagnostics.append(
            UpdateControllerDiagnostic(
                "intent_classified", "intent",
                f"{intent.intent_type}"
                + (f" via {intent.pattern.pattern_id}" if intent.pattern.pattern_id else ""),
            )
        )

        # A forget directive leaves update intelligence entirely.
        if intent.intent_type == UpdateIntentType.FORGET_DIRECTIVE:
            diagnostics.append(
                UpdateControllerDiagnostic(
                    AbstentionReason.FORGET_HANDOFF, "forget",
                    "affirmative forget directive; no positive creation or "
                    "update proposed",
                )
            )
            return self._abstain(
                statement, intent, AbstentionReason.FORGET_HANDOFF,
                diagnostics, started, stages, identity,
            )

        # Frozen rejection transitions the source itself establishes.
        rejection = _INTENT_REJECTION.get(intent.intent_type)
        if rejection:
            proposal = self._rejection_proposal(
                rejection, statement, evidence, before_state, intent
            )
            return self._finish(
                statement, intent, identity,
                TargetResolution(TargetResolutionStatus.NO_TARGET_REQUIRED),
                proposal, before_state, diagnostics, started, stages,
            )

        mark = time.perf_counter()
        target = self._resolve_target(identity, before_state, intent)
        stages["target_ms"] = (time.perf_counter() - mark) * 1000.0
        diagnostics.append(
            UpdateControllerDiagnostic(
                "target_resolved", "target",
                f"{target.status}"
                + (f" -> {target.target_id}" if target.target_id else ""),
            )
        )

        mark = time.perf_counter()
        proposal = self._build(
            statement, evidence, before_state, identity, target, intent, diagnostics
        )
        stages["proposal_ms"] = (time.perf_counter() - mark) * 1000.0
        if proposal is None:
            return self._abstain(
                statement, intent, AbstentionReason.IDENTITY_INCOMPLETE,
                diagnostics, started, stages, identity, target,
            )
        return self._finish(
            statement, intent, identity, target, proposal, before_state,
            diagnostics, started, stages,
        )

    # -- classification --------------------------------------------------

    def _classify(self, statement, identity, before_state) -> UpdateIntent:
        lowered = normalize_text(statement)
        markers = identity.markers

        # 1. Non-durable source markers come from the identity layer.
        if identity.temporal_status == TemporalStatus.QUESTION:
            return UpdateIntent(UpdateIntentType.QUESTION, markers=markers)
        if identity.temporal_status == TemporalStatus.HYPOTHETICAL:
            return UpdateIntent(UpdateIntentType.HYPOTHETICAL, markers=markers)
        if identity.temporal_status == TemporalStatus.TEMPORARY:
            return UpdateIntent(
                UpdateIntentType.TEMPORARY_EXCEPTION, markers=markers
            )

        # 2. Forget language. Negative first: "Don't forget that I prefer
        # X" asserts X and must not read as a removal.
        if _NEGATIVE_FORGET.search(lowered):
            return UpdateIntent(
                UpdateIntentType.NEGATIVE_FORGET, markers=markers, durable=True,
                detail="negative forget asserts the memory rather than removing it",
            )
        if _AFFIRMATIVE_FORGET.search(lowered):
            return UpdateIntent(
                UpdateIntentType.FORGET_DIRECTIVE, markers=markers,
                detail="affirmative forget directive",
            )

        # 3. A purely historical statement describes a prior state.
        if identity.temporal_status == TemporalStatus.HISTORICAL:
            return UpdateIntent(
                UpdateIntentType.HISTORICAL_ONLY, markers=markers,
                detail="historical marker with no current clause",
            )

        # 4. A one-off task asks for work; it asserts nothing durable.
        if _TASK_OPENER.search(lowered) and not _STANDING_SCOPE.search(lowered):
            return UpdateIntent(
                UpdateIntentType.TASK_REQUEST, markers=markers,
                pattern=UpdatePatternMatch(pattern_id="task_opener"),
                detail="one-off request, no durable assertion",
            )

        # 5. An update request that names a topic but no new value.
        request = _UPDATE_REQUEST.match(lowered)
        if request and not identity.value.known:
            topic = request.group("topic").strip()
            return UpdateIntent(
                UpdateIntentType.VALUELESS_UPDATE_REQUEST, markers=markers,
                pattern=UpdatePatternMatch(
                    pattern_id="valueless_update_request", topic=topic,
                    surface=request.group(0),
                ),
                detail=f"names {topic!r} but asserts no new value",
            )

        # 6. Explicit replacement forms, most specific first.
        pattern = self._replacement_pattern(lowered, identity)
        if pattern is not None:
            return pattern

        # 7. A durable assertion: the identity layer projected a current
        # value, or a standing-scope cue makes an imperative durable.
        if identity.value.known and identity.temporal_status == (
            TemporalStatus.CURRENT
        ):
            return UpdateIntent(
                UpdateIntentType.DURABLE_ASSERTION, markers=markers, durable=True
            )
        if _STANDING_SCOPE.search(lowered):
            return UpdateIntent(
                UpdateIntentType.DURABLE_ASSERTION, markers=markers, durable=True,
                pattern=UpdatePatternMatch(pattern_id="standing_scope"),
                detail="standing-scope instruction",
            )

        # 8. Nothing durable was established and nothing was requested:
        # transient conversational state.
        return UpdateIntent(
            UpdateIntentType.TEMPORARY_EXCEPTION, markers=markers,
            detail="no durable assertion established from the source",
        )

    def _replacement_pattern(self, lowered, identity) -> UpdateIntent | None:
        switched = _SWITCHED_FROM_TO.search(lowered)
        if switched:
            return UpdateIntent(
                UpdateIntentType.SWITCHED_FROM_TO, markers=identity.markers,
                durable=True,
                pattern=UpdatePatternMatch(
                    pattern_id="switched_from_to",
                    old_value=switched.group("old").strip(),
                    new_value=switched.group("new").strip(),
                    surface=switched.group(0),
                ),
            )
        instead = _INSTEAD_OF_OLD.search(lowered)
        if instead:
            return UpdateIntent(
                UpdateIntentType.INSTEAD_OF_REPLACEMENT, markers=identity.markers,
                durable=True,
                pattern=UpdatePatternMatch(
                    pattern_id="instead_of",
                    old_value=instead.group("old").strip(),
                    new_value=identity.value.value if identity.value.known else None,
                    surface=instead.group(0),
                ),
            )
        no_longer = _NO_LONGER.search(lowered)
        if no_longer and identity.value.known:
            return UpdateIntent(
                UpdateIntentType.NO_LONGER_NOW, markers=identity.markers,
                durable=True,
                pattern=UpdatePatternMatch(
                    pattern_id="no_longer_now",
                    old_value=no_longer.group("old").strip(),
                    new_value=identity.value.value,
                    surface=no_longer.group(0),
                ),
            )
        if _USED_TO.search(lowered) and identity.historical_value:
            return UpdateIntent(
                UpdateIntentType.USED_TO_NOW, markers=identity.markers,
                durable=True,
                pattern=UpdatePatternMatch(
                    pattern_id="used_to_now",
                    old_value=identity.historical_value,
                    new_value=identity.value.value if identity.value.known else None,
                    surface="used to ... now",
                ),
            )
        if _CORRECTION_LEAD.search(lowered) and identity.value.known:
            return UpdateIntent(
                UpdateIntentType.CORRECTION, markers=identity.markers,
                durable=True,
                pattern=UpdatePatternMatch(
                    pattern_id="correction",
                    new_value=identity.value.value,
                    surface=lowered.split()[0],
                ),
            )
        if _DIRECT_NOW.search(lowered) and identity.value.known:
            return UpdateIntent(
                UpdateIntentType.DIRECT_REPLACEMENT, markers=identity.markers,
                durable=True,
                pattern=UpdatePatternMatch(
                    pattern_id="direct_now", new_value=identity.value.value,
                    surface="now",
                ),
            )
        return None

    # -- target resolution -----------------------------------------------

    def _resolve_target(self, identity, before_state, intent) -> TargetResolution:
        active = list(before_state.active())
        if not active:
            return TargetResolution(
                TargetResolutionStatus.NO_MATCHING_TARGET,
                detail="no active memory",
            )
        identities = [before_state.identity_of(m.memory_id) for m in active]
        pairs = [(m, i) for m, i in zip(active, identities) if i is not None]
        if not pairs:
            return TargetResolution(
                TargetResolutionStatus.UNSUPPORTED,
                detail="no active identity could be projected",
            )

        # A valueless request cannot update anything; whether it is
        # ambiguous or merely unsupported depends on how many active
        # memories its topic could name.
        if intent.intent_type == UpdateIntentType.VALUELESS_UPDATE_REQUEST:
            topic = intent.pattern.topic
            matches = [
                m.memory_id for m, i in pairs if _mentions_topic(i, m, topic)
            ]
            if len(matches) > 1:
                return TargetResolution(
                    TargetResolutionStatus.MULTIPLE_TARGETS,
                    candidates=tuple(matches[: self.config.max_candidate_diagnostics]),
                    detail=f"{len(matches)} active memories match {topic!r}",
                )
            return TargetResolution(
                TargetResolutionStatus.UNSUPPORTED,
                candidates=tuple(matches),
                detail=f"no new value asserted for {topic!r}",
            )

        resolution = resolve_identity(identity, [i for _, i in pairs])
        relation = resolution.relation
        index = resolution.target_index
        target_id = pairs[index][0].memory_id if index is not None else None

        status = {
            IdentityRelation.EXACT_DUPLICATE: TargetResolutionStatus.EXACT_TARGET,
            IdentityRelation.SEMANTIC_DUPLICATE: (
                TargetResolutionStatus.SEMANTIC_TARGET
            ),
            IdentityRelation.CURRENT_STATE_CONFLICT: (
                TargetResolutionStatus.CONFLICT_TARGET
            ),
            IdentityRelation.SCOPED_COEXISTENCE: (
                TargetResolutionStatus.SCOPED_COEXISTENCE
            ),
            IdentityRelation.UNRELATED: TargetResolutionStatus.UNRELATED_ONLY,
            IdentityRelation.AMBIGUOUS: TargetResolutionStatus.IDENTITY_AMBIGUOUS,
        }.get(relation, TargetResolutionStatus.UNSUPPORTED)

        if relation == IdentityRelation.AMBIGUOUS:
            codes = {d.code for d in resolution.rationale}
            if "multiple_conflict_targets" in codes:
                status = TargetResolutionStatus.MULTIPLE_TARGETS

        # An explicit old value must match the target it claims to
        # replace, or the proposal is naming the wrong memory.
        if status == TargetResolutionStatus.CONFLICT_TARGET and (
            intent.pattern.old_value
        ):
            existing = pairs[index][1]
            if not _old_value_matches(intent.pattern.old_value, existing):
                return TargetResolution(
                    TargetResolutionStatus.OLD_VALUE_MISMATCH,
                    target_id=target_id, relation=relation,
                    candidates=(target_id,),
                    detail=(
                        f"source replaces {intent.pattern.old_value!r} but the "
                        f"target holds {existing.value.value!r}"
                    ),
                )

        return TargetResolution(
            status=status, target_id=target_id, relation=relation,
            candidates=tuple(
                m.memory_id for m, _ in pairs[: self.config.max_candidate_diagnostics]
            ),
            detail=" ".join(d.code for d in resolution.rationale),
        )

    # -- proposal construction -------------------------------------------

    def _build(
        self, statement, evidence, before_state, identity, target, intent,
        diagnostics,
    ) -> ProposedTransition | None:
        active_ids = [m.memory_id for m in before_state.active()]
        status = target.status

        if status == TargetResolutionStatus.EXACT_TARGET:
            return self._noop("duplicate_noop", statement, evidence,
                              before_state, active_ids)
        if status == TargetResolutionStatus.SEMANTIC_TARGET:
            return self._noop("semantic_duplicate_noop", statement, evidence,
                              before_state, active_ids)
        if status == TargetResolutionStatus.MULTIPLE_TARGETS:
            return self._rejection_proposal(
                "reject_ambiguous", statement, evidence, before_state, intent
            )
        if status in (
            TargetResolutionStatus.IDENTITY_AMBIGUOUS,
            TargetResolutionStatus.OLD_VALUE_MISMATCH,
            TargetResolutionStatus.UNSUPPORTED,
        ):
            frozen = (
                "reject_ambiguous"
                if status == TargetResolutionStatus.IDENTITY_AMBIGUOUS
                else "reject_unsupported"
            )
            return self._rejection_proposal(
                frozen, statement, evidence, before_state, intent
            )
        if status == TargetResolutionStatus.CONFLICT_TARGET:
            return self._supersede(
                statement, evidence, before_state, identity, target, active_ids
            )
        if status == TargetResolutionStatus.SCOPED_COEXISTENCE:
            return self._coexist(
                statement, evidence, before_state, identity, active_ids
            )
        if status in (
            TargetResolutionStatus.UNRELATED_ONLY,
            TargetResolutionStatus.NO_MATCHING_TARGET,
        ):
            if not identity.value.known and not intent.durable:
                return None
            return self._create(
                statement, evidence, before_state, identity, active_ids
            )
        return None

    def _created_spec(self, statement, identity, replaces=None):
        must_include = (
            (identity.value.evidence or identity.value.value,)
            if identity.value.known
            else ()
        )
        return CreatedMemorySpec(
            candidate=ProposedMemoryCandidate(kind=identity.kind, text=statement),
            local_ref="created:0",
            must_include=must_include,
            replaces=replaces,
        )

    def _base(self, transition_type, statement, evidence, before_state):
        return dict(
            proposal_id=f"{UPDATE_CONTROLLER_ID}:{before_state.digest()}:"
                        f"{_digest(statement)}",
            transition_type=transition_type,
            evidence=evidence,
            before_state_digest=before_state.digest(),
            proposer_id=UPDATE_CONTROLLER_ID,
            proposal_source="deterministic_update_controller",
        )

    def _noop(self, transition_type, statement, evidence, before_state, active_ids):
        return ProposedTransition(
            preserved_ids=tuple(active_ids),
            unchanged_ids=tuple(active_ids),
            expected_after_state=AfterStateExpectation(
                active_ids=tuple(active_ids),
                preserved_ids=tuple(active_ids),
                unchanged_ids=tuple(active_ids),
                no_mutation=True,
            ),
            rationale="an equivalent memory is already active",
            **self._base(transition_type, statement, evidence, before_state),
        )

    def _rejection_proposal(
        self, transition_type, statement, evidence, before_state, intent
    ):
        active_ids = [m.memory_id for m in before_state.active()]
        return ProposedTransition(
            preserved_ids=tuple(active_ids),
            unchanged_ids=tuple(active_ids),
            expected_after_state=AfterStateExpectation(
                active_ids=tuple(active_ids),
                preserved_ids=tuple(active_ids),
                unchanged_ids=tuple(active_ids),
                no_mutation=True,
            ),
            rationale=intent.detail or intent.intent_type,
            **self._base(transition_type, statement, evidence, before_state),
        )

    def _supersede(
        self, statement, evidence, before_state, identity, target, active_ids
    ):
        others = [m for m in active_ids if m != target.target_id]
        return ProposedTransition(
            target_ids=(target.target_id,),
            created=(self._created_spec(statement, identity, replaces=target.target_id),),
            superseded_ids=(target.target_id,),
            preserved_ids=tuple(active_ids),
            unchanged_ids=tuple(others),
            lineage_edges=((target.target_id, "created:0"),),
            expected_after_state=AfterStateExpectation(
                active_ids=tuple(others),
                superseded_ids=(target.target_id,),
                created_refs=("created:0",),
                preserved_ids=tuple(active_ids),
                unchanged_ids=tuple(others),
                lineage_edges=((target.target_id, "created:0"),),
                expected_action_count=2,
            ),
            requests_canonical_effect=self.config.request_canonical_effect,
            rationale=(
                f"current value replaced for {identity.target_key()}"
                if identity.target_key()
                else "current value replaced"
            ),
            **self._base("supersede_existing", statement, evidence, before_state),
        )

    def _coexist(self, statement, evidence, before_state, identity, active_ids):
        return ProposedTransition(
            created=(self._created_spec(statement, identity),),
            preserved_ids=tuple(active_ids),
            unchanged_ids=tuple(active_ids),
            expected_after_state=AfterStateExpectation(
                active_ids=tuple(active_ids),
                created_refs=("created:0",),
                preserved_ids=tuple(active_ids),
                unchanged_ids=tuple(active_ids),
                expected_action_count=1,
            ),
            requests_canonical_effect=self.config.request_canonical_effect,
            rationale="distinct supported scope; both memories remain true",
            **self._base("scoped_coexistence", statement, evidence, before_state),
        )

    def _create(self, statement, evidence, before_state, identity, active_ids):
        return ProposedTransition(
            created=(self._created_spec(statement, identity),),
            preserved_ids=tuple(active_ids),
            unchanged_ids=tuple(active_ids),
            expected_after_state=AfterStateExpectation(
                active_ids=tuple(active_ids),
                created_refs=("created:0",),
                preserved_ids=tuple(active_ids),
                unchanged_ids=tuple(active_ids),
                expected_action_count=1,
            ),
            requests_canonical_effect=self.config.request_canonical_effect,
            rationale="new durable experience with no active lifecycle match",
            **self._base("create_new", statement, evidence, before_state),
        )

    # -- result assembly -------------------------------------------------

    def _finish(
        self, statement, intent, identity, target, proposal, before_state,
        diagnostics, started, stages,
    ):
        verification = None
        if self.config.verify:
            mark = time.perf_counter()
            verification = self._verifier.verify(proposal, before_state)
            stages["verifier_ms"] = (time.perf_counter() - mark) * 1000.0
            diagnostics.append(
                UpdateControllerDiagnostic(
                    "verifier_status", "verification",
                    f"{verification.status}"
                    + (
                        f" ({verification.rejection_reason})"
                        if verification.rejection_reason
                        else ""
                    ),
                )
            )
        return UpdateProposalResult(
            statement=statement,
            intent=intent,
            identity=identity,
            target=target,
            proposal=proposal,
            verification=verification,
            diagnostics=tuple(diagnostics),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            stage_latency_ms=dict(stages),
        )

    def _abstain(
        self, statement, intent, reason, diagnostics, started, stages,
        identity=None, target=None,
    ):
        return UpdateProposalResult(
            statement=statement,
            intent=intent,
            identity=identity,
            target=target,
            abstained=True,
            abstention_reason=reason,
            diagnostics=tuple(diagnostics),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            stage_latency_ms=dict(stages),
        )


#: Intents the source itself resolves into a frozen rejection.
_INTENT_REJECTION = {
    UpdateIntentType.QUESTION: "reject_question",
    UpdateIntentType.HYPOTHETICAL: "reject_hypothetical",
    UpdateIntentType.TEMPORARY_EXCEPTION: "reject_temporary",
    # The frozen oracle records a historical-only statement as an
    # unsupported transition, not as its own class.
    UpdateIntentType.HISTORICAL_ONLY: "reject_unsupported",
    UpdateIntentType.TASK_REQUEST: "reject_unsupported",
}


def _mentions_topic(identity, memory, topic: str) -> bool:
    """Whether an active memory plausibly concerns a bare topic noun."""
    words = [w for w in _CANDIDATE_DOMAIN_HINT.findall(normalize_text(topic))]
    if not words:
        return False
    attribute = identity.attribute.value if identity.attribute.known else ""
    haystack = f"{attribute} {normalize_text(memory.text)}"
    return any(word in haystack for word in words)


def _old_value_matches(old_value: str, existing: MemoryIdentity) -> bool:
    """Whether an explicitly replaced value names the resolved target."""
    if not existing.value.known:
        return False
    canonical, _ = canonical_value(existing.value_domain, old_value)
    if canonical == existing.value.value:
        return True
    # Fall back to surface containment for open vocabularies (airport
    # codes, channel names) the synonym tables do not enumerate.
    return existing.value.value in normalize_text(old_value)


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


_CONTROLLER = DeterministicUpdateController()


def propose_update_transition(
    statement: str, evidence: TransitionSourceEvidence, before_state, verifier=None
) -> UpdateProposalResult:
    """Propose a transition for one statement. Deterministic, non-mutating."""
    controller = (
        DeterministicUpdateController(verifier=verifier)
        if verifier is not None
        else _CONTROLLER
    )
    return controller.propose(statement, evidence, before_state)
