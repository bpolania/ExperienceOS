"""Lifecycle edge cases most likely to break the live demo.

Each test proves that inactive memories cannot leak back into
retrieval, selection, compression, or final context — and that the
supporting machinery (reset, tie ordering, metadata persistence)
behaves deterministically.
"""

from datetime import datetime, timezone

from demo.demo_config import DEMO_USER_ID
from demo.support import create_agent, reset_demo_state
from experienceos import ExperienceOS
from experienceos.context import ContextBuilder
from experienceos.events import EventType
from experienceos.memory import ExperienceEntry, MemoryStatus
from experienceos.providers import MockProvider


def chat_all(agent, messages, user_id="u1"):
    for i, message in enumerate(messages):
        agent.chat(user_id=user_id, session_id=f"s-{i}", message=message)
    return agent


def last_context_built(agent):
    return [e for e in agent.events if e.type == EventType.CONTEXT_BUILT][-1].payload


def context_text(payload):
    return " ".join(m["content"] for m in payload["context_messages"])


TRAVEL_SEED = [
    "I prefer aisle seats.",
    "I prefer evening flights.",
    "I prefer quiet hotels near the airport.",
    "My home airport is SFO.",
    "When planning work trips, include airport transfer time.",
]


def test_forgotten_memories_are_not_compressed():
    agent = chat_all(create_agent(MockProvider()), TRAVEL_SEED)
    forgotten_id = next(
        m.id for m in agent.memories_for_user("u1") if "aisle" in m.text
    )
    agent.chat(
        user_id="u1", session_id="forget", message="Forget my aisle seat preference."
    )
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = last_context_built(agent)
    summaries = payload["compressed_summaries"]
    assert summaries, "scenario should trigger compression"
    for summary in summaries:
        assert forgotten_id not in summary["source_memory_ids"]
        assert "Prefers aisle seats." not in summary["source_texts"]
        assert "aisle" not in summary["text"].lower()


def test_superseded_memories_are_not_compressed():
    agent = chat_all(create_agent(MockProvider()), TRAVEL_SEED)
    superseded_id = next(
        m.id for m in agent.memories_for_user("u1") if "evening" in m.text
    )
    agent.chat(
        user_id="u1",
        session_id="update",
        message="Actually, I prefer morning flights now.",
    )
    replacement_id = next(
        m.id for m in agent.memories_for_user("u1") if "morning" in m.text
    )
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = last_context_built(agent)
    summaries = payload["compressed_summaries"]
    assert summaries, "scenario should trigger compression"
    all_sources = {i for s in summaries for i in s["source_memory_ids"]}
    assert superseded_id not in all_sources
    assert replacement_id in all_sources
    assert "Prefers evening flights." not in summaries[0]["source_texts"]


def test_forgotten_memories_are_not_selected():
    agent = chat_all(create_agent(MockProvider()), TRAVEL_SEED)
    forgotten_id = next(
        m.id for m in agent.memories_for_user("u1") if "evening" in m.text
    )
    agent.chat(
        user_id="u1",
        session_id="forget",
        message="Forget my evening flight preference.",
    )
    # The request would strongly match the forgotten memory if it leaked.
    agent.chat(user_id="u1", session_id="ask", message="Book me an evening flight.")
    payload = last_context_built(agent)
    assert forgotten_id not in payload["candidate_memory_ids"]
    assert forgotten_id not in payload["selected_memory_ids"]
    assert "Prefers evening flights." not in context_text(payload)


def test_superseded_memories_are_not_selected():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer morning flights.")
    superseded_id = agent.memories_for_user("u1")[0].id
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer evening flights."
    )
    # The request wording favors the OLD memory; it must still stay retired.
    agent.chat(user_id="u1", session_id="ask", message="Book me a morning flight.")
    payload = last_context_built(agent)
    assert superseded_id not in payload["candidate_memory_ids"]
    assert superseded_id not in payload["selected_memory_ids"]
    text = context_text(payload)
    assert "Prefers morning flights." not in text
    assert "Prefers evening flights." in text


def test_fact_update_retrieval_uses_new_fact():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    old_id = agent.memories_for_user("u1")[0].id
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, my home airport is now SJC."
    )
    agent.chat(
        user_id="u1", session_id="ask", message="Book a flight from my home airport."
    )
    payload = last_context_built(agent)
    assert old_id not in payload["candidate_memory_ids"]
    text = context_text(payload)
    assert "Home airport is SJC." in text
    assert "SFO" not in text
    old = agent.memory_store.get(old_id)
    assert old.status == MemoryStatus.SUPERSEDED


def test_instruction_update_retrieval_uses_new_instruction():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(
        user_id="u1", session_id="s1", message="From now on, keep trip notes brief."
    )
    old_id = agent.memories_for_user("u1")[0].id
    agent.chat(
        user_id="u1",
        session_id="s2",
        message="Going forward, give detailed trip notes.",
    )
    agent.chat(user_id="u1", session_id="ask", message="Plan a trip for me.")
    payload = last_context_built(agent)
    assert old_id not in payload["candidate_memory_ids"]
    text = context_text(payload)
    assert "Give detailed trip notes." in text
    assert "Keep trip notes brief." not in text
    assert agent.memory_store.get(old_id).status == MemoryStatus.SUPERSEDED


def test_preference_update_then_forget_does_not_resurrect_old_memory():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer morning flights.")
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer evening flights."
    )
    agent.chat(
        user_id="u1",
        session_id="s3",
        message="Forget my evening flight preference.",
    )
    # Neither the superseded original nor the forgotten replacement may
    # come back — forgetting must not fall back to older experience.
    agent.chat(user_id="u1", session_id="ask", message="Book me a flight.")
    payload = last_context_built(agent)
    assert payload["candidate_memory_ids"] == []
    text = context_text(payload)
    assert "morning flights" not in text
    assert "evening flights" not in text
    statuses = {
        m.text: m.status for m in agent.memories_for_user("u1", status=None)
    }
    assert statuses == {
        "Prefers morning flights.": MemoryStatus.SUPERSEDED,
        "Prefers evening flights.": MemoryStatus.FORGOTTEN,
    }


def test_reset_removes_inactive_demo_history():
    agent = create_agent(MockProvider())
    chat_all(
        agent,
        [
            "I prefer morning flights.",
            "Actually, I prefer evening flights.",
            "Forget my evening flight preference.",
        ],
        user_id=DEMO_USER_ID,
    )
    agent.chat(
        user_id="other-user", session_id="o1", message="I prefer window seats."
    )
    assert agent.memories_for_user(DEMO_USER_ID, status=MemoryStatus.SUPERSEDED)
    assert agent.memories_for_user(DEMO_USER_ID, status=MemoryStatus.FORGOTTEN)

    reset_demo_state(agent, DEMO_USER_ID)
    assert agent.memories_for_user(DEMO_USER_ID, status=None) == []
    # Reset is user-scoped: the other user's memory is untouched.
    assert [m.text for m in agent.memories_for_user("other-user")] == [
        "Prefers window seats."
    ]


def test_context_selection_is_stable_when_scores_tie():
    # Identical timestamps, kinds, and zero keyword overlap: ordering
    # must fall through to the stable id tie-break.
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries = [
        ExperienceEntry(
            user_id="u1",
            text=f"Prefers option {c}.",
            created_at=fixed,
            updated_at=fixed,
        )
        for c in "abcdef"
    ]
    builder = ContextBuilder(memory_budget=3)

    first_selected, first_skipped = builder.select_memories("hello", list(entries))
    again_selected, again_skipped = builder.select_memories("hello", list(entries))
    reversed_selected, reversed_skipped = builder.select_memories(
        "hello", list(reversed(entries))
    )

    assert [m.id for m in first_selected] == [m.id for m in again_selected]
    assert [m.id for m in first_skipped] == [m.id for m in again_skipped]
    # Input order must not influence the outcome.
    assert [m.id for m in first_selected] == [m.id for m in reversed_selected]
    assert [m.id for m in first_skipped] == [m.id for m in reversed_skipped]


def test_tags_and_domains_survive_sqlite_persistence(tmp_path):
    db_path = str(tmp_path / "tags-edge.sqlite3")
    first = ExperienceOS.with_sqlite_memory(model=MockProvider(), db_path=db_path)
    first.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")

    reopened = ExperienceOS.with_sqlite_memory(
        model=MockProvider(), db_path=db_path
    )
    memory = reopened.memories_for_user("u1")[0]
    assert memory.metadata["tags"] == ["travel", "airport"]
    assert memory.metadata["domain"] == "travel"

    # Persisted tags remain usable by selection explanations.
    reopened.chat(user_id="u1", session_id="ask", message="Book me a flight.")
    record = last_context_built(reopened)["selection_records"][0]
    assert record["tags"] == ["travel", "airport"]
    assert record["matched_domains"] == ["travel"]
