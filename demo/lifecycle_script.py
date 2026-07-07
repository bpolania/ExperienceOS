"""One-command full lifecycle runner.

Executes the canonical scripted demo programmatically — reset, then
remember → retrieve → update → forget → select → explain → compress —
and returns structured state plus explicit lifecycle assertions that
tests and the terminal example can inspect. Offline, deterministic,
MockProvider by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from demo.demo_config import DEMO_USER_ID, SCRIPTED_DEMO
from demo.support import (
    create_agent,
    growth_metrics,
    lifecycle_timeline,
    reset_demo_state,
)
from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory import MemoryStatus
from experienceos.providers import MockProvider


def get_full_lifecycle_turns() -> list[tuple[str, str]]:
    """The canonical scripted demo turns (session_id, message)."""
    return list(SCRIPTED_DEMO)


@dataclass
class LifecycleDemoResult:
    turns: list[dict] = field(default_factory=list)
    active_memories: list = field(default_factory=list)
    superseded_memories: list = field(default_factory=list)
    forgotten_memories: list = field(default_factory=list)
    selected_memories: list[dict] = field(default_factory=list)
    skipped_memories: list[dict] = field(default_factory=list)
    compressed_summaries: list[dict] = field(default_factory=list)
    final_context: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)
    assertions: list[dict] = field(default_factory=list)

    @property
    def all_assertions_passed(self) -> bool:
        return all(a["passed"] for a in self.assertions)


def run_full_lifecycle_demo(
    agent: ExperienceOS | None = None, user_id: str = DEMO_USER_ID
) -> LifecycleDemoResult:
    """Run the full lifecycle from a reset state and collect the evidence."""
    agent = agent or create_agent(MockProvider())
    reset_demo_state(agent, user_id)

    result = LifecycleDemoResult()
    for session_id, message in get_full_lifecycle_turns():
        response = agent.chat(
            user_id=user_id, session_id=session_id, message=message
        )
        result.turns.append(
            {"session_id": session_id, "message": message, "response": response}
        )

    result.active_memories = agent.memories_for_user(user_id)
    result.superseded_memories = agent.memories_for_user(
        user_id, status=MemoryStatus.SUPERSEDED
    )
    result.forgotten_memories = agent.memories_for_user(
        user_id, status=MemoryStatus.FORGOTTEN
    )

    final_build = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload
    records = final_build.get("selection_records", [])
    result.selected_memories = [r for r in records if r["selected"]]
    result.skipped_memories = [r for r in records if not r["selected"]]
    result.compressed_summaries = final_build.get("compressed_summaries", [])
    result.final_context = [
        m["content"] for m in final_build.get("context_messages", [])
    ]
    result.metrics = growth_metrics(agent, user_id)
    result.timeline = lifecycle_timeline(agent.events)
    result.assertions = _lifecycle_assertions(result)
    return result


def _lifecycle_assertions(result: LifecycleDemoResult) -> list[dict]:
    """Explicit, factual checks computed from the actual run state."""
    context_text = " ".join(result.final_context)
    selected_texts = {r["text"] for r in result.selected_memories}
    superseded_texts = [m.text for m in result.superseded_memories]
    forgotten_texts = [m.text for m in result.forgotten_memories]
    replacement_texts = {
        m.text for m in result.active_memories if m.metadata.get("replaces")
    }

    def check(name: str, passed: bool, detail: str) -> dict:
        return {"check": name, "passed": passed, "detail": detail}

    return [
        check(
            "superseded memories are not selected",
            all(t not in selected_texts for t in superseded_texts),
            f"superseded: {superseded_texts}",
        ),
        check(
            "forgotten memories are not selected",
            all(t not in selected_texts for t in forgotten_texts),
            f"forgotten: {forgotten_texts}",
        ),
        check(
            "superseded memories are absent from final context",
            all(t not in context_text for t in superseded_texts),
            "final context contains no superseded text",
        ),
        check(
            "forgotten memories are absent from final context",
            all(t not in context_text for t in forgotten_texts),
            "final context contains no forgotten text",
        ),
        check(
            "updated active memories are used instead of the old ones",
            bool(replacement_texts)
            and all(t in selected_texts for t in replacement_texts),
            f"replacements selected for the final turn (rendered directly "
            f"or via the compressed summary): {sorted(replacement_texts)}",
        ),
        check(
            "related experience is compressed into a summary",
            bool(result.compressed_summaries)
            and all(
                s["saved_chars"] > 0 for s in result.compressed_summaries
            ),
            f"{len(result.compressed_summaries)} summary(ies) in final context",
        ),
    ]


def format_lifecycle_demo_report(result: LifecycleDemoResult) -> str:
    """Terminal-friendly, factual report of a lifecycle run."""
    lines: list[str] = []

    def section(title: str) -> None:
        lines.append("")
        lines.append(f"=== {title} ===")

    lines.append("ExperienceOS full lifecycle run (offline, MockProvider)")
    lines.append(f"Demo state reset for user: {DEMO_USER_ID}")

    section(f"Turns executed ({len(result.turns)})")
    for i, turn in enumerate(result.turns, start=1):
        lines.append(f"{i:2d}. [{turn['session_id']}] {turn['message']}")

    section("Lifecycle timeline")
    for row in result.timeline:
        lines.append(f"  turn {row['Turn']:2d}  {row['Event']:<10} {row['Summary']}")

    section(f"Final active memories ({len(result.active_memories)})")
    for m in result.active_memories:
        lines.append(f"  - ({m.kind}) {m.text}")

    section(
        f"Final inactive memories "
        f"({len(result.superseded_memories)} superseded, "
        f"{len(result.forgotten_memories)} forgotten)"
    )
    for m in result.superseded_memories:
        lines.append(f"  - (superseded) {m.text}")
    for m in result.forgotten_memories:
        lines.append(f"  - (forgotten) {m.text}")

    section(
        f"Final turn selection "
        f"({len(result.selected_memories)} selected, "
        f"{len(result.skipped_memories)} skipped)"
    )
    for r in result.selected_memories:
        lines.append(f"  + {r['text']} — {r['reason']}")
    for r in result.skipped_memories:
        lines.append(f"  - {r['text']} — {r['reason']}")

    section(f"Compressed summaries ({len(result.compressed_summaries)})")
    for s in result.compressed_summaries:
        lines.append(
            f"  {len(s['source_memory_ids'])} memories -> 1 summary "
            f"({s['original_chars']} -> {s['compressed_chars']} chars, "
            f"saved {s['saved_chars']})"
        )
        for line in s["text"].splitlines():
            lines.append(f"    {line}")

    section("Final supplied context")
    for content in result.final_context:
        for line in content.splitlines():
            lines.append(f"  {line}")

    section("Growth metrics")
    for key, value in result.metrics.items():
        lines.append(f"  {key}: {value}")

    section("Lifecycle assertions")
    for a in result.assertions:
        status = "PASS" if a["passed"] else "FAIL"
        lines.append(f"  [{status}] {a['check']}")
        if not a["passed"]:
            lines.append(f"         {a['detail']}")

    lines.append("")
    lines.append(
        "RESULT: all lifecycle assertions passed"
        if result.all_assertions_passed
        else "RESULT: LIFECYCLE ASSERTION FAILURE"
    )
    return "\n".join(lines)
