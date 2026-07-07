"""Support logic for the demo dashboard.

Kept free of Streamlit imports so provider selection, agent creation,
and event display logic stay testable without the demo extra installed.
"""

from __future__ import annotations

from experienceos import ExperienceOS
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
    """Agent with fresh event history; memory store optional (in-memory default)."""
    return ExperienceOS(
        model=provider, memory_store=memory_store or InMemoryMemoryStore()
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
        return f"{p.get('memory_count', 0)} memories included in context."
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


def superseded_rows(agent: ExperienceOS, user_id: str) -> list[dict]:
    """Display rows for superseded memories, resolving replacement texts."""
    all_by_id = {m.id: m for m in agent.memories_for_user(user_id, status=None)}
    rows = []
    for m in agent.memories_for_user(user_id, status="superseded"):
        replacement = all_by_id.get(m.metadata.get("superseded_by", ""))
        rows.append(
            {
                "Memory": m.text,
                "Status": m.status,
                "Replaced by": replacement.text if replacement else "—",
                "Source session": m.source_session_id,
                "Updated": m.updated_at.strftime("%H:%M:%S"),
            }
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
