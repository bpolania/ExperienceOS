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
        "memory_budget": 6,  # demo path uses a slightly larger budget
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
        ("preference", "Dislikes red-eye flights."),
        ("preference", "Prefers quiet hotels near the airport."),
        ("fact", "Home airport is SJC."),
        ("fact", "Company is based in San Jose."),
        ("instruction", "Include airport transfer time when planning work trips."),
    }
    superseded = agent.memories_for_user("demo-user", status="superseded")
    assert {m.text for m in superseded} == {
        "Prefers morning flights.",
        "Home airport is SFO.",
    }
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
    # Run through the first planning turn (7 memories > demo budget 6).
    for session_id, message in SCRIPTED_DEMO[:6]:
        agent.chat(user_id="demo-user", session_id=session_id, message=message)
    summary = selection_summary(agent.events)
    assert summary["candidates"] == 7
    assert summary["selected"] == 6
    assert summary["skipped"] == 1


def run_scripted_demo():
    from demo.demo_config import SCRIPTED_DEMO

    agent = create_agent(MockProvider())
    for session_id, message in SCRIPTED_DEMO:
        agent.chat(user_id="demo-user", session_id=session_id, message=message)
    return agent


def test_demo_agent_enables_compression_but_sdk_default_does_not():
    from experienceos import ExperienceOS

    assert create_agent(MockProvider()).context_builder.compressor is not None
    assert ExperienceOS(model=MockProvider()).context_builder.compressor is None


def test_compressed_summaries_helper_exposes_latest_turn():
    from demo.support import compressed_summaries

    agent = run_scripted_demo()
    summaries = compressed_summaries(agent.events)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["text"].startswith("Travel experience summary:")
    assert "Home airport is SJC." in summary["source_texts"]
    assert "Prefers evening flights." in summary["source_texts"]
    assert len(summary["source_memory_ids"]) == len(summary["source_texts"])
    assert summary["saved_chars"] > 0
    assert summary["reason"]
    # Superseded and forgotten memories never appear as sources.
    assert "Home airport is SFO." not in summary["source_texts"]
    assert "Prefers morning flights." not in summary["source_texts"]
    assert "Prefers aisle seats." not in summary["source_texts"]


def test_compression_totals_aggregates():
    from demo.support import compressed_summaries, compression_totals

    agent = run_scripted_demo()
    summaries = compressed_summaries(agent.events)
    totals = compression_totals(summaries)
    assert totals["count"] == 1
    assert totals["source_count"] == len(summaries[0]["source_memory_ids"])
    assert (
        totals["saved_chars"]
        == totals["original_chars"] - totals["compressed_chars"]
    )
    assert totals["saved_chars"] > 0


def test_no_compression_turn_is_clean():
    from demo.support import compressed_summaries, compression_totals

    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    assert compressed_summaries(agent.events) == []
    totals = compression_totals([])
    assert totals == {
        "count": 0,
        "source_count": 0,
        "original_chars": 0,
        "compressed_chars": 0,
        "saved_chars": 0,
    }
    built = [e for e in agent.events if e.type == EventType.CONTEXT_BUILT][-1]
    assert summarize_event(built) == "Context built: 1 selected, 0 skipped."


def test_summarize_event_mentions_compression():
    agent = run_scripted_demo()
    built = [e for e in agent.events if e.type == EventType.CONTEXT_BUILT][-1]
    summary = summarize_event(built)
    assert summary.startswith("Context built: 6 selected, 0 skipped.")
    assert "5 memories compressed into 1 summary" in summary
    assert "saved" in summary


def test_growth_metrics_from_scripted_demo():
    from demo.support import growth_metrics

    agent = run_scripted_demo()
    metrics = growth_metrics(agent, "demo-user")
    assert metrics["active_memories"] == 6
    assert metrics["created_memories"] == 9  # 7 originals + 2 replacements
    assert metrics["updated_memories"] == 2  # airport fact + flight preference
    assert metrics["forgotten_memories"] == 1
    assert metrics["recalls"] >= 5
    assert metrics["compressed_summaries_used"] >= 1
    assert metrics["context_saved_chars"] >= 1


def test_growth_metrics_exact_small_flow():
    from demo.support import growth_metrics

    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    assert growth_metrics(agent, "u1") == {
        "active_memories": 1,
        "created_memories": 1,
        "recalls": 1,
        "updated_memories": 0,
        "forgotten_memories": 0,
        "compressed_summaries_used": 0,
        "context_saved_chars": 0,
    }


def test_growth_metrics_empty_agent():
    from demo.support import growth_metrics, lifecycle_timeline

    agent = create_agent(MockProvider())
    metrics = growth_metrics(agent, "u1")
    assert metrics["active_memories"] == 0
    assert metrics["created_memories"] == 0
    assert lifecycle_timeline(agent.events) == []


def test_lifecycle_timeline_from_scripted_demo():
    from demo.support import lifecycle_timeline

    agent = run_scripted_demo()
    rows = lifecycle_timeline(agent.events)
    events = [(r["Event"], r["Summary"]) for r in rows]

    assert ("Remembered", "Prefers aisle seats.") in events
    assert ("Remembered", "Home airport is SFO.") in events
    assert (
        "Updated",
        "Home airport is SFO. → Home airport is SJC.",
    ) in events
    assert (
        "Updated",
        "Prefers morning flights. → Prefers evening flights.",
    ) in events
    assert ("Forgot", "Prefers aisle seats.") in events
    # Replacements do not double-report as "Remembered".
    assert ("Remembered", "Home airport is SJC.") not in events
    # Recall and compression rows appear.
    assert any(r["Event"] == "Recalled" for r in rows)
    compressed_rows = [r for r in rows if r["Event"] == "Compressed"]
    assert compressed_rows
    assert "saved" in compressed_rows[0]["Summary"]
    # Turns are 1-based and non-decreasing.
    turns = [r["Turn"] for r in rows]
    assert turns[0] == 1
    assert turns == sorted(turns)


def test_lifecycle_timeline_recall_row_counts():
    from demo.support import lifecycle_timeline

    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    rows = lifecycle_timeline(agent.events)
    assert rows == [
        {"Turn": 1, "Event": "Remembered", "Summary": "Prefers aisle seats."},
        {"Turn": 2, "Event": "Recalled", "Summary": "1 selected, 0 skipped"},
    ]


def test_summarize_event_reads_well():
    agent = create_agent(MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    summaries = {e.type: summarize_event(e) for e in agent.events}
    assert summaries[EventType.MEMORY_CREATED] == "Prefers aisle seats."
    assert summaries[EventType.MEMORY_RETRIEVED] == "0 active memories retrieved."
    assert summaries[EventType.CONTEXT_BUILT] == "Context built: 0 selected, 0 skipped."
    assert "mock called with" in summaries[EventType.MODEL_CALLED]
