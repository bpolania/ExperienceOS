"""SQLite persistence tests. All use tmp_path — no shared local database."""

from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory import (
    ExperienceEntry,
    MemoryStatus,
    SQLiteMemoryStore,
)
from experienceos.providers import MockProvider


def make_store(tmp_path):
    return SQLiteMemoryStore(tmp_path / "test.sqlite3")


def test_table_created_automatically(tmp_path):
    store = make_store(tmp_path)
    assert store.list_memories("u1") == []


def test_add_and_get_roundtrip(tmp_path):
    store = make_store(tmp_path)
    entry = ExperienceEntry(
        user_id="u1",
        text="Prefers aisle seats.",
        source_session_id="s1",
        metadata={"note": "test"},
    )
    store.add(entry)
    loaded = store.get(entry.id)
    assert loaded.to_record() == entry.to_record()


def test_list_memories_by_user_and_status(tmp_path):
    store = make_store(tmp_path)
    store.add(ExperienceEntry(user_id="u1", text="A."))
    store.add(ExperienceEntry(user_id="u1", text="B.", status=MemoryStatus.SUPERSEDED))
    store.add(ExperienceEntry(user_id="u2", text="C."))
    assert [m.text for m in store.list_memories("u1")] == ["A.", "B."]
    assert [m.text for m in store.active_for_user("u1")] == ["A."]
    assert [
        m.text for m in store.list_memories("u1", status=MemoryStatus.SUPERSEDED)
    ] == ["B."]


def test_supersede_persists_status_and_lineage(tmp_path):
    store = make_store(tmp_path)
    old = store.add(ExperienceEntry(user_id="u1", text="Prefers aisle seats."))
    store.supersede(old.id, superseded_by="new-id", reason="Changed preference.")
    reloaded = SQLiteMemoryStore(tmp_path / "test.sqlite3").get(old.id)
    assert reloaded.status == MemoryStatus.SUPERSEDED
    assert reloaded.metadata["superseded_by"] == "new-id"
    assert reloaded.metadata["superseded_reason"] == "Changed preference."
    assert reloaded.metadata["superseded_at"]


def test_new_store_instance_loads_prior_memories(tmp_path):
    db = tmp_path / "test.sqlite3"
    SQLiteMemoryStore(db).add(ExperienceEntry(user_id="u1", text="Persists."))
    assert [m.text for m in SQLiteMemoryStore(db).active_for_user("u1")] == [
        "Persists."
    ]


def test_clear_removes_all_entries(tmp_path):
    store = make_store(tmp_path)
    store.add(ExperienceEntry(user_id="u1", text="A."))
    store.clear()
    assert store.list_memories("u1") == []


def sqlite_agent(tmp_path):
    return ExperienceOS.with_sqlite_memory(
        model=MockProvider(), db_path=tmp_path / "agent.sqlite3"
    )


def test_agent_recreation_retrieves_persisted_memories(tmp_path):
    agent_a = sqlite_agent(tmp_path)
    agent_a.chat(
        user_id="u1",
        session_id="s1",
        message="I prefer aisle seats and morning flights.",
    )

    agent_b = sqlite_agent(tmp_path)
    agent_b.chat(user_id="u1", session_id="s2", message="Help me book a trip.")
    retrieved = [e for e in agent_b.events if e.type == EventType.MEMORY_RETRIEVED]
    assert retrieved[0].payload["count"] == 2
    assert {m.text for m in agent_b.memories_for_user("u1")} == {
        "Prefers aisle seats.",
        "Prefers morning flights.",
    }


def test_superseded_memories_excluded_from_context_after_restart(tmp_path):
    agent_a = sqlite_agent(tmp_path)
    agent_a.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent_a.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer window seats now."
    )

    agent_b = sqlite_agent(tmp_path)
    agent_b.chat(user_id="u1", session_id="s3", message="Help me book a trip.")
    final_context = [
        e for e in agent_b.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload["context_messages"]
    context_text = " ".join(m["content"] for m in final_context)
    assert "Prefers window seats." in context_text
    assert "Prefers aisle seats." not in context_text
    superseded = agent_b.memories_for_user("u1", status=MemoryStatus.SUPERSEDED)
    assert [m.text for m in superseded] == ["Prefers aisle seats."]
