"""Integration tests for runtime transition authorization.

Exercise the adopted transition path end-to-end through the real
coordinator and engine with the bounded runtime authority configured, and
prove the exact consumers stay authoritative, planner fallback is
preserved on denial, the engine remains the sole mutation boundary, and
non-mutating modes never invoke the authority. Test-only construction —
no canonical composition root is activated here.
"""

from __future__ import annotations

import dataclasses

from experienceos import ExperienceOS
from experienceos.providers import MockProvider
from experienceos.memory.store import MemoryStore
from experienceos.memory.transition_authority import (
    BoundedRuntimeTransitionAuthority,
)
from experienceos.memory.transition_integration import (
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    EvidenceMode, TransitionSourceEvidence, build_before_state,
)
from experienceos.controllers.base import MemorySnapshot
from experienceos.memory.update_intelligence import DeterministicUpdateController


def _agent(**kwargs):
    cfg = TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        runtime_authority=BoundedRuntimeTransitionAuthority(),
        planner_precedence=True, **kwargs)
    return ExperienceOS(model=MockProvider(), transition=cfg)


def _active(agent, uid):
    return [(m.kind, m.text) for m in agent.memories_for_user(uid, status="active")]


def _by_status(agent, uid, status):
    return [m.text for m in agent.memories_for_user(uid, status=status)]


def _last_transition(agent, since):
    events = [e for e in agent.events[since:]
              if e.type == "transition_integration_evaluated"]
    return events[-1].payload if events else None


# -- 10.1 / 10.7 runtime supersede + governed replacement --------------------


def test_runtime_supersede_replaces_without_duplicate():
    agent = _agent()
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    diag = _last_transition(agent, n)
    assert diag["canonical_action_effect"] == "action_replaced"
    assert diag["runtime_authority_checked"] is True
    assert diag["runtime_authorization_receipt_digest"]  # a receipt was issued
    assert diag["replacement"]["applied"] is True
    assert diag["replacement"]["runtime_replacement_receipt_issued"] is True
    coffees = [t for k, t in _active(agent, uid) if "coffee" in t.lower()]
    assert len(coffees) == 1  # planner create was replaced, not appended
    assert any("tea" in t.lower() for t in _by_status(agent, uid, "superseded"))


# -- forget: planner precedence, no duplicate --------------------------------


def test_runtime_forget_defers_to_planner_without_duplicate():
    # The canonical planner already forgets a recognized preference. The
    # transition forget would duplicate it, so the planner-precedence guard
    # defers: the target is forgotten exactly once and nothing is active.
    # (The runtime forget authority itself is proven directly in
    # tests/test_transition_authority.py.)
    agent = _agent()
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s2",
               message="Forget that I prefer tea in the morning.")
    diag = _last_transition(agent, n)
    assert diag["canonical_action_effect"] == "verified_existing_actions"
    assert diag["generated_action_types"] == []
    assert _active(agent, uid) == []
    forgotten = _by_status(agent, uid, "forgotten")
    assert [t for t in forgotten if "tea" in t.lower()]
    # Exactly one forget was applied — the guard prevents a double forget.
    forgets = [e for e in agent.events[n:] if e.type == "memory_forgotten"]
    assert len(forgets) == 1


# -- 10.3 authority denial preserves planner fallback ------------------------


def test_ordinary_create_is_not_a_transition_and_is_preserved():
    agent = _agent()
    uid = "u"
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s1", message="I prefer aisle seats.")
    diag = _last_transition(agent, n)
    # No conflicting memory -> controller abstains -> no adopted effect,
    # planner create preserved.
    assert diag["canonical_action_effect"] not in ("action_added", "action_replaced")
    assert len(_active(agent, uid)) == 1


def test_denied_runtime_authority_preserves_planner_actions():
    # An authority that always denies (empty allowlists) never issues a
    # receipt; the planner create survives, nothing is superseded.
    denying = BoundedRuntimeTransitionAuthority(
        allowed_update_controllers=frozenset(),
        allowed_forget_controllers=frozenset())
    agent = ExperienceOS(model=MockProvider(), transition=TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED, runtime_authority=denying))
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    diag = _last_transition(agent, n)
    assert diag["canonical_action_effect"] == "authorization_denied"
    assert diag["fallback_used"] is True
    # both remain active (planner append), nothing superseded by transition
    assert _by_status(agent, uid, "superseded") == []
    assert len(_active(agent, uid)) == 2


# -- 10.4 exact consumer remains authoritative -------------------------------


class _LyingAuthority:
    """Returns authorized=True with a receipt bound to a different request;
    the exact _authorize must still reject it."""

    def authorize_transition(self, *, coordinator, request, proposal,
                             verification, translation):
        from experienceos.memory.transition_integration import build_authorization
        from experienceos.memory.transition_authority import (
            RuntimeAuthorityDecision,
        )
        other = dataclasses.replace(request, request_id="SOMETHING_ELSE")
        receipt = build_authorization(
            coordinator, other, proposal, verification, translation)
        return RuntimeAuthorityDecision(True, "authorized", receipt=receipt)

    def authorize_replacement(self, plan):
        return None


def test_mismatched_runtime_receipt_is_rejected_by_exact_authorize():
    agent = ExperienceOS(model=MockProvider(), transition=TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED, runtime_authority=_LyingAuthority()))
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    diag = _last_transition(agent, n)
    # Runtime authority "issued" a receipt, but its binding is wrong, so the
    # exact _authorize rejects it -> no canonical transition effect.
    assert diag["canonical_action_effect"] == "authorization_denied"
    assert _by_status(agent, uid, "superseded") == []


# -- 10.5 static + runtime candidates ----------------------------------------


def test_static_receipt_succeeds_even_when_runtime_denies():
    # Build a valid static receipt for the exact case, plus a denying
    # runtime authority; the static candidate still authorizes.
    from experienceos.memory.transition_integration import build_authorization
    stmt = "Actually, I prefer coffee in the morning."
    ev = TransitionSourceEvidence(
        source_statement=stmt, source_event_id="s2:1", session_id="s2",
        evidence_mode=EvidenceMode.GROUNDED_VALID, provenance_ref="user_asserted")
    before = build_before_state([MemorySnapshot(
        memory_id="food.morning_drink", kind="preference",
        text="Prefers tea in the morning.", status="active")], snapshot_source="t")
    res = DeterministicUpdateController().propose(stmt, ev, before)
    coord = TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(mode=TransitionIntegrationMode.ADOPTED))
    req = TransitionIntegrationRequest(
        statement=stmt, evidence=ev, before_state=before, request_id="s2:1",
        user_id="u", existing_actions=())
    tr = translate_transition(res.proposal, res.verification, before)
    receipt = build_authorization(coord, req, res.proposal, res.verification, tr)
    denying = BoundedRuntimeTransitionAuthority(
        allowed_update_controllers=frozenset(),
        allowed_forget_controllers=frozenset())
    # static authorization present + denying runtime authority
    d = coord._authorize(dataclasses.replace(req, authorization=receipt),
                        res.proposal, res.verification, tr, extra_candidate=None)
    assert d.authorized is True  # static candidate still works


# -- 10.6 authority exception containment ------------------------------------


class _ExplodingAuthority:
    def authorize_transition(self, **kwargs):
        raise RuntimeError("boom-secret")

    def authorize_replacement(self, plan):
        raise RuntimeError("boom-secret")


def test_authority_exception_is_contained_no_crash_no_effect():
    agent = ExperienceOS(model=MockProvider(), transition=TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED, runtime_authority=_ExplodingAuthority()))
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    n = len(agent.events)
    # Does not raise:
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    diag = _last_transition(agent, n)
    kinds = [d["code"] for d in diag["diagnostics"]]
    assert "runtime_authority_error" in kinds
    assert diag["canonical_action_effect"] == "authorization_denied"
    # only the exception type name leaked, never the message
    import json
    assert "boom-secret" not in json.dumps(diag)


# -- 10.10 engine sole mutation boundary -------------------------------------


def test_coordinator_and_authority_hold_no_store():
    coord = TransitionIntegrationCoordinator(TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        runtime_authority=BoundedRuntimeTransitionAuthority()))
    for obj in (coord, coord.config.runtime_authority):
        for forbidden in ("memory_store", "store", "_apply_memory_actions",
                          "engine", "experience_manager"):
            assert not hasattr(obj, forbidden)


# -- 10.11 non-mutating modes never invoke the authority ---------------------


class _SpyAuthority:
    def __init__(self):
        self.calls = 0

    def authorize_transition(self, **kwargs):
        self.calls += 1
        from experienceos.memory.transition_authority import RuntimeAuthorityDecision
        return RuntimeAuthorityDecision(False, "spy")

    def authorize_replacement(self, plan):
        self.calls += 1
        return None


def test_non_adopted_modes_never_invoke_runtime_authority():
    for mode in (TransitionIntegrationMode.DISABLED,
                 TransitionIntegrationMode.SHADOW,
                 TransitionIntegrationMode.CANDIDATE,
                 TransitionIntegrationMode.VERIFY_ONLY):
        spy = _SpyAuthority()
        agent = ExperienceOS(model=MockProvider(), transition=TransitionIntegrationConfig(
            mode=mode, runtime_authority=spy))
        uid = "u"
        agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
        agent.chat(user_id=uid, session_id="s2",
                   message="Actually, I prefer coffee in the morning.")
        assert spy.calls == 0, f"authority invoked in {mode}"
        # non-mutating: nothing superseded by the transition path
        assert _by_status(agent, uid, "superseded") == []


def test_adopted_without_runtime_authority_is_unchanged():
    # No runtime authority and no static authorization -> planner-only.
    agent = ExperienceOS(model=MockProvider(), transition=TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED))
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    # missing authorization fails closed -> both active, nothing superseded
    assert _by_status(agent, uid, "superseded") == []


def test_default_config_has_no_runtime_authority():
    cfg = TransitionIntegrationConfig()
    assert cfg.runtime_authority is None
    assert cfg.to_record()["runtime_authority_configured"] is False
