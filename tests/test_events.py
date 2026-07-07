"""Event bus and interaction lifecycle event tests."""

from experienceos import ExperienceOS
from experienceos.events import EventBus, EventType
from experienceos.providers import MockProvider

# Lifecycle for a message that creates no memories.
BASE_LIFECYCLE = [
    EventType.INTERACTION_STARTED,
    EventType.CONTEXT_REQUESTED,
    EventType.MEMORY_RETRIEVED,
    EventType.CONTEXT_BUILT,
    EventType.MEMORY_ACTION_PLANNED,
    EventType.MODEL_CALLED,
    EventType.RESPONSE_RETURNED,
    EventType.INTERACTION_COMPLETED,
]


def test_chat_emits_expected_event_sequence():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="Help me book a trip.")
    assert [e.type for e in agent.events] == BASE_LIFECYCLE


def test_preference_chat_adds_memory_created_events():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    types = [e.type for e in agent.events]
    expected = list(BASE_LIFECYCLE)
    expected.insert(
        expected.index(EventType.MODEL_CALLED), EventType.MEMORY_CREATED
    )
    assert types == expected


def test_events_carry_identity_fields():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="hello")
    for event in agent.events:
        assert event.id
        assert event.timestamp.tzinfo is not None
        assert event.user_id == "u1"
        assert event.session_id == "s1"


def test_for_session_filters_history():
    bus = EventBus()
    agent = ExperienceOS(model=MockProvider(), event_bus=bus)
    agent.chat(user_id="u1", session_id="s1", message="one")
    agent.chat(user_id="u2", session_id="s2", message="two")
    assert len(bus.for_session("u1", "s1")) == len(BASE_LIFECYCLE)
    assert len(bus.history()) == 2 * len(BASE_LIFECYCLE)


def test_subscribe_and_clear():
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    bus.emit(EventType.INTERACTION_STARTED, "u1", "s1", {"message": "hi"})
    assert len(received) == 1
    bus.clear()
    assert bus.history() == []
