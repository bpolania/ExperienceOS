"""Fact and instruction memory kind tests: detection, grouping, persistence."""

from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory import MemoryKind, MemoryStatus, SQLiteMemoryStore
from experienceos.providers import MockProvider


def make_agent(**kwargs):
    return ExperienceOS(model=MockProvider(), **kwargs)


def texts_by_kind(agent, user_id="u1"):
    grouped = {}
    for m in agent.memories_for_user(user_id):
        grouped.setdefault(m.kind, []).append(m.text)
    return grouped


def test_fact_from_home_airport():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    assert texts_by_kind(agent) == {MemoryKind.FACT: ["Home airport is SFO."]}


def test_fact_from_work_location():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I work out of Santa Clara.")
    assert texts_by_kind(agent) == {MemoryKind.FACT: ["Works out of Santa Clara."]}


def test_fact_from_live_near_and_company():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I live near San Francisco.")
    agent.chat(
        user_id="u1", session_id="s1", message="My company is based in San Jose."
    )
    assert texts_by_kind(agent) == {
        MemoryKind.FACT: [
            "Lives near San Francisco.",
            "Company is based in San Jose.",
        ]
    }


def test_instruction_from_remember_to():
    agent = make_agent()
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="Remember to keep travel plans concise.",
    )
    assert texts_by_kind(agent) == {
        MemoryKind.INSTRUCTION: ["Keep travel plans concise."]
    }


def test_instruction_from_from_now_on():
    agent = make_agent()
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="From now on, give me options with estimated tradeoffs.",
    )
    assert texts_by_kind(agent) == {
        MemoryKind.INSTRUCTION: ["Give options with estimated tradeoffs."]
    }


def test_instruction_from_when_clause():
    agent = make_agent()
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="When planning work trips, include airport transfer time.",
    )
    assert texts_by_kind(agent) == {
        MemoryKind.INSTRUCTION: [
            "Include airport transfer time when planning work trips."
        ]
    }


def test_instruction_from_always_and_trailing_from_now_on():
    agent = make_agent()
    agent.chat(
        user_id="u1", session_id="s1", message="Always include airport transfer time."
    )
    agent.chat(
        user_id="u1",
        session_id="s2",
        message="Please keep recommendations concise from now on.",
    )
    assert texts_by_kind(agent) == {
        MemoryKind.INSTRUCTION: [
            "Include airport transfer time.",
            "Keep recommendations concise.",
        ]
    }


def test_kind_persists_in_sqlite(tmp_path):
    db = tmp_path / "kinds.sqlite3"
    agent = ExperienceOS.with_sqlite_memory(model=MockProvider(), db_path=db)
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="Remember to keep travel plans concise.",
    )
    reloaded = SQLiteMemoryStore(db).active_for_user("u1")
    assert {(m.kind, m.text) for m in reloaded} == {
        (MemoryKind.PREFERENCE, "Prefers aisle seats."),
        (MemoryKind.FACT, "Home airport is SFO."),
        (MemoryKind.INSTRUCTION, "Keep travel plans concise."),
    }


def test_context_groups_memories_by_kind():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="When planning work trips, include airport transfer time.",
    )
    agent.chat(
        user_id="u1", session_id="s2", message="Help me plan a work trip to New York."
    )
    final_context = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload["context_messages"]
    memory_block = next(
        m["content"] for m in final_context if "Preferences:" in m["content"]
    )
    assert "Preferences:\n- Prefers aisle seats." in memory_block
    assert "Facts:\n- Home airport is SFO." in memory_block
    assert (
        "Instructions:\n- Include airport transfer time when planning work trips."
        in memory_block
    )
    assert memory_block.index("Preferences:") < memory_block.index("Facts:")
    assert memory_block.index("Facts:") < memory_block.index("Instructions:")


def test_preference_conflict_does_not_cross_kinds():
    agent = make_agent()
    agent.chat(
        user_id="u1", session_id="s1", message="My favorite seat is the window seat."
    )
    agent.chat(user_id="u1", session_id="s2", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s3", message="I prefer window seats now.")
    grouped = texts_by_kind(agent)
    # The fact is untouched; only the preference was superseded.
    assert grouped[MemoryKind.FACT] == ["Favorite seat is the window seat."]
    assert grouped[MemoryKind.PREFERENCE] == ["Prefers window seats."]
    superseded = agent.memories_for_user("u1", status=MemoryStatus.SUPERSEDED)
    assert [m.text for m in superseded] == ["Prefers aisle seats."]


def test_duplicate_fact_not_created():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    agent.chat(user_id="u1", session_id="s2", message="My home airport is SFO.")
    assert texts_by_kind(agent) == {MemoryKind.FACT: ["Home airport is SFO."]}


def test_duplicate_instruction_not_created():
    agent = make_agent()
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="Remember to keep travel plans concise.",
    )
    agent.chat(
        user_id="u1",
        session_id="s2",
        message="Remember to keep travel plans concise.",
    )
    assert texts_by_kind(agent) == {
        MemoryKind.INSTRUCTION: ["Keep travel plans concise."]
    }


def test_memory_created_events_carry_kind():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    agent.chat(
        user_id="u1",
        session_id="s1",
        message="Remember to keep travel plans concise.",
    )
    kinds = [
        e.payload["kind"]
        for e in agent.events
        if e.type == EventType.MEMORY_CREATED
    ]
    assert kinds == [MemoryKind.FACT, MemoryKind.INSTRUCTION]


def test_facts_can_be_forgotten():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    agent.chat(user_id="u1", session_id="s2", message="Forget my home airport.")
    assert agent.memories_for_user("u1") == []
    assert [
        m.text for m in agent.memories_for_user("u1", status=MemoryStatus.FORGOTTEN)
    ] == ["Home airport is SFO."]


def test_first_person_statements_are_not_instructions():
    agent = make_agent()
    agent.chat(
        user_id="u1", session_id="s1", message="From now on, I prefer window seats."
    )
    grouped = texts_by_kind(agent)
    assert MemoryKind.INSTRUCTION not in grouped
    assert grouped[MemoryKind.PREFERENCE] == ["Prefers window seats."]