"""Benchmark systems and isolated execution.

Every system receives the same source statement, the same frozen
before-state, the same evidence, and its own isolated in-memory store.
No system run can reach another system's state, and none touches the
demo database or any user data.

Reference levels, in the order §10 of the benchmark contract prefers:

- `full_composition` — the real `hybrid_full_v2` planner stack plus the
  real `ExperienceManager`, the real `ExperienceEngine`, and isolated
  application. This is what the reference actually does to memory, not a
  projection of it.
- `component_only` — planner actions alone, kept for continuity with the
  earlier controller comparisons and labelled as such.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from experienceos import ExperienceOS
from experienceos.memory import ExperienceEntry
from experienceos.memory.identity import (
    IdentityProjector,
    IdentityRelation,
    compare_memory_identity,
)
from experienceos.memory.schema import MemoryStatus
from experienceos.memory.transition_integration import (
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    build_authorization,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    build_before_state,
)
from experienceos.providers import MockProvider

REFERENCE_ID = "experienceos_hybrid_full_v2_reference"
SHADOW_ID = "experienceos_transition_shadow_v1"
CANDIDATE_ID = "experienceos_transition_candidate_v1"
RULES_ID = "experienceos_transition_rules_v1"
ADOPTED_ID = "experienceos_transition_adopted_v1"
LEARNED_ID = "experienceos_transition_learned_shadow_v1"
QWEN_ID = "experienceos_transition_qwen_ceiling_v1"

FULL_COMPOSITION = "full_composition"
COMPONENT_ONLY = "component_only"
PROPOSAL_ONLY = "proposal_only"
UNAVAILABLE = "unavailable"

_PROJECTOR = IdentityProjector()


@dataclass(frozen=True)
class SystemSpec:
    system_id: str
    kind: str
    reference_level: str
    mode: str
    description: str
    available: bool = True
    unavailable_reason: str = ""

    def to_record(self) -> dict:
        return {
            "system_id": self.system_id,
            "kind": self.kind,
            "reference_level": self.reference_level,
            "mode": self.mode,
            "description": self.description,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


def _learned_available() -> tuple:
    """Optional learned path. Never downloads, never installs."""
    return False, "no learned transition controller exists in this repository"


def _qwen_available() -> tuple:
    """Optional live-Qwen ceiling. Never calls the network by default."""
    import os

    if os.environ.get("EXPERIENCEOS_QWEN_API_KEY"):
        return False, "credential present but live-Qwen benchmarking is opt-in only"
    return False, "no credentials configured; live-Qwen path is credential-gated"


def registry() -> tuple:
    learned_ok, learned_reason = _learned_available()
    qwen_ok, qwen_reason = _qwen_available()
    return (
        SystemSpec(
            REFERENCE_ID, "reference", FULL_COMPOSITION, "disabled",
            "canonical hybrid_full_v2 planner stack through the real manager, "
            "engine, and an isolated store; transition integration disabled",
        ),
        SystemSpec(
            SHADOW_ID, "transition", FULL_COMPOSITION, "shadow",
            "canonical composition plus transition shadow: controller and "
            "verifier run, canonical actions untouched",
        ),
        SystemSpec(
            CANDIDATE_ID, "transition", FULL_COMPOSITION, "candidate",
            "canonical composition plus transition candidate: full path "
            "including inert translation, nothing inserted",
        ),
        SystemSpec(
            RULES_ID, "controller", PROPOSAL_ONLY, "shadow",
            "deterministic update controller with forget routing; proposal "
            "quality only, no canonical application",
        ),
        SystemSpec(
            ADOPTED_ID, "transition", FULL_COMPOSITION, "adopted",
            "isolated adopted infrastructure: exact authorization required; "
            "never a default and never canonical",
        ),
        SystemSpec(
            LEARNED_ID, "optional", UNAVAILABLE, "shadow",
            "optional learned transition verifier, shadow-only",
            available=learned_ok, unavailable_reason=learned_reason,
        ),
        SystemSpec(
            QWEN_ID, "optional", UNAVAILABLE, "shadow",
            "optional live-Qwen ceiling, credential-gated",
            available=qwen_ok, unavailable_reason=qwen_reason,
        ),
    )


def canonical_planner():
    """The real hybrid_full_v2 planner stack, constructed offline."""
    from benchmarks.adapters.experienceos_local_v2 import _make_planner_stack

    return _make_planner_stack()


def _seed(record):
    """An isolated agent whose store holds exactly the frozen before-state."""
    agent = ExperienceOS(model=MockProvider(), memory_planner=canonical_planner())
    for memory in record["before_state"]:
        entry = ExperienceEntry(
            user_id="u",
            text=memory.get("canonical_text") or "",
            kind=memory["kind"],
            status=memory["lifecycle_state"],
            source_session_id="benchmark",
        )
        entry.id = memory["memory_ref"]["logical_id"]
        agent.memory_store.add(entry)
    return agent


def _coordinator(mode):
    return TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(mode=mode)
    )


def evidence_for(record, mode=EvidenceMode.GROUNDED_VALID):
    return TransitionSourceEvidence(
        source_statement=record.get("source_statement") or "",
        source_event_id=record["case_id"],
        session_id="benchmark",
        evidence_mode=mode,
        provenance_ref="user_asserted",
    )


@dataclass
class CaseObservation:
    """What actually happened to memory for one system on one case."""

    system_id: str
    reference_level: str
    seeded_ids: tuple = ()
    active_ids: tuple = ()
    superseded_ids: tuple = ()
    forgotten_ids: tuple = ()
    created_count: int = 0
    semantic_duplicate_pairs: int = 0
    stale_active_pairs: int = 0
    annotation: dict | None = None
    proposal_type: str | None = None
    proposal_targets: tuple = ()
    verifier_status: str | None = None
    authorization: str | None = None
    action_applied: bool = False
    latency_ms: float = 0.0
    error: str | None = None
    # What the transition proposal *would* produce if it alone governed
    # the state. Distinct from `active_ids`, which is what actually
    # happened. Non-mutating modes leave the two deliberately different.
    projected_active: tuple = ()
    projected_duplicate_pairs: int = 0
    projected_stale_pairs: int = 0
    projected_available: bool = False

    def to_record(self) -> dict:
        return {
            "system_id": self.system_id,
            "reference_level": self.reference_level,
            "active_ids": sorted(self.active_ids),
            "superseded_ids": sorted(self.superseded_ids),
            "forgotten_ids": sorted(self.forgotten_ids),
            "created_count": self.created_count,
            "semantic_duplicate_pairs": self.semantic_duplicate_pairs,
            "stale_active_pairs": self.stale_active_pairs,
            "proposal_type": self.proposal_type,
            "proposal_targets": sorted(self.proposal_targets),
            "verifier_status": self.verifier_status,
            "authorization": self.authorization,
            "action_applied": self.action_applied,
            "projected_active": sorted(self.projected_active),
            "projected_duplicate_pairs": self.projected_duplicate_pairs,
            "projected_stale_pairs": self.projected_stale_pairs,
            "projected_available": self.projected_available,
            "annotation": self.annotation,
            "error": self.error,
        }


def _pairs(entries) -> tuple:
    """(semantic duplicate pairs, stale conflicting pairs) among actives."""
    identities = [
        _PROJECTOR.project_text(e.text, kind=e.kind) for e in entries
    ]
    duplicates = stale = 0
    for index, first in enumerate(identities):
        for second in identities[index + 1:]:
            relation = compare_memory_identity(first, second).relation
            if relation in (
                IdentityRelation.EXACT_DUPLICATE,
                IdentityRelation.SEMANTIC_DUPLICATE,
            ):
                duplicates += 1
            elif relation == IdentityRelation.CURRENT_STATE_CONFLICT:
                stale += 1
    return duplicates, stale


def _stable_ids(entries, seeded) -> dict:
    """Map runtime UUIDs to stable labels by store order.

    A created memory gets a fresh UUID every run, which would make the
    committed artifacts differ byte-for-byte while describing identical
    behavior. Store order is deterministic, so first-seen order gives a
    stable label — the same convention the suite's digest normalization
    already uses.
    """
    mapping = {}
    index = 0
    for entry in entries:
        if entry.id in seeded:
            mapping[entry.id] = entry.id
        else:
            mapping[entry.id] = f"created:{index}"
            index += 1
    return mapping


def _observe(agent, record, system, annotation=None, latency=0.0):
    seeded = {m["memory_ref"]["logical_id"] for m in record["before_state"]}
    entries = agent.memory_store.list_memories(user_id="u")
    stable = _stable_ids(entries, seeded)
    active = [e for e in entries if e.status == MemoryStatus.ACTIVE]
    duplicates, stale = _pairs(active)
    return CaseObservation(
        system_id=system.system_id,
        reference_level=system.reference_level,
        seeded_ids=tuple(sorted(seeded)),
        active_ids=tuple(stable[e.id] for e in active),
        superseded_ids=tuple(
            stable[e.id] for e in entries if e.status == MemoryStatus.SUPERSEDED
        ),
        forgotten_ids=tuple(
            stable[e.id] for e in entries if e.status == MemoryStatus.FORGOTTEN
        ),
        created_count=sum(1 for e in entries if e.id not in seeded),
        semantic_duplicate_pairs=duplicates,
        stale_active_pairs=stale,
        annotation=annotation,
        proposal_type=(annotation or {}).get("transition_type"),
        proposal_targets=tuple((annotation or {}).get("target_ids") or ()),
        verifier_status=(annotation or {}).get("verifier_status"),
        authorization=(
            ((annotation or {}).get("authorization") or {}).get("authorized")
            if (annotation or {}).get("authorization") is not None
            else None
        ),
        action_applied=bool((annotation or {}).get("action_applied")),
        latency_ms=latency,
    )


def project_transition_state(record, proposal) -> tuple:
    """The state the transition proposal alone would produce.

    Deterministic and inert: it applies the proposal's deactivations to
    the frozen before-state and adds the created text, then counts
    duplicate and stale pairs over the result. Nothing is stored.
    """
    if proposal is None:
        return (), 0, 0, False
    deactivated = set(proposal.superseded_ids) | set(proposal.forgotten_ids)
    survivors = [
        _entry_from(memory)
        for memory in record["before_state"]
        if memory["lifecycle_state"] == MemoryStatus.ACTIVE
        and memory["memory_ref"]["logical_id"] not in deactivated
    ]
    for index, spec in enumerate(proposal.created):
        created = ExperienceEntry(
            user_id="u", text=spec.candidate.text, kind=spec.candidate.kind
        )
        created.id = f"created:{index}"
        survivors.append(created)
    duplicates, stale = _pairs(survivors)
    return tuple(e.id for e in survivors), duplicates, stale, True


def _last_annotation(agent):
    events = [
        e for e in agent.event_bus.history()
        if e.type == "transition_integration_evaluated"
    ]
    return events[-1].payload if events else None


def run_case(system: SystemSpec, record) -> CaseObservation:
    """Run one system on one case against an isolated seeded store."""
    statement = record.get("source_statement") or ""
    if system.system_id == RULES_ID:
        return _run_rules(system, record, statement)
    if system.system_id == ADOPTED_ID:
        return _run_adopted(system, record, statement)

    agent = _seed(record)
    if system.mode != "disabled":
        agent.engine.transition_coordinator = _coordinator(system.mode)
    started = time.perf_counter()
    agent.chat("u", "benchmark", statement)
    elapsed = (time.perf_counter() - started) * 1000.0
    observation = _observe(agent, record, system, _last_annotation(agent), elapsed)
    if system.mode in ("shadow", "candidate"):
        # A non-mutating mode leaves state identical to the reference by
        # design, so what it *would* do has to be measured separately.
        proposal = _standalone_proposal(record, statement)
        (
            observation.projected_active,
            observation.projected_duplicate_pairs,
            observation.projected_stale_pairs,
            observation.projected_available,
        ) = project_transition_state(record, proposal)
    return observation


def _standalone_proposal(record, statement):
    """The proposal the coordinator produces, without touching a store."""
    from experienceos.memory.transition_integration import (
        TransitionIntegrationRequest,
    )

    before = build_before_state(
        [_entry_from(m) for m in record["before_state"]], user_id="u"
    )
    request = TransitionIntegrationRequest(
        statement=statement, evidence=evidence_for(record),
        before_state=before, request_id=record["case_id"], user_id="u",
    )
    result = _coordinator(TransitionIntegrationMode.CANDIDATE).evaluate(request)
    return result.proposal


def _run_rules(system, record, statement):
    """Proposal quality only: the controller never touches a store."""
    from experienceos.memory.update_intelligence import AbstentionReason

    coordinator = _coordinator(TransitionIntegrationMode.SHADOW)
    before = build_before_state(
        [
            _entry_from(memory)
            for memory in record["before_state"]
        ],
        user_id="u",
    )
    from experienceos.memory.transition_integration import (
        TransitionIntegrationRequest,
    )

    request = TransitionIntegrationRequest(
        statement=statement, evidence=evidence_for(record),
        before_state=before, request_id=record["case_id"], user_id="u",
    )
    started = time.perf_counter()
    result = coordinator.evaluate(request)
    elapsed = (time.perf_counter() - started) * 1000.0
    del AbstentionReason
    projected = project_transition_state(record, result.proposal)
    return CaseObservation(
        system_id=system.system_id,
        reference_level=system.reference_level,
        seeded_ids=tuple(sorted(m.memory_id for m in before.memories)),
        active_ids=tuple(m.memory_id for m in before.active()),
        annotation=result.to_record(),
        proposal_type=result.transition_type,
        proposal_targets=tuple(
            (getattr(result.proposal, "superseded_ids", ()) or ())
            + (getattr(result.proposal, "forgotten_ids", ()) or ())
        ),
        verifier_status=getattr(result.verification, "status", None),
        action_applied=False,
        latency_ms=elapsed,
        projected_active=projected[0],
        projected_duplicate_pairs=projected[1],
        projected_stale_pairs=projected[2],
        projected_available=projected[3],
    )


def _entry_from(memory):
    entry = ExperienceEntry(
        user_id="u",
        text=memory.get("canonical_text") or "",
        kind=memory["kind"],
        status=memory["lifecycle_state"],
    )
    entry.id = memory["memory_ref"]["logical_id"]
    return entry


def _run_adopted(system, record, statement):
    """Isolated adopted infrastructure.

    Two passes, exactly as an operator would: verify the proposal first,
    then authorize *that* proposal. The coordinator never authorizes
    itself — the authorization is built outside it and must match every
    bound field. Both passes are seeded identically and deterministic, so
    the binding computed in pass one is the binding pass two produces.
    """
    probe = _seed(record)
    probe_coordinator = _coordinator(TransitionIntegrationMode.CANDIDATE)
    probe.engine.transition_coordinator = probe_coordinator
    probe.chat("u", "benchmark", statement)
    annotation = _last_annotation(probe)
    if not annotation or annotation.get("canonical_effect_eligible") is not True:
        # Nothing eligible to authorize: adopted behaves as candidate.
        agent = _seed(record)
        agent.engine.transition_coordinator = _coordinator(
            TransitionIntegrationMode.ADOPTED
        )
        started = time.perf_counter()
        agent.chat("u", "benchmark", statement)
        elapsed = (time.perf_counter() - started) * 1000.0
        return _observe(agent, record, system, _last_annotation(agent), elapsed)

    authorization = _authorization_for(record, statement)
    agent = _seed(record)
    agent.engine.transition_coordinator = TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(
            mode=TransitionIntegrationMode.ADOPTED,
            authorizations=(authorization,) if authorization else (),
        )
    )
    started = time.perf_counter()
    agent.chat("u", "benchmark", statement)
    elapsed = (time.perf_counter() - started) * 1000.0
    return _observe(agent, record, system, _last_annotation(agent), elapsed)


def _authorization_for(record, statement):
    """Build the exact authorization the engine's request will produce.

    Rebuilds the engine's own request identity (`session:history_length`)
    and before-state, then binds every field to the real proposal.
    """
    from experienceos.memory.transition_integration import (
        TransitionIntegrationRequest,
    )

    agent = _seed(record)
    coordinator = _coordinator(TransitionIntegrationMode.ADOPTED)
    # The engine builds its request id from the event history length at
    # the hook. Replay the same interaction to learn it.
    probe = _seed(record)
    probe.engine.transition_coordinator = _coordinator(
        TransitionIntegrationMode.SHADOW
    )
    probe.chat("u", "benchmark", statement)
    events = probe.event_bus.history()
    index = next(
        (
            i for i, e in enumerate(events)
            if e.type == "transition_integration_evaluated"
        ),
        None,
    )
    if index is None:
        return None
    # The hook runs before the planned/integration events are emitted.
    request_id = f"benchmark:{_hook_history_length(events)}"
    before = build_before_state(
        [_entry_from(m) for m in record["before_state"]], user_id="u"
    )
    request = TransitionIntegrationRequest(
        statement=statement,
        evidence=TransitionSourceEvidence(
            source_statement=statement,
            source_event_id=request_id,
            session_id="benchmark",
            evidence_mode=EvidenceMode.GROUNDED_VALID,
            provenance_ref="user_asserted",
        ),
        before_state=before,
        request_id=request_id,
        user_id="u",
    )
    route, controller_result = coordinator._route(request)
    proposal = getattr(controller_result, "proposal", None)
    verification = getattr(controller_result, "verification", None)
    if proposal is None or verification is None or not verification.accepted:
        return None
    translation = translate_transition(proposal, verification, before)
    if not translation.succeeded or not translation.actions:
        return None
    del agent, route
    return build_authorization(
        coordinator, request, proposal, verification, translation
    )


def _hook_history_length(events) -> int:
    """Event history length at the moment the engine's hook ran.

    The hook is reached after context and before the planned-action
    event, so its request id counts exactly the events emitted up to
    that point.
    """
    for index, event in enumerate(events):
        if event.type == "memory_action_planned":
            return index
    return len(events)
