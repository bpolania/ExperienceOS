"""Demo reset tests: clean state across all lifecycle statuses and stores."""

from demo.demo_config import DEMO_USER_ID, SCRIPTED_DEMO
from demo.support import (
    compressed_summaries,
    create_agent,
    growth_metrics,
    lifecycle_timeline,
    make_memory_store,
    reset_demo_state,
    selection_records,
    supplied_context_lines,
    STORAGE_SQLITE,
)
from experienceos import ExperienceOS
from experienceos.memory import (
    ExperienceEntry,
    InMemoryMemoryStore,
    MemoryStatus,
    SQLiteMemoryStore,
)
from experienceos.providers import MockProvider

ALL_STATUSES = (MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED, MemoryStatus.FORGOTTEN)


def seed_full_lifecycle(agent, user_id=DEMO_USER_ID):
    """Create active, superseded, and forgotten memories plus events."""
    for session_id, message in SCRIPTED_DEMO:
        agent.chat(user_id=user_id, session_id=session_id, message=message)
    assert agent.memories_for_user(user_id)
    assert agent.memories_for_user(user_id, status=MemoryStatus.SUPERSEDED)
    assert agent.memories_for_user(user_id, status=MemoryStatus.FORGOTTEN)
    assert agent.events
    return agent


def assert_no_memories(agent, user_id=DEMO_USER_ID):
    for status in ALL_STATUSES:
        assert agent.memories_for_user(user_id, status=status) == []
    assert agent.memories_for_user(user_id, status=None) == []


def test_in_memory_reset_clears_all_lifecycle_statuses():
    agent = seed_full_lifecycle(create_agent(MockProvider()))
    reset_demo_state(agent)
    assert_no_memories(agent)
    assert agent.events == []


def test_sqlite_reset_clears_all_lifecycle_statuses(tmp_path):
    db_path = str(tmp_path / "reset.sqlite3")
    agent = seed_full_lifecycle(
        create_agent(MockProvider(), make_memory_store(STORAGE_SQLITE, db_path))
    )
    reset_demo_state(agent)
    assert_no_memories(agent)
    assert agent.events == []
    # The clean state is persisted: a fresh store sees nothing either.
    fresh = SQLiteMemoryStore(db_path)
    assert fresh.list_memories(DEMO_USER_ID) == []


def test_reset_clears_event_derived_display_state():
    agent = seed_full_lifecycle(create_agent(MockProvider()))
    assert compressed_summaries(agent.events)
    assert selection_records(agent.events)
    assert supplied_context_lines(agent.events)
    assert lifecycle_timeline(agent.events)

    reset_demo_state(agent)
    assert compressed_summaries(agent.events) == []
    assert selection_records(agent.events) == []
    assert supplied_context_lines(agent.events) == []
    assert lifecycle_timeline(agent.events) == []
    metrics = growth_metrics(agent, DEMO_USER_ID)
    assert metrics["active_memories"] == 0
    assert metrics["created_memories"] == 0
    assert metrics["context_saved_chars"] == 0


def test_reset_is_scoped_to_the_demo_user(tmp_path):
    db_path = str(tmp_path / "scoped.sqlite3")
    agent = create_agent(
        MockProvider(), make_memory_store(STORAGE_SQLITE, db_path)
    )
    agent.chat(
        user_id="other-user", session_id="s1", message="I prefer window seats."
    )
    seed_full_lifecycle(agent)

    reset_demo_state(agent, DEMO_USER_ID)
    assert_no_memories(agent)
    assert [m.text for m in agent.memories_for_user("other-user")] == [
        "Prefers window seats."
    ]


def test_in_memory_store_clear_user_memories_scoped():
    store = InMemoryMemoryStore()
    store.add(ExperienceEntry(user_id="u1", text="A."))
    store.add(ExperienceEntry(user_id="u1", text="B.", status=MemoryStatus.FORGOTTEN))
    store.add(ExperienceEntry(user_id="u2", text="C."))
    store.clear_user_memories("u1")
    assert store.list_memories("u1") == []
    assert [m.text for m in store.list_memories("u2")] == ["C."]


def test_sqlite_store_clear_user_memories_scoped(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "scoped-store.sqlite3")
    store.add(ExperienceEntry(user_id="u1", text="A."))
    store.add(
        ExperienceEntry(user_id="u1", text="B.", status=MemoryStatus.SUPERSEDED)
    )
    store.add(ExperienceEntry(user_id="u2", text="C."))
    store.clear_user_memories("u1")
    assert store.list_memories("u1") == []
    assert [m.text for m in store.list_memories("u2")] == ["C."]


def test_scripted_demo_is_repeatable_after_reset():
    agent = seed_full_lifecycle(create_agent(MockProvider()))
    first_active = {m.text for m in agent.memories_for_user(DEMO_USER_ID)}

    reset_demo_state(agent)
    seed_full_lifecycle(agent)
    second_active = {m.text for m in agent.memories_for_user(DEMO_USER_ID)}

    assert second_active == first_active
    assert len(
        agent.memories_for_user(DEMO_USER_ID, status=MemoryStatus.SUPERSEDED)
    ) == 2
    assert len(
        agent.memories_for_user(DEMO_USER_ID, status=MemoryStatus.FORGOTTEN)
    ) == 1


def test_sdk_entrypoints_unchanged(tmp_path):
    assert ExperienceOS(model=MockProvider()).chat(
        user_id="u1", session_id="s1", message="hello"
    )
    assert ExperienceOS.wrap(MockProvider()).chat(
        user_id="u1", session_id="s1", message="hello"
    )
    agent = ExperienceOS.with_sqlite_memory(
        model=MockProvider(), db_path=str(tmp_path / "sdk.sqlite3")
    )
    assert agent.chat(user_id="u1", session_id="s1", message="hello")
