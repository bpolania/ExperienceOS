"""Experience compression tests: grouping, summaries, lifecycle exclusion."""

from experienceos import ExperienceOS
from experienceos.context import ContextBuilder, ExperienceCompressor
from experienceos.events import EventType
from experienceos.memory import ExperienceEntry, MemoryKind, MemoryStatus
from experienceos.providers import MockProvider

TRAVEL_MESSAGES = [
    "I prefer aisle seats.",
    "I prefer evening flights.",
    "I don't like red-eye flights.",
    "My home airport is SFO.",
    "When planning work trips, include airport transfer time.",
]


def travel_entries():
    return [
        ExperienceEntry(user_id="u1", text="Prefers aisle seats."),
        ExperienceEntry(user_id="u1", text="Prefers evening flights."),
        ExperienceEntry(user_id="u1", text="Dislikes red-eye flights."),
        ExperienceEntry(user_id="u1", text="Home airport is SFO.", kind=MemoryKind.FACT),
        ExperienceEntry(
            user_id="u1",
            text="Include airport transfer time when planning work trips.",
            kind=MemoryKind.INSTRUCTION,
        ),
    ]


def compressing_agent(memory_budget=8):
    builder = ContextBuilder(
        memory_budget=memory_budget, compressor=ExperienceCompressor()
    )
    return ExperienceOS(model=MockProvider(), context_builder=builder)


def last_context_built(agent):
    return [e for e in agent.events if e.type == EventType.CONTEXT_BUILT][-1].payload


def test_related_memories_produce_travel_summary():
    summaries = ExperienceCompressor().compress(travel_entries())
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.domain == "travel"
    assert summary.text.startswith("Travel experience summary:\n")
    assert "The user's home airport is SFO." in summary.text
    body = summary.text.lower()
    assert "prefer aisle seats" in body
    assert "prefer evening flights" in body
    assert "avoid red-eye flights" in body
    assert "include airport transfer time when planning work trips" in body


def test_summary_tracks_source_memories_and_savings():
    entries = travel_entries()
    summary = ExperienceCompressor().compress(entries)[0]
    assert set(summary.source_memory_ids) == {m.id for m in entries}
    assert summary.source_texts == [m.text for m in entries]
    assert summary.reason
    payload = summary.to_payload()
    assert payload["saved_chars"] == payload["original_chars"] - payload["compressed_chars"]


def test_context_builder_uses_compressed_summary():
    builder = ContextBuilder(memory_budget=8, compressor=ExperienceCompressor())
    result = builder.build_context("u1", "s1", "Plan a trip.", memories=travel_entries())
    assert len(result.summaries) == 1
    rendered = " ".join(m["content"] for m in result.messages)
    assert "Travel experience summary:" in rendered
    # Individual bullets for compressed memories are gone from context.
    assert "- Prefers aisle seats." not in rendered
    assert "- Home airport is SFO." not in rendered
    # Compression only used because it genuinely shrinks the context.
    assert result.summaries[0].saved_chars > 0


def test_selection_explanations_preserved_with_compression():
    agent = compressing_agent()
    for i, message in enumerate(TRAVEL_MESSAGES):
        agent.chat(user_id="u1", session_id=f"s-{i}", message=message)
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = last_context_built(agent)
    assert len(payload["selection_records"]) == 5
    assert {r["memory_id"] for r in payload["selection_records"]} == set(
        payload["candidate_memory_ids"]
    )
    summaries = payload["compressed_summaries"]
    assert len(summaries) == 1
    assert set(summaries[0]["source_memory_ids"]) <= set(
        payload["selected_memory_ids"]
    )
    assert summaries[0]["saved_chars"] > 0


def test_source_memories_remain_stored_and_unchanged():
    agent = compressing_agent()
    for i, message in enumerate(TRAVEL_MESSAGES):
        agent.chat(user_id="u1", session_id=f"s-{i}", message=message)
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    memories = agent.memories_for_user("u1")
    assert len(memories) == 5
    assert all(m.status == MemoryStatus.ACTIVE for m in memories)
    assert {m.text for m in memories} == {
        "Prefers aisle seats.",
        "Prefers evening flights.",
        "Dislikes red-eye flights.",
        "Home airport is SFO.",
        "Include airport transfer time when planning work trips.",
    }


def test_forgotten_memories_excluded_from_compression():
    agent = compressing_agent()
    for i, message in enumerate(TRAVEL_MESSAGES):
        agent.chat(user_id="u1", session_id=f"s-{i}", message=message)
    agent.chat(
        user_id="u1", session_id="forget", message="Forget my aisle seat preference."
    )
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = last_context_built(agent)
    summary = payload["compressed_summaries"][0]
    assert "Prefers aisle seats." not in summary["source_texts"]
    assert "prefer aisle seats" not in summary["text"].lower()
    forgotten = agent.memories_for_user("u1", status=MemoryStatus.FORGOTTEN)
    assert [m.id for m in forgotten][0] not in summary["source_memory_ids"]


def test_superseded_memories_excluded_from_compression():
    agent = compressing_agent()
    agent.chat(user_id="u1", session_id="s1", message="I prefer morning flights.")
    agent.chat(user_id="u1", session_id="s2", message="My home airport is SFO.")
    agent.chat(
        user_id="u1",
        session_id="s3",
        message="When planning work trips, include airport transfer time.",
    )
    agent.chat(
        user_id="u1", session_id="s4", message="Actually, I prefer evening flights."
    )
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = last_context_built(agent)
    summary = payload["compressed_summaries"][0]
    assert "Prefers morning flights." not in summary["source_texts"]
    assert "prefer evening flights" in summary["text"]


def test_single_memory_not_compressed():
    builder = ContextBuilder(compressor=ExperienceCompressor())
    result = builder.build_context(
        "u1",
        "s1",
        "anything",
        memories=[ExperienceEntry(user_id="u1", text="Prefers aisle seats.")],
    )
    assert result.summaries == []
    rendered = " ".join(m["content"] for m in result.messages)
    assert "- Prefers aisle seats." in rendered


def test_non_travel_memories_use_generic_fallback():
    entries = [
        ExperienceEntry(user_id="u1", text="Likes jazz."),
        ExperienceEntry(user_id="u1", text="Likes quiet cafes."),
        ExperienceEntry(user_id="u1", text="Dislikes crowded restaurants."),
    ]
    summaries = ExperienceCompressor().compress(entries)
    assert len(summaries) == 1
    assert summaries[0].domain == MemoryKind.PREFERENCE
    assert summaries[0].text.startswith("Preference experience summary:\n")
    body = summaries[0].text.lower()
    assert "like jazz" in body
    assert "avoid crowded restaurants" in body


def test_two_non_travel_memories_stay_uncompressed():
    entries = [
        ExperienceEntry(user_id="u1", text="Likes jazz."),
        ExperienceEntry(user_id="u1", text="Likes quiet cafes."),
    ]
    assert ExperienceCompressor().compress(entries) == []


def test_compression_is_off_by_default():
    agent = ExperienceOS(model=MockProvider())
    for i, message in enumerate(TRAVEL_MESSAGES[:3]):
        agent.chat(user_id="u1", session_id=f"s-{i}", message=message)
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = last_context_built(agent)
    assert payload["compressed_summaries"] == []
    rendered = " ".join(m["content"] for m in payload["context_messages"])
    assert "- Prefers aisle seats." in rendered
    assert "experience summary" not in rendered.lower()
