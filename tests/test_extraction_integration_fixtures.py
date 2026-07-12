"""Development-fixture integration behavior for the four effect modes.

Development-only evidence over the grounded-extraction development
fixtures. This exercises how the integration coordinator behaves inside
a real interaction across effect modes; it is not a benchmark of
precision or recall.
"""

import json

import pytest

from benchmarks.fixtures.grounded_extraction import (
    load_development_fixtures,
)
from experienceos import ExperienceOS
from experienceos.events.schema import EventType
from experienceos.memory.extraction_integration import (
    ExtractionIntegrationConfig,
    MODE_CANDIDATE,
    MODE_DISABLED,
    MODE_SHADOW,
)
from experienceos.providers.mock import MockProvider

INTEGRATION_EVENT = EventType.EXTRACTION_INTEGRATION_EVALUATED
FIXTURES = load_development_fixtures()
POSITIVE = [f for f in FIXTURES if f["candidate_expected"]]
NEGATIVE = [f for f in FIXTURES if not f["candidate_expected"]]


def run(mode, message, user="u1"):
    config = ExtractionIntegrationConfig(effect_mode=mode)
    instance = ExperienceOS(model=MockProvider(), extraction=config)
    instance.chat(user_id=user, session_id="s1", message=message)
    events = [e for e in instance.events if e.type == INTEGRATION_EVENT]
    return instance, events


def baseline_memory_texts(message, user="u1"):
    baseline = ExperienceOS(model=MockProvider())
    baseline.chat(user_id=user, session_id="s1", message=message)
    return [m.text for m in baseline.memories_for_user(user)]


def test_fixtures_exist():
    assert POSITIVE and NEGATIVE


def test_disabled_never_invokes_controller_for_any_fixture():
    for fixture in FIXTURES:
        _, events = run(MODE_DISABLED, fixture["user_message"])
        assert events == [], fixture["case_id"]


@pytest.mark.parametrize("fixture", POSITIVE, ids=lambda f: f["case_id"])
def test_shadow_proposes_without_canonical_effect_for_positives(fixture):
    _, events = run(MODE_SHADOW, fixture["user_message"])
    payload = events[0].payload
    assert payload["proposal_present"] is True, fixture["case_id"]
    assert payload["canonical_effect"] is False, fixture["case_id"]


@pytest.mark.parametrize("fixture", NEGATIVE, ids=lambda f: f["case_id"])
def test_shadow_abstains_for_negatives(fixture):
    _, events = run(MODE_SHADOW, fixture["user_message"])
    payload = events[0].payload
    assert payload["proposal_present"] is False, fixture["case_id"]
    assert payload["canonical_effect"] is False, fixture["case_id"]


def test_shadow_proposed_kind_matches_expected_kind():
    # The deterministic baseline recovers the expected kind for grounded
    # positives. The unsupported-normalization cases are development
    # markers where a faithful excerpt does not license the expected
    # normalization, so their kind is best-effort and excluded here.
    checked = 0
    for fixture in POSITIVE:
        if fixture["category"] == "unsupported-normalization":
            continue
        _, events = run(MODE_SHADOW, fixture["user_message"])
        payload = events[0].payload
        assert payload["proposed_kind"] == fixture["expected_kind"], (
            fixture["case_id"]
        )
        checked += 1
    assert checked > 0


def test_shadow_never_changes_canonical_memory_for_fixtures():
    for fixture in FIXTURES:
        message = fixture["user_message"]
        shadow, _ = run(MODE_SHADOW, message)
        assert [m.text for m in shadow.memories_for_user("u1")] == (
            baseline_memory_texts(message)
        ), fixture["case_id"]


def test_candidate_evaluates_positives_without_mutation():
    for fixture in POSITIVE:
        message = fixture["user_message"]
        instance, events = run(MODE_CANDIDATE, message)
        payload = events[0].payload
        assert payload["action_generated"] is True, fixture["case_id"]
        assert payload["action_applied"] is False, fixture["case_id"]
        assert payload["lifecycle_evaluation"] in (
            "eligible",
            "rejected",
        ), fixture["case_id"]
        assert [m.text for m in instance.memories_for_user("u1")] == (
            baseline_memory_texts(message)
        ), fixture["case_id"]


def test_ambiguous_durability_fixture_abstains_in_shadow():
    fixture = next(
        f for f in FIXTURES if f["category"] == "ambiguous-durability"
        and not f["candidate_expected"]
    )
    _, events = run(MODE_SHADOW, fixture["user_message"])
    assert events[0].payload["proposal_present"] is False


def test_preference_change_fixtures_never_supersede_or_forget():
    changes = [f for f in POSITIVE if f["category"] == "preference-change"]
    assert changes
    for fixture in changes:
        _, events = run(MODE_CANDIDATE, fixture["user_message"])
        payload = events[0].payload
        # A translated action is CREATE-shaped only; the coordinator
        # never supersedes or forgets regardless of the fixture's later
        # lifecycle intent.
        assert payload["canonical_effect"] is False, fixture["case_id"]
        serialized = json.dumps(payload)
        assert "supersede" not in serialized
        assert "forget" not in serialized
