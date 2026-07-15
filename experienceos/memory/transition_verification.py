"""Deterministic verification of proposed memory lifecycle transitions.

This module answers one question and applies no answer:

> Given a source statement, its evidence, the memory state before it, and
> a proposed before-to-after lifecycle transition — is that transition
> structurally valid, grounded, identity-consistent, lifecycle-legal,
> correctly targeted, scope-safe, preservation-safe, and lineage-safe?

It produces a *verified description of an intended effect*, never a
mutation. `ExperienceManager` remains lifecycle-policy authority and
`ExperienceEngine._apply_memory_actions` remains the sole durable
mutation boundary. The verifier holds no store, emits no durable event,
and constructs nothing the engine can consume by accident.

Naming note: `experienceos/controllers/transition.py` already defines
`TransitionEvidence` and `TransitionProposal` for a different layer — a
controller's approve/reject/abstain *recommendation*. To avoid two
representations wearing one name, the before-to-after models here are
`TransitionSourceEvidence` and `ProposedTransition`.

Reused rather than forked: `MemorySnapshot` and `ProposedMemoryCandidate`
(read-only lifecycle and proposal primitives) and the identity relations
from `experienceos/memory/identity.py`.

Grounding is *consumed, not re-validated*. The verifier never runs its
own grounding check — that would be a second validator competing with
`experienceos/memory/grounding.py`. It reads the caller's declared
`evidence_mode` and the `GroundingValidation` the caller attaches, and
decides only what that support licenses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from experienceos.controllers.base import MEMORY_KINDS, MemorySnapshot
from experienceos.controllers.extraction import ProposedMemoryCandidate
from experienceos.memory.identity import (
    IdentityProjector,
    IdentityRelation,
    MemoryIdentity,
    compare_memory_identity,
)
from experienceos.memory.schema import MemoryStatus

TRANSITION_VERIFIER_ID = "transition_rules-1"
VERIFICATION_VERSION = "1"
PROPOSAL_VERSION = "1"

# The frozen transition taxonomy (contract §6). Unknown types fail
# closed as `unsupported` — never as a permissive default.
TRANSITION_TYPES = (
    "create_new",
    "duplicate_noop",
    "semantic_duplicate_noop",
    "supersede_existing",
    "scoped_coexistence",
    "forget_existing",
    "reject_forget_directive_as_creation",
    "reject_unsupported",
    "reject_ambiguous",
    "reject_temporary",
    "reject_question",
    "reject_hypothetical",
    "reject_unrelated",
    "shadow_only",
)

#: Types whose correct effect is a durable mutation.
MUTATING_TYPES = frozenset(
    {"create_new", "supersede_existing", "scoped_coexistence", "forget_existing"}
)
#: Types whose correct effect is explicitly no mutation.
NOOP_TYPES = frozenset({"duplicate_noop", "semantic_duplicate_noop"})
#: Types that assert the transition must be refused.
REJECTION_TYPES = frozenset(
    {
        "reject_forget_directive_as_creation",
        "reject_unsupported",
        "reject_ambiguous",
        "reject_temporary",
        "reject_question",
        "reject_hypothetical",
        "reject_unrelated",
    }
)
#: Types that must never carry a canonical effect.
NON_MUTATING_TYPES = NOOP_TYPES | REJECTION_TYPES | {"shadow_only"}


class TransitionStatus:
    """Outcome of verification. Never an authorization token."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SHADOW_ONLY = "shadow_only"
    STRUCTURALLY_INVALID = "structurally_invalid"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class EvidenceMode:
    """How a proposal's source support was established."""

    GROUNDED_VALID = "grounded_valid"
    GROUNDED_INVALID = "grounded_invalid"
    UNGROUNDED = "ungrounded"
    # Frozen benchmark case that predates grounded extraction. Usable
    # for audit-only verification; never for production adoption.
    HISTORICAL_ORACLE = "historical_oracle"
    # Explicitly synthetic fixture evidence. Never production grounding.
    DEVELOPMENT_FIXTURE = "development_fixture"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


#: Only real, validated grounding can ever support canonical effect.
PRODUCTION_GROUNDED = frozenset({EvidenceMode.GROUNDED_VALID})
#: Modes acceptable for non-canonical (audit / fixture) verification.
NON_CANONICAL_MODES = frozenset(
    {EvidenceMode.HISTORICAL_ORACLE, EvidenceMode.DEVELOPMENT_FIXTURE}
)


class TransitionRejectionReason:
    """Stable rejection codes."""

    UNKNOWN_TRANSITION_TYPE = "unknown_transition_type"
    UNSUPPORTED_PROPOSAL_VERSION = "unsupported_proposal_version"
    MISSING_PROPOSAL_ID = "missing_proposal_id"
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_BEFORE_STATE = "missing_before_state"
    DUPLICATE_TARGET_IDS = "duplicate_target_ids"
    CONTRADICTORY_LIFECYCLE_SETS = "contradictory_lifecycle_sets"
    REJECTION_WITH_MUTATION = "rejection_with_mutation"
    NOOP_WITH_CREATION = "noop_with_creation"
    SUPERSEDE_WITHOUT_REPLACEMENT = "supersede_without_replacement"
    FORGET_WITHOUT_TARGET = "forget_without_target"
    FORGET_WITH_CREATION = "forget_with_creation"
    COEXISTENCE_SUPERSEDES_SCOPE = "coexistence_supersedes_scope"
    CREATED_REF_REUSED_AS_TARGET = "created_ref_reused_as_target"
    UNKNOWN_SAFETY_FIELD = "unknown_safety_field"
    TARGET_NOT_FOUND = "target_not_found"
    TARGET_NOT_ACTIVE = "target_not_active"
    TARGET_NOT_UNIQUE = "target_not_unique"
    TARGET_UNRELATED = "target_unrelated"
    TARGET_KIND_INCOMPATIBLE = "target_kind_incompatible"
    TARGET_SCOPE_INCOMPATIBLE = "target_scope_incompatible"
    IDENTITY_RELATION_MISMATCH = "identity_relation_mismatch"
    IDENTITY_AMBIGUOUS = "identity_ambiguous"
    TEMPORARY_NOT_DURABLE = "temporary_not_durable"
    HISTORICAL_NOT_CURRENT = "historical_not_current"
    HYPOTHETICAL_NOT_ASSERTED = "hypothetical_not_asserted"
    QUESTION_NOT_ASSERTED = "question_not_asserted"
    GROUNDING_INVALID = "grounding_invalid"
    GROUNDING_REQUIRED = "grounding_required"
    UNSUPPORTED_CREATED_VALUE = "unsupported_created_value"
    UNSUPPORTED_SCOPE = "unsupported_scope"
    UNSUPPORTED_KIND_CHANGE = "unsupported_kind_change"
    FORGET_AS_CREATION = "forget_as_creation"
    UNRELATED_MEMORY_DEACTIVATED = "unrelated_memory_deactivated"
    SCOPED_MEMORY_LOST = "scoped_memory_lost"
    PRESERVATION_NOT_PROVEN = "preservation_not_proven"
    REACTIVATION_FORBIDDEN = "reactivation_forbidden"
    DOUBLE_SUPERSESSION = "double_supersession"
    DOUBLE_FORGET = "double_forget"
    LINEAGE_MISSING_PREDECESSOR = "lineage_missing_predecessor"
    LINEAGE_SELF_REFERENCE = "lineage_self_reference"
    LINEAGE_INACTIVE_PREDECESSOR = "lineage_inactive_predecessor"
    LINEAGE_UNRELATED_PREDECESSOR = "lineage_unrelated_predecessor"
    LINEAGE_VALUE_UNCHANGED = "lineage_value_unchanged"
    AFTER_STATE_MISMATCH = "after_state_mismatch"
    BEFORE_STATE_INCOMPLETE = "before_state_incomplete"


class CheckSeverity:
    BLOCKING = "blocking"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class TransitionDiagnostic:
    """One structured reason contributing to a verification outcome."""

    code: str
    category: str
    severity: str = CheckSeverity.BLOCKING
    field_ref: str = ""
    memory_id: str = ""
    detail: str = ""

    def to_record(self) -> dict:
        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "field_ref": self.field_ref,
            "memory_id": self.memory_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TransitionSourceEvidence:
    """Bounded source support for a proposal.

    Provenance and grounding status come from the *caller*, never from
    the proposal: a proposal cannot upgrade its own trust by claiming a
    stronger mode.
    """

    source_statement: str = ""
    source_event_id: str = ""
    source_role: str = "user"
    source_turn_id: str = ""
    session_id: str = ""
    grounded_candidate_ref: str = ""
    evidence_span_ref: str = ""
    source_text_digest: str = ""
    evidence_mode: str = EvidenceMode.UNAVAILABLE
    grounding_validation = None  # GroundingValidation | None
    grounding_validator_id: str = ""
    provenance_ref: str = "user_asserted"
    source_kind: str = ""
    markers: tuple = ()
    diagnostics: dict = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.evidence_mode != EvidenceMode.UNAVAILABLE

    @property
    def production_grounded(self) -> bool:
        return self.evidence_mode in PRODUCTION_GROUNDED

    @property
    def usable(self) -> bool:
        """Usable for verification at all (canonical or audit-only)."""
        return self.production_grounded or self.evidence_mode in NON_CANONICAL_MODES

    def to_record(self) -> dict:
        return {
            "source_event_id": self.source_event_id,
            "source_role": self.source_role,
            "source_turn_id": self.source_turn_id,
            "session_id": self.session_id,
            "grounded_candidate_ref": self.grounded_candidate_ref,
            "evidence_span_ref": self.evidence_span_ref,
            "source_text_digest": self.source_text_digest,
            "evidence_mode": self.evidence_mode,
            "grounding_validator_id": self.grounding_validator_id,
            "provenance_ref": self.provenance_ref,
            "source_kind": self.source_kind,
            "markers": list(self.markers),
            "available": self.available,
            "production_grounded": self.production_grounded,
        }


@dataclass(frozen=True)
class BeforeStateSnapshot:
    """Detached lifecycle state before a proposed transition.

    Built once from read-only `MemorySnapshot` primitives and never
    holding a reference to a live mutable collection: mutating the
    source list afterwards cannot alter this snapshot.
    """

    memories: tuple = ()
    identities: dict = field(default_factory=dict)  # memory_id -> MemoryIdentity
    user_id: str = ""
    coverage_complete: bool = True
    coverage_note: str = ""
    snapshot_source: str = "caller_supplied"
    notes: tuple = ()

    def by_id(self, memory_id: str):
        for memory in self.memories:
            if memory.memory_id == memory_id:
                return memory
        return None

    def active(self) -> tuple:
        return tuple(
            m for m in self.memories if m.status == MemoryStatus.ACTIVE
        )

    def active_ids(self) -> frozenset:
        return frozenset(m.memory_id for m in self.active())

    def identity_of(self, memory_id: str):
        return self.identities.get(memory_id)

    def digest(self) -> str:
        """Deterministic content digest of the snapshot."""
        parts = [
            f"{m.memory_id}:{m.kind}:{m.status}:{m.text}"
            for m in sorted(self.memories, key=lambda m: m.memory_id)
        ]
        return _digest("|".join(parts))

    def to_record(self) -> dict:
        return {
            "user_id": self.user_id,
            "digest": self.digest(),
            "memory_count": len(self.memories),
            "active_count": len(self.active()),
            "coverage_complete": self.coverage_complete,
            "coverage_note": self.coverage_note,
            "snapshot_source": self.snapshot_source,
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "kind": m.kind,
                    "status": m.status,
                    "attribute": m.attribute,
                    "value": m.value,
                    "scope": m.scope,
                }
                for m in sorted(self.memories, key=lambda m: m.memory_id)
            ],
        }


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_before_state(
    memories,
    user_id: str = "",
    coverage_complete: bool = True,
    coverage_note: str = "",
    snapshot_source: str = "caller_supplied",
    projector: IdentityProjector | None = None,
) -> BeforeStateSnapshot:
    """Detach a lifecycle snapshot and project every memory's identity.

    ``memories`` may be `MemorySnapshot` values or `ExperienceEntry`
    records; both are copied into frozen primitives, so later mutation
    of the caller's collection cannot reach the snapshot.
    """
    projector = projector or IdentityProjector()
    frozen = []
    identities = {}
    for memory in tuple(memories):
        snapshot = _as_snapshot(memory)
        frozen.append(snapshot)
        identities[snapshot.memory_id] = projector.project_text(
            snapshot.text, kind=snapshot.kind
        )
    return BeforeStateSnapshot(
        memories=tuple(frozen),
        identities=dict(identities),
        user_id=user_id,
        coverage_complete=coverage_complete,
        coverage_note=coverage_note,
        snapshot_source=snapshot_source,
    )


def _as_snapshot(memory) -> MemorySnapshot:
    if isinstance(memory, MemorySnapshot):
        return memory
    # An ExperienceEntry: copy the primitives only.
    metadata = getattr(memory, "metadata", None) or {}
    identity = metadata.get("semantic_identity") or {}
    return MemorySnapshot(
        memory_id=memory.id,
        kind=memory.kind,
        text=memory.text,
        status=memory.status,
        attribute=str(identity.get("attribute", "")),
        value=str(identity.get("value", "")),
        scope=str(identity.get("scope", "")),
    )


@dataclass(frozen=True)
class CreatedMemorySpec:
    """A memory a proposal would create. Never a durable record.

    Referenced by a stable proposal-local ref (``created:0``) because no
    durable ID can exist before the engine applies anything.
    """

    candidate: ProposedMemoryCandidate
    local_ref: str = "created:0"
    replaces: str | None = None
    scope: str = ""
    must_include: tuple = ()

    def to_record(self) -> dict:
        return {
            "local_ref": self.local_ref,
            "kind": self.candidate.kind,
            "text": self.candidate.text,
            "replaces": self.replaces,
            "scope": self.scope,
            "must_include": list(self.must_include),
        }


@dataclass(frozen=True)
class AfterStateExpectation:
    """The lifecycle result a proposal claims, before any application."""

    active_ids: tuple = ()
    superseded_ids: tuple = ()
    forgotten_ids: tuple = ()
    created_refs: tuple = ()
    preserved_ids: tuple = ()
    unchanged_ids: tuple = ()
    lineage_edges: tuple = ()  # (predecessor_id, created_local_ref)
    semantic_duplicate_count: int = 0
    stale_active_count: int = 0
    expected_action_count: int = 0
    no_mutation: bool = False
    final_active_summary: str = ""

    def to_record(self) -> dict:
        return {
            "active_ids": sorted(self.active_ids),
            "superseded_ids": sorted(self.superseded_ids),
            "forgotten_ids": sorted(self.forgotten_ids),
            "created_refs": list(self.created_refs),
            "preserved_ids": sorted(self.preserved_ids),
            "unchanged_ids": sorted(self.unchanged_ids),
            "lineage_edges": [list(e) for e in self.lineage_edges],
            "semantic_duplicate_count": self.semantic_duplicate_count,
            "stale_active_count": self.stale_active_count,
            "expected_action_count": self.expected_action_count,
            "no_mutation": self.no_mutation,
        }


@dataclass(frozen=True)
class ProposedTransition:
    """One proposed before-to-after lifecycle transition.

    A proposal may *request* canonical effect. It never receives it: the
    verifier grants no execution authority, and confidence never
    overrides a structural, lifecycle, grounding, identity, or
    preservation failure.
    """

    proposal_id: str
    transition_type: str
    evidence: TransitionSourceEvidence
    before_state_digest: str = ""
    target_ids: tuple = ()
    created: tuple = ()  # CreatedMemorySpec
    superseded_ids: tuple = ()
    forgotten_ids: tuple = ()
    preserved_ids: tuple = ()
    unchanged_ids: tuple = ()
    lineage_edges: tuple = ()
    expected_after_state: AfterStateExpectation | None = None
    identity_comparisons: dict = field(default_factory=dict)
    proposer_id: str = ""
    proposal_source: str = ""
    confidence: float | None = None
    rationale: str = ""
    diagnostics: dict = field(default_factory=dict)
    requests_canonical_effect: bool = False
    proposal_version: str = PROPOSAL_VERSION

    def to_record(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "transition_type": self.transition_type,
            "evidence": self.evidence.to_record(),
            "before_state_digest": self.before_state_digest,
            "target_ids": sorted(self.target_ids),
            "created": [c.to_record() for c in self.created],
            "superseded_ids": sorted(self.superseded_ids),
            "forgotten_ids": sorted(self.forgotten_ids),
            "preserved_ids": sorted(self.preserved_ids),
            "unchanged_ids": sorted(self.unchanged_ids),
            "lineage_edges": [list(e) for e in self.lineage_edges],
            "proposer_id": self.proposer_id,
            "proposal_source": self.proposal_source,
            "confidence": self.confidence,
            "requests_canonical_effect": self.requests_canonical_effect,
            "proposal_version": self.proposal_version,
        }


@dataclass(frozen=True)
class VerifiedActionSpec:
    """Inert description of an action a verified proposal would need.

    Deliberately **not** a `MemoryAction`. The engine cannot consume this
    type, so a verification result can never be mistaken for something
    applicable: translating it into a canonical action is a later,
    explicit integration step that this prompt does not build.
    """

    action: str  # "create" | "supersede" | "forget"
    kind: str = ""
    text: str = ""
    target_id: str | None = None
    replaces: str | None = None
    local_ref: str = ""
    preconditions: tuple = ()
    metadata: dict = field(default_factory=dict)
    applied: bool = False  # immutable evidence: never applied here

    def to_record(self) -> dict:
        return {
            "action": self.action,
            "kind": self.kind,
            "text": self.text,
            "target_id": self.target_id,
            "replaces": self.replaces,
            "local_ref": self.local_ref,
            "preconditions": list(self.preconditions),
            "applied": self.applied,
        }


@dataclass(frozen=True)
class ProjectedAfterState:
    """Inert projection of the lifecycle result. Diagnostic only."""

    active_ids: frozenset = frozenset()
    superseded_ids: frozenset = frozenset()
    forgotten_ids: frozenset = frozenset()
    created_refs: tuple = ()
    lineage_edges: tuple = ()
    semantic_duplicate_count: int = 0
    stale_active_count: int = 0

    def to_record(self) -> dict:
        return {
            "active_ids": sorted(self.active_ids),
            "superseded_ids": sorted(self.superseded_ids),
            "forgotten_ids": sorted(self.forgotten_ids),
            "created_refs": list(self.created_refs),
            "lineage_edges": [list(e) for e in self.lineage_edges],
            "semantic_duplicate_count": self.semantic_duplicate_count,
            "stale_active_count": self.stale_active_count,
        }


@dataclass(frozen=True)
class TransitionVerificationResult:
    """Explained verification outcome.

    Not an authorization token, and not proof that anything was applied:
    ``action_applied`` is immutably ``False`` here.
    """

    proposal_id: str
    transition_type: str
    status: str
    checks: dict = field(default_factory=dict)
    rejection_reason: str | None = None
    diagnostics: tuple = ()
    projected_after_state: ProjectedAfterState | None = None
    action_specs: tuple = ()
    canonical_effect_eligible: bool = False
    canonical_effect_reason: str = ""
    fail_closed: bool = False
    before_state_coverage_complete: bool = True
    identity_relations: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    verifier_id: str = TRANSITION_VERIFIER_ID
    verifier_version: str = VERIFICATION_VERSION
    action_applied: bool = False

    @property
    def accepted(self) -> bool:
        return self.status == TransitionStatus.ACCEPTED

    def to_record(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "transition_type": self.transition_type,
            "status": self.status,
            "checks": dict(sorted(self.checks.items())),
            "rejection_reason": self.rejection_reason,
            "diagnostics": [d.to_record() for d in self.diagnostics],
            "projected_after_state": (
                self.projected_after_state.to_record()
                if self.projected_after_state
                else None
            ),
            "action_specs": [a.to_record() for a in self.action_specs],
            "canonical_effect_eligible": self.canonical_effect_eligible,
            "canonical_effect_reason": self.canonical_effect_reason,
            "fail_closed": self.fail_closed,
            "before_state_coverage_complete": self.before_state_coverage_complete,
            "identity_relations": dict(sorted(self.identity_relations.items())),
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "action_applied": self.action_applied,
        }


# --- Candidate normalization -------------------------------------------------


@dataclass(frozen=True)
class TransitionCandidate:
    """Raw proposer output before normalization.

    Kept bounded and separate from `ProposedTransition` so a controller's
    native shape is never mistaken for a verified proposal.
    """

    transition_type: str = ""
    raw: dict = field(default_factory=dict)
    proposer_id: str = ""


class TransitionNormalizationError(ValueError):
    """Raised when normalization would require guessing."""


def normalize_candidate(
    candidate: TransitionCandidate,
    evidence: TransitionSourceEvidence,
    before_state: BeforeStateSnapshot,
    proposal_id: str,
) -> ProposedTransition:
    """Map raw controller output onto a typed proposal.

    Never repairs a dangerous proposal: an unknown type, an unresolvable
    identifier, or a missing safety-relevant field raises rather than
    being guessed into something plausible.
    """
    if candidate.transition_type not in TRANSITION_TYPES:
        raise TransitionNormalizationError(
            f"unknown transition type {candidate.transition_type!r}"
        )
    raw = dict(candidate.raw)
    known_ids = {m.memory_id for m in before_state.memories}
    for key in ("target_ids", "superseded_ids", "forgotten_ids", "preserved_ids"):
        for memory_id in raw.get(key, ()) or ():
            if memory_id not in known_ids:
                raise TransitionNormalizationError(
                    f"{key} references unknown memory {memory_id!r}"
                )
    return ProposedTransition(
        proposal_id=proposal_id,
        transition_type=candidate.transition_type,
        evidence=evidence,
        before_state_digest=before_state.digest(),
        target_ids=tuple(raw.get("target_ids", ()) or ()),
        created=tuple(raw.get("created", ()) or ()),
        superseded_ids=tuple(raw.get("superseded_ids", ()) or ()),
        forgotten_ids=tuple(raw.get("forgotten_ids", ()) or ()),
        preserved_ids=tuple(raw.get("preserved_ids", ()) or ()),
        unchanged_ids=tuple(raw.get("unchanged_ids", ()) or ()),
        lineage_edges=tuple(raw.get("lineage_edges", ()) or ()),
        proposer_id=candidate.proposer_id,
        proposal_source="normalized_candidate",
    )


# --- Verifier ----------------------------------------------------------------

#: Identity relations each mutating/no-op type requires.
_REQUIRED_RELATIONS = {
    # `duplicate_noop` asserts "this duplicates existing experience, so
    # do nothing". Whether the duplicate is exact or semantic is carried
    # by the frozen scoring category, not by the transition type, so both
    # relations satisfy it.
    "duplicate_noop": (
        IdentityRelation.EXACT_DUPLICATE,
        IdentityRelation.SEMANTIC_DUPLICATE,
    ),
    "semantic_duplicate_noop": (
        IdentityRelation.SEMANTIC_DUPLICATE,
        IdentityRelation.EXACT_DUPLICATE,
    ),
    "supersede_existing": (IdentityRelation.CURRENT_STATE_CONFLICT,),
    "scoped_coexistence": (IdentityRelation.SCOPED_COEXISTENCE,),
}

#: Identity relations that prove a proposal is not a durable assertion.
_NON_DURABLE_RELATIONS = {
    IdentityRelation.TEMPORARY_EXCEPTION: (
        TransitionRejectionReason.TEMPORARY_NOT_DURABLE
    ),
    IdentityRelation.HISTORICAL: TransitionRejectionReason.HISTORICAL_NOT_CURRENT,
    IdentityRelation.HYPOTHETICAL: (
        TransitionRejectionReason.HYPOTHETICAL_NOT_ASSERTED
    ),
    IdentityRelation.QUESTION: TransitionRejectionReason.QUESTION_NOT_ASSERTED,
}


class TransitionVerifier:
    """Deterministic, non-mutating before-to-after transition verifier."""

    verifier_id = TRANSITION_VERIFIER_ID
    version = VERIFICATION_VERSION

    def __init__(self, projector: IdentityProjector | None = None):
        self._projector = projector or IdentityProjector()

    def verify(
        self,
        proposal: ProposedTransition,
        before_state: BeforeStateSnapshot,
    ) -> TransitionVerificationResult:
        """Verify a proposal. Pure: mutates neither argument."""
        started = time.perf_counter()
        diagnostics = []
        checks = {}

        def finish(status, reason=None, *, fail_closed=False, projected=None,
                   specs=(), relations=None, eligible=False, elig_reason=""):
            return TransitionVerificationResult(
                proposal_id=proposal.proposal_id,
                transition_type=proposal.transition_type,
                status=status,
                checks=dict(checks),
                rejection_reason=reason,
                diagnostics=tuple(diagnostics),
                projected_after_state=projected,
                action_specs=tuple(specs),
                canonical_effect_eligible=eligible,
                canonical_effect_reason=elig_reason,
                fail_closed=fail_closed,
                before_state_coverage_complete=before_state.coverage_complete,
                identity_relations=dict(relations or {}),
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

        def fail(code, category, status, *, memory_id="", field_ref="", detail="",
                 fail_closed=False):
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category=category, memory_id=memory_id,
                    field_ref=field_ref, detail=detail,
                )
            )
            return finish(status, code, fail_closed=fail_closed)

        # 1. Structure -------------------------------------------------------
        structural = self._check_structure(proposal, before_state)
        checks["structural_valid"] = structural is None
        if structural is not None:
            code, detail, field_ref = structural
            status = (
                TransitionStatus.UNSUPPORTED
                if code == TransitionRejectionReason.UNKNOWN_TRANSITION_TYPE
                else TransitionStatus.STRUCTURALLY_INVALID
            )
            return fail(code, "structure", status, field_ref=field_ref,
                        detail=detail, fail_closed=True)

        # 2. Evidence --------------------------------------------------------
        evidence = proposal.evidence
        checks["evidence_available"] = evidence.available
        checks["evidence_usable"] = evidence.usable
        if not evidence.usable:
            reason = (
                TransitionRejectionReason.GROUNDING_INVALID
                if evidence.evidence_mode == EvidenceMode.GROUNDED_INVALID
                else TransitionRejectionReason.GROUNDING_REQUIRED
            )
            return fail(reason, "grounding", TransitionStatus.REJECTED,
                        detail=f"evidence mode {evidence.evidence_mode}",
                        fail_closed=True)
        checks["grounding_consistent"] = True

        # 3. Source durability ----------------------------------------------
        # A property of the statement, not of any target: a temporary,
        # historical, hypothetical, or question-like source can never
        # justify a durable effect, whatever it names.
        proposed_identity = self._proposed_identity(proposal)
        relations = self._relations(proposal, before_state, proposed_identity)
        durability = self._check_source_durability(proposal, relations)
        if durability is not None:
            code, detail, memory_id = durability
            checks["identity_consistent"] = False
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category="identity", memory_id=memory_id,
                    detail=detail,
                )
            )
            return finish(
                TransitionStatus.REJECTED, code, fail_closed=True,
                relations=relations,
            )

        # 4. Targets ---------------------------------------------------------
        target_outcome = self._check_targets(proposal, before_state, relations)
        checks["targets_valid"] = target_outcome is None
        if target_outcome is not None:
            code, detail, memory_id = target_outcome
            status = (
                TransitionStatus.AMBIGUOUS
                if code == TransitionRejectionReason.TARGET_NOT_UNIQUE
                else TransitionStatus.REJECTED
            )
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category="target", memory_id=memory_id,
                    detail=detail,
                )
            )
            return finish(status, code, fail_closed=True, relations=relations)

        # 5. Identity relation ------------------------------------------------
        identity_outcome = self._check_relation_match(
            proposal, before_state, relations, proposed_identity
        )
        checks["identity_consistent"] = identity_outcome is None
        if identity_outcome is not None:
            code, detail, memory_id = identity_outcome
            status = (
                TransitionStatus.AMBIGUOUS
                if code == TransitionRejectionReason.IDENTITY_AMBIGUOUS
                else TransitionStatus.REJECTED
            )
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category="identity", memory_id=memory_id,
                    detail=detail,
                )
            )
            return finish(status, code, fail_closed=True, relations=relations)

        # 5. Lifecycle legality ---------------------------------------------
        legality = self._check_lifecycle(proposal, before_state)
        checks["lifecycle_legal"] = legality is None
        if legality is not None:
            code, detail, memory_id = legality
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category="lifecycle", memory_id=memory_id,
                    detail=detail,
                )
            )
            return finish(TransitionStatus.REJECTED, code, fail_closed=True,
                          relations=relations)

        # 6. Unsupported changes --------------------------------------------
        unsupported = self._check_supported(proposal, before_state)
        checks["no_unsupported_changes"] = unsupported is None
        if unsupported is not None:
            code, detail, field_ref = unsupported
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category="grounding", field_ref=field_ref,
                    detail=detail,
                )
            )
            return finish(TransitionStatus.REJECTED, code, fail_closed=True,
                          relations=relations)

        # 7. After-state projection -----------------------------------------
        projected = self._project(proposal, before_state)
        mismatch = self._check_after_state(proposal, projected)
        checks["after_state_consistent"] = mismatch is None
        if mismatch is not None:
            diagnostics.append(
                TransitionDiagnostic(
                    code=TransitionRejectionReason.AFTER_STATE_MISMATCH,
                    category="after_state", detail=mismatch,
                )
            )
            return finish(
                TransitionStatus.REJECTED,
                TransitionRejectionReason.AFTER_STATE_MISMATCH,
                fail_closed=True, projected=projected, relations=relations,
            )

        # 8. Preservation ----------------------------------------------------
        preservation = self._check_preservation(
            proposal, before_state, projected, relations
        )
        checks["preservation_safe"] = preservation is None
        if preservation is not None:
            code, detail, memory_id = preservation
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category="preservation", memory_id=memory_id,
                    detail=detail,
                )
            )
            return finish(TransitionStatus.REJECTED, code, fail_closed=True,
                          projected=projected, relations=relations)

        # 9. Lineage ---------------------------------------------------------
        lineage = self._check_lineage(proposal, before_state, relations)
        checks["lineage_valid"] = lineage is None
        if lineage is not None:
            code, detail, memory_id = lineage
            diagnostics.append(
                TransitionDiagnostic(
                    code=code, category="lineage", memory_id=memory_id,
                    detail=detail,
                )
            )
            return finish(TransitionStatus.REJECTED, code, fail_closed=True,
                          projected=projected, relations=relations)

        # 10. Eligibility ----------------------------------------------------
        specs = self._action_specs(proposal)
        eligible, elig_reason = self._eligibility(proposal, before_state)
        checks["canonical_effect_eligible"] = eligible

        if not before_state.coverage_complete:
            diagnostics.append(
                TransitionDiagnostic(
                    code=TransitionRejectionReason.BEFORE_STATE_INCOMPLETE,
                    category="preservation",
                    severity=CheckSeverity.ADVISORY,
                    detail=before_state.coverage_note
                    or "preservation not proven from a partial snapshot",
                )
            )
            return finish(
                TransitionStatus.SHADOW_ONLY, None, projected=projected,
                specs=specs, relations=relations, eligible=False,
                elig_reason=TransitionRejectionReason.BEFORE_STATE_INCOMPLETE,
            )

        diagnostics.append(
            TransitionDiagnostic(
                code="verified", category="summary",
                severity=CheckSeverity.ADVISORY,
                detail=f"{proposal.transition_type} verified against "
                       f"{len(before_state.memories)} snapshot memories",
            )
        )
        return finish(
            TransitionStatus.ACCEPTED, None, projected=projected, specs=specs,
            relations=relations, eligible=eligible, elig_reason=elig_reason,
        )

    # -- checks ------------------------------------------------------------

    def _check_structure(self, proposal, before_state):
        if proposal.transition_type not in TRANSITION_TYPES:
            return (
                TransitionRejectionReason.UNKNOWN_TRANSITION_TYPE,
                f"{proposal.transition_type!r} is not in the frozen taxonomy",
                "transition_type",
            )
        if proposal.proposal_version != PROPOSAL_VERSION:
            return (
                TransitionRejectionReason.UNSUPPORTED_PROPOSAL_VERSION,
                proposal.proposal_version, "proposal_version",
            )
        if not proposal.proposal_id:
            return (
                TransitionRejectionReason.MISSING_PROPOSAL_ID, "", "proposal_id"
            )
        if proposal.evidence is None:
            return (TransitionRejectionReason.MISSING_EVIDENCE, "", "evidence")
        if before_state is None:
            return (
                TransitionRejectionReason.MISSING_BEFORE_STATE, "", "before_state"
            )

        superseded = list(proposal.superseded_ids)
        forgotten = list(proposal.forgotten_ids)
        preserved = set(proposal.preserved_ids)
        for name, ids in (
            ("superseded_ids", superseded), ("forgotten_ids", forgotten),
            ("target_ids", list(proposal.target_ids)),
        ):
            if len(ids) != len(set(ids)):
                return (
                    TransitionRejectionReason.DUPLICATE_TARGET_IDS,
                    f"repeated ids in {name}", name,
                )

        overlap = set(superseded) & set(forgotten)
        if overlap:
            return (
                TransitionRejectionReason.CONTRADICTORY_LIFECYCLE_SETS,
                f"{sorted(overlap)} both superseded and forgotten",
                "superseded_ids",
            )
        # `preserved` means the record survives as visible history — it is
        # compatible with being superseded or forgotten, because
        # ExperienceOS never hard-deletes. `unchanged` is the stronger
        # claim: still active and untouched. Only that one contradicts a
        # deactivation.
        still_active = set(proposal.unchanged_ids)
        both = still_active & (set(superseded) | set(forgotten))
        if both:
            return (
                TransitionRejectionReason.CONTRADICTORY_LIFECYCLE_SETS,
                f"{sorted(both)} both unchanged and deactivated",
                "unchanged_ids",
            )

        created_refs = {c.local_ref for c in proposal.created}
        reused = created_refs & (
            set(superseded) | set(forgotten) | set(proposal.target_ids)
        )
        if reused:
            return (
                TransitionRejectionReason.CREATED_REF_REUSED_AS_TARGET,
                f"{sorted(reused)} used as both created ref and target",
                "created",
            )

        mutates = bool(proposal.created or superseded or forgotten)
        if proposal.transition_type in REJECTION_TYPES and mutates:
            return (
                TransitionRejectionReason.REJECTION_WITH_MUTATION,
                f"{proposal.transition_type} must not mutate", "transition_type",
            )
        if proposal.transition_type in NOOP_TYPES and (
            proposal.created or superseded or forgotten
        ):
            return (
                TransitionRejectionReason.NOOP_WITH_CREATION,
                f"{proposal.transition_type} must not create or deactivate",
                "created",
            )
        if proposal.transition_type == "supersede_existing":
            if not superseded:
                return (
                    TransitionRejectionReason.SUPERSEDE_WITHOUT_REPLACEMENT,
                    "no supersession target", "superseded_ids",
                )
            if not proposal.created:
                return (
                    TransitionRejectionReason.SUPERSEDE_WITHOUT_REPLACEMENT,
                    "supersession without a replacement create", "created",
                )
        if proposal.transition_type == "forget_existing":
            if not forgotten:
                return (
                    TransitionRejectionReason.FORGET_WITHOUT_TARGET, "",
                    "forgotten_ids",
                )
            if proposal.created:
                return (
                    TransitionRejectionReason.FORGET_WITH_CREATION,
                    "a forget directive must not create a positive memory",
                    "created",
                )
        if proposal.transition_type == "scoped_coexistence" and superseded:
            return (
                TransitionRejectionReason.COEXISTENCE_SUPERSEDES_SCOPE,
                "coexistence must not deactivate the existing scoped memory",
                "superseded_ids",
            )
        if proposal.transition_type == "create_new" and (superseded or forgotten):
            return (
                TransitionRejectionReason.CONTRADICTORY_LIFECYCLE_SETS,
                "create_new must not deactivate existing memory",
                "superseded_ids",
            )
        return None

    def _proposed_identity(self, proposal) -> MemoryIdentity | None:
        statement = proposal.evidence.source_statement
        if not statement:
            return None
        kind = proposal.evidence.source_kind or None
        return self._projector.project_text(statement, kind=kind)

    def _relations(self, proposal, before_state, proposed_identity) -> dict:
        if proposed_identity is None:
            return {}
        relations = {}
        for memory in before_state.active():
            existing = before_state.identity_of(memory.memory_id)
            if existing is None:
                continue
            relations[memory.memory_id] = compare_memory_identity(
                existing, proposed_identity
            ).relation
        return relations

    def _check_source_durability(self, proposal, relations):
        """A non-durable source can never justify a durable effect."""
        ttype = proposal.transition_type
        if ttype not in MUTATING_TYPES or ttype == "forget_existing":
            return None
        for memory_id, relation in sorted(relations.items()):
            reason = _NON_DURABLE_RELATIONS.get(relation)
            if reason:
                return (reason, f"source is {relation}", memory_id)
        return None

    def _check_relation_match(self, proposal, before_state, relations, proposed):
        ttype = proposal.transition_type
        if proposed is None:
            return None
        required = _REQUIRED_RELATIONS.get(ttype)
        if not required:
            return None
        targets = (
            set(proposal.target_ids)
            or set(proposal.superseded_ids)
            or {m.memory_id for m in before_state.active()}
        )
        observed = {
            memory_id: relation
            for memory_id, relation in relations.items()
            if memory_id in targets
        }
        if not observed:
            return None
        if any(r == IdentityRelation.AMBIGUOUS for r in observed.values()):
            return (
                TransitionRejectionReason.IDENTITY_AMBIGUOUS,
                "identity comparison is ambiguous", "",
            )
        if not any(r in required for r in observed.values()):
            found = sorted(set(observed.values()))
            return (
                TransitionRejectionReason.IDENTITY_RELATION_MISMATCH,
                f"{ttype} requires {list(required)}, found {found}", "",
            )
        return None

    def _check_targets(self, proposal, before_state, relations):
        targets = tuple(proposal.superseded_ids) + tuple(proposal.forgotten_ids)
        for memory_id in targets:
            memory = before_state.by_id(memory_id)
            if memory is None:
                return (
                    TransitionRejectionReason.TARGET_NOT_FOUND,
                    "target absent from the supplied snapshot", memory_id,
                )
            if memory.status != MemoryStatus.ACTIVE:
                return (
                    TransitionRejectionReason.TARGET_NOT_ACTIVE,
                    f"target status is {memory.status}", memory_id,
                )
            relation = relations.get(memory_id)
            if relation == IdentityRelation.UNRELATED:
                return (
                    TransitionRejectionReason.TARGET_UNRELATED,
                    "target shares no lifecycle identity with the source",
                    memory_id,
                )
            # A forget directive is not a durable assertion, so its
            # identity projection cannot gate an explicitly supplied
            # target: the directive names the target, identity only
            # guards against a confidently unrelated one.
            if proposal.transition_type == "forget_existing":
                continue
            if relation == IdentityRelation.SCOPED_COEXISTENCE:
                return (
                    TransitionRejectionReason.TARGET_SCOPE_INCOMPATIBLE,
                    "target holds a distinct supported scope", memory_id,
                )
            if relation == IdentityRelation.AMBIGUOUS:
                return (
                    TransitionRejectionReason.TARGET_NOT_UNIQUE,
                    "target cannot be resolved unambiguously", memory_id,
                )
        # A supersession must name exactly one predecessor.
        if proposal.transition_type == "supersede_existing" and (
            len(proposal.superseded_ids) > 1
        ):
            return (
                TransitionRejectionReason.TARGET_NOT_UNIQUE,
                f"{len(proposal.superseded_ids)} supersession targets", "",
            )
        return None

    def _check_lifecycle(self, proposal, before_state):
        for memory_id in proposal.superseded_ids:
            memory = before_state.by_id(memory_id)
            if memory and memory.status == MemoryStatus.SUPERSEDED:
                return (
                    TransitionRejectionReason.DOUBLE_SUPERSESSION,
                    "already superseded", memory_id,
                )
            if memory and memory.status == MemoryStatus.FORGOTTEN:
                return (
                    TransitionRejectionReason.REACTIVATION_FORBIDDEN,
                    "a forgotten memory cannot be superseded", memory_id,
                )
        for memory_id in proposal.forgotten_ids:
            memory = before_state.by_id(memory_id)
            if memory and memory.status == MemoryStatus.FORGOTTEN:
                return (
                    TransitionRejectionReason.DOUBLE_FORGET, "already forgotten",
                    memory_id,
                )
        expectation = proposal.expected_after_state
        if expectation:
            for memory_id in expectation.active_ids:
                memory = before_state.by_id(memory_id)
                if memory and memory.status != MemoryStatus.ACTIVE:
                    return (
                        TransitionRejectionReason.REACTIVATION_FORBIDDEN,
                        f"{memory.status} memory expected active again",
                        memory_id,
                    )
        for spec in proposal.created:
            if before_state.by_id(spec.local_ref) is not None:
                return (
                    TransitionRejectionReason.CREATED_REF_REUSED_AS_TARGET,
                    "created ref collides with a durable id", spec.local_ref,
                )
        return None

    def _check_supported(self, proposal, before_state):
        """Every created value and scope must appear in the evidence."""
        statement = (proposal.evidence.source_statement or "").lower()
        if not statement:
            return None
        for spec in proposal.created:
            for term in spec.must_include:
                if term.lower() not in statement:
                    return (
                        TransitionRejectionReason.UNSUPPORTED_CREATED_VALUE,
                        f"{term!r} is not supported by the source statement",
                        spec.local_ref,
                    )
            if spec.scope and spec.scope.lower() not in statement:
                return (
                    TransitionRejectionReason.UNSUPPORTED_SCOPE,
                    f"scope {spec.scope!r} is not supported by the source",
                    spec.local_ref,
                )
            if spec.candidate.kind not in MEMORY_KINDS:
                return (
                    TransitionRejectionReason.UNSUPPORTED_KIND_CHANGE,
                    spec.candidate.kind, spec.local_ref,
                )
        return None

    def _project(self, proposal, before_state) -> ProjectedAfterState:
        """Inert lifecycle projection. Touches no store."""
        active = set(before_state.active_ids())
        superseded = {
            m.memory_id for m in before_state.memories
            if m.status == MemoryStatus.SUPERSEDED
        }
        forgotten = {
            m.memory_id for m in before_state.memories
            if m.status == MemoryStatus.FORGOTTEN
        }
        for memory_id in proposal.superseded_ids:
            active.discard(memory_id)
            superseded.add(memory_id)
        for memory_id in proposal.forgotten_ids:
            active.discard(memory_id)
            forgotten.add(memory_id)
        created_refs = tuple(spec.local_ref for spec in proposal.created)

        # A created memory is projected active; duplicates and stale
        # pairs are counted over the projected active set.
        projected_identities = [
            before_state.identity_of(memory_id)
            for memory_id in sorted(active)
        ]
        created_identities = [
            self._projector.project_text(spec.candidate.text, kind=spec.candidate.kind)
            for spec in proposal.created
        ]
        duplicates, stale = _count_pairs(
            [i for i in projected_identities if i] + created_identities
        )
        return ProjectedAfterState(
            active_ids=frozenset(active) | set(created_refs),
            superseded_ids=frozenset(superseded),
            forgotten_ids=frozenset(forgotten),
            created_refs=created_refs,
            lineage_edges=tuple(proposal.lineage_edges),
            semantic_duplicate_count=duplicates,
            stale_active_count=stale,
        )

    def _check_after_state(self, proposal, projected):
        expectation = proposal.expected_after_state
        if expectation is None:
            return None
        expected_active = set(expectation.active_ids) | set(expectation.created_refs)
        if expected_active and expected_active != set(projected.active_ids):
            missing = sorted(expected_active - set(projected.active_ids))
            extra = sorted(set(projected.active_ids) - expected_active)
            return f"active mismatch; missing={missing} unexpected={extra}"
        if set(expectation.superseded_ids) - set(projected.superseded_ids):
            return "expected superseded memories are not projected superseded"
        if set(expectation.forgotten_ids) - set(projected.forgotten_ids):
            return "expected forgotten memories are not projected forgotten"
        if expectation.no_mutation and (
            projected.created_refs
            or set(proposal.superseded_ids)
            or set(proposal.forgotten_ids)
        ):
            return "no-mutation expected but the proposal mutates"
        return None

    def _check_preservation(self, proposal, before_state, projected, relations):
        deactivated = set(proposal.superseded_ids) | set(proposal.forgotten_ids)

        # Unrelated and distinctly scoped memories must survive intact.
        for memory in before_state.active():
            if memory.memory_id not in deactivated:
                continue
            relation = relations.get(memory.memory_id)
            if relation == IdentityRelation.UNRELATED:
                return (
                    TransitionRejectionReason.UNRELATED_MEMORY_DEACTIVATED,
                    "an unrelated active memory would be deactivated",
                    memory.memory_id,
                )
            if relation == IdentityRelation.SCOPED_COEXISTENCE:
                return (
                    TransitionRejectionReason.SCOPED_MEMORY_LOST,
                    "a compatible scoped memory would be deactivated",
                    memory.memory_id,
                )

        # A preserved memory must still exist somewhere in the projected
        # lifecycle: preservation forbids deletion, not deactivation.
        projected_ids = (
            set(projected.active_ids)
            | set(projected.superseded_ids)
            | set(projected.forgotten_ids)
        )
        for memory_id in proposal.preserved_ids:
            if memory_id not in projected_ids:
                return (
                    TransitionRejectionReason.PRESERVATION_NOT_PROVEN,
                    "memory promised as preserved would not survive",
                    memory_id,
                )

        # An unchanged memory makes the stronger claim: still active.
        for memory_id in proposal.unchanged_ids:
            if memory_id not in projected.active_ids:
                return (
                    TransitionRejectionReason.PRESERVATION_NOT_PROVEN,
                    "memory promised as unchanged is not projected active",
                    memory_id,
                )

        # A rejection or no-op must leave every active memory untouched.
        if proposal.transition_type in NON_MUTATING_TYPES:
            if set(projected.active_ids) != before_state.active_ids():
                return (
                    TransitionRejectionReason.PRESERVATION_NOT_PROVEN,
                    f"{proposal.transition_type} changed the active set", "",
                )
        return None

    def _check_lineage(self, proposal, before_state, relations):
        if proposal.transition_type != "supersede_existing":
            if proposal.lineage_edges and proposal.transition_type in (
                NOOP_TYPES | REJECTION_TYPES
            ):
                return (
                    TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR,
                    f"{proposal.transition_type} must not claim lineage", "",
                )
            return None

        created_refs = {spec.local_ref for spec in proposal.created}
        if not proposal.lineage_edges:
            return (
                TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR,
                "supersession requires a lineage edge", "",
            )
        for predecessor, successor in proposal.lineage_edges:
            if predecessor == successor:
                return (
                    TransitionRejectionReason.LINEAGE_SELF_REFERENCE,
                    "lineage edge points at itself", predecessor,
                )
            if successor not in created_refs:
                return (
                    TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR,
                    "lineage successor is not a created memory", successor,
                )
            memory = before_state.by_id(predecessor)
            if memory is None:
                return (
                    TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR,
                    "predecessor absent from the snapshot", predecessor,
                )
            if memory.status != MemoryStatus.ACTIVE:
                return (
                    TransitionRejectionReason.LINEAGE_INACTIVE_PREDECESSOR,
                    f"predecessor is {memory.status}", predecessor,
                )
            if relations.get(predecessor) == IdentityRelation.UNRELATED:
                return (
                    TransitionRejectionReason.LINEAGE_UNRELATED_PREDECESSOR,
                    "predecessor shares no identity with the replacement",
                    predecessor,
                )
            if predecessor not in proposal.superseded_ids:
                return (
                    TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR,
                    "predecessor is not preserved as superseded", predecessor,
                )
        return None

    def _action_specs(self, proposal) -> tuple:
        specs = []
        for memory_id in sorted(proposal.superseded_ids):
            specs.append(
                VerifiedActionSpec(
                    action="supersede", target_id=memory_id,
                    preconditions=("target_active",),
                )
            )
        for memory_id in sorted(proposal.forgotten_ids):
            specs.append(
                VerifiedActionSpec(
                    action="forget", target_id=memory_id,
                    preconditions=("target_active",),
                )
            )
        for spec in proposal.created:
            specs.append(
                VerifiedActionSpec(
                    action="create", kind=spec.candidate.kind,
                    text=spec.candidate.text, replaces=spec.replaces,
                    local_ref=spec.local_ref,
                    preconditions=("no_active_duplicate",),
                )
            )
        return tuple(specs)

    def _eligibility(self, proposal, before_state) -> tuple:
        if proposal.transition_type in NON_MUTATING_TYPES:
            return False, "transition_type_has_no_canonical_effect"
        if not proposal.evidence.production_grounded:
            return False, "evidence_mode_not_production_grounded"
        if not before_state.coverage_complete:
            return False, TransitionRejectionReason.BEFORE_STATE_INCOMPLETE
        return True, "all_checks_passed"


def _count_pairs(identities) -> tuple:
    """(semantic duplicate pairs, stale conflicting pairs) among actives."""
    duplicates = 0
    stale = 0
    for i, first in enumerate(identities):
        for second in identities[i + 1:]:
            relation = compare_memory_identity(first, second).relation
            if relation in (
                IdentityRelation.EXACT_DUPLICATE,
                IdentityRelation.SEMANTIC_DUPLICATE,
            ):
                duplicates += 1
            elif relation == IdentityRelation.CURRENT_STATE_CONFLICT:
                stale += 1
    return duplicates, stale


_VERIFIER = TransitionVerifier()


def verify_transition(
    proposal: ProposedTransition, before_state: BeforeStateSnapshot
) -> TransitionVerificationResult:
    """Verify one proposed transition. Deterministic and non-mutating."""
    return _VERIFIER.verify(proposal, before_state)
