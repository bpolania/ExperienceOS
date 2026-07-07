"""Dashboard support logic tests (no Streamlit required)."""

import pytest

from demo.support import (
    PROVIDER_MOCK,
    PROVIDER_QWEN,
    create_agent,
    make_provider,
    provider_status,
    summarize_event,
    superseded_rows,
    supplied_context_lines,
)
from experienceos.events import EventType
from experienceos.providers import MockProvider, QwenCloudProvider


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("QWEN_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_default_provider_is_mock():
    assert isinstance(make_provider(), MockProvider)
    assert isinstance(make_provider(PROVIDER_MOCK), MockProvider)


def test_qwen_without_credentials_reports_missing_without_raising(clean_env):
    provider = make_provider(PROVIDER_QWEN)
    assert isinstance(provider, QwenCloudProvider)
    assert provider_status(provider) == "Missing credentials"


def test_qwen_with_credentials_reports_configured(clean_env):
    clean_env.setenv("QWEN_API_KEY", "k")
    assert provider_status(make_provider(PROVIDER_QWEN)) == "Configured"


def test_mock_status():
    assert provider_status(MockProvider()) == "Offline demo mode"


def test_make_memory_store_defaults_to_in_memory():
    from demo.support import STORAGE_SQLITE, make_memory_store, storage_status
    from experienceos.memory import InMemoryMemoryStore, SQLiteMemoryStore

    assert isinstance(make_memory_store(), InMemoryMemoryStore)
    assert storage_status(make_memory_store()) == ("In-memory", "none")


def test_make_memory_store_sqlite(tmp_path):
    from demo.support import STORAGE_SQLITE, make_memory_store, storage_status
    from experienceos.memory import SQLiteMemoryStore

    db_path = str(tmp_path / "demo.sqlite3")
    store = make_memory_store(STORAGE_SQLITE, db_path=db_path)
    assert isinstance(store, SQLiteMemoryStore)
    assert storage_status(store) == ("SQLite", db_path)


def test_create_agent_accepts_persistent_store(tmp_path):
    from demo.support import STORAGE_SQLITE, make_memory_store

    db_path = str(tmp_path / "demo.sqlite3")
    agent = create_agent(
        MockProvider(), make_memory_store(STORAGE_SQLITE, db_path=db_path)
    )
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    fresh = create_agent(
        MockProvider(), make_memory_store(STORAGE_SQLITE, db_path=db_path)
    )
    assert [m.text for m in fresh.memories_for_user("u1")] == ["Prefers aisle seats."]


def test_create_agent_is_fresh():
    agent = create_agent(MockProvider())
    assert agent.events == []
    assert agent.memories_for_user("demo-user") == []


def test_context_built_event_supports_dashboard():
    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    built = [e for e in agent.events if e.type == EventType.CONTEXT_BUILT]
    assert built[-1].payload["memory_count"] == 1
    assert isinstance(built[-1].payload["context_messages"], list)


def test_supplied_context_lines_show_retrieved_experience():
    agent = create_agent(MockProvider())
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="I prefer aisle seats and morning flights.",
    )
    assert supplied_context_lines(agent.events) == []
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    # Selection ranks memories (relevance, kind, recency), so compare as a set.
    assert set(supplied_context_lines(agent.events)) == {
        "Prefers aisle seats.",
        "Prefers morning flights.",
    }


def test_superseded_rows_resolve_replacement():
    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer window seats now."
    )
    rows = superseded_rows(agent, "u1")
    assert len(rows) == 1
    assert rows[0]["Memory"] == "Prefers aisle seats."
    assert rows[0]["Replaced by"] == "Prefers window seats."
    assert rows[0]["Status"] == "superseded"


def test_summarize_superseded_event():
    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer window seats now."
    )
    superseded = [
        e for e in agent.events if e.type == EventType.MEMORY_SUPERSEDED
    ]
    assert summarize_event(superseded[0]) == "Superseded: Prefers aisle seats."


def test_forgotten_rows_show_reason_and_time():
    from demo.support import forgotten_rows

    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my aisle seat preference."
    )
    rows = forgotten_rows(agent, "u1")
    assert len(rows) == 1
    assert rows[0]["Memory"] == "Prefers aisle seats."
    assert rows[0]["Kind"] == "preference"
    assert rows[0]["Status"] == "forgotten"
    assert rows[0]["Reason"] == "User asked to forget this experience."
    assert rows[0]["Forgotten at"] != "—"


def test_summarize_forgotten_event():
    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(
        user_id="u1", session_id="s2", message="Forget my aisle seat preference."
    )
    forgotten = [
        e for e in agent.events if e.type == EventType.MEMORY_FORGOTTEN
    ]
    assert summarize_event(forgotten[0]) == "Forgotten: Prefers aisle seats."


def test_selection_summary_reports_budget_and_counts():
    from demo.support import selection_summary

    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    summary = selection_summary(agent.events)
    assert summary == {
        "memory_budget": 4,
        "candidates": 1,
        "selected": 1,
        "skipped": 0,
    }


def test_scripted_demo_covers_full_lifecycle():
    from demo.demo_config import SCRIPTED_DEMO
    from demo.support import selection_records

    agent = create_agent(MockProvider())
    for session_id, message in SCRIPTED_DEMO:
        agent.chat(user_id="demo-user", session_id=session_id, message=message)

    active = {(m.kind, m.text) for m in agent.memories_for_user("demo-user")}
    assert active == {
        ("preference", "Prefers evening flights."),
        ("fact", "Home airport is SFO."),
        ("fact", "Company is based in San Jose."),
        ("instruction", "Include airport transfer time when planning work trips."),
    }
    superseded = agent.memories_for_user("demo-user", status="superseded")
    assert [m.text for m in superseded] == ["Prefers morning flights."]
    forgotten = agent.memories_for_user("demo-user", status="forgotten")
    assert [m.text for m in forgotten] == ["Prefers aisle seats."]

    event_types = {e.type for e in agent.events}
    assert EventType.MEMORY_CREATED in event_types
    assert EventType.MEMORY_SUPERSEDED in event_types
    assert EventType.MEMORY_FORGOTTEN in event_types
    assert EventType.MEMORY_RETRIEVED in event_types

    # The final planning turn selects only current experience.
    records = selection_records(agent.events)
    assert records, "final turn should produce selection records"
    selected_texts = {r["text"] for r in records if r["selected"]}
    assert "Prefers aisle seats." not in selected_texts
    assert "Prefers morning flights." not in selected_texts
    assert "Prefers evening flights." in selected_texts


def test_scripted_demo_mid_run_shows_skipping():
    from demo.demo_config import SCRIPTED_DEMO
    from demo.support import selection_summary

    agent = create_agent(MockProvider())
    # Run through the first planning turn (5 memories > budget 4).
    for session_id, message in SCRIPTED_DEMO[:5]:
        agent.chat(user_id="demo-user", session_id=session_id, message=message)
    summary = selection_summary(agent.events)
    assert summary["candidates"] == 5
    assert summary["selected"] == 4
    assert summary["skipped"] == 1


def test_summarize_event_reads_well():
    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    summaries = {e.type: summarize_event(e) for e in agent.events}
    assert summaries[EventType.MEMORY_CREATED] == "Prefers aisle seats."
    assert summaries[EventType.MEMORY_RETRIEVED] == "0 active memories retrieved."
    assert summaries[EventType.CONTEXT_BUILT] == "Context built: 0 selected, 0 skipped."
    assert "mock called with" in summaries[EventType.MODEL_CALLED]
