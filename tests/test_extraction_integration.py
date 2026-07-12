"""Unit and engine-integration tests for grounded extraction modes."""

import json

import pytest

from experienceos import ExperienceOS
from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.events.schema import EventType
from experienceos.memory.extraction_integration import (
    AdoptionAuthorization,
    CONTROLLER_DETERMINISTIC,
    CONTROLLER_LEARNED,
    EFFECT_MODES,
    ExtractionIntegrationConfig,
    ExtractionIntegrationCoordinator,
    ExtractionIntegrationError,
    MODE_ADOPTED,
    MODE_CANDIDATE,
    MODE_DISABLED,
    MODE_SHADOW,
    STATUS_AUTHORIZATION_MISMATCH,
    STATUS_AUTHORIZATION_MISSING,
    STATUS_AUTHORIZED,
    STATUS_GROUNDING_REJECTED,
    STATUS_NO_CANDIDATE,
    STATUS_PROPOSED,
)
from experienceos.memory.learned_extraction import (
    LearnedExtractionRunnerResult,
    LearnedGroundedExtractionController,
    RUNNER_OK,
)
from experienceos.providers.mock import MockProvider

INTEGRATION_EVENT = EventType.EXTRACTION_INTEGRATION_EVALUATED
DETERMINISTIC_ID = "grounded_rules-1"


def agent(mode=MODE_DISABLED, controller_type=CONTROLLER_DETERMINISTIC,
          authorizations=(), learned_controller=None):
    config = ExtractionIntegrationConfig(
        effect_mode=mode, controller_type=controller_type,
        authorizations=authorizations,
        learned_controller=learned_controller,
    )
    return ExperienceOS(model=MockProvider(), extraction=config)


def integration_events(instance):
    return [e for e in instance.events if e.type == INTEGRATION_EVENT]


def chat(instance, message, user="u1", session="s1"):
    instance.chat(user_id=user, session_id=session, message=message)
    return instance


class FakeRunner:
    runner_id = "fake_runner"
    runner_version = "1"

    def __init__(self, raw=None, available=True):
        self.raw = raw
        self._available = available

    def availability(self):
        return self._available

    def run(self, request):
        return LearnedExtractionRunnerResult(
            raw_output=self.raw, runner_id=self.runner_id,
            runner_version=self.runner_version, available=True,
            status=RUNNER_OK, elapsed_ms=1.0,
        )


def learned_candidate_json(message, kind="fact",
                           normalized="Home airport is SJC"):
    return json.dumps({
        "action": "candidate", "kind": kind,
        "normalized_text": normalized, "evidence_text": message,
        "start_offset": 0, "end_offset": len(message),
        "confidence": 0.9, "reason": "durable",
    })


def det_auth(source="controller"):
    return AdoptionAuthorization(
        controller_id=DETERMINISTIC_ID, controller_version="1",
        final_proposal_source=source,
    )


# -- mode vocabulary ---------------------------------------------------------------


def test_effect_modes_are_closed():
    assert EFFECT_MODES == (
        MODE_DISABLED, MODE_SHADOW, MODE_CANDIDATE, MODE_ADOPTED
    )


def test_invalid_mode_and_controller_rejected():
    with pytest.raises(ExtractionIntegrationError):
        ExtractionIntegrationConfig(effect_mode="enforce")
    with pytest.raises(ExtractionIntegrationError):
        ExtractionIntegrationConfig(controller_type="qwen")
    with pytest.raises(ExtractionIntegrationError):
        ExtractionIntegrationConfig(authorizations=("not-an-auth",))


def test_learned_type_requires_a_learned_controller():
    coordinator = ExtractionIntegrationCoordinator(
        ExtractionIntegrationConfig(
            effect_mode=MODE_SHADOW,
            controller_type=CONTROLLER_LEARNED,
        )
    )
    with pytest.raises(ExtractionIntegrationError):
        coordinator.evaluate(
            ExtractionEvidence(user_text="hi",
                               metadata={"source_id": "s"}),
            source_id="s", provenance="user_asserted",
        )


def test_sdk_rejects_bad_extraction_argument():
    with pytest.raises(ValueError):
        ExperienceOS(model=MockProvider(), extraction="on")


# -- default behavior --------------------------------------------------------------


def test_default_construction_has_no_coordinator():
    plain = ExperienceOS(model=MockProvider())
    assert plain.extraction_coordinator is None
    chat(plain, "I prefer aisle seats.")
    assert integration_events(plain) == []


def test_disabled_is_byte_identical_to_no_extraction():
    plain = ExperienceOS(model=MockProvider())
    disabled = agent(MODE_DISABLED)
    for instance in (plain, disabled):
        chat(instance, "I prefer aisle seats.")
    plain_types = [e.type for e in plain.events]
    disabled_types = [e.type for e in disabled.events]
    assert plain_types == disabled_types
    assert integration_events(disabled) == []
    assert [m.text for m in plain.memories_for_user("u1")] == [
        m.text for m in disabled.memories_for_user("u1")
    ]


def test_disabled_invokes_no_controller():
    coordinator = ExtractionIntegrationCoordinator(
        ExtractionIntegrationConfig(effect_mode=MODE_DISABLED)
    )
    assert coordinator.enabled is False


# -- shadow mode -------------------------------------------------------------------


def test_shadow_emits_proposal_without_mutation():
    instance = agent(MODE_SHADOW)
    # Use a message the canonical planner does not capture, so any new
    # memory would have to come from the controller.
    baseline = ExperienceOS(model=MockProvider())
    message = "When planning work trips, always include transfer time."
    chat(baseline, message)
    chat(instance, message)
    event = integration_events(instance)[0].payload
    assert event["effect_mode"] == MODE_SHADOW
    assert event["integration_status"] == STATUS_PROPOSED
    assert event["proposal_present"] is True
    assert event["canonical_effect"] is False
    assert event["action_applied"] is False
    # Canonical memory outcome is identical to the no-extraction run.
    assert [m.text for m in instance.memories_for_user("u1")] == [
        m.text for m in baseline.memories_for_user("u1")
    ]


def test_shadow_abstains_on_negative_message():
    instance = agent(MODE_SHADOW)
    chat(instance, "Should I use SFO or SJC?")
    event = integration_events(instance)[0].payload
    assert event["integration_status"] == STATUS_NO_CANDIDATE
    assert event["proposal_present"] is False
    assert event["canonical_effect"] is False


def test_learned_shadow_with_fake_runner():
    message = "My home airport is SJC."
    learned = LearnedGroundedExtractionController(
        FakeRunner(learned_candidate_json(message)),
        fallback_mode="none",
    )
    instance = agent(MODE_SHADOW, CONTROLLER_LEARNED,
                    learned_controller=learned)
    chat(instance, message)
    event = integration_events(instance)[0].payload
    assert event["controller_type"] == CONTROLLER_LEARNED
    assert event["integration_status"] == STATUS_PROPOSED
    assert event["runner_status"] == RUNNER_OK
    assert event["canonical_effect"] is False


def test_learned_shadow_fallback_attribution_visible():
    learned = LearnedGroundedExtractionController(
        FakeRunner(None, available=False),
        fallback_mode="deterministic_on_unavailable",
    )
    instance = agent(MODE_SHADOW, CONTROLLER_LEARNED,
                    learned_controller=learned)
    chat(instance, "I prefer aisle seats.")
    event = integration_events(instance)[0].payload
    assert event["fallback_used"] is True
    assert event["final_proposal_source"] == "deterministic_fallback"
    assert event["canonical_effect"] is False


# -- candidate mode ----------------------------------------------------------------


def test_candidate_evaluates_without_mutation():
    baseline = ExperienceOS(model=MockProvider())
    message = "When planning work trips, always include transfer time."
    chat(baseline, message)
    instance = agent(MODE_CANDIDATE)
    chat(instance, message)
    event = integration_events(instance)[0].payload
    assert event["effect_mode"] == MODE_CANDIDATE
    assert event["lifecycle_evaluation"] == "eligible"
    assert event["action_generated"] is True
    assert event["action_applied"] is False
    assert event["canonical_effect"] is False
    assert [m.text for m in instance.memories_for_user("u1")] == [
        m.text for m in baseline.memories_for_user("u1")
    ]


def test_candidate_identifies_duplicate_of_active():
    instance = agent(MODE_CANDIDATE)
    chat(instance, "My home airport is SJC.")  # canonical creates it
    chat(instance, "My home airport is SJC.")  # now a duplicate
    event = integration_events(instance)[-1].payload
    assert event["lifecycle_evaluation"] == "rejected"
    assert event["duplicate_or_conflict"] == "duplicate_of_active"
    assert event["canonical_effect"] is False


def test_candidate_does_not_reach_lifecycle_on_abstention():
    instance = agent(MODE_CANDIDATE)
    chat(instance, "Should I use SFO?")
    event = integration_events(instance)[0].payload
    assert event["integration_status"] == STATUS_NO_CANDIDATE
    assert event["lifecycle_evaluation"] is None


# -- adoption authorization --------------------------------------------------------


def test_adopted_without_authorization_fails_closed():
    instance = agent(MODE_ADOPTED)
    chat(instance, "When planning work trips, always add transfer time.")
    event = integration_events(instance)[0].payload
    assert event["integration_status"] == STATUS_AUTHORIZATION_MISSING
    assert event["canonical_effect"] is False
    assert event["action_applied"] is False
    # No controller-origin memory was created.
    assert not any(
        m.metadata.get("extraction_origin")
        for m in instance.memories_for_user("u1")
    )


def test_adopted_authorization_mismatch_on_source():
    # Authorize a different final source than the controller produces.
    instance = agent(MODE_ADOPTED,
                    authorizations=(det_auth(source="learned"),))
    chat(instance, "My home airport is SJC.")
    event = integration_events(instance)[0].payload
    assert event["integration_status"] == STATUS_AUTHORIZATION_MISMATCH
    assert event["canonical_effect"] is False


def test_authorization_cannot_bypass_grounding():
    # A negative message: even with authorization, no candidate exists.
    instance = agent(MODE_ADOPTED, authorizations=(det_auth(),))
    chat(instance, "If I ever move, I might use SEA.")
    event = integration_events(instance)[0].payload
    assert event["integration_status"] == STATUS_NO_CANDIDATE
    assert event["canonical_effect"] is False


# -- adopted deterministic path ----------------------------------------------------


def test_adopted_deterministic_creates_one_memory():
    instance = agent(MODE_ADOPTED, authorizations=(det_auth(),))
    chat(instance, "When planning work trips, always add transfer time.")
    event = integration_events(instance)[0].payload
    assert event["integration_status"] == STATUS_AUTHORIZED
    assert event["canonical_effect"] is True
    assert event["action_applied"] is True
    origins = [
        m.metadata.get("extraction_origin", {}).get("controller_id")
        for m in instance.memories_for_user("u1")
    ]
    assert DETERMINISTIC_ID in origins
    # A MEMORY_CREATED event was emitted by the engine (not the
    # coordinator).
    assert any(e.type == EventType.MEMORY_CREATED
               for e in instance.events)


def test_adopted_deduplicates_against_canonical_create():
    # The canonical planner ALSO creates the SJC fact; the controller
    # create must not add a second active memory (contract §14).
    instance = agent(MODE_ADOPTED, authorizations=(det_auth(),))
    chat(instance, "My home airport is SJC.")
    event = integration_events(instance)[0].payload
    assert event["duplicate_or_conflict"] == "duplicate_of_planned"
    assert event["canonical_effect"] is False
    assert sum(1 for m in instance.memories_for_user("u1")
               if "SJC" in m.text) == 1


def test_adopted_duplicate_of_active_across_turns():
    instance = agent(MODE_ADOPTED, authorizations=(det_auth(),))
    chat(instance,
         "When planning work trips, always add transfer time.")
    chat(instance,
         "When planning work trips, always add transfer time.")
    second = integration_events(instance)[-1].payload
    assert second["canonical_effect"] is False
    assert second["duplicate_or_conflict"] in (
        "duplicate_of_active", "duplicate_of_planned"
    )


# -- adopted learned path ----------------------------------------------------------


def test_adopted_learned_creates_through_lifecycle():
    message = "When planning work trips, always add transfer time."
    learned = LearnedGroundedExtractionController(
        FakeRunner(learned_candidate_json(
            message, kind="instruction",
            normalized="When planning work trips, always add transfer "
                       "time",
        )),
        fallback_mode="none",
    )
    learned_auth = AdoptionAuthorization(
        controller_id="grounded_learned_shadow-1",
        controller_version="1", final_proposal_source="learned",
    )
    instance = agent(MODE_ADOPTED, CONTROLLER_LEARNED,
                    authorizations=(learned_auth,),
                    learned_controller=learned)
    chat(instance, message)
    event = integration_events(instance)[0].payload
    assert event["integration_status"] == STATUS_AUTHORIZED
    assert event["final_proposal_source"] == "learned"
    assert event["canonical_effect"] is True


def test_adopted_learned_invalid_output_creates_nothing():
    learned = LearnedGroundedExtractionController(
        FakeRunner("garbage output"), fallback_mode="none",
    )
    learned_auth = AdoptionAuthorization(
        controller_id="grounded_learned_shadow-1",
        controller_version="1", final_proposal_source="learned",
    )
    instance = agent(MODE_ADOPTED, CONTROLLER_LEARNED,
                    authorizations=(learned_auth,),
                    learned_controller=learned)
    chat(instance, "My home airport is SJC.")
    event = integration_events(instance)[0].payload
    assert event["canonical_effect"] is False
    assert not any(
        m.metadata.get("extraction_origin")
        for m in instance.memories_for_user("u1")
    )


def test_learned_fallback_not_authorized_by_learned_authorization():
    # Runner unavailable -> deterministic fallback candidate. A
    # learned-only authorization must NOT authorize the fallback source.
    learned = LearnedGroundedExtractionController(
        FakeRunner(None, available=False),
        fallback_mode="deterministic_on_unavailable",
    )
    learned_auth = AdoptionAuthorization(
        controller_id="grounded_learned_shadow-1",
        controller_version="1", final_proposal_source="learned",
    )
    instance = agent(MODE_ADOPTED, CONTROLLER_LEARNED,
                    authorizations=(learned_auth,),
                    learned_controller=learned)
    chat(instance, "My home airport is SJC.")
    event = integration_events(instance)[0].payload
    assert event["final_proposal_source"] == "deterministic_fallback"
    assert event["integration_status"] == STATUS_AUTHORIZATION_MISMATCH
    assert event["canonical_effect"] is False


# -- authority and coordinator isolation -------------------------------------------


def test_coordinator_has_no_mutation_or_store_handle():
    import inspect

    coordinator = ExtractionIntegrationCoordinator(
        ExtractionIntegrationConfig()
    )
    forbidden = {"apply", "create", "mutate", "persist", "store",
                 "supersede", "forget"}
    assert not (
        {n for n in dir(coordinator) if not n.startswith("_")}
        & forbidden
    )
    parameters = inspect.signature(
        ExtractionIntegrationCoordinator
    ).parameters
    assert not any(
        token in name for name in parameters
        for token in ("store", "engine", "bus", "callback")
    )


def test_translated_action_assigns_no_lifecycle_fields():
    coordinator = ExtractionIntegrationCoordinator(
        ExtractionIntegrationConfig(effect_mode=MODE_CANDIDATE)
    )
    message = "My home airport is SJC."
    outcome = coordinator.evaluate(
        ExtractionEvidence(user_text=message,
                           metadata={"source_id": "s"}),
        source_id="s", provenance="user_asserted",
    )
    action = outcome.translated_action
    assert action is not None
    assert action.memory_id is None  # no target
    assert action.replaces is None
    from experienceos.memory.planner import CREATE

    assert action.action == CREATE


# -- diagnostics and serialization -------------------------------------------------


def test_integration_events_serialize_safely():
    for mode in (MODE_SHADOW, MODE_CANDIDATE, MODE_ADOPTED):
        instance = agent(mode, authorizations=(det_auth(),))
        chat(instance, "My home airport is SJC.")
        for event in integration_events(instance):
            payload = json.dumps(event.payload)
            assert "/Users/" not in payload and "/home/" not in payload
            assert "integration_id" in event.payload
            assert event.payload["integration_version"] == "1"


def test_no_raw_source_text_or_unbounded_output_leaks():
    long_message = "I prefer aisle seats " + "x" * 5000
    instance = agent(MODE_SHADOW)
    chat(instance, long_message)
    event = integration_events(instance)[0].payload
    # Normalized text (if any) is bounded; the full raw message is not
    # echoed into the payload (an over-long span is contained, not
    # leaked).
    payload = json.dumps(event)
    assert "x" * 5000 not in payload


# -- side effects ------------------------------------------------------------------


def test_shadow_and_candidate_perform_no_writes(tmp_path):
    for mode in (MODE_SHADOW, MODE_CANDIDATE):
        instance = agent(mode)
        message = "When planning work trips, always add transfer time."
        baseline = ExperienceOS(model=MockProvider())
        chat(baseline, message)
        chat(instance, message)
        assert [m.text for m in instance.memories_for_user("u1")] == [
            m.text for m in baseline.memories_for_user("u1")
        ]
    assert not list(tmp_path.iterdir())
