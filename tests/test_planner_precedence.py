"""Planner-precedence exact-match behavior for canonical transitions.

Planner precedence exists because the canonical planner and the
transition machinery can both perform the same lifecycle transition. When
the planner already performs a *well-formed* transition for the exact same
target, the coordinator defers; otherwise the verified runtime transition
still acts. This suite proves the matching is exact (target and transition
class), that a malformed planner batch never suppresses a verified
transition, that the create-only conflict cases still act, and that the
policy is off by default outside the canonical composition.
"""

from __future__ import annotations

from experienceos.controllers.base import MemorySnapshot
from experienceos.memory.planner import CREATE, FORGET, SUPERSEDE, MemoryAction
from experienceos.memory.transition_authority import (
    BoundedRuntimeTransitionAuthority,
)
from experienceos.memory.transition_integration import (
    CanonicalActionEffect,
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    build_before_state,
)
from experienceos.memory.update_intelligence import DeterministicUpdateController
from experienceos.memory.forget_intelligence import DeterministicForgetController

from experienceos import ExperienceOS
from experienceos.providers import MockProvider
from experienceos.memory import InMemoryMemoryStore
from demo.support import build_canonical_transition_config


# -- coordinator-level exact matching ----------------------------------------


def _supersede_case(precedence: bool):
    stmt = "Actually, I prefer coffee in the morning."
    ev = TransitionSourceEvidence(
        source_statement=stmt, source_event_id="e", session_id="s",
        evidence_mode=EvidenceMode.GROUNDED_VALID, provenance_ref="user_asserted")
    before = build_before_state([MemorySnapshot(
        memory_id="food.morning_drink", kind="preference",
        text="Prefers tea in the morning.", status="active")], snapshot_source="t")
    res = DeterministicUpdateController().propose(stmt, ev, before)
    coord = TransitionIntegrationCoordinator(TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        runtime_authority=BoundedRuntimeTransitionAuthority(),
        planner_precedence=precedence))
    target = res.proposal.superseded_ids[0]
    return coord, stmt, ev, before, target


def _effect(coord, stmt, ev, before, existing):
    req = TransitionIntegrationRequest(
        statement=stmt, evidence=ev, before_state=before,
        request_id="r", user_id="u", existing_actions=tuple(existing))
    return coord.evaluate(req).canonical_action_effect


def test_well_formed_planner_supersede_same_target_defers():
    coord, stmt, ev, before, target = _supersede_case(precedence=True)
    existing = (
        MemoryAction(action=SUPERSEDE, memory_id=target),
        MemoryAction(action=CREATE, kind="preference",
                     text="Prefers coffee.", replaces=target),
    )
    assert _effect(coord, stmt, ev, before, existing) == (
        CanonicalActionEffect.VERIFIED_EXISTING_ACTIONS)


def test_malformed_planner_supersede_does_not_suppress_verified_transition():
    # supersede(target) + create replacing a DIFFERENT id: broken lineage.
    coord, stmt, ev, before, target = _supersede_case(precedence=True)
    existing = (
        MemoryAction(action=SUPERSEDE, memory_id=target),
        MemoryAction(action=CREATE, kind="preference",
                     text="junk", replaces="SOMETHING_ELSE"),
    )
    assert _effect(coord, stmt, ev, before, existing) == (
        CanonicalActionEffect.ACTION_ADDED)


def test_planner_supersede_of_different_target_does_not_defer():
    coord, stmt, ev, before, target = _supersede_case(precedence=True)
    existing = (
        MemoryAction(action=SUPERSEDE, memory_id="unrelated.id"),
        MemoryAction(action=CREATE, kind="preference",
                     text="x", replaces="unrelated.id"),
    )
    assert _effect(coord, stmt, ev, before, existing) == (
        CanonicalActionEffect.ACTION_ADDED)


def test_create_only_planner_lets_transition_act():
    coord, stmt, ev, before, target = _supersede_case(precedence=True)
    existing = (MemoryAction(action=CREATE, kind="preference", text="Prefers coffee."),)
    assert _effect(coord, stmt, ev, before, existing) == (
        CanonicalActionEffect.ACTION_ADDED)


def test_precedence_off_by_default_never_defers():
    coord, stmt, ev, before, target = _supersede_case(precedence=False)
    existing = (
        MemoryAction(action=SUPERSEDE, memory_id=target),
        MemoryAction(action=CREATE, kind="preference",
                     text="Prefers coffee.", replaces=target),
    )
    # With precedence off, the coordinator runs the raw mechanism, not the
    # verified_existing_actions deferral.
    assert _effect(coord, stmt, ev, before, existing) != (
        CanonicalActionEffect.VERIFIED_EXISTING_ACTIONS)


def test_forget_precedence_defers_only_for_same_target():
    stmt = "Forget that I prefer studying in the evening."
    ev = TransitionSourceEvidence(
        source_statement=stmt, source_event_id="e", session_id="s",
        evidence_mode=EvidenceMode.GROUNDED_VALID, provenance_ref="user_asserted")
    before = build_before_state([MemorySnapshot(
        memory_id="study.time_of_day", kind="preference",
        text="Prefers studying in the evening.", status="active")],
        snapshot_source="t")
    res = DeterministicForgetController().propose(stmt, ev, before)
    target = res.proposal.forgotten_ids[0]
    coord = TransitionIntegrationCoordinator(TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        runtime_authority=BoundedRuntimeTransitionAuthority(),
        planner_precedence=True))
    same = (MemoryAction(action=FORGET, memory_id=target),)
    assert _effect(coord, stmt, ev, before, same) == (
        CanonicalActionEffect.VERIFIED_EXISTING_ACTIONS)
    other = (MemoryAction(action=FORGET, memory_id="unrelated.id"),)
    assert _effect(coord, stmt, ev, before, other) != (
        CanonicalActionEffect.VERIFIED_EXISTING_ACTIONS)


# -- end-to-end through the canonical composition ----------------------------


def _agent():
    return ExperienceOS(model=MockProvider(), memory_store=InMemoryMemoryStore(),
                        transition=build_canonical_transition_config())


GENUINE = [
    ("I prefer tea in the morning.",
     "Actually, I prefer coffee in the morning.", "tea", "coffee"),
    ("I prefer dark mode in my code editor.",
     "Switch that — I prefer light mode in my editor now.", "dark", "light"),
    ("My phone is a Pixel 6.",
     "I upgraded — my phone is a Pixel 9 now.", "pixel 6", "pixel 9"),
]


def test_genuine_create_only_conflicts_still_transition():
    import pytest
    for setup, update, old, new in GENUINE:
        agent = _agent()
        uid = "u"
        agent.chat(user_id=uid, session_id="s1", message=setup)
        agent.chat(user_id=uid, session_id="s2", message=update)
        active = [m.text.lower() for m in agent.memories_for_user(uid)]
        superseded = [m.text.lower() for m in agent.memories_for_user(uid, status="superseded")]
        assert len(active) == 1 and new in active[0]
        assert any(old in t for t in superseded)


def test_keyed_update_defers_to_planner_normalized_text():
    # Seat preference is a keyed domain the planner handles: precedence
    # keeps the planner's normalized create text and a single supersede.
    agent = _agent()
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer aisle seats.")
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s2", message="Actually, I prefer window seats now.")
    active = [m.text for m in agent.memories_for_user(uid)]
    assert active == ["Prefers window seats."]  # normalized, not raw
    supersedes = [e for e in agent.events[n:] if e.type == "memory_superseded"]
    assert len(supersedes) == 1  # no double supersede
