"""Fact and instruction supersession tests: update keys, lineage, context."""

from experienceos import ExperienceOS
from experienceos.context import ContextBuilder, ExperienceCompressor
from experienceos.events import EventType
from experienceos.memory import MemoryKind, MemoryStatus
from experienceos.providers import MockProvider


def make_agent(**kwargs):
    return ExperienceOS(model=MockProvider(), **kwargs)


def run_sequence(agent, messages):
    for i, message in enumerate(messages):
        agent.chat(user_id="u1", session_id=f"s-{i}", message=message)
    return agent


def active_texts(agent):
    return {m.text for m in agent.memories_for_user("u1")}


def superseded_texts(agent):
    return {
        m.text for m in agent.memories_for_user("u1", status=MemoryStatus.SUPERSEDED)
    }


def test_home_airport_fact_supersession_with_lineage():
    agent = run_sequence(
        make_agent(),
        ["My home airport is SFO.", "Actually, my home airport is now SJC."],
    )
    assert active_texts(agent) == {"Home airport is SJC."}
    assert superseded_texts(agent) == {"Home airport is SFO."}
    old = agent.memories_for_user("u1", status=MemoryStatus.SUPERSEDED)[0]
    new = agent.memories_for_user("u1")[0]
    assert old.metadata["superseded_by"] == new.id
    assert new.metadata["replaces"] == old.id
    assert old.metadata["superseded_reason"]
    superseded_events = [
        e for e in agent.events if e.type == EventType.MEMORY_SUPERSEDED
    ]
    assert len(superseded_events) == 1
    assert superseded_events[0].payload["text"] == "Home airport is SFO."


def test_home_airport_trailing_now_phrasing():
    agent = run_sequence(
        make_agent(),
        ["My home airport is SFO.", "My home airport is SJC now."],
    )
    assert active_texts(agent) == {"Home airport is SJC."}
    assert superseded_texts(agent) == {"Home airport is SFO."}


def test_work_location_fact_supersession():
    agent = run_sequence(
        make_agent(),
        [
            "I work out of Santa Clara.",
            "I no longer work out of Santa Clara. I work out of San Jose now.",
        ],
    )
    assert active_texts(agent) == {"Works out of San Jose."}
    assert superseded_texts(agent) == {"Works out of Santa Clara."}


def test_company_location_fact_supersession():
    agent = run_sequence(
        make_agent(),
        [
            "My company is based in San Jose.",
            "Actually, my company is based in Oakland now.",
        ],
    )
    assert active_texts(agent) == {"Company is based in Oakland."}
    assert superseded_texts(agent) == {"Company is based in San Jose."}


def test_planning_instruction_supersession():
    agent = run_sequence(
        make_agent(),
        [
            "When planning trips, include detailed options.",
            "From now on, keep travel plans even shorter.",
        ],
    )
    assert active_texts(agent) == {"Keep travel plans even shorter."}
    assert superseded_texts(agent) == {
        "Include detailed options when planning trips."
    }


def test_travel_instruction_supersession():
    agent = run_sequence(
        make_agent(),
        [
            "From now on, keep trip notes brief.",
            "Going forward, give detailed trip notes.",
        ],
    )
    assert active_texts(agent) == {"Give detailed trip notes."}
    assert superseded_texts(agent) == {"Keep trip notes brief."}


def test_response_style_instruction_supersession():
    agent = run_sequence(
        make_agent(),
        [
            "Please give detailed explanations.",
            "Going forward, keep answers concise.",
        ],
    )
    assert active_texts(agent) == {"Keep answers concise."}
    assert superseded_texts(agent) == {"Give detailed explanations."}


def test_content_instructions_accumulate_without_superseding():
    # Content instructions in the same domain carry no update key: only
    # detail-level/style instructions supersede each other.
    agent = run_sequence(
        make_agent(),
        [
            "When planning work trips, include airport transfer time.",
            "Remember to keep travel plans concise.",
        ],
    )
    assert active_texts(agent) == {
        "Include airport transfer time when planning work trips.",
        "Keep travel plans concise.",
    }
    assert superseded_texts(agent) == set()


def test_unrelated_facts_do_not_supersede_each_other():
    agent = run_sequence(
        make_agent(),
        ["My home airport is SFO.", "My company is based in San Jose."],
    )
    assert active_texts(agent) == {
        "Home airport is SFO.",
        "Company is based in San Jose.",
    }
    assert superseded_texts(agent) == set()


def test_superseded_fact_excluded_from_active_context():
    agent = run_sequence(
        make_agent(),
        ["My home airport is SFO.", "Actually, my home airport is now SJC."],
    )
    agent.chat(user_id="u1", session_id="trip", message="Plan a flight for me.")
    final_context = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload["context_messages"]
    context_text = " ".join(m["content"] for m in final_context)
    assert "Home airport is SJC." in context_text
    assert "SFO" not in context_text


def test_superseded_fact_excluded_from_compressed_summary():
    builder = ContextBuilder(memory_budget=8, compressor=ExperienceCompressor())
    agent = run_sequence(
        make_agent(context_builder=builder),
        [
            "My home airport is SFO.",
            "I prefer evening flights.",
            "When planning work trips, include airport transfer time.",
            "Actually, my home airport is now SJC.",
        ],
    )
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload
    summaries = payload["compressed_summaries"]
    assert len(summaries) == 1
    assert "SJC" in summaries[0]["text"]
    assert "SFO" not in summaries[0]["text"]
    assert "Home airport is SFO." not in summaries[0]["source_texts"]
    assert "Home airport is SJC." in summaries[0]["source_texts"]


def test_planned_actions_report_fact_update():
    agent = run_sequence(
        make_agent(),
        ["My home airport is SFO.", "Actually, my home airport is now SJC."],
    )
    planned = [
        e for e in agent.events if e.type == EventType.MEMORY_ACTION_PLANNED
    ][-1].payload["planned_actions"]
    assert {a["action"] for a in planned} == {"supersede", "create"}
    supersede = next(a for a in planned if a["action"] == "supersede")
    assert supersede["text"] == "Home airport is SFO."
    assert "home airport" in supersede["reason"]
