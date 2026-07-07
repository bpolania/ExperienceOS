"""Support logic for the demo dashboard.

Kept free of Streamlit imports so provider selection, agent creation,
and event display logic stay testable without the demo extra installed.
"""

from __future__ import annotations

from demo.demo_config import DEMO_USER_ID
from experienceos import ExperienceOS
from experienceos.context import ContextBuilder, ExperienceCompressor
from experienceos.context.builder import MEMORY_HEADER
from experienceos.events.schema import EventType, ExperienceEvent
from experienceos.memory import InMemoryMemoryStore, SQLiteMemoryStore
from experienceos.providers import MockProvider, ModelProvider, QwenCloudProvider

PROVIDER_MOCK = "Mock (offline)"
PROVIDER_QWEN = "Qwen Cloud"
PROVIDER_CHOICES = [PROVIDER_MOCK, PROVIDER_QWEN]

STORAGE_IN_MEMORY = "In-memory"
STORAGE_SQLITE = "SQLite persistent"
STORAGE_CHOICES = [STORAGE_IN_MEMORY, STORAGE_SQLITE]
DEFAULT_SQLITE_PATH = ".experienceos/demo_memory.sqlite3"
# Slightly larger than the SDK default so the compression moment groups
# a meaningful number of travel memories while skipping stays visible.
DEMO_MEMORY_BUDGET = 6

QWEN_SETUP_HINT = (
    "Set QWEN_API_KEY (or DASHSCOPE_API_KEY), and QWEN_BASE_URL if your "
    "Model Studio workspace requires a regional endpoint."
)


def make_provider(choice: str = PROVIDER_MOCK) -> ModelProvider:
    """Build the selected provider. Mock is the default; never raises."""
    if choice == PROVIDER_QWEN:
        return QwenCloudProvider()
    return MockProvider()


def provider_status(provider: ModelProvider) -> str:
    if isinstance(provider, QwenCloudProvider):
        return "Configured" if provider.is_configured else "Missing credentials"
    return "Offline demo mode"


def make_memory_store(
    choice: str = STORAGE_IN_MEMORY, db_path: str = DEFAULT_SQLITE_PATH
):
    """Build the selected memory store. In-memory is the default."""
    if choice == STORAGE_SQLITE:
        return SQLiteMemoryStore(db_path)
    return InMemoryMemoryStore()


def storage_status(store) -> tuple[str, str]:
    """(storage label, database description) for the dashboard status panel."""
    if isinstance(store, SQLiteMemoryStore):
        return "SQLite", store.db_path
    return "In-memory", "none"


def create_agent(provider: ModelProvider, memory_store=None) -> ExperienceOS:
    """Agent with fresh event history; memory store optional (in-memory default).

    The demo path enables experience compression so the dashboard can
    show related memories collapsing into compact context. SDK defaults
    remain uncompressed.
    """
    return ExperienceOS(
        model=provider,
        memory_store=memory_store or InMemoryMemoryStore(),
        context_builder=ContextBuilder(
            memory_budget=DEMO_MEMORY_BUDGET,
            compressor=ExperienceCompressor(),
        ),
    )


def _truncate(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_event(event: ExperienceEvent) -> str:
    """One readable line per event for the dashboard event log."""
    p = event.payload
    if event.type == EventType.INTERACTION_STARTED:
        return _truncate(p.get("message", ""))
    if event.type == EventType.MEMORY_RETRIEVED:
        return f"{p.get('count', 0)} active memories retrieved."
    if event.type == EventType.CONTEXT_BUILT:
        selected = p.get("selected_memory_count", p.get("memory_count", 0))
        skipped = p.get("skipped_memory_count", 0)
        summary = f"Context built: {selected} selected, {skipped} skipped."
        summaries = p.get("compressed_summaries", [])
        if summaries:
            sources = sum(len(s.get("source_memory_ids", [])) for s in summaries)
            saved = sum(s.get("saved_chars", 0) for s in summaries)
            summary += (
                f" {sources} memories compressed into {len(summaries)} "
                f"summary (saved {saved} chars)."
            )
        return summary
    if event.type == EventType.MEMORY_ACTION_PLANNED:
        return f"{len(p.get('planned_actions', []))} create action(s) planned."
    if event.type == EventType.MEMORY_CREATED:
        return p.get("text", "")
    if event.type == EventType.MEMORY_SUPERSEDED:
        return f"Superseded: {p.get('text', '')}"
    if event.type == EventType.MEMORY_FORGOTTEN:
        return f"Forgotten: {p.get('text', '')}"
    if event.type == EventType.MODEL_CALLED:
        provider = p.get("provider", "provider")
        return f"{provider} called with {p.get('message_count', 0)} messages."
    if event.type == EventType.RESPONSE_RETURNED:
        return _truncate(p.get("response", ""))
    return ""


def safe_memory_metadata(memory) -> dict:
    """Memory metadata as a dict, tolerating None or wrong types."""
    metadata = getattr(memory, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def safe_memory_tags(memory) -> list[str]:
    """Memory tags, empty when metadata or tags are absent."""
    tags = safe_memory_metadata(memory).get("tags")
    return list(tags) if isinstance(tags, (list, tuple)) else []


def safe_memory_domain(memory) -> str | None:
    """Primary memory domain, or None when absent."""
    domain = safe_memory_metadata(memory).get("domain")
    return domain if isinstance(domain, str) and domain else None


def active_memory_rows(agent: ExperienceOS, user_id: str) -> list[dict]:
    """Display rows for active memories, tolerating missing metadata."""
    return [
        {
            "Memory": m.text,
            "Kind": m.kind,
            "Tags": ", ".join(safe_memory_tags(m)) or "—",
            "Status": m.status,
            "Source session": m.source_session_id or "—",
            "Created": m.created_at.strftime("%H:%M:%S"),
        }
        for m in agent.memories_for_user(user_id)
    ]


def selection_rows(records: list[dict] | None) -> list[dict]:
    """Display rows for selection records, tolerating missing fields."""
    rows = []
    for r in records or []:
        reason = r.get("reason") or ""
        rows.append(
            {
                "Decision": "Selected" if r.get("selected") else "Skipped",
                "Rank": r.get("rank", "—"),
                "Kind": r.get("kind", "—"),
                "Memory": r.get("text", ""),
                "Score": r.get("score", 0),
                "Matched keywords": ", ".join(r.get("matched_keywords") or []),
                "Domains": ", ".join(r.get("matched_domains") or []) or "—",
                "Reason": reason.split(": ", 1)[-1] if reason else "—",
            }
        )
    return rows


def summary_display(summary: dict | None) -> dict:
    """A compressed summary shaped safely for display."""
    summary = summary or {}
    return {
        "text": summary.get("text", ""),
        "source_texts": list(summary.get("source_texts") or []),
        "reason": summary.get("reason", ""),
        "original_chars": summary.get("original_chars", 0),
        "compressed_chars": summary.get("compressed_chars", 0),
        "saved_chars": summary.get("saved_chars", 0),
    }


def superseded_rows(agent: ExperienceOS, user_id: str) -> list[dict]:
    """Display rows for superseded memories, resolving replacement texts."""
    all_by_id = {m.id: m for m in agent.memories_for_user(user_id, status=None)}
    rows = []
    for m in agent.memories_for_user(user_id, status="superseded"):
        replacement = all_by_id.get(
            safe_memory_metadata(m).get("superseded_by", "")
        )
        rows.append(
            {
                "Memory": m.text,
                "Kind": m.kind,
                "Status": m.status,
                "Replaced by": replacement.text if replacement else "—",
                "Source session": m.source_session_id or "—",
                "Updated": m.updated_at.strftime("%H:%M:%S"),
            }
        )
    return rows


def forgotten_rows(agent: ExperienceOS, user_id: str) -> list[dict]:
    """Display rows for forgotten memories, kept visible as history."""
    rows = []
    for m in agent.memories_for_user(user_id, status="forgotten"):
        metadata = safe_memory_metadata(m)
        forgotten_at = metadata.get("forgotten_at", "")
        rows.append(
            {
                "Memory": m.text,
                "Kind": m.kind,
                "Status": m.status,
                "Reason": metadata.get("forget_reason", "—"),
                "Forgotten at": (
                    forgotten_at[:19].replace("T", " ") if forgotten_at else "—"
                ),
            }
        )
    return rows


def selection_summary(events: list[ExperienceEvent]) -> dict | None:
    """Budget and counts from the last turn's context selection."""
    for event in reversed(events):
        if event.type == EventType.CONTEXT_BUILT:
            p = event.payload
            return {
                "memory_budget": p.get("memory_budget"),
                "candidates": p.get("memory_count", 0),
                "selected": p.get("selected_memory_count", 0),
                "skipped": p.get("skipped_memory_count", 0),
            }
    return None


def selection_records(events: list[ExperienceEvent]) -> list[dict]:
    """Selection records from the last turn's context_built event."""
    for event in reversed(events):
        if event.type == EventType.CONTEXT_BUILT:
            return event.payload.get("selection_records", [])
    return []


def summarize_selection_record(record: dict) -> str:
    """One readable line per selection decision.

    e.g. "Selected: Home airport is SFO. — matched airport; fact
    priority; within budget"
    """
    prefix = "Selected" if record.get("selected") else "Skipped"
    reason = record.get("reason", "")
    detail = reason.split(": ", 1)[-1] if reason else ""
    return f"{prefix}: {record.get('text', '')} — {detail}"


def compressed_summaries(events: list[ExperienceEvent]) -> list[dict]:
    """Compressed summaries used in the last turn's context build."""
    for event in reversed(events):
        if event.type == EventType.CONTEXT_BUILT:
            return event.payload.get("compressed_summaries", [])
    return []


def compression_totals(summaries: list[dict]) -> dict:
    """Aggregate counts for the compressed-context display."""
    return {
        "count": len(summaries),
        "source_count": sum(len(s.get("source_memory_ids", [])) for s in summaries),
        "original_chars": sum(s.get("original_chars", 0) for s in summaries),
        "compressed_chars": sum(s.get("compressed_chars", 0) for s in summaries),
        "saved_chars": sum(s.get("saved_chars", 0) for s in summaries),
    }


def reset_demo_state(agent: ExperienceOS, user_id: str = DEMO_USER_ID) -> None:
    """Return the demo to a known clean state for the given user.

    Removes the user's memories in every lifecycle status (works for
    both the in-memory and SQLite stores) and clears the in-process
    event history — which also empties every event-derived display:
    timeline, growth metrics, selection records, compressed summaries,
    and supplied context.
    """
    agent.memory_store.clear_user_memories(user_id)
    agent.event_bus.clear()


def growth_metrics(agent: ExperienceOS, user_id: str) -> dict:
    """Transparent counts showing accumulated experience over time."""
    events = agent.events

    def count(event_type: str) -> int:
        return sum(1 for e in events if e.type == event_type)

    compressed = [
        s
        for e in events
        if e.type == EventType.CONTEXT_BUILT
        for s in e.payload.get("compressed_summaries", [])
    ]
    return {
        "active_memories": len(agent.memories_for_user(user_id)),
        "created_memories": count(EventType.MEMORY_CREATED),
        "recalls": sum(
            1
            for e in events
            if e.type == EventType.MEMORY_RETRIEVED and e.payload.get("count", 0) > 0
        ),
        "updated_memories": count(EventType.MEMORY_SUPERSEDED),
        "forgotten_memories": count(EventType.MEMORY_FORGOTTEN),
        "compressed_summaries_used": len(compressed),
        "context_saved_chars": sum(s.get("saved_chars", 0) for s in compressed),
    }


def lifecycle_timeline(events: list[ExperienceEvent]) -> list[dict]:
    """Readable per-turn history of how experience changed."""
    created_texts = {
        e.payload.get("memory_id"): e.payload.get("text", "")
        for e in events
        if e.type == EventType.MEMORY_CREATED
    }
    replacement_ids = {
        e.payload.get("superseded_by")
        for e in events
        if e.type == EventType.MEMORY_SUPERSEDED
    } - {None}

    rows: list[dict] = []
    turn = 0
    for e in events:
        if e.type == EventType.INTERACTION_STARTED:
            turn += 1
        elif e.type == EventType.MEMORY_CREATED:
            # Replacements are covered by their "Updated" row.
            if e.payload.get("memory_id") not in replacement_ids:
                rows.append(
                    {"Turn": turn, "Event": "Remembered",
                     "Summary": e.payload.get("text", "")}
                )
        elif e.type == EventType.MEMORY_SUPERSEDED:
            new_text = created_texts.get(
                e.payload.get("superseded_by"), "a newer memory"
            )
            rows.append(
                {"Turn": turn, "Event": "Updated",
                 "Summary": f"{e.payload.get('text', '')} → {new_text}"}
            )
        elif e.type == EventType.MEMORY_FORGOTTEN:
            rows.append(
                {"Turn": turn, "Event": "Forgot",
                 "Summary": e.payload.get("text", "")}
            )
        elif e.type == EventType.CONTEXT_BUILT:
            selected = e.payload.get("selected_memory_count", 0)
            if selected:
                rows.append(
                    {"Turn": turn, "Event": "Recalled",
                     "Summary": f"{selected} selected, "
                                f"{e.payload.get('skipped_memory_count', 0)} skipped"}
                )
            summaries = e.payload.get("compressed_summaries", [])
            if summaries:
                sources = sum(
                    len(s.get("source_memory_ids", [])) for s in summaries
                )
                saved = sum(s.get("saved_chars", 0) for s in summaries)
                rows.append(
                    {"Turn": turn, "Event": "Compressed",
                     "Summary": f"{sources} memories → {len(summaries)} "
                                f"summary, saved {saved} chars"}
                )
    return rows


def supplied_context_lines(events: list[ExperienceEvent]) -> list[str]:
    """Experience lines ExperienceOS supplied to the provider on the last turn."""
    for event in reversed(events):
        if event.type != EventType.CONTEXT_BUILT:
            continue
        for message in event.payload.get("context_messages", []):
            content = message.get("content", "")
            if message.get("role") == "system" and MEMORY_HEADER in content:
                return [
                    line[2:].strip()
                    for line in content.splitlines()
                    if line.startswith("- ")
                ]
        return []
    return []
