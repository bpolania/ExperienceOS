"""Forgotten memory lifecycle tests: forget requests, exclusion, persistence."""

from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory import MemoryStatus, SQLiteMemoryStore
from experienceos.providers import MockProvider


def make_agent(**kwargs):
    return ExperienceOS(model=MockProvider(), **kwargs)


def seeded_agent():
    agent = make_agent()
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="I prefer aisle seats and morning flights.",
    )
    return agent


def test_forget_request_marks_matching_memory_forgotten():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my morning flight preference."
    )
    active = {m.text for m in agent.memories_for_user("u1")}
    assert active == {"Prefers aisle seats."}
    forgotten = agent.memories_for_user("u1", status=MemoryStatus.FORGOTTEN)
    assert [m.text for m in forgotten] == ["Prefers morning flights."]


def test_forgotten_excluded_from_active_for_user():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my morning flight preference."
    )
    assert all(
        m.status == MemoryStatus.ACTIVE
        for m in agent.memory_store.active_for_user("u1")
    )
    assert "Prefers morning flights." not in {
        m.text for m in agent.memory_store.active_for_user("u1")
    }


def test_forgotten_excluded_from_context():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my morning flight preference."
    )
    agent.chat(user_id="u1", session_id="s3", message="Help me book a work trip.")
    final_context = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload["context_messages"]
    context_text = " ".join(m["content"] for m in final_context)
    assert "Prefers aisle seats." in context_text
    assert "Prefers morning flights." not in context_text


def test_forgotten_visible_through_status_filter():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my morning flight preference."
    )
    forgotten = agent.memories_for_user("u1", status="forgotten")
    assert len(forgotten) == 1
    entry = forgotten[0]
    assert entry.metadata["forgotten_at"]
    assert entry.metadata["forget_reason"]


def test_forgotten_status_persists_in_sqlite(tmp_path):
    db = tmp_path / "forget.sqlite3"
    agent_a = ExperienceOS.with_sqlite_memory(model=MockProvider(), db_path=db)
    agent_a.chat(
        user_id="u1",
        session_id="s1",
        message="I prefer aisle seats and morning flights.",
    )
    agent_a.chat(
        user_id="u1", session_id="s2", message="Forget my morning flight preference."
    )

    store = SQLiteMemoryStore(db)
    forgotten = store.list_memories("u1", status=MemoryStatus.FORGOTTEN)
    assert [m.text for m in forgotten] == ["Prefers morning flights."]
    assert forgotten[0].metadata["forgotten_at"]
    assert [m.text for m in store.active_for_user("u1")] == ["Prefers aisle seats."]


def test_memory_forgotten_event_emitted_with_full_payload():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my morning flight preference."
    )
    events = [e for e in agent.events if e.type == EventType.MEMORY_FORGOTTEN]
    assert len(events) == 1
    payload = events[0].payload
    assert payload["memory_id"]
    assert payload["previous_status"] == MemoryStatus.ACTIVE
    assert payload["status"] == MemoryStatus.FORGOTTEN
    assert payload["text"] == "Prefers morning flights."
    assert payload["reason"]
    assert payload["request"] == "Forget my morning flight preference"


def test_planned_actions_include_forget():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my morning flight preference."
    )
    planned = [
        e
        for e in agent.events
        if e.type == EventType.MEMORY_ACTION_PLANNED and e.session_id == "s2"
    ][0].payload["planned_actions"]
    assert planned == [
        {
            "action": "forget",
            "memory_id": planned[0]["memory_id"],
            "text": "Prefers morning flights.",
            "reason": "User asked to forget this experience.",
            "request": "Forget my morning flight preference",
        }
    ]


def test_forget_with_no_matching_memory_is_a_noop():
    agent = seeded_agent()
    response = agent.chat(
        user_id="u1", session_id="s2", message="Forget my rental car preference."
    )
    assert isinstance(response, str)
    assert not [e for e in agent.events if e.type == EventType.MEMORY_FORGOTTEN]
    assert len(agent.memories_for_user("u1")) == 2


def test_no_longer_remember_phrasing():
    agent = seeded_agent()
    agent.chat(
        user_id="u1",
        session_id="s2",
        message="I no longer want you to remember my aisle seat preference.",
    )
    assert {m.text for m in agent.memories_for_user("u1")} == {
        "Prefers morning flights."
    }


def test_no_longer_prefer_phrasing():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="s2", message="I no longer prefer morning flights."
    )
    assert {m.text for m in agent.memories_for_user("u1")} == {
        "Prefers aisle seats."
    }


def test_do_not_care_anymore_phrasing():
    agent = make_agent()
    agent.chat(
        user_id="u1", session_id="s1", message="I prefer hotels with gyms."
    )
    agent.chat(
        user_id="u1",
        session_id="s2",
        message="I do not care about hotel gyms anymore.",
    )
    assert agent.memories_for_user("u1") == []
    assert [
        m.text for m in agent.memories_for_user("u1", status=MemoryStatus.FORGOTTEN)
    ] == ["Prefers hotels with gyms."]


def test_forget_request_does_not_create_a_memory():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I prefer hotels with gyms.")
    agent.chat(
        user_id="u1",
        session_id="s2",
        message="Forget that I prefer hotels with gyms.",
    )
    assert agent.memories_for_user("u1") == []
    created_s2 = [
        e
        for e in agent.events
        if e.type == EventType.MEMORY_CREATED and e.session_id == "s2"
    ]
    assert created_s2 == []


def test_forget_does_not_touch_unrelated_memories():
    agent = seeded_agent()
    agent.chat(user_id="u1", session_id="s2", message="I prefer quiet hotels.")
    agent.chat(
        user_id="u1", session_id="s3", message="Forget my morning flight preference."
    )
    assert {m.text for m in agent.memories_for_user("u1")} == {
        "Prefers aisle seats.",
        "Prefers quiet hotels.",
    }
