"""Dashboard state-hardening tests: empty, missing, and rebuilt state."""

from demo.demo_config import DEMO_USER_ID
from demo.support import (
    active_memory_rows,
    compressed_summaries,
    compression_totals,
    create_agent,
    forgotten_rows,
    growth_metrics,
    lifecycle_timeline,
    reset_demo_state,
    safe_memory_domain,
    safe_memory_metadata,
    safe_memory_tags,
    selection_records,
    selection_rows,
    selection_summary,
    summarize_selection_record,
    summary_display,
    superseded_rows,
    supplied_context_lines,
)
from experienceos.memory import ExperienceEntry
from experienceos.providers import MockProvider


def test_helpers_tolerate_empty_agent():
    agent = create_agent(MockProvider())
    assert active_memory_rows(agent, DEMO_USER_ID) == []
    assert superseded_rows(agent, DEMO_USER_ID) == []
    assert forgotten_rows(agent, DEMO_USER_ID) == []
    assert selection_records(agent.events) == []
    assert selection_rows([]) == []
    assert compressed_summaries(agent.events) == []
    assert supplied_context_lines(agent.events) == []
    assert lifecycle_timeline(agent.events) == []
    assert selection_summary(agent.events) is None
    metrics = growth_metrics(agent, DEMO_USER_ID)
    assert metrics["active_memories"] == 0
    assert metrics["context_saved_chars"] == 0


def test_safe_metadata_helpers_handle_missing_and_broken_metadata():
    plain = ExperienceEntry(user_id="u1", text="Prefers aisle seats.")
    assert safe_memory_metadata(plain) == {}
    assert safe_memory_tags(plain) == []
    assert safe_memory_domain(plain) is None

    broken = ExperienceEntry(user_id="u1", text="Broken.")
    broken.metadata = None
    assert safe_memory_metadata(broken) == {}
    assert safe_memory_tags(broken) == []
    assert safe_memory_domain(broken) is None

    odd = ExperienceEntry(user_id="u1", text="Odd.")
    odd.metadata = {"tags": "not-a-list", "domain": ""}
    assert safe_memory_tags(odd) == []
    assert safe_memory_domain(odd) is None

    tagged = ExperienceEntry(user_id="u1", text="Tagged.")
    tagged.metadata = {"tags": ["travel", "seat"], "domain": "travel"}
    assert safe_memory_tags(tagged) == ["travel", "seat"]
    assert safe_memory_domain(tagged) == "travel"


def test_active_rows_render_memories_without_tags():
    agent = create_agent(MockProvider())
    entry = ExperienceEntry(user_id=DEMO_USER_ID, text="Untagged memory.")
    entry.metadata = None
    agent.memory_store.add(entry)
    rows = active_memory_rows(agent, DEMO_USER_ID)
    assert rows[0]["Tags"] == "—"
    assert rows[0]["Source session"] == "—"


def test_lifecycle_rows_tolerate_missing_metadata():
    agent = create_agent(MockProvider())
    superseded = ExperienceEntry(
        user_id=DEMO_USER_ID, text="Old.", status="superseded"
    )
    superseded.metadata = None
    forgotten = ExperienceEntry(
        user_id=DEMO_USER_ID, text="Gone.", status="forgotten"
    )
    forgotten.metadata = None
    agent.memory_store.add(superseded)
    agent.memory_store.add(forgotten)

    s_rows = superseded_rows(agent, DEMO_USER_ID)
    assert s_rows[0]["Replaced by"] == "—"
    f_rows = forgotten_rows(agent, DEMO_USER_ID)
    assert f_rows[0]["Reason"] == "—"
    assert f_rows[0]["Forgotten at"] == "—"


def test_selection_rows_tolerate_missing_fields():
    rows = selection_rows(
        [
            {"selected": True, "text": "Something."},
            {"selected": False},
        ]
    )
    assert rows[0]["Decision"] == "Selected"
    assert rows[0]["Rank"] == "—"
    assert rows[0]["Matched keywords"] == ""
    assert rows[0]["Domains"] == "—"
    assert rows[0]["Reason"] == "—"
    assert rows[1]["Decision"] == "Skipped"
    assert rows[1]["Memory"] == ""
    assert selection_rows(None) == []
    # The summary line helper is equally tolerant.
    assert summarize_selection_record({"selected": False}) == "Skipped:  — "


def test_summary_display_tolerates_missing_fields():
    display = summary_display({"text": "Travel experience summary:\nBody."})
    assert display["source_texts"] == []
    assert display["saved_chars"] == 0
    assert summary_display(None)["text"] == ""
    assert compression_totals([summary_display(None)])["count"] == 1


def test_reset_leaves_helpers_in_safe_empty_state():
    agent = create_agent(MockProvider())
    agent.chat(
        user_id=DEMO_USER_ID, session_id="s1", message="I prefer aisle seats."
    )
    agent.chat(user_id=DEMO_USER_ID, session_id="s2", message="Book a trip.")
    assert selection_records(agent.events)

    reset_demo_state(agent, DEMO_USER_ID)
    assert active_memory_rows(agent, DEMO_USER_ID) == []
    assert selection_rows(selection_records(agent.events)) == []
    assert compressed_summaries(agent.events) == []
    assert supplied_context_lines(agent.events) == []
    assert lifecycle_timeline(agent.events) == []


def test_rebuilt_agent_has_no_stale_display_state():
    old_agent = create_agent(MockProvider())
    old_agent.chat(
        user_id=DEMO_USER_ID, session_id="s1", message="I prefer aisle seats."
    )
    assert old_agent.events

    # A sidebar provider/storage switch constructs a fresh agent; no
    # selected/skipped/compressed display state may carry over.
    new_agent = create_agent(MockProvider())
    assert new_agent.events == []
    assert selection_records(new_agent.events) == []
    assert compressed_summaries(new_agent.events) == []
    assert lifecycle_timeline(new_agent.events) == []
    assert growth_metrics(new_agent, DEMO_USER_ID)["created_memories"] == 0
