"""Deterministic forget-directive classification and target safety.

This controller answers one question and applies no answer:

> Given a source statement, its evidence, and the active memory state
> before it — is this a real forget directive, and if so which single
> active memory does it safely name?

Its goal is not to maximize the number of forgotten memories. It is to
recognize explicit forget intent, resolve exactly one safe active
target, preserve unrelated and differently scoped experience, and fail
closed when the request is unclear.

Boundaries:

- `ExperienceManager` remains lifecycle-policy authority and
  `ExperienceEngine._apply_memory_actions` remains the sole durable
  mutation boundary;
- the controller holds no store, emits no durable event, authorizes
  nothing, applies nothing, and **never constructs a created memory** —
  a forget directive can never become a positive assertion here;
- bulk deletion is not supported and is never approximated by splitting
  a broad request into single-target forgets.

Architecture (proposal adapter over the existing canonical resolver):

`experienceos/memory/forget.py` already implements the layered forget
handling the transition contract names as authoritative —
`ForgetIntentDetector` (negation, question, hypothetical, quoted,
current-turn-only, and bulk guards, in that order) and
`ForgetTargetResolver` (active-only scored resolution with explicit
score and margin thresholds that reject ambiguity rather than guessing).
That module is **unchanged and reused**; building a second forget parser
would fork the canonical semantics this prompt must stay consistent
with.

What this module adds is the layer that did not exist: mapping those
outcomes onto the frozen transition taxonomy, refusing multi-target
forgets, projecting identity through `experienceos/memory/identity.py`
so the resolver can see structured attributes, constructing
`ProposedTransition` values, and submitting every one to the verifier.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from experienceos.memory.forget import (
    _HYPOTHETICAL as _CANONICAL_HYPOTHETICAL,
    ForgetIntentDetector,
    ForgetOutcome,
    ForgetTargetResolver,
    describe_target,
)
from experienceos.memory.identity import (
    IdentityProjector,
    IdentityRelation,
    TemporalStatus,
    compare_memory_identity,
    normalize_text,
)
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.semantic import METADATA_KEY
from experienceos.memory.transition_verification import (
    AfterStateExpectation,
    ProposedTransition,
    TransitionSourceEvidence,
    TransitionVerifier,
)

#: The transition contract reserves no forget-specific system id — its
#: reserved ids are transition-scoped, and `experienceos_transition_
#: rules_v1` already names the update controller. A distinct behavior
#: needs a distinct id.
FORGET_CONTROLLER_ID = "experienceos_forget_rules_v1"
FORGET_CONTROLLER_VERSION = "1"

#: The snapshot carries no creation time, so recency is unavailable.
#: A single constant makes the canonical resolver's tie-break fall
#: through to memory-id ascending — deterministic, and with no
#: fabricated ordering.
_STABLE_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


class ForgetDirectiveType:
    """Controller-internal source classes, mapped onto the frozen taxonomy."""

    AFFIRMATIVE_TARGETED = "affirmative_targeted_forget"
    AFFIRMATIVE_SCOPED = "affirmative_scoped_forget"
    NEGATIVE_FORGET = "negative_forget"
    FORGET_CAPABILITY_QUESTION = "forget_capability_question"
    FORGET_CONFIRMATION_QUESTION = "forget_confirmation_question"
    MEMORY_INSPECTION_QUESTION = "memory_inspection_question"
    HYPOTHETICAL_FORGET = "hypothetical_forget"
    BROAD_FORGET = "broad_forget"
    BULK_FORGET = "bulk_forget"
    AMBIGUOUS_FORGET = "ambiguous_forget"
    NO_TARGET_FORGET = "no_target_forget"
    INACTIVE_TARGET_FORGET = "inactive_target_forget"
    QUOTED_FORGET = "quoted_third_party_forget"
    CURRENT_TURN_ONLY = "current_turn_only_forget"
    UNRELATED_SOURCE = "unrelated_source"
    UNSUPPORTED_FORGET = "unsupported_forget"
    POSITIVE_ASSERTION_WITH_FORGET_WORDING = "positive_assertion_with_forget_wording"


class ForgetTargetResolutionStatus:
    EXACT_TARGET = "exact_active_target"
    SEMANTIC_TARGET = "semantic_active_target"
    SCOPED_TARGET = "scoped_active_target"
    NO_ACTIVE_TARGET = "no_active_target"
    MULTIPLE_TARGETS = "multiple_active_targets"
    INACTIVE_ONLY = "inactive_only_match"
    AMBIGUOUS_SCOPE = "ambiguous_scope"
    AMBIGUOUS_KIND = "ambiguous_kind"
    AMBIGUOUS_ATTRIBUTE = "ambiguous_attribute"
    VALUE_ONLY_AMBIGUITY = "value_only_ambiguity"
    BROAD_UNSUPPORTED = "broad_request_unsupported"
    DESCRIPTION_INCOMPLETE = "target_description_incomplete"
    UNRELATED_ONLY = "unrelated_candidates_only"
    ALREADY_FORGOTTEN = "target_already_forgotten"
    ALREADY_SUPERSEDED = "target_already_superseded"
    NO_TARGET_REQUIRED = "no_target_required"
    UNSUPPORTED = "unsupported"


class ForgetAbstentionReason:
    NOT_A_FORGET_SOURCE = "not_a_forget_source"
    EVIDENCE_UNUSABLE = "evidence_unusable"
    UPDATE_HANDOFF = "negative_forget_assertion_handoff"


@dataclass(frozen=True)
class ForgetControllerDiagnostic:
    code: str
    category: str
    detail: str = ""

    def to_record(self) -> dict:
        return {"code": self.code, "category": self.category, "detail": self.detail}


@dataclass(frozen=True)
class ForgetPatternMatch:
    """The directive pattern that matched, and what it named."""

    pattern_id: str = ""
    target_text: str = ""
    surface: str = ""
    span: tuple = (0, 0)

    def to_record(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "target_text": self.target_text,
            "surface": self.surface,
            "span": list(self.span),
        }


@dataclass(frozen=True)
class ForgetDirectiveClassification:
    """Classified forget intent plus the markers that justified it."""

    directive_type: str
    pattern: ForgetPatternMatch = field(default_factory=ForgetPatternMatch)
    markers: tuple = ()
    affirmative: bool = False
    detail: str = ""

    def to_record(self) -> dict:
        return {
            "directive_type": self.directive_type,
            "pattern": self.pattern.to_record(),
            "markers": list(self.markers),
            "affirmative": self.affirmative,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ForgetTargetDescriptionRecord:
    """Structured description of what the source asks to forget.

    Wraps the canonical `describe_target` output and adds the identity
    fields the transition layer needs. Explicit fields come from the
    source; nothing is inferred from an arbitrary active memory.
    """

    raw: str = ""
    tokens: tuple = ()
    entities: tuple = ()
    attribute_hints: tuple = ()
    kind_hint: str | None = None
    historical: bool = False
    subject: str = "unknown"
    attribute: str = "unknown"
    value: str = "unknown"
    scope: str = "unknown"
    scope_specified: bool = False
    target_key: str | None = None
    semantic_key: str | None = None
    unknown_fields: tuple = ()

    def to_record(self) -> dict:
        return {
            "raw": self.raw,
            "tokens": sorted(self.tokens),
            "entities": sorted(self.entities),
            "attribute_hints": sorted(self.attribute_hints),
            "kind_hint": self.kind_hint,
            "historical": self.historical,
            "subject": self.subject,
            "attribute": self.attribute,
            "value": self.value,
            "scope": self.scope,
            "scope_specified": self.scope_specified,
            "target_key": self.target_key,
            "semantic_key": self.semantic_key,
            "unknown_fields": list(self.unknown_fields),
        }


@dataclass(frozen=True)
class ForgetTargetResolution:
    status: str
    target_id: str | None = None
    candidates: tuple = ()
    scores: tuple = ()
    detail: str = ""

    def to_record(self) -> dict:
        return {
            "status": self.status,
            "target_id": self.target_id,
            "candidates": list(self.candidates),
            "scores": [list(s) for s in self.scores],
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ForgetProposalResult:
    """Controller output. Never an authorized or applied action."""

    statement: str
    classification: ForgetDirectiveClassification
    description: ForgetTargetDescriptionRecord | None = None
    target: ForgetTargetResolution | None = None
    proposal: ProposedTransition | None = None
    verification: "object | None" = None
    abstained: bool = False
    abstention_reason: str = ""
    diagnostics: tuple = ()
    latency_ms: float = 0.0
    stage_latency_ms: dict = field(default_factory=dict)
    controller_id: str = FORGET_CONTROLLER_ID
    controller_version: str = FORGET_CONTROLLER_VERSION
    authorized: bool = False
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
            "classification": self.classification.to_record(),
            "description": self.description.to_record() if self.description else None,
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
            "authorized": self.authorized,
            "action_applied": self.action_applied,
        }


@dataclass(frozen=True)
class ForgetControllerConfig:
    """Deterministic configuration. No providers, no model, no network."""

    verify: bool = True
    max_candidate_diagnostics: int = 4
    request_canonical_effect: bool = False


# --- Bounded source markers the canonical detector does not classify ---------

# Memory-inspection wording. The canonical detector's question guard only
# fires on "forget"-shaped questions, so inspection questions
# ("Do you remember ...?") need their own bounded marker.
#: Removal wording. Broader than "forget": the canonical question guard
#: only fires on forget-shaped questions, so "Could you remove my airport
#: preference?" would otherwise reach the directive patterns and read as
#: a real removal. Questions must be caught for every removal verb.
_REMOVAL_LANGUAGE = re.compile(
    r"\b(?:forget|forgot|remove|delete|erase|wipe|clear)\b"
    r"|\bstop\s+remembering\b|\bdon'?t care about\b"
)
_RECALL_LANGUAGE = re.compile(r"\b(?:remember|remembering|remembered|recall)\b")
_MEMORY_LANGUAGE = re.compile(
    r"\b(?:forget|forgot|remember|remembering|remembered|recall"
    r"|remove|delete|erase|wipe)\b|\bdon'?t care about\b"
    r"|\bno longer (?:want|need|keep|remember)\b"
)
_INSPECTION = re.compile(
    r"\b(?:do you remember|what do you remember|are you still remembering"
    r"|what .* do you remember|do you still remember)\b"
)
# A broad request that names a topic rather than "everything" —
# the canonical bulk guard requires an explicit universal object.
_BROAD_TOPIC = re.compile(
    r"\bforget\s+(?:everything|all)\b|\b(?:delete|erase|wipe|clear)\s+"
    r"(?:everything|all)\b"
)
#: A clause that supplies the replacement value alongside the removal
#: ("I no longer prefer aisle seats; I prefer window seats."). That is a
#: supersession, and update intelligence already owns it.
_REPLACEMENT_CLAUSE = re.compile(
    r";\s*i\s+(?:now\s+)?(?:prefer|use|like|want)\b"
    r"|\bbut now\b|\binstead\b|\bnow i\s+(?:prefer|use|like)\b"
)

_QUOTED_REASON = "quoted third-party forget"
_CURRENT_TURN_REASON = "current-turn-only instruction"


class DeterministicForgetController:
    """Classifies forget directives and proposes one safe forget.

    Stateless: every call takes an explicit before-state snapshot.
    """

    controller_id = FORGET_CONTROLLER_ID
    version = FORGET_CONTROLLER_VERSION

    def __init__(
        self,
        config: ForgetControllerConfig | None = None,
        projector: IdentityProjector | None = None,
        verifier: TransitionVerifier | None = None,
        detector: ForgetIntentDetector | None = None,
        resolver: ForgetTargetResolver | None = None,
    ):
        self.config = config or ForgetControllerConfig()
        self._projector = projector or IdentityProjector()
        self._verifier = verifier or TransitionVerifier()
        self._detector = detector or ForgetIntentDetector()
        self._resolver = resolver or ForgetTargetResolver()

    # -- public API ------------------------------------------------------

    def propose(
        self, statement: str, evidence: TransitionSourceEvidence, before_state
    ) -> ForgetProposalResult:
        """Propose a forget transition for one statement. Mutates nothing."""
        started = time.perf_counter()
        stages = {}
        diagnostics = []

        if not evidence.usable:
            return self._abstain(
                statement,
                ForgetDirectiveClassification(ForgetDirectiveType.UNSUPPORTED_FORGET),
                ForgetAbstentionReason.EVIDENCE_UNUSABLE,
                diagnostics
                + [
                    ForgetControllerDiagnostic(
                        "evidence_unusable", "grounding",
                        f"evidence mode {evidence.evidence_mode}",
                    )
                ],
                started, stages,
            )

        mark = time.perf_counter()
        identity = self._projector.project_text(
            statement, kind=evidence.source_kind or None
        )
        classification = self._classify(statement, identity)
        stages["classification_ms"] = (time.perf_counter() - mark) * 1000.0
        diagnostics.append(
            ForgetControllerDiagnostic(
                "directive_classified", "classification",
                classification.directive_type,
            )
        )

        # A source with no forget bearing belongs to update intelligence.
        if classification.directive_type == ForgetDirectiveType.UNRELATED_SOURCE:
            return self._abstain(
                statement, classification,
                ForgetAbstentionReason.NOT_A_FORGET_SOURCE,
                diagnostics, started, stages,
            )

        # A frozen rejection the source itself establishes.
        rejection = _DIRECTIVE_REJECTION.get(classification.directive_type)
        if rejection:
            proposal = self._rejection(
                rejection, statement, evidence, before_state, classification
            )
            status = _DIRECTIVE_TARGET_STATUS.get(
                classification.directive_type,
                ForgetTargetResolutionStatus.NO_TARGET_REQUIRED,
            )
            return self._finish(
                statement, classification, None,
                ForgetTargetResolution(status, detail=classification.detail),
                proposal, before_state, diagnostics, started, stages,
            )

        # A negative forget asserts the memory. It never forgets, and it
        # never creates here: comparison against active state yields a
        # no-op, or the assertion is handed to update intelligence.
        if classification.directive_type == ForgetDirectiveType.NEGATIVE_FORGET:
            return self._negative_forget(
                statement, evidence, before_state, classification, identity,
                diagnostics, started, stages,
            )

        mark = time.perf_counter()
        description = self._describe(classification, identity)
        stages["description_ms"] = (time.perf_counter() - mark) * 1000.0

        mark = time.perf_counter()
        target = self._resolve(classification, before_state, description)
        stages["target_ms"] = (time.perf_counter() - mark) * 1000.0
        diagnostics.append(
            ForgetControllerDiagnostic(
                "target_resolved", "target",
                f"{target.status}"
                + (f" -> {target.target_id}" if target.target_id else ""),
            )
        )

        mark = time.perf_counter()
        proposal = self._build(
            statement, evidence, before_state, target, classification
        )
        stages["proposal_ms"] = (time.perf_counter() - mark) * 1000.0
        return self._finish(
            statement, classification, description, target, proposal,
            before_state, diagnostics, started, stages,
        )

    # -- classification --------------------------------------------------

    def _classify(self, statement, identity) -> ForgetDirectiveClassification:
        """Ordered so no reading can widen into an unsafe directive.

        1. inspection questions (memory language without forget wording);
        2. the canonical detector's own ordering — negation, question,
           hypothetical, quoted, current-turn-only, bulk — which already
           guarantees "Don't forget", "Can you forget", and "If I asked
           you to forget" can never become directives;
        3. a broad topic request that the bulk guard does not cover;
        4. a direct affirmative directive with a named target;
        5. anything else with no forget bearing is not ours.
        """
        lowered = normalize_text(statement)
        markers = identity.markers
        removal = bool(_REMOVAL_LANGUAGE.search(lowered))
        memory_language = bool(_MEMORY_LANGUAGE.search(lowered))

        # 1. Hypothetical, before any question or directive reading: the
        # clearest example of a hypothetical forget is phrased as a
        # question ("If I asked you to forget X, what would happen?"), so
        # a question-first order would mislabel it. Both are non-mutating,
        # so this ordering cannot widen anything.
        if memory_language and (
            identity.temporal_status == TemporalStatus.HYPOTHETICAL
            or _CANONICAL_HYPOTHETICAL.search(statement)
        ):
            return ForgetDirectiveClassification(
                ForgetDirectiveType.HYPOTHETICAL_FORGET, markers=markers,
                detail="hypothetical forget; nothing is requested",
            )

        # 2. Questions about memory, for every removal verb — not just
        # "forget". Polite question grammar is never permission to mutate.
        if memory_language and identity.temporal_status == TemporalStatus.QUESTION:
            if removal and not _INSPECTION.search(lowered):
                return ForgetDirectiveClassification(
                    ForgetDirectiveType.FORGET_CAPABILITY_QUESTION,
                    markers=markers,
                    detail="asks whether a memory can be removed; requests nothing",
                )
            return ForgetDirectiveClassification(
                ForgetDirectiveType.MEMORY_INSPECTION_QUESTION, markers=markers,
                detail="asks what is remembered; asserts nothing",
            )
        if _INSPECTION.search(lowered):
            return ForgetDirectiveClassification(
                ForgetDirectiveType.MEMORY_INSPECTION_QUESTION, markers=markers,
                detail="memory-inspection question",
            )

        # The canonical detector runs before any wording gate: a real
        # directive need not contain the word "forget" ("I don't care
        # about my study schedule preference anymore.").
        intent = self._detector.detect(statement)
        reason = intent.ambiguity_reason or ""

        # A statement that removes an old value *and supplies the new
        # one* is a replacement, not a forget. Update intelligence owns
        # it; claiming it here would produce two competing readings of
        # one sentence.
        if intent.detected and _REPLACEMENT_CLAUSE.search(lowered):
            return ForgetDirectiveClassification(
                ForgetDirectiveType.UNRELATED_SOURCE, markers=markers,
                detail="supplies a replacement value; update intelligence owns it",
            )

        if not intent.detected and not memory_language and not intent.negated:
            return ForgetDirectiveClassification(
                ForgetDirectiveType.UNRELATED_SOURCE, markers=markers,
                detail="no forget directive and no memory wording in the source",
            )

        if intent.negated:
            return ForgetDirectiveClassification(
                ForgetDirectiveType.NEGATIVE_FORGET, markers=markers,
                detail="negative forget asserts the memory rather than removing it",
            )
        if not intent.detected:
            if reason == "question about forgetting":
                return ForgetDirectiveClassification(
                    ForgetDirectiveType.FORGET_CAPABILITY_QUESTION,
                    markers=markers, detail=reason,
                )
            if reason == "hypothetical forget":
                return ForgetDirectiveClassification(
                    ForgetDirectiveType.HYPOTHETICAL_FORGET, markers=markers,
                    detail=reason,
                )
            if reason == _QUOTED_REASON:
                return ForgetDirectiveClassification(
                    ForgetDirectiveType.QUOTED_FORGET, markers=markers,
                    detail=reason,
                )
            if reason == _CURRENT_TURN_REASON:
                return ForgetDirectiveClassification(
                    ForgetDirectiveType.CURRENT_TURN_ONLY, markers=markers,
                    detail=reason,
                )
            # Forget wording with no directive reading: a positive
            # assertion that merely contains the word, or an unsupported
            # form. Either way it is not a directive.
            return ForgetDirectiveClassification(
                ForgetDirectiveType.POSITIVE_ASSERTION_WITH_FORGET_WORDING
                if identity.value.known
                else ForgetDirectiveType.UNSUPPORTED_FORGET,
                markers=markers,
                detail=reason or "forget wording without a directive reading",
            )
        if intent.bulk or _BROAD_TOPIC.search(lowered):
            return ForgetDirectiveClassification(
                ForgetDirectiveType.BROAD_FORGET, markers=markers,
                detail="broad or bulk request; per-memory directives required",
            )

        scoped = identity.scope_specified
        return ForgetDirectiveClassification(
            ForgetDirectiveType.AFFIRMATIVE_SCOPED
            if scoped
            else ForgetDirectiveType.AFFIRMATIVE_TARGETED,
            pattern=ForgetPatternMatch(
                pattern_id="canonical_forget_intent",
                target_text=intent.target_text,
                surface=statement[intent.span[0]: intent.span[1]],
                span=tuple(intent.span),
            ),
            markers=markers,
            affirmative=True,
            detail="affirmative forget directive with a named target",
        )

    # -- target description ----------------------------------------------

    def _describe(self, classification, identity) -> ForgetTargetDescriptionRecord:
        """Structured description of the requested target.

        The canonical `describe_target` supplies tokens, entities,
        attribute hints, kind hint, and the historical qualifier. The
        identity layer supplies subject/attribute/value/scope when the
        described text projects; unknown stays unknown — no field is
        filled in from an arbitrary active memory.
        """
        target_text = classification.pattern.target_text
        described = describe_target(target_text)
        projected = self._projector.project_text(target_text)
        unknown = tuple(
            name
            for name in ("subject", "attribute", "value", "scope")
            if not getattr(projected, name).known
        )
        return ForgetTargetDescriptionRecord(
            raw=described.raw,
            tokens=tuple(sorted(described.tokens)),
            entities=tuple(sorted(described.entities)),
            attribute_hints=tuple(sorted(described.attribute_hints)),
            kind_hint=described.kind_hint,
            historical=described.historical,
            subject=projected.subject.value,
            attribute=projected.attribute.value,
            value=projected.value.value,
            scope=projected.scope.value,
            scope_specified=projected.scope_specified,
            target_key=projected.target_key(),
            semantic_key=projected.semantic_key(),
            unknown_fields=unknown,
        )

    # -- target resolution -----------------------------------------------

    def _entries(self, before_state) -> list:
        """Snapshot as resolver-shaped entries, identity attached.

        The canonical resolver scores structured identity fields, which
        a raw snapshot does not carry; the identity layer already
        projected them, so they are passed through rather than re-derived
        or invented.
        """
        entries = []
        for memory in before_state.memories:
            identity = before_state.identity_of(memory.memory_id)
            metadata = {}
            if identity is not None:
                metadata[METADATA_KEY] = {
                    "attribute": (
                        identity.attribute.value if identity.attribute.known else ""
                    ),
                    "value": identity.value.value if identity.value.known else "",
                    "scope": identity.scope.value if identity.scope.known else "",
                }
            entry = ExperienceEntry(
                user_id=before_state.user_id or "snapshot-user",
                text=memory.text,
                kind=memory.kind,
                status=memory.status,
                metadata=metadata,
            )
            entry.id = memory.memory_id
            entry.created_at = _STABLE_EPOCH
            entry.updated_at = _STABLE_EPOCH
            entries.append(entry)
        return entries

    def _resolve(self, classification, before_state, description):
        if classification.directive_type == ForgetDirectiveType.BROAD_FORGET:
            return ForgetTargetResolution(
                ForgetTargetResolutionStatus.BROAD_UNSUPPORTED,
                detail="broad deletion is not supported; no subset selected",
            )
        intent = self._detector.detect(classification.pattern.target_text or "")
        # Re-detect on the raw statement so the canonical resolver sees
        # the same intent object it was designed for.
        intent = self._detector.detect(classification.pattern.surface or "")
        if not intent.detected:
            # Fall back to the classified target text: the surface span
            # is diagnostic, the target text is what was named.
            from experienceos.memory.forget import ForgetIntent

            intent = ForgetIntent(
                True, confidence=1.0,
                target_text=classification.pattern.target_text,
            )

        entries = self._entries(before_state)
        result = self._resolver.resolve(intent, entries)
        candidates = tuple(
            c.entry.id for c in result.scores[: self.config.max_candidate_diagnostics]
        )
        scores = tuple(
            (c.entry.id, round(c.score, 4))
            for c in result.scores[: self.config.max_candidate_diagnostics]
        )

        if result.outcome == ForgetOutcome.RESOLVED:
            # Bulk forgetting is not supported: a request that resolves
            # to several memories is refused rather than split.
            if len(result.targets) != 1:
                return ForgetTargetResolution(
                    ForgetTargetResolutionStatus.MULTIPLE_TARGETS,
                    candidates=tuple(t.id for t in result.targets),
                    scores=scores,
                    detail=(
                        f"{len(result.targets)} targets resolved; multi-target "
                        "forgetting is not supported"
                    ),
                )
            target = result.targets[0]
            status = self._match_kind(before_state, target.id, description)
            return ForgetTargetResolution(
                status=status, target_id=target.id, candidates=candidates,
                scores=scores, detail=result.reason,
            )

        status = {
            ForgetOutcome.AMBIGUOUS: ForgetTargetResolutionStatus.MULTIPLE_TARGETS,
            ForgetOutcome.BELOW_THRESHOLD: (
                ForgetTargetResolutionStatus.DESCRIPTION_INCOMPLETE
            ),
            ForgetOutcome.NO_ACTIVE_CANDIDATES: (
                ForgetTargetResolutionStatus.NO_ACTIVE_TARGET
            ),
            ForgetOutcome.INACTIVE_TARGET_ONLY: (
                ForgetTargetResolutionStatus.INACTIVE_ONLY
            ),
            ForgetOutcome.BULK_UNSUPPORTED: (
                ForgetTargetResolutionStatus.BROAD_UNSUPPORTED
            ),
            ForgetOutcome.NEGATED_OR_NON_DURABLE: (
                ForgetTargetResolutionStatus.UNSUPPORTED
            ),
            ForgetOutcome.NO_INTENT: ForgetTargetResolutionStatus.UNSUPPORTED,
        }.get(result.outcome, ForgetTargetResolutionStatus.UNSUPPORTED)
        return ForgetTargetResolution(
            status=status, candidates=candidates, scores=scores,
            detail=result.reason,
        )

    def _match_kind(self, before_state, target_id, description) -> str:
        """Classify how the resolved target was matched, and guard kind."""
        memory = before_state.by_id(target_id)
        if description and description.kind_hint and memory.kind != (
            description.kind_hint
        ):
            return ForgetTargetResolutionStatus.AMBIGUOUS_KIND
        if description and description.scope_specified:
            return ForgetTargetResolutionStatus.SCOPED_TARGET
        identity = before_state.identity_of(target_id)
        if identity and description and description.raw:
            described = self._projector.project_text(description.raw)
            relation = compare_memory_identity(identity, described).relation
            if relation == IdentityRelation.EXACT_DUPLICATE:
                return ForgetTargetResolutionStatus.EXACT_TARGET
            if relation == IdentityRelation.SEMANTIC_DUPLICATE:
                return ForgetTargetResolutionStatus.SEMANTIC_TARGET
        return ForgetTargetResolutionStatus.EXACT_TARGET

    # -- proposal construction -------------------------------------------

    _RESOLVED_STATUSES = frozenset(
        {
            ForgetTargetResolutionStatus.EXACT_TARGET,
            ForgetTargetResolutionStatus.SEMANTIC_TARGET,
            ForgetTargetResolutionStatus.SCOPED_TARGET,
        }
    )

    def _build(self, statement, evidence, before_state, target, classification):
        if target.status in self._RESOLVED_STATUSES and target.target_id:
            return self._forget(
                statement, evidence, before_state, target.target_id
            )
        frozen = {
            ForgetTargetResolutionStatus.MULTIPLE_TARGETS: "reject_ambiguous",
            ForgetTargetResolutionStatus.AMBIGUOUS_SCOPE: "reject_ambiguous",
            ForgetTargetResolutionStatus.AMBIGUOUS_KIND: "reject_ambiguous",
            ForgetTargetResolutionStatus.AMBIGUOUS_ATTRIBUTE: "reject_ambiguous",
            ForgetTargetResolutionStatus.VALUE_ONLY_AMBIGUITY: "reject_ambiguous",
            ForgetTargetResolutionStatus.DESCRIPTION_INCOMPLETE: "reject_ambiguous",
        }.get(target.status, "reject_unsupported")
        return self._rejection(
            frozen, statement, evidence, before_state, classification
        )

    def _base(self, transition_type, statement, evidence, before_state):
        return dict(
            proposal_id=f"{FORGET_CONTROLLER_ID}:{before_state.digest()}:"
                        f"{_digest(statement)}",
            transition_type=transition_type,
            evidence=evidence,
            before_state_digest=before_state.digest(),
            proposer_id=FORGET_CONTROLLER_ID,
            proposal_source="deterministic_forget_controller",
        )

    def _forget(self, statement, evidence, before_state, target_id):
        active_ids = [m.memory_id for m in before_state.active()]
        others = [m for m in active_ids if m != target_id]
        return ProposedTransition(
            target_ids=(target_id,),
            # A forget directive never creates and never supersedes.
            created=(),
            superseded_ids=(),
            forgotten_ids=(target_id,),
            preserved_ids=tuple(active_ids),
            unchanged_ids=tuple(others),
            lineage_edges=(),
            expected_after_state=AfterStateExpectation(
                active_ids=tuple(others),
                forgotten_ids=(target_id,),
                created_refs=(),
                preserved_ids=tuple(active_ids),
                unchanged_ids=tuple(others),
                lineage_edges=(),
                expected_action_count=1,
            ),
            requests_canonical_effect=self.config.request_canonical_effect,
            rationale="affirmative forget directive naming one active memory",
            **self._base("forget_existing", statement, evidence, before_state),
        )

    def _rejection(
        self, transition_type, statement, evidence, before_state, classification
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
            rationale=classification.detail or classification.directive_type,
            **self._base(transition_type, statement, evidence, before_state),
        )

    def _noop(self, transition_type, statement, evidence, before_state):
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
            rationale="negative forget: the asserted memory is already active",
            **self._base(transition_type, statement, evidence, before_state),
        )

    def _negative_forget(
        self, statement, evidence, before_state, classification, identity,
        diagnostics, started, stages,
    ):
        """A negative forget asserts the memory; it never removes it."""
        relation = None
        for memory in before_state.active():
            existing = before_state.identity_of(memory.memory_id)
            if existing is None:
                continue
            candidate = compare_memory_identity(existing, identity).relation
            if candidate in (
                IdentityRelation.EXACT_DUPLICATE,
                IdentityRelation.SEMANTIC_DUPLICATE,
            ):
                relation = candidate
                break
        if relation is None:
            # The assertion names no active memory. Creating it is not
            # this controller's authority.
            diagnostics.append(
                ForgetControllerDiagnostic(
                    ForgetAbstentionReason.UPDATE_HANDOFF, "handoff",
                    "negative forget asserts a memory that is not active; "
                    "creation belongs to update intelligence",
                )
            )
            return self._abstain(
                statement, classification, ForgetAbstentionReason.UPDATE_HANDOFF,
                diagnostics, started, stages,
            )
        transition_type = (
            "duplicate_noop"
            if relation == IdentityRelation.EXACT_DUPLICATE
            else "semantic_duplicate_noop"
        )
        proposal = self._noop(transition_type, statement, evidence, before_state)
        return self._finish(
            statement, classification, None,
            ForgetTargetResolution(
                ForgetTargetResolutionStatus.NO_TARGET_REQUIRED,
                detail="negative forget: no target deactivated",
            ),
            proposal, before_state, diagnostics, started, stages,
        )

    # -- result assembly -------------------------------------------------

    def _finish(
        self, statement, classification, description, target, proposal,
        before_state, diagnostics, started, stages,
    ):
        verification = None
        if self.config.verify and proposal is not None:
            mark = time.perf_counter()
            verification = self._verifier.verify(proposal, before_state)
            stages["verifier_ms"] = (time.perf_counter() - mark) * 1000.0
            diagnostics.append(
                ForgetControllerDiagnostic(
                    "verifier_status", "verification",
                    f"{verification.status}"
                    + (
                        f" ({verification.rejection_reason})"
                        if verification.rejection_reason
                        else ""
                    ),
                )
            )
        return ForgetProposalResult(
            statement=statement,
            classification=classification,
            description=description,
            target=target,
            proposal=proposal,
            verification=verification,
            diagnostics=tuple(diagnostics),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            stage_latency_ms=dict(stages),
        )

    def _abstain(
        self, statement, classification, reason, diagnostics, started, stages,
    ):
        return ForgetProposalResult(
            statement=statement,
            classification=classification,
            abstained=True,
            abstention_reason=reason,
            diagnostics=tuple(diagnostics),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            stage_latency_ms=dict(stages),
        )


#: Directive classes the source itself resolves into a frozen rejection.
_DIRECTIVE_REJECTION = {
    ForgetDirectiveType.FORGET_CAPABILITY_QUESTION: "reject_question",
    ForgetDirectiveType.FORGET_CONFIRMATION_QUESTION: "reject_question",
    ForgetDirectiveType.MEMORY_INSPECTION_QUESTION: "reject_question",
    ForgetDirectiveType.HYPOTHETICAL_FORGET: "reject_hypothetical",
    ForgetDirectiveType.BROAD_FORGET: "reject_unsupported",
    ForgetDirectiveType.BULK_FORGET: "reject_unsupported",
    ForgetDirectiveType.QUOTED_FORGET: "reject_unsupported",
    ForgetDirectiveType.CURRENT_TURN_ONLY: "reject_temporary",
    ForgetDirectiveType.UNSUPPORTED_FORGET: "reject_unsupported",
    ForgetDirectiveType.POSITIVE_ASSERTION_WITH_FORGET_WORDING: (
        "reject_forget_directive_as_creation"
    ),
}


#: The target status a directive-level rejection reports. A broad
#: request is refused *because* it is broad, not because no target was
#: required — the diagnostic should say so.
_DIRECTIVE_TARGET_STATUS = {
    ForgetDirectiveType.BROAD_FORGET: (
        ForgetTargetResolutionStatus.BROAD_UNSUPPORTED
    ),
    ForgetDirectiveType.BULK_FORGET: (
        ForgetTargetResolutionStatus.BROAD_UNSUPPORTED
    ),
    ForgetDirectiveType.UNSUPPORTED_FORGET: (
        ForgetTargetResolutionStatus.UNSUPPORTED
    ),
}


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


_CONTROLLER = DeterministicForgetController()


def propose_forget_transition(
    statement: str, evidence: TransitionSourceEvidence, before_state, verifier=None
) -> ForgetProposalResult:
    """Propose a forget transition. Deterministic and non-mutating."""
    controller = (
        DeterministicForgetController(verifier=verifier)
        if verifier is not None
        else _CONTROLLER
    )
    return controller.propose(statement, evidence, before_state)
