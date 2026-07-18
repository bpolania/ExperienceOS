"""Tests for the bounded runtime transition authority.

Deterministic and offline: eligible cases use the real canonical
controllers; denials are derived by perturbing the exact inputs. Every
test proves either an issued exact receipt the existing ``_authorize``
accepts, or a fail-closed denial with a stable reason — and that the
authority mutates nothing.
"""

from __future__ import annotations

import dataclasses

import pytest

from experienceos.controllers.base import MemorySnapshot
from experienceos.memory.forget_intelligence import (
    DeterministicForgetController, FORGET_CONTROLLER_ID,
)
from experienceos.memory.planner import CREATE, FORGET, MemoryAction, SUPERSEDE
from experienceos.memory.transition_authority import (
    AUTHORIZED,
    BoundedRuntimeTransitionAuthority,
    RuntimeAuthorityDecision,
    ALLOWED_UPDATE_CONTROLLERS,
)
import experienceos.memory.transition_authority as TA
from experienceos.memory.transition_integration import (
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    build_authorization,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    CreatedMemorySpec,
    EvidenceMode,
    ProposedTransition,
    TransitionSourceEvidence,
    TransitionStatus,
    TransitionVerificationResult,
    TRANSITION_VERIFIER_ID,
    build_before_state,
)
from experienceos.memory.update_intelligence import (
    DeterministicUpdateController, UPDATE_CONTROLLER_ID,
)


def _coord():
    return TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(mode=TransitionIntegrationMode.ADOPTED))


def _evidence(stmt):
    return TransitionSourceEvidence(
        source_statement=stmt, source_event_id="e", session_id="s",
        evidence_mode=EvidenceMode.GROUNDED_VALID, provenance_ref="user_asserted")


def _bs(mems):
    return build_before_state(
        [MemorySnapshot(memory_id=i, kind=k, text=t, status=s)
         for i, k, t, s in mems], snapshot_source="test")


def _case(statement, mems, controller):
    ev = _evidence(statement)
    before = _bs(mems)
    result = controller.propose(statement, ev, before)
    request = TransitionIntegrationRequest(
        statement=statement, evidence=ev, before_state=before,
        request_id="r", user_id="u", existing_actions=())
    translation = translate_transition(
        result.proposal, result.verification, before)
    return {
        "coordinator": _coord(), "request": request,
        "proposal": result.proposal, "verification": result.verification,
        "translation": translation, "before": before,
    }


def _supersede():
    return _case(
        "Actually, I prefer coffee in the morning.",
        [("food.morning_drink", "preference", "Prefers tea in the morning.",
          "active")],
        DeterministicUpdateController())


def _forget():
    return _case(
        "Forget that I prefer studying in the evening.",
        [("study.time_of_day", "preference", "Prefers studying in the evening.",
          "active")],
        DeterministicForgetController())


def _authorize(c, **over):
    args = {k: c[k] for k in ("request", "proposal", "verification",
                             "translation")}
    args.update(over)
    return BoundedRuntimeTransitionAuthority().authorize_transition(
        coordinator=c["coordinator"], **args)


def _accepts_receipt(c, receipt):
    req = dataclasses.replace(c["request"], authorization=receipt)
    return c["coordinator"]._authorize(
        req, c["proposal"], c["verification"], c["translation"]).authorized


# -- 12.1 / 12.2 eligible supersede and forget -------------------------------


def test_eligible_supersede_issues_accepted_receipt():
    c = _supersede()
    assert c["proposal"].transition_type == "supersede_existing"
    assert len(c["proposal"].superseded_ids) == 1
    assert c["verification"].accepted and c["verification"].canonical_effect_eligible
    assert c["translation"].succeeded
    d = _authorize(c)
    assert d.authorized is True and d.reason == AUTHORIZED
    assert type(d.receipt).__name__ == "TransitionAuthorization"
    assert _accepts_receipt(c, d.receipt) is True  # existing _authorize accepts


def test_eligible_forget_issues_accepted_receipt():
    c = _forget()
    assert c["proposal"].transition_type == "forget_existing"
    assert len(c["proposal"].forgotten_ids) == 1
    assert not c["proposal"].created
    d = _authorize(c)
    assert d.authorized is True and type(d.receipt).__name__ == (
        "TransitionAuthorization")
    assert _accepts_receipt(c, d.receipt) is True


# -- 12.3 immutability -------------------------------------------------------


def test_decision_and_receipt_are_immutable():
    d = _authorize(_supersede())
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.authorized = False
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.receipt.request_id = "x"
    assert isinstance(ALLOWED_UPDATE_CONTROLLERS, frozenset)


# -- 12.4 determinism --------------------------------------------------------


def test_repeated_issuance_is_deterministic():
    c = _supersede()
    a = _authorize(c)
    b = _authorize(c)
    assert a.receipt.digest() == b.receipt.digest()
    assert a.receipt.binding() == b.receipt.binding()


# -- 12.5 controller denial --------------------------------------------------


def test_qwen_and_unknown_and_missing_controllers_denied():
    c = _supersede()
    for bad in ("qwen_update-1", "grounded_qwen_shadow-1", "some_learned-9"):
        p = dataclasses.replace(c["proposal"], proposer_id=bad)
        assert _authorize(c, proposal=p).reason == TA.CONTROLLER_NOT_ALLOWLISTED
    p = dataclasses.replace(c["proposal"], proposer_id="")
    assert _authorize(c, proposal=p).reason == TA.CONTROLLER_MISSING


def test_wrong_controller_version_denied():
    c = _supersede()
    authority = BoundedRuntimeTransitionAuthority(
        allowed_update_controllers=frozenset({(UPDATE_CONTROLLER_ID, "999")}))
    d = authority.authorize_transition(
        coordinator=c["coordinator"], request=c["request"],
        proposal=c["proposal"], verification=c["verification"],
        translation=c["translation"])
    assert d.reason == TA.CONTROLLER_VERSION_NOT_ALLOWLISTED


# -- 12.6 verification denial ------------------------------------------------


def test_verification_denials():
    c = _supersede()
    assert _authorize(c, verification=None).reason == TA.VERIFICATION_MISSING
    rej = dataclasses.replace(c["verification"], status=TransitionStatus.REJECTED)
    assert _authorize(c, verification=rej).reason == TA.VERIFICATION_REJECTED
    inelig = dataclasses.replace(c["verification"], canonical_effect_eligible=False)
    assert _authorize(c, verification=inelig).reason == TA.CANONICAL_EFFECT_INELIGIBLE
    badverifier = dataclasses.replace(c["verification"], verifier_id="other-1")
    assert _authorize(c, verification=badverifier).reason == TA.VERIFIER_NOT_ALLOWLISTED
    # verification tied to a different proposal / type
    mismatch = dataclasses.replace(c["verification"], proposal_id="other")
    assert _authorize(c, verification=mismatch).reason == TA.VERIFICATION_PROPOSAL_MISMATCH
    # verification tied to a modified (renamed) proposal
    p = dataclasses.replace(c["proposal"], proposal_id="renamed")
    assert _authorize(c, proposal=p).reason == TA.VERIFICATION_PROPOSAL_MISMATCH


def test_no_receipt_before_verification():
    c = _supersede()
    # Without a verification the authority cannot issue anything.
    assert _authorize(c, verification=None).receipt is None


# -- 12.7 transition type denial ---------------------------------------------


def test_transition_type_denials():
    c = _supersede()
    for bad in ("create_new", "scoped_coexistence", "reject_ambiguous",
                "reject_unsupported", "duplicate", "no_change", "mystery"):
        p = dataclasses.replace(c["proposal"], transition_type=bad)
        assert _authorize(c, proposal=p).reason == TA.TRANSITION_TYPE_UNSUPPORTED


# -- 12.8 target denial ------------------------------------------------------


def test_target_cardinality_denials():
    c = _supersede()
    zero = dataclasses.replace(c["proposal"], superseded_ids=())
    assert _authorize(c, proposal=zero).reason == TA.TARGET_MISSING
    two = dataclasses.replace(c["proposal"], superseded_ids=("a", "b"))
    assert _authorize(c, proposal=two).reason == TA.MULTIPLE_TARGETS
    both = dataclasses.replace(c["proposal"], forgotten_ids=("z",))
    assert _authorize(c, proposal=both).reason == TA.TARGET_CONFLICT
    f = _forget()
    twof = dataclasses.replace(f["proposal"], forgotten_ids=("a", "b"))
    assert _authorize(f, proposal=twof).reason == TA.MULTIPLE_TARGETS


def _craft_supersede(before, target):
    """A hand-crafted, internally consistent supersede for isolating the
    active-target checks (real controllers never propose an inactive
    target)."""
    ev = _evidence("crafted")
    proposal = ProposedTransition(
        proposal_id="p", transition_type="supersede_existing", evidence=ev,
        before_state_digest=before.digest(), target_ids=(target,),
        superseded_ids=(target,),
        created=(CreatedMemorySpec(candidate=None, local_ref="created:0",
                                   replaces=target),),
        proposer_id=UPDATE_CONTROLLER_ID)
    verification = TransitionVerificationResult(
        proposal_id="p", transition_type="supersede_existing",
        status=TransitionStatus.ACCEPTED, canonical_effect_eligible=True,
        verifier_id=TRANSITION_VERIFIER_ID)
    translation = dataclasses.replace(  # a valid supersede translation shape
        _forget()["translation"], succeeded=True, action_type=SUPERSEDE,
        actions=(MemoryAction(action=SUPERSEDE, memory_id=target),
                 MemoryAction(action=CREATE, text="new", replaces=target)))
    request = TransitionIntegrationRequest(
        statement="crafted", evidence=ev, before_state=before,
        request_id="r", user_id="u", existing_actions=())
    return {"coordinator": _coord(), "request": request, "proposal": proposal,
            "verification": verification, "translation": translation,
            "before": before}


def test_inactive_and_absent_target_denied():
    inactive = _bs([("food.morning_drink", "preference", "tea", "superseded")])
    c = _craft_supersede(inactive, "food.morning_drink")
    assert _authorize(c).reason == TA.TARGET_NOT_ACTIVE
    absent = _bs([("other.id", "preference", "x", "active")])
    c2 = _craft_supersede(absent, "food.morning_drink")
    assert _authorize(c2).reason == TA.TARGET_NOT_IN_BEFORE_STATE


# -- 12.9 translation denial -------------------------------------------------


def test_translation_denials():
    c = _supersede()
    assert _authorize(c, translation=None).reason == TA.TRANSLATION_MISSING
    failed = dataclasses.replace(c["translation"], succeeded=False)
    assert _authorize(c, translation=failed).reason == TA.TRANSLATION_FAILED
    wrongtype = dataclasses.replace(c["translation"], action_type=FORGET)
    assert _authorize(c, translation=wrongtype).reason == TA.WRONG_ACTION_TYPE
    # wrong count: only the create action
    only_create = dataclasses.replace(
        c["translation"],
        actions=(MemoryAction(action=CREATE, text="x",
                              replaces="food.morning_drink"),))
    assert _authorize(c, translation=only_create).reason == TA.WRONG_ACTION_COUNT
    # supersede with a forget side effect
    with_forget = dataclasses.replace(
        c["translation"],
        actions=(MemoryAction(action=SUPERSEDE, memory_id="food.morning_drink"),
                 MemoryAction(action=FORGET, memory_id="food.morning_drink")))
    assert _authorize(c, translation=with_forget).reason == TA.SUPERSEDE_HAS_FORGET_EFFECT
    # supersede without lineage (create replaces nothing)
    no_lineage = dataclasses.replace(
        c["translation"],
        actions=(MemoryAction(action=SUPERSEDE, memory_id="food.morning_drink"),
                 MemoryAction(action=CREATE, text="x", replaces=None)))
    assert _authorize(c, translation=no_lineage).reason == TA.SUPERSEDE_LINEAGE_MISSING


def test_forget_translation_denials():
    f = _forget()
    # forget proposal that (illegally) carries a created memory
    p = dataclasses.replace(
        f["proposal"],
        created=(CreatedMemorySpec(candidate=None, local_ref="created:0"),))
    assert _authorize(f, proposal=p).reason == TA.FORGET_CREATES_MEMORY
    # forget with a supersede in the proposal target set
    p2 = dataclasses.replace(f["proposal"], superseded_ids=("z",))
    assert _authorize(f, proposal=p2).reason in (
        TA.TARGET_CONFLICT, TA.FORGET_HAS_SUPERSEDE_EFFECT)
    # forget with wrong action type / count
    wrong = dataclasses.replace(
        f["translation"], action_type=SUPERSEDE,
        actions=(MemoryAction(action=SUPERSEDE, memory_id="study.time_of_day"),))
    assert _authorize(f, translation=wrong).reason == TA.WRONG_ACTION_TYPE


# -- 12.10 exact binding protection (via the existing consumer) ---------------


@pytest.mark.parametrize("mutate", [
    ("request", dict(request_id="TAMPER")),
    ("request", dict(statement="different source text")),
    ("proposal", dict(proposal_id="TAMPER")),
    ("proposal", dict(superseded_ids=("other.target",))),
])
def test_exact_binding_rejects_tampered_consumption(mutate):
    c = _supersede()
    d = _authorize(c)
    assert d.authorized
    field, changes = mutate
    tampered = dataclasses.replace(c[field], **changes)
    kwargs = {"request": c["request"], "proposal": c["proposal"],
              "verification": c["verification"], "translation": c["translation"]}
    kwargs[field] = tampered
    req = dataclasses.replace(kwargs["request"], authorization=d.receipt)
    accepted = c["coordinator"]._authorize(
        req, kwargs["proposal"], kwargs["verification"], kwargs["translation"]
    ).authorized
    assert accepted is False  # the existing consumer fails closed


# -- 12.11 no mutation capability --------------------------------------------


def test_authority_has_no_store_or_mutation_capability():
    authority = BoundedRuntimeTransitionAuthority()
    for forbidden in ("memory_store", "store", "engine", "experience_manager",
                      "manager", "apply", "save", "delete", "supersede",
                      "forget", "_apply_memory_actions", "mutate"):
        assert not hasattr(authority, forbidden)


def test_authorizing_does_not_mutate_before_state():
    c = _supersede()
    before = c["before"].digest()
    _authorize(c)
    assert c["before"].digest() == before  # unchanged


# -- 12.12 static authorization compatibility --------------------------------


def test_static_authorization_path_still_works():
    c = _supersede()
    receipt = build_authorization(
        c["coordinator"], c["request"], c["proposal"], c["verification"],
        c["translation"])
    coord = TransitionIntegrationCoordinator(TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED, authorizations=(receipt,)))
    assert coord._authorize(
        c["request"], c["proposal"], c["verification"], c["translation"]
    ).authorized is True


# -- mode + replacement + malformed ------------------------------------------


def test_non_adopted_mode_denied():
    c = _supersede()
    disabled = TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(mode=TransitionIntegrationMode.SHADOW))
    d = BoundedRuntimeTransitionAuthority().authorize_transition(
        coordinator=disabled, request=c["request"], proposal=c["proposal"],
        verification=c["verification"], translation=c["translation"])
    assert d.reason == TA.MODE_NOT_ADOPTED


def test_malformed_input_is_contained_not_raised():
    d = BoundedRuntimeTransitionAuthority().authorize_transition(
        coordinator=object(), request=None, proposal=None, verification=None,
        translation=None)
    assert d.authorized is False
    assert d.reason in (TA.MODE_NOT_ADOPTED, TA.MALFORMED_INPUT)


def test_authorize_replacement_issues_only_for_ready_plan():
    from experienceos.memory.action_replacement import build_replacement
    c = _supersede()
    sequence = tuple(c["translation"].actions)
    planner_create = MemoryAction(action=CREATE, kind="preference",
                                  text="Prefers coffee in the morning.")
    decision, plan = build_replacement(
        (planner_create,), sequence, verification_accepted=True,
        transition_type="supersede_existing",
        source_digest=c["request"].source_digest(),
        before_state_digest=c["before"].digest(),
        verified_transition_id=c["proposal"].proposal_id)
    authority = BoundedRuntimeTransitionAuthority()
    if plan.ready:
        assert authority.authorize_replacement(plan) is not None
    assert authority.authorize_replacement(None) is None


def test_decision_is_a_frozen_dataclass():
    assert dataclasses.is_dataclass(RuntimeAuthorityDecision)
    d = RuntimeAuthorityDecision(authorized=False, reason="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.reason = "y"
