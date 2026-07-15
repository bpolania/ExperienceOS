"""Governed transition integration: modes, authorization, and authority.

All deterministic and offline: no provider beyond the mock, no model, no
network. Adopted mode is exercised only in isolated infrastructure tests
and is never a default anywhere.
"""

import json
import socket

import pytest

from experienceos import ExperienceOS
from experienceos.memory import ExperienceEntry, MemoryAction
from experienceos.memory.planner import CREATE, FORGET, SUPERSEDE
from experienceos.memory.schema import MemoryKind, MemoryStatus
from experienceos.memory.transition_integration import (
    ANNOTATION_VERSION,
    INTEGRATION_MODES,
    CanonicalActionEffect,
    CanonicalEffectStatus,
    ExistingActionStatus,
    TransitionAuthorization,
    TransitionFailureStage,
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationError,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    TransitionRoute,
    TransitionSystemId,
    build_authorization,
    infer_existing_transition,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    build_before_state,
)
from experienceos.providers import MockProvider

AISLE_TEXT = "I prefer aisle seats for short work trips."
WINDOW_TEXT = "I now prefer window seats for short work trips."
FORGET_TEXT = "Forget that I prefer aisle seats."


def entry(memory_id, text, kind=MemoryKind.PREFERENCE, status=MemoryStatus.ACTIVE):
    record = ExperienceEntry(user_id="u", text=text, kind=kind, status=status)
    record.id = memory_id
    return record


def state(*entries):
    return build_before_state(list(entries) or [entry("m1", AISLE_TEXT)], user_id="u")


def request(statement, before=None, mode=EvidenceMode.GROUNDED_VALID, **kwargs):
    return TransitionIntegrationRequest(
        statement=statement,
        evidence=TransitionSourceEvidence(
            source_statement=statement, source_event_id="r1", evidence_mode=mode
        ),
        before_state=before or state(),
        request_id="r1",
        user_id="u",
        **kwargs,
    )


def coordinator(mode, **kwargs):
    return TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(mode=mode, **kwargs)
    )


def authorized_setup(statement=WINDOW_TEXT, before=None, **overrides):
    """A coordinator holding an authorization bound to the real proposal."""
    plain = coordinator(TransitionIntegrationMode.ADOPTED)
    req = request(statement, before=before)
    route, controller_result = plain._route(req)
    proposal = controller_result.proposal
    verification = controller_result.verification
    translation = translate_transition(proposal, verification, req.before_state)
    auth = build_authorization(
        plain, req, proposal, verification, translation, **overrides
    )
    return (
        coordinator(TransitionIntegrationMode.ADOPTED, authorizations=(auth,)),
        req,
        auth,
    )


# --- Configuration ------------------------------------------------------------


def test_default_configuration_is_disabled():
    assert TransitionIntegrationConfig().mode == TransitionIntegrationMode.DISABLED
    assert TransitionIntegrationConfig().enabled is False


def test_all_five_modes_are_supported():
    assert set(INTEGRATION_MODES) == {
        "disabled", "shadow", "candidate", "verify_only", "adopted",
    }
    for mode in INTEGRATION_MODES:
        assert TransitionIntegrationConfig(mode=mode).mode == mode


def test_invalid_mode_raises():
    with pytest.raises(TransitionIntegrationError):
        TransitionIntegrationConfig(mode="enabled")


def test_invalid_authorization_type_raises():
    with pytest.raises(TransitionIntegrationError):
        TransitionIntegrationConfig(
            mode=TransitionIntegrationMode.ADOPTED, authorizations=("yes",)
        )


def test_config_serializes_without_authorization_contents():
    record = TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.SHADOW
    ).to_record()
    assert record["mode"] == "shadow"
    assert json.dumps(record, sort_keys=True)


def test_sdk_default_constructs_no_transition_coordinator():
    agent = ExperienceOS(model=MockProvider())
    assert agent.transition_coordinator is None
    assert agent.engine.transition_coordinator is None


def test_sdk_rejects_an_unstructured_transition_argument():
    # A bare string can never enable anything: adopted mode needs a
    # structured config plus an exact authorization.
    with pytest.raises(ValueError):
        ExperienceOS(model=MockProvider(), transition="adopted")


def test_sdk_accepts_a_config_or_a_coordinator():
    agent = ExperienceOS(
        model=MockProvider(),
        transition=TransitionIntegrationConfig(mode=TransitionIntegrationMode.SHADOW),
    )
    assert agent.transition_coordinator.mode == "shadow"
    ready = coordinator(TransitionIntegrationMode.CANDIDATE)
    assert ExperienceOS(
        model=MockProvider(), transition=ready
    ).transition_coordinator is ready


# --- Disabled mode ------------------------------------------------------------


def test_disabled_invokes_nothing_and_leaves_actions_unchanged():
    class Exploding:
        def propose(self, *args, **kwargs):
            raise AssertionError("controller must not run in disabled mode")

    result = coordinator(
        TransitionIntegrationMode.DISABLED,
        update_controller=Exploding(), forget_controller=Exploding(),
    ).evaluate(request(WINDOW_TEXT))
    assert result.route == TransitionRoute.NOT_INVOKED
    assert result.controller_invoked is False
    assert result.verifier_invoked is False
    assert result.authorization_checked is False
    assert result.translation_attempted is False
    assert result.canonical_action_effect == CanonicalActionEffect.UNCHANGED
    assert result.action_applied is False
    assert [d.code for d in result.diagnostics] == ["transition_disabled"]


def test_disabled_engine_behavior_equals_baseline_and_emits_no_event():
    def run(agent):
        agent.chat("u", "s", AISLE_TEXT)
        agent.chat("u", "s", WINDOW_TEXT)
        return [
            (m.text, m.status)
            for m in agent.memory_store.list_memories(user_id="u")
        ]

    baseline = run(ExperienceOS(model=MockProvider()))
    disabled = ExperienceOS(
        model=MockProvider(),
        transition=TransitionIntegrationConfig(
            mode=TransitionIntegrationMode.DISABLED
        ),
    )
    assert run(disabled) == baseline
    assert not [
        e for e in disabled.event_bus.history()
        if e.type == "transition_integration_evaluated"
    ]


# --- Routing ------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement,expected_route",
    [
        (WINDOW_TEXT, TransitionRoute.UPDATE),
        (AISLE_TEXT, TransitionRoute.UPDATE),
        ("For long international flights, I prefer window seats.", TransitionRoute.UPDATE),
        (FORGET_TEXT, TransitionRoute.FORGET),
        ("Forget everything about travel.", TransitionRoute.FORGET),
        ("Don't forget that I prefer aisle seats.", TransitionRoute.UPDATE),
        ("Can you forget my seat preference?", TransitionRoute.UPDATE),
        ("Do you remember my seat preference?", TransitionRoute.UPDATE),
    ],
)
def test_routing_is_mutually_exclusive(statement, expected_route):
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request(statement)
    )
    assert result.route == expected_route


def test_one_source_produces_at_most_one_proposal():
    for statement in (
        WINDOW_TEXT, FORGET_TEXT, AISLE_TEXT,
        "Don't forget that I prefer aisle seats.",
        "Forget everything about travel.",
        "If I moved to New York, I might use JFK.",
    ):
        result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
            request(statement)
        )
        assert result.proposal is None or isinstance(result.proposal.transition_type, str)
        assert result.route in (
            TransitionRoute.UPDATE, TransitionRoute.FORGET, TransitionRoute.ABSTAINED
        )


def test_affirmative_forget_never_reaches_update_adoption():
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request(FORGET_TEXT)
    )
    assert result.route == TransitionRoute.FORGET
    assert result.transition_type == "forget_existing"
    assert result.proposal.created == ()
    assert result.proposal.superseded_ids == ()


def test_negative_forget_does_not_route_to_forget_mutation():
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request("Don't forget that I prefer aisle seats.")
    )
    assert result.route == TransitionRoute.UPDATE
    assert result.proposal.forgotten_ids == ()


@pytest.mark.parametrize(
    "statement",
    [
        "Can you forget my seat preference?",
        "If I asked you to forget my seat preference, what would happen?",
        "Forget everything about travel.",
    ],
)
def test_non_durable_forget_sources_produce_no_mutating_proposal(statement):
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request(statement)
    )
    proposal = result.proposal
    if proposal is not None:
        assert proposal.forgotten_ids == ()
        assert proposal.created == ()
        assert proposal.superseded_ids == ()


def test_controller_exception_is_contained_and_falls_back_to_baseline():
    class Exploding:
        def propose(self, *args, **kwargs):
            raise RuntimeError("boom")

    result = coordinator(
        TransitionIntegrationMode.SHADOW, update_controller=Exploding()
    ).evaluate(request(WINDOW_TEXT))
    assert result.route == TransitionRoute.ERROR
    assert result.failure_stage == TransitionFailureStage.CONTROLLER
    assert result.failure_reason == "RuntimeError"
    assert result.canonical_action_effect == CanonicalActionEffect.UNCHANGED
    assert result.fallback_used is True
    assert result.action_applied is False
    # The bounded diagnostic names the type, never the message.
    assert all("boom" not in d.detail for d in result.diagnostics)


# --- Shadow mode --------------------------------------------------------------


def test_shadow_verifies_but_changes_nothing():
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request(WINDOW_TEXT)
    )
    assert result.controller_invoked is True
    assert result.verifier_invoked is True
    assert result.verification.accepted is True
    assert result.canonical_action_effect == CanonicalActionEffect.DIAGNOSTICS_ONLY
    assert result.canonical_effect_status == CanonicalEffectStatus.SHADOW_ONLY
    assert result.generated_actions == ()
    assert result.authorization_checked is False
    assert result.action_applied is False
    assert result.system_id == TransitionSystemId.SHADOW


def test_shadow_engine_run_mutates_nothing_beyond_baseline():
    def run(agent):
        agent.chat("u", "s", AISLE_TEXT)
        agent.chat("u", "s", WINDOW_TEXT)
        return [
            (m.text, m.status)
            for m in agent.memory_store.list_memories(user_id="u")
        ]

    baseline = run(ExperienceOS(model=MockProvider()))
    shadow = ExperienceOS(
        model=MockProvider(),
        transition=TransitionIntegrationConfig(mode=TransitionIntegrationMode.SHADOW),
    )
    assert run(shadow) == baseline
    events = [
        e for e in shadow.event_bus.history()
        if e.type == "transition_integration_evaluated"
    ]
    assert events
    assert all(e.payload["action_applied"] is False for e in events)


# --- Candidate mode -----------------------------------------------------------


def test_candidate_translates_but_inserts_nothing():
    result = coordinator(TransitionIntegrationMode.CANDIDATE).evaluate(
        request(WINDOW_TEXT)
    )
    assert result.translation_attempted is True
    assert result.translation.succeeded is True
    # Translation really ran — the actions exist, they are just not inserted.
    assert [a.action for a in result.translation.actions] == [SUPERSEDE, CREATE]
    assert result.canonical_action_effect == CanonicalActionEffect.CANDIDATE_ONLY
    assert result.canonical_effect_status == CanonicalEffectStatus.CANDIDATE_ONLY
    assert result.generated_actions == ()
    assert result.action_applied is False
    assert "candidate_action_not_inserted" in [d.code for d in result.diagnostics]


def test_candidate_engine_run_mutates_nothing_beyond_baseline():
    def run(agent):
        agent.chat("u", "s", AISLE_TEXT)
        agent.chat("u", "s", WINDOW_TEXT)
        return [
            (m.text, m.status)
            for m in agent.memory_store.list_memories(user_id="u")
        ]

    baseline = run(ExperienceOS(model=MockProvider()))
    candidate = ExperienceOS(
        model=MockProvider(),
        transition=TransitionIntegrationConfig(
            mode=TransitionIntegrationMode.CANDIDATE
        ),
    )
    assert run(candidate) == baseline


# --- Verify-only mode ---------------------------------------------------------


def test_infer_existing_transition_covers_the_action_vocabulary():
    assert infer_existing_transition(
        (MemoryAction(action=CREATE, text="x"),)
    )[0] == "create_new"
    assert infer_existing_transition(
        (
            MemoryAction(action=SUPERSEDE, memory_id="m1"),
            MemoryAction(action=CREATE, text="x", replaces="m1"),
        )
    )[0] == "supersede_existing"
    assert infer_existing_transition(
        (MemoryAction(action=FORGET, memory_id="m1"),)
    )[0] == "forget_existing"
    assert infer_existing_transition(())[0] is None


def test_verify_only_verifies_a_valid_existing_supersession():
    actions = (
        MemoryAction(action=SUPERSEDE, memory_id="m1", text=AISLE_TEXT),
        MemoryAction(action=CREATE, text=WINDOW_TEXT, replaces="m1"),
    )
    result = coordinator(TransitionIntegrationMode.VERIFY_ONLY).evaluate(
        request(WINDOW_TEXT, existing_actions=actions)
    )
    assert result.route == TransitionRoute.NOT_INVOKED
    verification = result.existing_action_verifications[0]
    assert verification.inferred_transition == "supersede_existing"
    assert verification.status == ExistingActionStatus.VERIFIED
    assert result.canonical_action_effect == (
        CanonicalActionEffect.VERIFIED_EXISTING_ACTIONS
    )
    assert result.generated_actions == ()
    assert result.action_applied is False


def test_verify_only_rejects_an_existing_action_with_a_wrong_target():
    actions = (
        MemoryAction(action=SUPERSEDE, memory_id="ghost", text="x"),
        MemoryAction(action=CREATE, text=WINDOW_TEXT, replaces="ghost"),
    )
    result = coordinator(TransitionIntegrationMode.VERIFY_ONLY).evaluate(
        request(WINDOW_TEXT, existing_actions=actions)
    )
    verification = result.existing_action_verifications[0]
    assert verification.status == ExistingActionStatus.REJECTED
    assert verification.reason


def test_verify_only_diagnoses_a_forget_that_should_not_be_one():
    # A forget action produced from a question is diagnosed, not rewritten.
    actions = (MemoryAction(action=FORGET, memory_id="m1", text=AISLE_TEXT),)
    result = coordinator(TransitionIntegrationMode.VERIFY_ONLY).evaluate(
        request("Can you forget my seat preference?", existing_actions=actions)
    )
    verification = result.existing_action_verifications[0]
    assert verification.inferred_transition == "forget_existing"
    assert verification.status in (
        ExistingActionStatus.REJECTED, ExistingActionStatus.VERIFIED,
    )
    # Whatever the verdict, the action is untouched.
    assert result.generated_actions == ()
    assert result.canonical_action_effect != CanonicalActionEffect.ACTION_SUPPRESSED


def test_verify_only_marks_a_non_transition_batch_as_not_relevant():
    result = coordinator(TransitionIntegrationMode.VERIFY_ONLY).evaluate(
        request("What's 15% of 240?", existing_actions=())
    )
    assert result.existing_action_verifications == ()
    assert result.canonical_action_effect == CanonicalActionEffect.UNCHANGED


def test_verify_only_never_changes_the_action_list():
    actions = [
        MemoryAction(action=SUPERSEDE, memory_id="ghost", text="x"),
        MemoryAction(action=CREATE, text=WINDOW_TEXT, replaces="ghost"),
    ]
    snapshot = list(actions)
    coordinator(TransitionIntegrationMode.VERIFY_ONLY).evaluate(
        request(WINDOW_TEXT, existing_actions=tuple(actions))
    )
    assert actions == snapshot


# --- Translation --------------------------------------------------------------


def _proposal_for(statement, before=None):
    plain = coordinator(TransitionIntegrationMode.CANDIDATE)
    req = request(statement, before=before)
    _, controller_result = plain._route(req)
    return controller_result.proposal, controller_result.verification, req


def test_translation_of_create_new_produces_one_create():
    proposal, verification, req = _proposal_for(
        "I am allergic to shellfish.", before=state()
    )
    result = translate_transition(proposal, verification, req.before_state)
    assert result.succeeded is True
    assert [a.action for a in result.actions] == [CREATE]
    assert result.actions[0].memory_id is None


def test_translation_of_supersession_uses_the_canonical_representation():
    proposal, verification, req = _proposal_for(WINDOW_TEXT)
    result = translate_transition(proposal, verification, req.before_state)
    assert result.succeeded is True
    assert [a.action for a in result.actions] == [SUPERSEDE, CREATE]
    assert result.actions[0].memory_id == "m1"
    assert result.actions[1].replaces == "m1"


def test_translation_of_scoped_coexistence_produces_one_create_no_supersede():
    proposal, verification, req = _proposal_for(
        "For long international flights, I prefer window seats."
    )
    result = translate_transition(proposal, verification, req.before_state)
    assert [a.action for a in result.actions] == [CREATE]


def test_translation_of_forget_produces_one_forget_and_no_create():
    proposal, verification, req = _proposal_for(FORGET_TEXT)
    result = translate_transition(proposal, verification, req.before_state)
    assert [a.action for a in result.actions] == [FORGET]
    assert result.actions[0].memory_id == "m1"


@pytest.mark.parametrize(
    "statement",
    [AISLE_TEXT, "Can you forget my seat preference?", "This time only, use a window seat."],
)
def test_noop_and_rejection_transitions_translate_to_zero_actions(statement):
    proposal, verification, req = _proposal_for(statement)
    result = translate_transition(proposal, verification, req.before_state)
    assert result.succeeded is True
    assert result.actions == ()
    assert result.action_type == "none"


def test_unverified_proposal_cannot_be_translated():
    proposal, _, req = _proposal_for(WINDOW_TEXT)
    result = translate_transition(proposal, None, req.before_state)
    assert result.succeeded is False
    assert result.actions == ()


def test_translation_of_an_inactive_target_fails_closed():
    inactive = state(entry("m1", AISLE_TEXT, status=MemoryStatus.SUPERSEDED))
    proposal, verification, req = _proposal_for(WINDOW_TEXT)
    result = translate_transition(proposal, verification, inactive)
    assert result.succeeded is False
    assert "not active" in result.reason


def test_translation_applies_nothing():
    agent = ExperienceOS(model=MockProvider())
    record = agent.memory_store.add(ExperienceEntry(user_id="u", text=AISLE_TEXT))
    before = build_before_state([record], user_id="u")
    proposal, verification, _ = _proposal_for(WINDOW_TEXT, before=before)
    translate_transition(proposal, verification, before)
    assert agent.memory_store.get(record.id).status == MemoryStatus.ACTIVE


# --- Authorization ------------------------------------------------------------


def test_exact_authorization_is_accepted_and_produces_actions():
    coord, req, _ = authorized_setup()
    result = coord.evaluate(req)
    assert result.authorization_decision.authorized is True
    assert result.authorization_decision.reason == "exact_match"
    assert result.canonical_action_effect == CanonicalActionEffect.ACTION_ADDED
    assert [a.action for a in result.generated_actions] == [SUPERSEDE, CREATE]
    # Authorized is still not applied.
    assert result.action_applied is False
    assert result.canonical_effect_status == (
        CanonicalEffectStatus.AUTHORIZED_NOT_APPLIED
    )


@pytest.mark.parametrize(
    "statement",
    [
        "I am allergic to shellfish.",
        WINDOW_TEXT,
        "For long international flights, I prefer window seats.",
        FORGET_TEXT,
    ],
)
def test_each_mutating_transition_has_an_exact_match_success_path(statement):
    coord, req, _ = authorized_setup(statement)
    result = coord.evaluate(req)
    assert result.authorization_decision.authorized is True
    assert result.generated_actions


def test_missing_authorization_fails_closed():
    result = coordinator(TransitionIntegrationMode.ADOPTED).evaluate(
        request(WINDOW_TEXT)
    )
    assert result.authorization_decision.authorized is False
    assert result.authorization_decision.reason == "authorization_missing"
    assert result.canonical_action_effect == CanonicalActionEffect.AUTHORIZATION_DENIED
    assert result.generated_actions == ()


@pytest.mark.parametrize(
    "field_name,bad_value",
    [
        ("mode", TransitionIntegrationMode.SHADOW),
        ("system_id", TransitionSystemId.RULES),
        ("controller_id", "someone_else"),
        ("controller_version", "99"),
        ("request_id", "other-request"),
        ("source_digest", "deadbeefdeadbeef"),
        ("evidence_mode", EvidenceMode.HISTORICAL_ORACLE),
        ("evidence_digest", "deadbeefdeadbeef"),
        ("before_state_digest", "deadbeefdeadbeef"),
        ("proposal_id", "other-proposal"),
        ("proposal_digest", "deadbeefdeadbeef"),
        ("transition_type", "create_new"),
        ("target_ids", ("ghost",)),
        ("created_digest", "deadbeefdeadbeef"),
        ("verifier_id", "other_verifier"),
        ("verifier_version", "99"),
        ("verification_digest", "deadbeefdeadbeef"),
        ("expected_action_type", "forget"),
        ("expected_action_count", 99),
        ("authorization_version", "99"),
    ],
)
def test_every_bound_field_mismatch_fails_closed(field_name, bad_value):
    coord, req, _ = authorized_setup(**{field_name: bad_value})
    result = coord.evaluate(req)
    assert result.authorization_decision.authorized is False, field_name
    assert result.authorization_decision.reason == "authorization_mismatch"
    assert field_name in result.authorization_decision.mismatched_fields
    assert result.canonical_action_effect == CanonicalActionEffect.AUTHORIZATION_DENIED
    assert result.generated_actions == ()


def test_authorization_for_another_source_is_rejected():
    coord, _, _ = authorized_setup(WINDOW_TEXT)
    other = request("I now prefer middle seats for short work trips.")
    result = coord.evaluate(other)
    assert result.authorization_decision.authorized is False
    assert result.generated_actions == ()


def test_historical_oracle_evidence_cannot_authorize_a_canonical_effect():
    plain = coordinator(TransitionIntegrationMode.ADOPTED)
    req = request(WINDOW_TEXT, mode=EvidenceMode.HISTORICAL_ORACLE)
    _, controller_result = plain._route(req)
    translation = translate_transition(
        controller_result.proposal, controller_result.verification, req.before_state
    )
    auth = build_authorization(
        plain, req, controller_result.proposal, controller_result.verification,
        translation,
    )
    coord = coordinator(
        TransitionIntegrationMode.ADOPTED, authorizations=(auth,)
    )
    result = coord.evaluate(req)
    # Ineligible evidence is refused before any authorization can match.
    assert result.authorization_decision.authorized is False
    assert result.authorization_decision.reason == "canonical_effect_ineligible"
    assert result.generated_actions == ()


def test_development_fixture_evidence_cannot_authorize_a_canonical_effect():
    result = coordinator(TransitionIntegrationMode.ADOPTED).evaluate(
        request(WINDOW_TEXT, mode=EvidenceMode.DEVELOPMENT_FIXTURE)
    )
    assert result.canonical_effect_eligible is False
    assert result.authorization_decision.authorized is False
    assert result.generated_actions == ()


def test_authorization_over_an_ambiguous_proposal_is_rejected():
    two_scopes = state(
        entry("m1", AISLE_TEXT),
        entry("m2", "I prefer window seats for long international flights."),
    )
    result = coordinator(TransitionIntegrationMode.ADOPTED).evaluate(
        request("Change my seat preference.", before=two_scopes)
    )
    assert result.transition_type == "reject_ambiguous"
    assert result.authorization_decision.authorized is False
    assert result.generated_actions == ()


def test_authorization_never_substitutes_for_verification():
    class RejectingVerifier:
        verifier_id = "stub"
        version = "1"

        def verify(self, proposal, before_state):
            from experienceos.memory.transition_verification import (
                TransitionVerificationResult,
                TransitionStatus,
            )

            return TransitionVerificationResult(
                proposal_id=proposal.proposal_id,
                transition_type=proposal.transition_type,
                status=TransitionStatus.REJECTED,
                rejection_reason="target_not_found",
            )

    coord = coordinator(
        TransitionIntegrationMode.ADOPTED, verifier=RejectingVerifier()
    )
    result = coord.evaluate(request(WINDOW_TEXT))
    assert result.authorization_decision.authorized is False
    assert result.authorization_decision.reason == "proposal_not_verified"
    assert result.generated_actions == ()


def test_authorization_digest_is_deterministic():
    coord, req, auth = authorized_setup()
    assert auth.digest() == auth.digest()
    other = TransitionAuthorization(**{**auth.binding(), "target_ids": tuple(
        auth.binding()["target_ids"]
    )})
    assert other.digest() == auth.digest()


def test_wildcard_authorization_is_impossible():
    # Every bound field is required; there is no "any" value.
    import dataclasses

    required = {
        f.name for f in dataclasses.fields(TransitionAuthorization)
        if f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING
    }
    assert "proposal_digest" in required
    assert "verification_digest" in required
    assert "before_state_digest" in required


# --- Adopted infrastructure through the engine --------------------------------


class _StubCoordinator:
    """Returns a prepared adopted result so the engine seam can be tested."""

    def __init__(self, actions):
        self._actions = tuple(actions)

    enabled = True

    def evaluate(self, request):
        from experienceos.memory.transition_integration import (
            TransitionIntegrationResult,
        )

        return TransitionIntegrationResult(
            configured_mode=TransitionIntegrationMode.ADOPTED,
            effective_mode=TransitionIntegrationMode.ADOPTED,
            system_id=TransitionSystemId.ADOPTED,
            route=TransitionRoute.UPDATE,
            canonical_action_effect=CanonicalActionEffect.ACTION_ADDED,
            canonical_effect_status=CanonicalEffectStatus.AUTHORIZED_NOT_APPLIED,
            generated_actions=self._actions,
        )


def test_engine_applies_an_authorized_admissible_action_through_the_existing_path():
    agent = ExperienceOS(model=MockProvider())
    agent.chat("u", "s", AISLE_TEXT)
    target = agent.memory_store.active_for_user("u")[0]
    agent.engine.transition_coordinator = _StubCoordinator(
        (
            MemoryAction(action=FORGET, memory_id=target.id, text=target.text),
        )
    )
    agent.chat("u", "s", "unrelated chatter")
    assert agent.memory_store.get(target.id).status == MemoryStatus.FORGOTTEN
    event = [
        e for e in agent.event_bus.history()
        if e.type == "transition_integration_evaluated"
    ][-1]
    assert event.payload["action_applied"] is True
    assert event.payload["canonical_action_effect"] == CanonicalActionEffect.APPLIED
    # The durable event came from the existing application path.
    assert [e for e in agent.event_bus.history() if e.type == "memory_forgotten"]


def test_engine_rejects_an_inadmissible_action_and_reports_it_unapplied():
    agent = ExperienceOS(model=MockProvider())
    agent.chat("u", "s", AISLE_TEXT)
    agent.engine.transition_coordinator = _StubCoordinator(
        (MemoryAction(action=FORGET, memory_id="ghost", text="x"),)
    )
    agent.chat("u", "s", "unrelated chatter")
    event = [
        e for e in agent.event_bus.history()
        if e.type == "transition_integration_evaluated"
    ][-1]
    assert event.payload["action_applied"] is False
    assert event.payload["canonical_action_effect"] == (
        CanonicalActionEffect.LIFECYCLE_REJECTED
    )
    assert event.payload["lifecycle_rejection_reason"] == "target_not_active"
    assert not [
        e for e in agent.event_bus.history() if e.type == "memory_forgotten"
    ]


def test_engine_never_applies_a_non_adopted_result():
    agent = ExperienceOS(model=MockProvider())
    agent.chat("u", "s", AISLE_TEXT)
    target = agent.memory_store.active_for_user("u")[0]

    class ShadowStub(_StubCoordinator):
        def evaluate(self, request):
            result = super().evaluate(request)
            result.effective_mode = TransitionIntegrationMode.SHADOW
            result.canonical_action_effect = CanonicalActionEffect.DIAGNOSTICS_ONLY
            return result

    agent.engine.transition_coordinator = ShadowStub(
        (MemoryAction(action=FORGET, memory_id=target.id, text=target.text),)
    )
    agent.chat("u", "s", "unrelated chatter")
    assert agent.memory_store.get(target.id).status == MemoryStatus.ACTIVE


# --- Authority and non-mutation -----------------------------------------------


def test_coordinator_has_no_store_and_no_mutation_method():
    coord = coordinator(TransitionIntegrationMode.SHADOW)
    assert not hasattr(coord, "memory_store")
    for banned in ("add", "supersede", "forget", "apply", "commit", "persist"):
        assert not hasattr(coord, banned), banned


def test_integration_module_imports_no_store_or_provider_code():
    import ast

    import experienceos.memory.transition_integration as module

    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in (
        "experienceos.engine",
        "experienceos.policy",
        "experienceos.providers",
        "experienceos.embeddings",
        "experienceos.memory.store",
        "experienceos.memory.sqlite_store",
        "requests",
        "urllib",
        "httpx",
        "socket",
    ):
        assert not any(
            n == banned or n.startswith(f"{banned}.") for n in imported
        ), f"integration imports {banned}"


def test_integration_module_calls_no_engine_application():
    import ast

    import experienceos.memory.transition_integration as module

    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_apply_memory_actions" not in called


@pytest.mark.parametrize(
    "mode",
    [
        TransitionIntegrationMode.DISABLED,
        TransitionIntegrationMode.SHADOW,
        TransitionIntegrationMode.CANDIDATE,
        TransitionIntegrationMode.VERIFY_ONLY,
    ],
)
def test_non_adopted_modes_never_generate_actions(mode):
    for statement in (WINDOW_TEXT, FORGET_TEXT, AISLE_TEXT):
        result = coordinator(mode).evaluate(request(statement))
        assert result.generated_actions == (), f"{mode}:{statement}"
        assert result.action_applied is False


def test_coordinator_does_not_mutate_its_request():
    req = request(WINDOW_TEXT)
    before = json.dumps(req.before_state.to_record(), sort_keys=True)
    coordinator(TransitionIntegrationMode.ADOPTED).evaluate(req)
    assert json.dumps(req.before_state.to_record(), sort_keys=True) == before


def test_coordinator_performs_no_network_access(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("transition integration attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request(WINDOW_TEXT)
    )
    assert result.canonical_action_effect == CanonicalActionEffect.DIAGNOSTICS_ONLY


# --- Annotations --------------------------------------------------------------


def test_annotation_is_versioned_and_deterministic():
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request(WINDOW_TEXT)
    )
    first = json.dumps(result.to_record(), sort_keys=True)
    second = json.dumps(result.to_record(), sort_keys=True)
    assert first == second
    payload = json.loads(first)
    assert payload["annotation_version"] == ANNOTATION_VERSION
    assert payload["action_applied"] is False


@pytest.mark.parametrize(
    "mode",
    [
        TransitionIntegrationMode.DISABLED,
        TransitionIntegrationMode.SHADOW,
        TransitionIntegrationMode.CANDIDATE,
        TransitionIntegrationMode.VERIFY_ONLY,
        TransitionIntegrationMode.ADOPTED,
    ],
)
def test_every_mode_produces_a_serializable_annotation(mode):
    result = coordinator(mode).evaluate(request(WINDOW_TEXT))
    payload = result.to_record()
    assert json.dumps(payload, sort_keys=True)
    assert payload["configured_mode"] == mode
    assert payload["effective_mode"] == mode


def test_annotation_leaks_no_paths_or_secrets():
    result = coordinator(TransitionIntegrationMode.SHADOW).evaluate(
        request(WINDOW_TEXT)
    )
    blob = json.dumps(result.to_record())
    assert "/Users/" not in blob
    assert "/home/" not in blob
    for secret in ("api_key", "password", "secret"):
        assert secret not in blob.lower()


def test_old_events_without_transition_metadata_remain_readable():
    agent = ExperienceOS(model=MockProvider())
    agent.chat("u", "s", AISLE_TEXT)
    for event in agent.event_bus.history():
        assert isinstance(event.payload, dict)
        assert "transition_integration" not in event.type
    # An event stream with no transition annotation deserializes fine.
    assert json.dumps(
        [{"type": e.type, "payload": e.payload} for e in agent.event_bus.history()],
        default=str,
    )


def test_authorization_denied_annotation_records_the_reason():
    result = coordinator(TransitionIntegrationMode.ADOPTED).evaluate(
        request(WINDOW_TEXT)
    )
    payload = result.to_record()
    assert payload["authorization"]["authorized"] is False
    assert payload["canonical_action_effect"] == (
        CanonicalActionEffect.AUTHORIZATION_DENIED
    )
    assert payload["action_applied"] is False


# --- Diagnostics --------------------------------------------------------------


def test_diagnostics_are_structured_and_deterministically_ordered():
    first = coordinator(TransitionIntegrationMode.ADOPTED).evaluate(
        request(WINDOW_TEXT)
    )
    second = coordinator(TransitionIntegrationMode.ADOPTED).evaluate(
        request(WINDOW_TEXT)
    )
    assert [d.code for d in first.diagnostics] == [d.code for d in second.diagnostics]
    codes = [d.code for d in first.diagnostics]
    assert "update_controller_selected" in codes
    assert "proposal_generated" in codes
    assert "verification_accepted" in codes
    assert "authorization_missing" in codes


def test_diagnostic_categories_cover_the_required_surface():
    coord, req, _ = authorized_setup()
    result = coord.evaluate(req)
    categories = {d.category for d in result.diagnostics}
    assert {"routing", "controller", "verifier", "translation", "authorization"} <= (
        categories
    )


# --- Prior-layer regression ---------------------------------------------------


def test_prior_layer_evaluations_are_unchanged():
    from benchmarks.forget_intelligence.evaluation import (
        evaluate_corpus as forget_corpus,
    )
    from benchmarks.transition_verification.evaluation import (
        evaluate_corpus as verify_corpus,
    )
    from benchmarks.update_intelligence.evaluation import (
        evaluate_corpus as update_corpus,
    )

    verify = verify_corpus()
    assert verify["historical_scored"]["correct_accepted"] == 28
    assert verify["development_only"]["correct_accepted"] == 27

    update = update_corpus()
    assert update["historical_scored"]["transition_accuracy"]["correct"] == 24
    assert update["development_only"]["transition_accuracy"]["correct"] == 24

    forget = forget_corpus()
    assert forget["historical_scored"]["classification"]["correct"] == 4
    assert forget["development_only"]["classification"]["correct"] == 6


def test_corpus_manifest_unchanged():
    from benchmarks.annotations import transition_verification as tv

    assert tv.verify_manifest() is True
