"""Memory-intelligence visibility and memory-value comparison tests."""

import pytest

from demo.demo_config import DEMO_USER_ID
from demo.support import (
    POLICY_LOCAL_MODEL,
    POLICY_RULE_BASED,
    create_agent,
    decision_rows,
    local_runtime_status,
    make_memory_policy,
    memory_intelligence_summary,
    policy_provenance,
    reset_demo_state,
)
from examples.memory_value_comparison import (
    ScriptedTravelRunner,
    format_report,
    main as comparison_main,
    run_comparison,
)
from experienceos import ExperienceOS, LocalModelMemoryPolicy
from experienceos.events import EventType
from experienceos.events.schema import ExperienceEvent
from experienceos.policy import LocalModelUnavailable, MemoryDecisionProposal
from experienceos.policy.local_runner import LocalModelAvailability
from experienceos.providers import MockProvider
from tests.helpers import FakeLocalModelRunner


def decisions(*items):
    return {"decisions": list(items)}


def create_decision(text="Prefers aisle seats.", confidence=0.9):
    return {
        "action": "create",
        "kind": "preference",
        "text": text,
        "target_memory_id": None,
        "replaces": None,
        "confidence": confidence,
        "explanation": "Durable preference.",
    }


# --- Provenance helper -------------------------------------------------------------


def test_provenance_none_before_any_planning():
    agent = ExperienceOS(model=MockProvider())
    assert policy_provenance(agent.events) is None
    assert memory_intelligence_summary(None) == "No memory decisions yet."
    assert decision_rows(None) == []


def test_rule_based_provenance():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    provenance = policy_provenance(agent.events)
    assert provenance["mode"] == "rule_based"
    assert provenance["decision_source"] == "rule_based"
    assert provenance["fallback_used"] is False
    assert memory_intelligence_summary(provenance) == "Rule-based decision."
    rows = decision_rows(provenance)
    assert rows[0]["Decision"] == "Accepted"
    assert rows[0]["Source"] == "rule_based"
    assert rows[0]["Confidence"] == 1.0


def test_accepted_local_provenance():
    runner = FakeLocalModelRunner(data=decisions(create_decision()))
    agent = ExperienceOS(
        model=MockProvider(), memory_policy=LocalModelMemoryPolicy(runner)
    )
    agent.chat(user_id="u1", session_id="s1", message="anything")
    provenance = policy_provenance(agent.events)
    assert provenance["mode"] == "local_model"
    assert provenance["fallback_used"] is False
    assert memory_intelligence_summary(provenance) == (
        "Local model decisions accepted."
    )
    rows = decision_rows(provenance)
    assert rows[0]["Source"] == "local_model"
    assert rows[0]["Confidence"] == 0.9


def test_fallback_provenance_and_reason():
    runner = FakeLocalModelRunner(error=LocalModelUnavailable("no model"))
    agent = ExperienceOS(
        model=MockProvider(), memory_policy=LocalModelMemoryPolicy(runner)
    )
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    provenance = policy_provenance(agent.events)
    assert provenance["fallback_used"] is True
    assert provenance["fallback_reason"] == "model_unavailable"
    summary = memory_intelligence_summary(provenance)
    assert "fallback" in summary
    assert "model_unavailable" in summary
    assert decision_rows(provenance)[0]["Source"] == "fallback"


def test_no_action_provenance_local_and_rule():
    local = ExperienceOS(
        model=MockProvider(),
        memory_policy=LocalModelMemoryPolicy(
            FakeLocalModelRunner(data=decisions())
        ),
    )
    local.chat(user_id="u1", session_id="s1", message="what time is it?")
    assert memory_intelligence_summary(policy_provenance(local.events)) == (
        "No memory action proposed (local model)."
    )

    rule = ExperienceOS(model=MockProvider())
    rule.chat(user_id="u1", session_id="s1", message="what time is it?")
    assert memory_intelligence_summary(policy_provenance(rule.events)) == (
        "No memory action proposed (rule-based)."
    )


def test_rejected_target_visible_without_fallback():
    class BadTargetPolicy:
        mode = "local_model"

        def plan(self, context):
            return [
                MemoryDecisionProposal(
                    action="forget",
                    target_memory_id="no-such-id",
                    decision_source="local_model",
                    confidence=0.9,
                )
            ]

    agent = ExperienceOS(model=MockProvider(), memory_policy=BadTargetPolicy())
    agent.chat(user_id="u1", session_id="s1", message="anything")
    provenance = policy_provenance(agent.events)
    assert provenance["fallback_used"] is False
    assert len(provenance["rejected"]) == 1
    summary = memory_intelligence_summary(provenance)
    assert "rejected by lifecycle validation" in summary
    assert "no fallback" in summary
    rows = decision_rows(provenance)
    rejected = [r for r in rows if r["Decision"] == "Rejected"]
    assert rejected[0]["Explanation"] == "target_not_active"


def test_duplicate_create_rejection_visible_with_reason():
    runner = FakeLocalModelRunner(
        data=decisions(
            create_decision(text="Aisle seats are preferred for short work trips.")
        )
    )
    agent = ExperienceOS(
        model=MockProvider(), memory_policy=LocalModelMemoryPolicy(runner)
    )
    agent.chat(user_id="u1", session_id="s1", message="first")
    agent.chat(user_id="u1", session_id="s1", message="second")
    provenance = policy_provenance(agent.events)
    assert provenance["fallback_used"] is False
    summary = memory_intelligence_summary(provenance)
    assert "duplicate of active" in summary
    assert "no fallback" in summary
    rejected = [
        r for r in decision_rows(provenance) if r["Decision"] == "Rejected"
    ]
    assert rejected[0]["Explanation"] == "duplicate_of_active"


def test_provenance_tolerates_missing_optional_fields():
    # An older-style payload without the policy block or provenance keys.
    event = ExperienceEvent(
        type=EventType.MEMORY_ACTION_PLANNED,
        user_id="u1",
        session_id="s1",
        payload={"planned_actions": [{"action": "create", "text": "X."}]},
    )
    provenance = policy_provenance([event])
    assert provenance["mode"] == "rule_based"
    assert provenance["fallback_used"] is False
    rows = decision_rows(provenance)
    assert rows[0]["Source"] == "rule_based"
    assert rows[0]["Confidence"] == "—"
    assert rows[0]["Explanation"] == "—"
    assert isinstance(memory_intelligence_summary(provenance), str)


def test_reset_clears_provenance():
    agent = create_agent(MockProvider())
    agent.chat(
        user_id=DEMO_USER_ID, session_id="s1", message="I prefer aisle seats."
    )
    assert policy_provenance(agent.events) is not None
    reset_demo_state(agent, DEMO_USER_ID)
    assert policy_provenance(agent.events) is None


# --- Local runtime status ----------------------------------------------------------


def test_runtime_status_not_configured_for_rule_based():
    agent = ExperienceOS(model=MockProvider())
    status = local_runtime_status(agent)
    assert status["configured"] is False
    assert status["label"] == "Not configured"


def test_runtime_status_unavailable_without_dependency(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    monkeypatch.delenv("EXPERIENCEOS_LOCAL_MODEL_PATH", raising=False)
    agent = create_agent(
        MockProvider(), memory_policy=make_memory_policy(POLICY_LOCAL_MODEL)
    )
    status = local_runtime_status(agent)
    assert status["configured"] is True
    assert status["label"] == "Unavailable"
    assert status["reason"] == "dependency_missing"
    # And the agent still works — decisions fall back to rules.
    agent.chat(
        user_id=DEMO_USER_ID, session_id="s1", message="I prefer aisle seats."
    )
    assert policy_provenance(agent.events)["fallback_used"] is True


def test_runtime_status_available_and_load_failed_without_loading():
    ready = FakeLocalModelRunner()
    agent = ExperienceOS(
        model=MockProvider(), memory_policy=LocalModelMemoryPolicy(ready)
    )
    status = local_runtime_status(agent)
    assert status["configured"] is True
    assert status["label"].startswith("Available")
    # Rendering the status never triggered generation or loading.
    assert ready.calls == []

    failed = FakeLocalModelRunner(
        available=LocalModelAvailability(
            available=False, reason="model_load_failed", detail="bad magic"
        )
    )
    agent2 = ExperienceOS(
        model=MockProvider(), memory_policy=LocalModelMemoryPolicy(failed)
    )
    assert local_runtime_status(agent2)["label"] == "Load failed"


def test_make_memory_policy_defaults():
    assert make_memory_policy() is None
    assert make_memory_policy(POLICY_RULE_BASED) is None
    policy = make_memory_policy(POLICY_LOCAL_MODEL)
    assert isinstance(policy, LocalModelMemoryPolicy)


# --- Memory value comparison ----------------------------------------------------------


@pytest.fixture(scope="module")
def comparison():
    return run_comparison()


def test_all_three_modes_complete_offline(comparison):
    for key in ("baseline", "rule_based", "local"):
        assert len(comparison[key]["turns"]) == 6
        assert comparison[key]["final_response"]


def test_all_comparison_assertions_pass(comparison):
    failing = [a for a in comparison["assertions"] if not a["passed"]]
    assert failing == []
    assert len(comparison["assertions"]) == 12


def test_baseline_is_isolated_from_experienced_modes(comparison):
    assert comparison["baseline"]["active"] == []
    assert comparison["baseline"]["counts"]["created"] == 0
    # Experienced modes each built their own state.
    assert comparison["rule_based"]["counts"]["created"] == 4
    assert comparison["local"]["counts"]["created"] == 4


def test_local_mode_uses_fake_runner_with_fallback(comparison):
    local = comparison["local"]
    assert local["decision_sources"]["local_model"] >= 3
    assert local["fallbacks"] == ["generation_failed"]


def test_retired_memories_excluded_in_both_experienced_modes(comparison):
    for key in ("rule_based", "local"):
        mode = comparison[key]
        context = " ".join(mode["final_context"])
        assert mode["superseded"] == ["Prefers morning flights."]
        assert mode["forgotten"] == ["Prefers aisle seats."]
        assert "morning" not in context.lower()
        assert "aisle" not in context.lower()


def test_comparison_is_deterministic_across_runs(comparison):
    second = run_comparison()
    for key in ("baseline", "rule_based", "local"):
        assert second[key]["active"] == comparison[key]["active"]
        assert second[key]["counts"] == comparison[key]["counts"]
        assert dict(second[key]["decision_sources"]) == dict(
            comparison[key]["decision_sources"]
        )
    assert [a["passed"] for a in second["assertions"]] == [
        a["passed"] for a in comparison["assertions"]
    ]


def test_comparison_entrypoint_and_report(comparison, capsys):
    assert comparison_main() == 0
    out = capsys.readouterr().out
    assert "RESULT: memory value comparison passed" in out
    report = format_report(comparison)
    for heading in (
        "no-memory baseline",
        "rule-based ExperienceOS",
        "local-policy ExperienceOS",
        "Comparison assertions",
    ):
        assert heading in report


def test_scripted_runner_reads_target_from_prompt():
    runner = ScriptedTravelRunner()
    agent = ExperienceOS(
        model=MockProvider(), memory_policy=LocalModelMemoryPolicy(runner)
    )
    # Fast-forward the script to the forget turn.
    for session_id, message in [
        ("s1", "I prefer aisle seats and morning flights."),
        ("s1", "My home airport is SFO."),
        ("s2", "Book me a flight for next week."),
        ("s3", "Actually, I prefer evening flights."),
    ]:
        agent.chat(user_id="u1", session_id=session_id, message=message)
    aisle_id = next(
        m.id for m in agent.memories_for_user("u1") if "aisle" in m.text
    )
    agent.chat(
        user_id="u1", session_id="s4", message="Forget my aisle seat preference."
    )
    from experienceos.memory import MemoryStatus

    assert agent.memory_store.get(aisle_id).status == MemoryStatus.FORGOTTEN


# --- Source guards ---------------------------------------------------------------------


def test_comparison_and_dashboard_have_no_network_or_runtime_leaks():
    from pathlib import Path

    comparison_text = Path("examples/memory_value_comparison.py").read_text()
    for forbidden in ("requests", "httpx", "urllib.request", "huggingface_hub"):
        assert forbidden not in comparison_text
    for path in Path("demo").glob("*.py"):
        assert "llama_cpp" not in path.read_text(), f"llama_cpp in {path}"
