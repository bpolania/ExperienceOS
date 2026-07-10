"""Memory value comparison: no memory vs rules vs local policy. Offline.

Runs the same six-turn work-travel scenario in three modes and proves,
with deterministic assertions, what accumulated experience changes:

  1. no-memory baseline — the provider sees only the current message
  2. rule-based ExperienceOS — deterministic memory policy
  3. local-policy ExperienceOS — LocalModelMemoryPolicy driven by a
     scripted fake runner (no real model, no downloads, no network),
     exercising accepted local decisions AND one typed fallback

Run:

    PYTHONPATH=. python examples/memory_value_comparison.py

Exits 0 when every comparison assertion passes. The local mode uses a
fake runner by design; real local-model execution remains a separate
optional verification via examples/local_runner_smoke.py.
"""

from __future__ import annotations

import re
import sys
from collections import Counter

from experienceos import ExperienceOS, LocalModelMemoryPolicy
from experienceos.events import EventType
from experienceos.memory import MemoryStatus
from experienceos.policy.local_runner import LocalModelGenerationFailed
from experienceos.providers import MockProvider
from tests.helpers import FakeLocalModelRunner

USER_ID = "traveler"

SCENARIO = [
    ("session-1", "I prefer aisle seats and morning flights."),
    ("session-1", "My home airport is SFO."),
    ("session-2", "Book me a flight for next week."),
    ("session-3", "Actually, I prefer evening flights."),
    ("session-4", "Forget my aisle seat preference."),
    ("session-5", "Plan my next work trip."),
]

SYSTEM_MESSAGE = {
    "role": "system",
    "content": "You are a helpful work-travel assistant.",
}


def _decision(action, kind, text, confidence, explanation, target=None):
    return {
        "action": action,
        "kind": kind,
        "text": text,
        "target_memory_id": target,
        "replaces": target if action == "supersede" else None,
        "confidence": confidence,
        "explanation": explanation,
    }


class ScriptedTravelRunner(FakeLocalModelRunner):
    """Deterministic per-turn local decisions for the scenario.

    Turn 5 (the forget) reads the aisle-seat memory id from the bounded
    prompt's ACTIVE MEMORIES block — exactly the id channel a real local
    model would use. Turn 4 raises a typed generation failure to prove
    whole-batch fallback attribution.
    """

    def __init__(self):
        super().__init__(
            script=[
                {
                    "decisions": [
                        _decision(
                            "create", "preference", "Prefers aisle seats.",
                            0.92, "Durable seating preference.",
                        ),
                        _decision(
                            "create", "preference", "Prefers morning flights.",
                            0.88, "Durable flight-time preference.",
                        ),
                    ]
                },
                {
                    "decisions": [
                        _decision(
                            "create", "fact", "Home airport is SFO.",
                            0.95, "Durable home-airport fact.",
                        )
                    ]
                },
                {"decisions": []},  # booking request: nothing durable
                LocalModelGenerationFailed("decode error"),  # → fallback
            ]
        )

    def generate_structured(self, *, system_prompt, user_prompt, schema):
        if "Forget my aisle seat preference." in user_prompt:
            match = re.search(
                r"- id: (\S+)\n  kind: preference\n  text: Prefers aisle seats\.",
                user_prompt,
            )
            target = match.group(1) if match else "unknown"
            self.calls.append({"user_prompt": user_prompt, "schema": schema})
            from experienceos.policy.local_runner import LocalModelResult

            return LocalModelResult(
                data={
                    "decisions": [
                        _decision(
                            "forget", "preference", None, 0.9,
                            "User said aisle seats no longer matter.",
                            target=target,
                        )
                    ]
                },
                model_path="fake.gguf",
                model_name="fake.gguf",
            )
        if "Plan my next work trip." in user_prompt:
            self.calls.append({"user_prompt": user_prompt, "schema": schema})
            from experienceos.policy.local_runner import LocalModelResult

            return LocalModelResult(
                data={"decisions": []},
                model_path="fake.gguf",
                model_name="fake.gguf",
            )
        return super().generate_structured(
            system_prompt=system_prompt, user_prompt=user_prompt, schema=schema
        )


def run_no_memory_mode() -> dict:
    """Baseline: provider sees only the current message. No memories."""
    provider = MockProvider()
    turns = []
    final_messages = None
    for _, message in SCENARIO:
        messages = [SYSTEM_MESSAGE, {"role": "user", "content": message}]
        final_messages = messages
        turns.append({"message": message, "response": provider.complete(messages)})
    return {
        "mode": "no-memory baseline",
        "turns": turns,
        "final_response": turns[-1]["response"],
        "final_context": [m["content"] for m in final_messages],
        "active": [],
        "superseded": [],
        "forgotten": [],
        "decision_sources": Counter(),
        "fallbacks": [],
        "counts": {"created": 0, "superseded": 0, "forgotten": 0, "rejected": 0},
    }


def run_experienceos_mode(mode_name: str, agent: ExperienceOS) -> dict:
    turns = []
    for session_id, message in SCENARIO:
        response = agent.chat(
            user_id=USER_ID, session_id=session_id, message=message
        )
        turns.append({"message": message, "response": response})

    events = agent.events
    planned_events = [
        e for e in events if e.type == EventType.MEMORY_ACTION_PLANNED
    ]
    decision_sources: Counter = Counter()
    fallbacks = []
    rejected = 0
    for event in planned_events:
        for action in event.payload.get("planned_actions", []):
            decision_sources[action.get("decision_source", "rule_based")] += 1
        rejected += len(event.payload.get("rejected_actions", []))
        policy = event.payload.get("policy") or {}
        if policy.get("fallback_used"):
            fallbacks.append(policy.get("fallback_reason"))

    final_context = [
        m["content"]
        for m in [
            e for e in events if e.type == EventType.CONTEXT_BUILT
        ][-1].payload["context_messages"]
    ]
    return {
        "mode": mode_name,
        "turns": turns,
        "final_response": turns[-1]["response"],
        "final_context": final_context,
        "active": [m.text for m in agent.memories_for_user(USER_ID)],
        "superseded": [
            m.text
            for m in agent.memories_for_user(USER_ID, status=MemoryStatus.SUPERSEDED)
        ],
        "forgotten": [
            m.text
            for m in agent.memories_for_user(USER_ID, status=MemoryStatus.FORGOTTEN)
        ],
        "decision_sources": decision_sources,
        "fallbacks": fallbacks,
        "counts": {
            "created": sum(
                1 for e in events if e.type == EventType.MEMORY_CREATED
            ),
            "superseded": sum(
                1 for e in events if e.type == EventType.MEMORY_SUPERSEDED
            ),
            "forgotten": sum(
                1 for e in events if e.type == EventType.MEMORY_FORGOTTEN
            ),
            "rejected": rejected,
        },
    }


def run_comparison() -> dict:
    """Run all three modes with isolated agents/stores; return results."""
    baseline = run_no_memory_mode()
    rule_agent = ExperienceOS(model=MockProvider())
    rule_based = run_experienceos_mode("rule-based ExperienceOS", rule_agent)
    local_agent = ExperienceOS(
        model=MockProvider(),
        memory_policy=LocalModelMemoryPolicy(ScriptedTravelRunner()),
    )
    local = run_experienceos_mode("local-policy ExperienceOS", local_agent)
    assert rule_agent.memory_store is not local_agent.memory_store

    results = {"baseline": baseline, "rule_based": rule_based, "local": local}
    results["assertions"] = _comparison_assertions(results)
    return results


def _comparison_assertions(results: dict) -> list[dict]:
    baseline, rules, local = (
        results["baseline"],
        results["rule_based"],
        results["local"],
    )

    def check(name, passed, detail=""):
        return {"check": name, "passed": bool(passed), "detail": detail}

    checks = []
    baseline_context = " ".join(baseline["final_context"])
    checks.append(
        check(
            "no-memory mode injects no prior-session experience",
            "Prefers" not in baseline_context
            and "Home airport" not in baseline_context
            and "with 0 retrieved experience entries" in baseline["final_response"],
            baseline["final_response"],
        )
    )
    for mode in (rules, local):
        context = " ".join(mode["final_context"])
        checks.append(
            check(
                f"{mode['mode']}: retrieves relevant prior experience",
                "Home airport is SFO." in context
                and "evening flights" in context.lower(),
            )
        )
        checks.append(
            check(
                f"{mode['mode']}: changed preference supersedes the old one",
                mode["superseded"] == ["Prefers morning flights."]
                and "Prefers evening flights." in mode["active"],
            )
        )
        checks.append(
            check(
                f"{mode['mode']}: forgotten memory excluded from context",
                mode["forgotten"] == ["Prefers aisle seats."]
                and "aisle" not in context.lower()
                and "morning" not in context.lower(),
            )
        )
        checks.append(
            check(
                f"{mode['mode']}: final response uses active experience",
                "retrieved experience entries" in mode["final_response"]
                and "with 0 retrieved" not in mode["final_response"],
                mode["final_response"],
            )
        )
    checks.append(
        check(
            "local mode records accepted local decisions",
            results["local"]["decision_sources"]["local_model"] >= 3,
            str(dict(results["local"]["decision_sources"])),
        )
    )
    checks.append(
        check(
            "local mode exercises typed fallback with attribution",
            results["local"]["fallbacks"] == ["generation_failed"]
            and results["local"]["decision_sources"]["fallback"] >= 1,
            f"fallbacks={results['local']['fallbacks']}",
        )
    )
    checks.append(
        check(
            "rule-based mode never falls back",
            rules["fallbacks"] == []
            and rules["decision_sources"].get("fallback", 0) == 0,
        )
    )
    return checks


def format_report(results: dict) -> str:
    lines = ["ExperienceOS memory value comparison (offline, deterministic)"]
    for key in ("baseline", "rule_based", "local"):
        mode = results[key]
        lines.append("")
        lines.append(f"=== {mode['mode']} ===")
        lines.append(f"turns executed: {len(mode['turns'])}")
        lines.append(
            f"memories — active: {len(mode['active'])}, "
            f"superseded: {len(mode['superseded'])}, "
            f"forgotten: {len(mode['forgotten'])}"
        )
        for text in mode["active"]:
            lines.append(f"  active: {text}")
        counts = mode["counts"]
        lines.append(
            f"lifecycle — created: {counts['created']}, "
            f"superseded: {counts['superseded']}, "
            f"forgotten: {counts['forgotten']}, rejected: {counts['rejected']}"
        )
        lines.append(
            f"decision sources: {dict(mode['decision_sources']) or '(none)'}"
        )
        lines.append(f"fallbacks: {mode['fallbacks'] or '(none)'}")
        lines.append("final context supplied to provider:")
        for content in mode["final_context"]:
            for line in content.splitlines():
                lines.append(f"    {line}")
        lines.append(f"final response: {mode['final_response']}")

    lines.append("")
    lines.append("=== Comparison assertions ===")
    for a in results["assertions"]:
        status = "PASS" if a["passed"] else "FAIL"
        lines.append(f"  [{status}] {a['check']}")
        if not a["passed"] and a["detail"]:
            lines.append(f"         {a['detail']}")
    all_passed = all(a["passed"] for a in results["assertions"])
    lines.append("")
    lines.append(
        "RESULT: memory value comparison passed"
        if all_passed
        else "RESULT: MEMORY VALUE COMPARISON FAILED"
    )
    return "\n".join(lines)


def main() -> int:
    results = run_comparison()
    print(format_report(results))
    return 0 if all(a["passed"] for a in results["assertions"]) else 1


if __name__ == "__main__":
    sys.exit(main())
