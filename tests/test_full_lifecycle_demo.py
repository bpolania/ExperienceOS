"""Full lifecycle runner tests: reset start, lifecycle proof, repeatability."""

from demo.demo_config import DEMO_USER_ID
from demo.lifecycle_script import (
    format_lifecycle_demo_report,
    get_full_lifecycle_turns,
    run_full_lifecycle_demo,
)
from demo.support import create_agent
from experienceos.memory import MemoryStatus
from experienceos.providers import MockProvider


def test_runner_executes_offline_with_mock_provider():
    result = run_full_lifecycle_demo()
    assert len(result.turns) == len(get_full_lifecycle_turns())
    assert all(turn["response"] for turn in result.turns)


def test_runner_starts_from_reset_state():
    agent = create_agent(MockProvider())
    # Stale state from a previous run must not leak into the demo.
    agent.chat(
        user_id=DEMO_USER_ID, session_id="stale", message="I prefer window seats."
    )
    result = run_full_lifecycle_demo(agent=agent)
    all_texts = {
        m.text
        for m in (
            result.active_memories
            + result.superseded_memories
            + result.forgotten_memories
        )
    }
    assert "Prefers window seats." not in all_texts


def test_runner_creates_supersedes_and_forgets():
    result = run_full_lifecycle_demo()
    assert len(result.active_memories) == 6
    superseded = {m.text for m in result.superseded_memories}
    assert superseded == {"Prefers morning flights.", "Home airport is SFO."}
    assert [m.text for m in result.forgotten_memories] == ["Prefers aisle seats."]


def test_final_selection_excludes_retired_memories():
    result = run_full_lifecycle_demo()
    selected = {r["text"] for r in result.selected_memories}
    assert "Prefers morning flights." not in selected
    assert "Home airport is SFO." not in selected
    assert "Prefers aisle seats." not in selected
    assert "Prefers evening flights." in selected
    assert "Home airport is SJC." in selected


def test_final_context_excludes_retired_and_uses_updates():
    result = run_full_lifecycle_demo()
    context_text = " ".join(result.final_context)
    assert "SFO" not in context_text
    assert "morning" not in context_text
    assert "aisle" not in context_text
    assert "SJC" in context_text
    assert "evening flights" in context_text


def test_compression_appears_in_final_context():
    result = run_full_lifecycle_demo()
    assert len(result.compressed_summaries) == 1
    summary = result.compressed_summaries[0]
    assert summary["saved_chars"] > 0
    assert len(summary["source_memory_ids"]) == 5
    context_text = " ".join(result.final_context)
    assert "Travel experience summary:" in context_text


def test_all_lifecycle_assertions_pass():
    result = run_full_lifecycle_demo()
    assert result.all_assertions_passed, [
        a for a in result.assertions if not a["passed"]
    ]
    assert len(result.assertions) == 6


def test_runner_is_repeatable():
    agent = create_agent(MockProvider())
    first = run_full_lifecycle_demo(agent=agent)
    second = run_full_lifecycle_demo(agent=agent)
    assert {m.text for m in second.active_memories} == {
        m.text for m in first.active_memories
    }
    assert len(second.superseded_memories) == len(first.superseded_memories)
    assert len(second.forgotten_memories) == len(first.forgotten_memories)
    assert second.all_assertions_passed


def test_report_formats_all_sections():
    result = run_full_lifecycle_demo()
    report = format_lifecycle_demo_report(result)
    for heading in (
        "Turns executed",
        "Lifecycle timeline",
        "Final active memories",
        "Final inactive memories",
        "Final turn selection",
        "Compressed summaries",
        "Final supplied context",
        "Growth metrics",
        "Lifecycle assertions",
    ):
        assert heading in report
    assert "RESULT: all lifecycle assertions passed" in report
    assert "FAIL" not in report


def test_example_entrypoint_returns_zero(capsys):
    from examples.full_lifecycle_demo import main

    assert main() == 0
    out = capsys.readouterr().out
    assert "RESULT: all lifecycle assertions passed" in out


def test_sdk_defaults_unaffected():
    from experienceos import ExperienceOS

    agent = ExperienceOS(model=MockProvider())
    assert agent.chat(user_id="u1", session_id="s1", message="hello")
    assert agent.memories_for_user("u1", status=MemoryStatus.FORGOTTEN) == []
