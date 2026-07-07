"""First-pass memory creation, retrieval, and context injection tests."""

from experienceos import ExperienceOS
from experienceos.context.builder import MEMORY_HEADER, ContextBuilder
from experienceos.events import EventType
from experienceos.memory import (
    ExperienceEntry,
    MemoryKind,
    MemoryStatus,
    MemoryStore,
)
from experienceos.providers import MockProvider

PREFERENCE_MESSAGE = "I prefer aisle seats and morning flights."


def make_agent():
    return ExperienceOS(model=MockProvider())


def test_preference_message_creates_active_memories():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    memories = agent.memories_for_user("u1")
    assert {m.text for m in memories} == {
        "Prefers aisle seats.",
        "Prefers morning flights.",
    }
    assert all(m.status == MemoryStatus.ACTIVE for m in memories)
    assert all(m.kind == MemoryKind.PREFERENCE for m in memories)


def test_created_memories_belong_to_correct_user():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    assert all(m.user_id == "u1" for m in agent.memories_for_user("u1"))
    assert agent.memories_for_user("someone-else") == []


def test_store_lists_active_memories():
    store = MemoryStore()
    store.add(ExperienceEntry(user_id="u1", text="Prefers aisle seats."))
    store.add(
        ExperienceEntry(
            user_id="u1", text="Old habit.", status=MemoryStatus.FORGOTTEN
        )
    )
    active = store.active_for_user("u1")
    assert [m.text for m in active] == ["Prefers aisle seats."]
    assert len(store.list_memories("u1")) == 2


def test_later_chat_retrieves_active_memories():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    agent.chat(user_id="u1", session_id="s2", message="Help me book a trip.")
    retrieved = [
        e
        for e in agent.events
        if e.type == EventType.MEMORY_RETRIEVED and e.session_id == "s2"
    ]
    assert len(retrieved) == 1
    assert retrieved[0].payload["count"] == 2


def test_context_builder_includes_memories():
    builder = ContextBuilder()
    memories = [
        ExperienceEntry(user_id="u1", text="Prefers aisle seats."),
        ExperienceEntry(user_id="u1", text="Prefers morning flights."),
    ]
    context = builder.build_context(
        "u1", "s1", "book a trip", memories=memories
    ).messages
    memory_blocks = [
        m for m in context if m["role"] == "system" and MEMORY_HEADER in m["content"]
    ]
    assert len(memory_blocks) == 1
    assert "- Prefers aisle seats." in memory_blocks[0]["content"]
    assert "- Prefers morning flights." in memory_blocks[0]["content"]


def test_retrieved_memories_reach_the_provider():
    class SpyProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = []

        def complete(self, messages):
            self.calls.append(messages)
            return super().complete(messages)

    spy = SpyProvider()
    agent = ExperienceOS(model=spy)
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    agent.chat(user_id="u1", session_id="s2", message="Help me book a trip.")
    second_call = spy.calls[1]
    assert any(
        m["role"] == "system" and "Prefers aisle seats." in m["content"]
        for m in second_call
    )
    assert second_call[-1] == {"role": "user", "content": "Help me book a trip."}


def test_memory_action_planned_reports_create_actions():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    planned = [
        e for e in agent.events if e.type == EventType.MEMORY_ACTION_PLANNED
    ]
    assert len(planned) == 1
    actions = planned[0].payload["planned_actions"]
    assert {a["action"] for a in actions} == {"create"}
    assert {a["text"] for a in actions} == {
        "Prefers aisle seats.",
        "Prefers morning flights.",
    }


def test_memory_created_emitted_per_memory():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    created = [e for e in agent.events if e.type == EventType.MEMORY_CREATED]
    assert len(created) == 2
    for event in created:
        assert event.payload["memory_id"]
        assert event.payload["status"] == MemoryStatus.ACTIVE


def test_superseded_and_forgotten_states_exist_but_unused():
    assert MemoryStatus.SUPERSEDED == "superseded"
    assert MemoryStatus.FORGOTTEN == "forgotten"
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    assert all(
        m.status == MemoryStatus.ACTIVE
        for m in agent.memory_store.list_memories("u1")
    )


def test_restating_a_preference_does_not_duplicate():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="I prefer aisle seats.")
    assert len(agent.memories_for_user("u1")) == 1


def run_update_scenario():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message=PREFERENCE_MESSAGE)
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer window seats now."
    )
    return agent


def test_changed_preference_supersedes_old_one():
    agent = run_update_scenario()
    active = {m.text for m in agent.memories_for_user("u1")}
    assert active == {"Prefers morning flights.", "Prefers window seats."}


def test_superseded_memory_remains_in_store_with_lineage():
    agent = run_update_scenario()
    superseded = agent.memories_for_user("u1", status=MemoryStatus.SUPERSEDED)
    assert [m.text for m in superseded] == ["Prefers aisle seats."]
    old = superseded[0]
    replacement = agent.memory_store.get(old.metadata["superseded_by"])
    assert replacement.text == "Prefers window seats."
    assert replacement.status == MemoryStatus.ACTIVE
    assert replacement.metadata["replaces"] == old.id
    assert old.metadata["superseded_reason"]


def test_memory_superseded_event_emitted():
    agent = run_update_scenario()
    superseded_events = [
        e for e in agent.events if e.type == EventType.MEMORY_SUPERSEDED
    ]
    assert len(superseded_events) == 1
    payload = superseded_events[0].payload
    assert payload["text"] == "Prefers aisle seats."
    assert payload["status"] == MemoryStatus.SUPERSEDED
    assert payload["superseded_by"]
    assert payload["reason"]


def test_planned_actions_include_supersede_and_create():
    agent = run_update_scenario()
    planned = [
        e
        for e in agent.events
        if e.type == EventType.MEMORY_ACTION_PLANNED and e.session_id == "s2"
    ][0].payload["planned_actions"]
    assert {a["action"] for a in planned} == {"supersede", "create"}
    supersede = next(a for a in planned if a["action"] == "supersede")
    assert supersede["text"] == "Prefers aisle seats."
    assert supersede["memory_id"]
    assert supersede["reason"]


def test_final_context_uses_replacement_not_superseded():
    agent = run_update_scenario()
    agent.chat(user_id="u1", session_id="s3", message="Help me book a trip to NYC.")
    final_context = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload["context_messages"]
    context_text = " ".join(m["content"] for m in final_context)
    assert "Prefers window seats." in context_text
    assert "Prefers morning flights." in context_text
    assert "Prefers aisle seats." not in context_text


def test_non_conflicting_preferences_are_not_superseded():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="I prefer quiet hotels.")
    assert agent.memories_for_user("u1", status=MemoryStatus.SUPERSEDED) == []
    assert {m.text for m in agent.memories_for_user("u1")} == {
        "Prefers aisle seats.",
        "Prefers quiet hotels.",
    }


def test_unknown_domain_never_supersedes():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I like jazz.")
    agent.chat(user_id="u1", session_id="s2", message="I like classical music.")
    assert agent.memories_for_user("u1", status=MemoryStatus.SUPERSEDED) == []
    assert len(agent.memories_for_user("u1")) == 2


def test_dislike_detection():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I don't like red-eye flights.")
    assert [m.text for m in agent.memories_for_user("u1")] == [
        "Dislikes red-eye flights."
    ]
