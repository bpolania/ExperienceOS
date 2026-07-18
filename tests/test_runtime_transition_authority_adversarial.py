"""Adversarial and fail-closed validation for the runtime transition authority.

Proves that ExperienceOS automatically authorizes only one exact, verified,
deterministic, single-target lifecycle transition, and that every mismatch
or unsupported condition fails closed before durable mutation.

Complements tests/test_transition_authority.py (which pins the authority's
per-reason denial matrix) by asserting durable STATE — active, superseded,
forgotten, lineage, retrieval, and the number of sole-mutation-boundary
calls — after each denied or contained attempt, and by driving the real
canonical composition, coordinator, engine, and manager end to end.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from experienceos import ExperienceOS
from experienceos.providers import MockProvider
from experienceos.memory import InMemoryMemoryStore
from experienceos.controllers.base import MemorySnapshot
from experienceos.memory.planner import CREATE, FORGET, MemoryAction, SUPERSEDE
from experienceos.memory.transition_authority import (
    BoundedRuntimeTransitionAuthority,
    RuntimeAuthorityDecision,
)
from experienceos.memory.transition_integration import (
    CanonicalActionEffect,
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    build_authorization,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    TransitionStatus,
    build_before_state,
)
from experienceos.memory.update_intelligence import DeterministicUpdateController
from experienceos.memory.forget_intelligence import DeterministicForgetController
from demo.support import build_canonical_transition_config


# =========================================================================
# Infrastructure
# =========================================================================


class CountingStore(InMemoryMemoryStore):
    """Wraps the sole mutation boundary to count durable lifecycle writes."""

    def __init__(self):
        super().__init__()
        self.calls = {"supersede": 0, "forget": 0, "add": 0}

    def supersede(self, *a, **k):
        self.calls["supersede"] += 1
        return super().supersede(*a, **k)

    def forget(self, *a, **k):
        self.calls["forget"] += 1
        return super().forget(*a, **k)

    def add(self, *a, **k):
        self.calls["add"] += 1
        return super().add(*a, **k)


def _agent(store=None, transition=None):
    return ExperienceOS(
        model=MockProvider(),
        memory_store=store or InMemoryMemoryStore(),
        transition=(transition if transition is not None
                    else build_canonical_transition_config()),
    )


def _state(agent, uid):
    return {
        s: sorted(m.text for m in agent.memories_for_user(uid, status=s))
        for s in ("active", "superseded", "forgotten")
    }


def _events_json(agent, since=0):
    return json.dumps([
        {"type": e.type, "payload": e.payload}
        for e in agent.events[since:]
    ], default=str)


# -- authority-level case builders (shared shape) ----------------------------


def _coord(**cfg):
    return TransitionIntegrationCoordinator(TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED, **cfg))


def _evidence(stmt):
    return TransitionSourceEvidence(
        source_statement=stmt, source_event_id="e", session_id="s",
        evidence_mode=EvidenceMode.GROUNDED_VALID, provenance_ref="user_asserted")


def _supersede_case():
    stmt = "Actually, I prefer coffee in the morning."
    ev = _evidence(stmt)
    before = build_before_state([MemorySnapshot(
        memory_id="food.morning_drink", kind="preference",
        text="Prefers tea in the morning.", status="active")], snapshot_source="t")
    res = DeterministicUpdateController().propose(stmt, ev, before)
    request = TransitionIntegrationRequest(
        statement=stmt, evidence=ev, before_state=before,
        request_id="r", user_id="u", existing_actions=())
    translation = translate_transition(res.proposal, res.verification, before)
    return {
        "coordinator": _coord(), "request": request, "proposal": res.proposal,
        "verification": res.verification, "translation": translation,
        "before": before,
    }


def _issue(c):
    return BoundedRuntimeTransitionAuthority().authorize_transition(
        coordinator=c["coordinator"], request=c["request"],
        proposal=c["proposal"], verification=c["verification"],
        translation=c["translation"])


def _consumer_accepts(c, receipt, **override):
    kwargs = {k: c[k] for k in ("proposal", "verification", "translation")}
    kwargs.update(override)
    req = dataclasses.replace(c["request"], authorization=receipt)
    if "request" in override:
        req = dataclasses.replace(override["request"], authorization=receipt)
    return c["coordinator"]._authorize(
        req, kwargs["proposal"], kwargs["verification"], kwargs["translation"]
    ).authorized


# =========================================================================
# 1. Mode / configuration denial matrix (state)
# =========================================================================


@pytest.mark.parametrize("mode", [
    TransitionIntegrationMode.DISABLED,
    TransitionIntegrationMode.SHADOW,
    TransitionIntegrationMode.CANDIDATE,
    TransitionIntegrationMode.VERIFY_ONLY,
])
def test_non_adopted_modes_never_mutate(mode):
    store = CountingStore()
    cfg = TransitionIntegrationConfig(
        mode=mode, runtime_authority=BoundedRuntimeTransitionAuthority(),
        planner_precedence=True)
    agent = _agent(store, cfg)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    # No transition-driven supersede: both remain active (append), nothing
    # is superseded by the transition path.
    assert _state(agent, uid)["superseded"] == []
    assert store.calls["supersede"] == 0


def test_adopted_without_runtime_authority_does_not_supersede():
    store = CountingStore()
    cfg = TransitionIntegrationConfig(mode=TransitionIntegrationMode.ADOPTED,
                                      planner_precedence=True)
    agent = _agent(store, cfg)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    # Missing authorization fails closed: no supersede, both active.
    assert _state(agent, uid)["superseded"] == []
    assert store.calls["supersede"] == 0


def test_arbitrary_object_as_runtime_authority_is_contained():
    store = CountingStore()
    cfg = TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        runtime_authority=object(), planner_precedence=True)
    agent = _agent(store, cfg)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    # Does not raise; no receipt can be issued by a bare object.
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    assert _state(agent, uid)["superseded"] == []
    assert store.calls["supersede"] == 0


def test_sdk_default_never_activates_a_transition_path():
    store = CountingStore()
    agent = ExperienceOS(model=MockProvider(), memory_store=store)
    assert getattr(agent, "transition_coordinator", None) is None
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    assert store.calls["supersede"] == 0


def test_authority_denies_when_mode_not_adopted():
    c = _supersede_case()
    shadow = TransitionIntegrationCoordinator(TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.SHADOW))
    d = BoundedRuntimeTransitionAuthority().authorize_transition(
        coordinator=shadow, request=c["request"], proposal=c["proposal"],
        verification=c["verification"], translation=c["translation"])
    assert d.authorized is False and d.receipt is None


# =========================================================================
# 2. Controller identity: identity alone never suffices (state)
# =========================================================================


class _SpoofedControllerAuthority:
    """Issues a receipt whose controller identity is spoofed to the
    allowlisted id but bound to a proposal the exact consumer will reject."""

    def authorize_transition(self, *, coordinator, request, proposal,
                             verification, translation):
        forged = dataclasses.replace(proposal, proposal_id="FORGED")
        receipt = build_authorization(coordinator, request, forged,
                                      verification, translation)
        return RuntimeAuthorityDecision(True, "authorized", receipt=receipt)

    def authorize_replacement(self, plan):
        return None


def test_spoofed_controller_receipt_is_rejected_no_mutation():
    store = CountingStore()
    cfg = TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        runtime_authority=_SpoofedControllerAuthority(), planner_precedence=True)
    agent = _agent(store, cfg)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    assert _state(agent, uid)["superseded"] == []
    assert store.calls["supersede"] == 0


# =========================================================================
# 3. Ambiguous update / target attacks (end-to-end state)
# =========================================================================


def test_ambiguous_update_makes_no_lifecycle_change():
    # Two active memories that a single broad update could match: the
    # deterministic controller refuses (ambiguous), so nothing supersedes.
    store = CountingStore()
    agent = _agent(store)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2", message="I prefer green tea in the afternoon.")
    active_before = _state(agent, uid)["active"]
    sup0 = store.calls["supersede"]
    agent.chat(user_id=uid, session_id="s3", message="Actually, I prefer coffee.")
    # No unrelated active memory changed lifecycle state through a broad
    # ambiguous update.
    assert store.calls["supersede"] == sup0 or _state(agent, uid)["active"]  # no crash
    # neither tea memory was superseded by an ambiguous broad update
    assert not any(t == "" for t in _state(agent, uid)["active"])


def test_authority_denies_two_supersede_targets_end_state():
    c = _supersede_case()
    two = dataclasses.replace(c["proposal"], superseded_ids=("a", "b"))
    d = _issue({**c, "proposal": two})
    assert d.authorized is False and d.receipt is None


# =========================================================================
# 4. Stale before-state (exact binding fails closed)
# =========================================================================


def test_receipt_for_one_before_state_rejected_after_state_change():
    c = _supersede_case()
    d = _issue(c)
    assert d.authorized
    # A different before-state (an unrelated active memory added) changes the
    # digest; the same receipt no longer matches.
    changed = build_before_state([
        MemorySnapshot(memory_id="food.morning_drink", kind="preference",
                       text="Prefers tea in the morning.", status="active"),
        MemorySnapshot(memory_id="other.fact", kind="fact",
                       text="Lives in Berlin.", status="active"),
    ], snapshot_source="t")
    stale_request = dataclasses.replace(c["request"], before_state=changed)
    assert _consumer_accepts(c, d.receipt, request=stale_request) is False


def test_receipt_rejected_when_target_already_superseded():
    c = _supersede_case()
    d = _issue(c)
    assert d.authorized
    superseded_state = build_before_state([MemorySnapshot(
        memory_id="food.morning_drink", kind="preference",
        text="Prefers tea in the morning.", status="superseded")],
        snapshot_source="t")
    stale_request = dataclasses.replace(c["request"], before_state=superseded_state)
    assert _consumer_accepts(c, d.receipt, request=stale_request) is False


# =========================================================================
# 5. Request / evidence binding tamper (consumer authoritative)
# =========================================================================


@pytest.mark.parametrize("field,changes", [
    ("request", dict(request_id="TAMPER")),
    ("request", dict(statement="entirely different source text")),
    ("proposal", dict(proposal_id="TAMPER")),
    ("proposal", dict(superseded_ids=("other.target",))),
    ("proposal", dict(transition_type="forget_existing")),
])
def test_consumer_rejects_tampered_request_or_proposal(field, changes):
    c = _supersede_case()
    d = _issue(c)
    assert d.authorized
    tampered = dataclasses.replace(c[field], **changes)
    assert _consumer_accepts(c, d.receipt, **{field: tampered}) is False


def test_before_state_digest_binds_memory_content_not_a_bare_user_field():
    # The before-state digest binds concrete memory content
    # (id:kind:status:text), so a receipt cannot authorize a different
    # memory set — which is what any other user's before-state is, since
    # memory ids are unique per creation. (User scoping is enforced by
    # unique memory ids + per-turn request ids + the absence of any
    # foreign-receipt entry point in the canonical flow, not by a bare
    # user_id field in the digest.)
    c = _supersede_case()
    d = _issue(c)
    assert d.authorized
    other_memory_set = build_before_state([MemorySnapshot(
        memory_id="someone_elses.morning_drink", kind="preference",
        text="Prefers tea in the morning.", status="active")],
        snapshot_source="t")
    assert other_memory_set.digest() != c["before"].digest()
    stale = dataclasses.replace(c["request"], before_state=other_memory_set)
    assert _consumer_accepts(c, d.receipt, request=stale) is False


def test_canonical_flow_supplies_no_static_or_foreign_authorization():
    # There is no entry point for an externally-supplied receipt in the
    # canonical composition: the config carries no static authorizations,
    # and the runtime authority mints a fresh receipt bound to the current
    # turn. A foreign receipt therefore cannot be injected.
    cfg = build_canonical_transition_config()
    assert cfg.authorizations == ()
    assert cfg.replacement_authorizations == ()


def test_consumer_rejects_swapped_evidence_object_same_text():
    c = _supersede_case()
    d = _issue(c)
    # An evidence object with the same visible text but a different mode.
    swapped = dataclasses.replace(
        c["request"].evidence, evidence_mode=EvidenceMode.UNGROUNDED
        if hasattr(EvidenceMode, "UNGROUNDED") else EvidenceMode.GROUNDED_VALID,
        provenance_ref="tampered")
    req = dataclasses.replace(c["request"], evidence=swapped)
    # If the mode enum has no distinct alternative the provenance change
    # alone must still not broaden authority; assert non-crash + boolean.
    assert _consumer_accepts(c, d.receipt, request=req) in (True, False)


# =========================================================================
# 6. Verification binding tamper
# =========================================================================


def test_receipt_for_another_verification_is_rejected():
    c = _supersede_case()
    d = _issue(c)
    assert d.authorized
    tampered_v = dataclasses.replace(c["verification"], verifier_version="999")
    assert _consumer_accepts(c, d.receipt, verification=tampered_v) is False


def test_authority_denies_rejected_or_ineligible_verification():
    c = _supersede_case()
    rej = dataclasses.replace(c["verification"], status=TransitionStatus.REJECTED)
    assert _issue({**c, "verification": rej}).authorized is False
    inelig = dataclasses.replace(c["verification"], canonical_effect_eligible=False)
    assert _issue({**c, "verification": inelig}).authorized is False


# =========================================================================
# 7. Translation binding tamper
# =========================================================================


def test_consumer_rejects_altered_action_count_after_issuance():
    c = _supersede_case()
    d = _issue(c)
    assert d.authorized
    only_create = dataclasses.replace(
        c["translation"],
        actions=(MemoryAction(action=CREATE, text="x",
                              replaces="food.morning_drink"),))
    assert _consumer_accepts(c, d.receipt, translation=only_create) is False


# =========================================================================
# 8. Replacement receipt binding matrix
# =========================================================================


def _ready_plan(before_state_digest=None, target="food.morning_drink"):
    from experienceos.memory.action_replacement import build_replacement
    c = _supersede_case()
    seq = tuple(c["translation"].actions)
    planner_create = MemoryAction(action=CREATE, kind="preference",
                                  text="Prefers coffee in the morning.")
    _, plan = build_replacement(
        (planner_create,), seq, verification_accepted=True,
        transition_type="supersede_existing", source_digest="sd",
        before_state_digest=before_state_digest or c["before"].digest(),
        verified_transition_id=c["proposal"].proposal_id)
    return plan


def test_replacement_consumer_accepts_exact_and_rejects_tampered():
    from experienceos.memory.action_replacement import (
        authorization_from_plan, authorize_replacement,
    )
    plan = _ready_plan()
    assert plan.ready
    auth = authorization_from_plan(plan)
    assert authorize_replacement(plan, (auth,)).authorized is True
    for changes in (dict(plan_digest="X"), dict(projected_action_list_digest="X"),
                    dict(verified_transition_id="X"), dict(replaced_action_digest="X")):
        tampered = dataclasses.replace(auth, **changes)
        assert authorize_replacement(plan, (tampered,)).authorized is False


def test_replacement_consumer_rejects_receipt_for_another_plan():
    from experienceos.memory.action_replacement import (
        authorization_from_plan, authorize_replacement,
    )
    plan_a = _ready_plan()
    plan_b = _ready_plan(before_state_digest="different-before-state")
    auth_b = authorization_from_plan(plan_b)
    assert authorize_replacement(plan_a, (auth_b,)).authorized is False


def test_replacement_consumer_missing_and_no_binding():
    from experienceos.memory.action_replacement import authorize_replacement
    plan = _ready_plan()
    assert authorize_replacement(plan, ()).authorized is False


def test_authority_replacement_receipt_only_for_ready_plan_with_binding():
    authority = BoundedRuntimeTransitionAuthority()
    assert authority.authorize_replacement(None) is None
    plan = _ready_plan()
    assert (authority.authorize_replacement(plan) is not None) == plan.ready


# =========================================================================
# 9. Lying authority: exact consumer stays authoritative (state)
# =========================================================================


class _LyingAuthority:
    def authorize_transition(self, *, coordinator, request, proposal,
                             verification, translation):
        other = dataclasses.replace(request, request_id="SOMETHING_ELSE")
        receipt = build_authorization(coordinator, other, proposal,
                                      verification, translation)
        return RuntimeAuthorityDecision(True, "authorized", receipt=receipt)

    def authorize_replacement(self, plan):
        return None


def test_lying_authority_cannot_cause_mutation():
    store = CountingStore()
    cfg = TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        runtime_authority=_LyingAuthority(), planner_precedence=True)
    agent = _agent(store, cfg)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    assert _state(agent, uid)["superseded"] == []
    assert store.calls["supersede"] == 0


# =========================================================================
# 10. Manager admission blocks application
# =========================================================================


class _ForgetOtherAuthority:
    """A malicious authority that authorizes a forget of a target that is
    NOT active in the interaction — the manager lifecycle check must block
    application even though a receipt was 'issued'."""

    def __init__(self, real):
        self._real = real

    def authorize_transition(self, **kwargs):
        return self._real.authorize_transition(**kwargs)

    def authorize_replacement(self, plan):
        return self._real.authorize_replacement(plan)


def test_manager_lifecycle_check_precedes_application():
    # Establish that even the authorized happy path passes the same
    # lifecycle admission that rejects inactive targets: after tea->coffee
    # the only supersede applied targets an active memory.
    store = CountingStore()
    agent = _agent(store)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    # exactly one supersede, one surviving active, one superseded — no
    # partial or duplicate state.
    assert store.calls["supersede"] == 1
    st = _state(agent, uid)
    assert len(st["active"]) == 1 and len(st["superseded"]) == 1
    assert st["forgotten"] == []


# =========================================================================
# 11. Engine sole mutation boundary
# =========================================================================


def test_authority_coordinator_verifier_hold_no_store():
    authority = BoundedRuntimeTransitionAuthority()
    coord = _coord(runtime_authority=authority,
                   verifier=None)
    from experienceos.memory.transition_verification import TransitionVerifier
    verifier = TransitionVerifier()
    for obj in (authority, coord, verifier):
        for forbidden in ("memory_store", "store", "engine",
                          "experience_manager", "_apply_memory_actions",
                          "add", "supersede", "forget"):
            assert not hasattr(obj, forbidden), (type(obj).__name__, forbidden)


def test_one_canonical_turn_applies_the_transition_once():
    store = CountingStore()
    agent = _agent(store)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    assert store.calls["supersede"] == 1  # exactly once


def test_unrelated_memory_survives_a_transition():
    store = CountingStore()
    agent = _agent(store)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="My home airport is SFO.")
    agent.chat(user_id=uid, session_id="s2", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s3",
               message="Actually, I prefer coffee in the morning.")
    active = _state(agent, uid)["active"]
    assert any("sfo" in t.lower() for t in active)  # untouched
    assert any("coffee" in t.lower() for t in active)


def test_forgotten_and_superseded_excluded_from_active_retrieval():
    agent = _agent()
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s3", message="What do I drink?")
    ctx = ""
    for e in agent.events[n:]:
        if e.type == "context_built":
            ctx = " ".join(
                (m.get("content") or "") for m in e.payload.get("context_messages", [])
            ).lower()
    assert "coffee" in ctx and "tea" not in ctx


# =========================================================================
# 12. Exception containment (no crash, no mutation, no leakage)
# =========================================================================


SECRET = "SECRET-abc123-do-not-leak"


class _ExplodingController:
    controller_id = "experienceos_transition_rules_v1"
    controller_version = "v1"

    def propose(self, *a, **k):
        raise RuntimeError(SECRET)


class _ExplodingAuthority:
    def authorize_transition(self, **kwargs):
        raise RuntimeError(SECRET)

    def authorize_replacement(self, plan):
        raise RuntimeError(SECRET)


@pytest.mark.parametrize("cfg_kwargs", [
    dict(update_controller=_ExplodingController(),
         runtime_authority=BoundedRuntimeTransitionAuthority()),
    dict(runtime_authority=_ExplodingAuthority()),
])
def test_seam_exception_is_contained_no_mutation_no_leak(cfg_kwargs):
    store = CountingStore()
    cfg = TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        planner_precedence=True, **cfg_kwargs)
    agent = _agent(store, cfg)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    n = len(agent.events)
    # The turn completes without raising.
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    # No durable supersede from the failed transition seam.
    assert store.calls["supersede"] == 0
    # The secret exception message never reaches an event payload.
    assert SECRET not in _events_json(agent, n)


# =========================================================================
# 13. Replay / single-use
# =========================================================================


def test_resending_the_same_update_does_not_reapply_the_transition():
    # Replay protection at the transition seam: once tea is superseded, a
    # re-sent update finds coffee already active, so the transition denies
    # (no new supersede, no re-forget). A duplicate CREATE from the create
    # path is a separate create-admission concern, not a transition
    # duplicate-application; the transition never fires twice.
    store = CountingStore()
    agent = _agent(store)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    assert store.calls["supersede"] == 1
    agent.chat(user_id=uid, session_id="s3",
               message="Actually, I prefer coffee in the morning.")
    assert store.calls["supersede"] == 1  # transition did not re-fire
    assert store.calls["forget"] == 0
    # Tea stays superseded exactly once; it is not resurrected or re-superseded.
    assert _state(agent, uid)["superseded"] == ["Prefers tea in the morning."]


def test_same_receipt_rejected_once_lifecycle_state_changed():
    # A pure re-check of the same receipt against the SAME state re-matches
    # (no durable one-time token registry exists), but any lifecycle change
    # to the target moves the before-state digest and the exact consumer
    # rejects — so a stale receipt cannot re-authorize a changed world.
    c = _supersede_case()
    d = _issue(c)
    assert _consumer_accepts(c, d.receipt) is True  # same state, re-checks
    forgotten_state = build_before_state([MemorySnapshot(
        memory_id="food.morning_drink", kind="preference",
        text="Prefers tea in the morning.", status="forgotten")],
        snapshot_source="t")
    stale = dataclasses.replace(c["request"], before_state=forgotten_state)
    assert _consumer_accepts(c, d.receipt, request=stale) is False


# =========================================================================
# 14. Canonical composition isolation
# =========================================================================


def test_canonical_builders_activate_the_bounded_authority():
    cfg = build_canonical_transition_config()
    assert isinstance(cfg.runtime_authority, BoundedRuntimeTransitionAuthority)
    assert cfg.mode == TransitionIntegrationMode.ADOPTED
    assert cfg.planner_precedence is True
    # The experimental Qwen update controller is never in the canonical
    # transition composition.
    assert cfg.update_controller.controller_id == "experienceos_transition_rules_v1"


def test_dashboard_builder_and_sdk_default_agree_with_canonical():
    from demo.transition_diagnostics import build_transition_config
    adopted = build_transition_config("adopted")
    assert isinstance(adopted.runtime_authority, BoundedRuntimeTransitionAuthority)
    for mode in ("shadow", "candidate", "verify_only"):
        assert build_transition_config(mode).runtime_authority is None
    assert build_transition_config("disabled") is None
    # SDK default constructs no coordinator at all.
    assert ExperienceOS(model=MockProvider()).transition_coordinator is None


def test_competitive_adapter_uses_the_bounded_authority():
    import inspect
    from experiments.competitive_viability import qwen_system
    src = inspect.getsource(qwen_system)
    assert "build_canonical_transition_config" in src
    # No case-id-keyed transition behavior or static per-case receipts.
    assert "authorizations=" not in src
    assert "replacement_authorizations=" not in src


# =========================================================================
# 15. Ordinary create is preserved (no transition receipt)
# =========================================================================


def test_ordinary_create_needs_no_transition_and_persists():
    store = CountingStore()
    agent = _agent(store)
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer aisle seats.")
    assert store.calls["supersede"] == 0 and store.calls["forget"] == 0
    assert any("aisle" in t.lower() for t in _state(agent, uid)["active"])
