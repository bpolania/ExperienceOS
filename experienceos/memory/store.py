"""In-memory store for accumulated experience.

Use SQLiteMemoryStore (memory/sqlite_store.py) when experience must
persist across restarts.
"""

from __future__ import annotations

from experienceos.memory.schema import ExperienceEntry, MemoryStatus, _utcnow


class InMemoryMemoryStore:
    """Deterministic in-memory store of experience entries.

    The default store: zero setup, vanishes with the process. Use
    SQLiteMemoryStore (memory/sqlite_store.py) when experience must
    survive restarts. Both expose the same methods.
    """

    def __init__(self):
        self._entries: list[ExperienceEntry] = []

    def add(self, memory: ExperienceEntry) -> ExperienceEntry:
        self._entries.append(memory)
        return memory

    def get(self, memory_id: str) -> ExperienceEntry | None:
        return next((e for e in self._entries if e.id == memory_id), None)

    def supersede(
        self,
        memory_id: str,
        *,
        superseded_by: str | None = None,
        reason: str | None = None,
    ) -> ExperienceEntry:
        """Mark a memory superseded, preserving it with lineage metadata."""
        memory = self.get(memory_id)
        if memory is None:
            raise KeyError(f"No memory with id {memory_id!r}")
        memory.status = MemoryStatus.SUPERSEDED
        memory.updated_at = _utcnow()
        memory.metadata["superseded_at"] = memory.updated_at.isoformat()
        if superseded_by:
            memory.metadata["superseded_by"] = superseded_by
        if reason:
            memory.metadata["superseded_reason"] = reason
        return memory

    def forget(self, memory_id: str, *, reason: str | None = None) -> ExperienceEntry:
        """Mark a memory forgotten, preserving it as inactive history."""
        memory = self.get(memory_id)
        if memory is None:
            raise KeyError(f"No memory with id {memory_id!r}")
        memory.status = MemoryStatus.FORGOTTEN
        memory.updated_at = _utcnow()
        memory.metadata["forgotten_at"] = memory.updated_at.isoformat()
        if reason:
            memory.metadata["forget_reason"] = reason
        return memory

    def list_memories(
        self, user_id: str, *, status: str | None = None
    ) -> list[ExperienceEntry]:
        return [
            e
            for e in self._entries
            if e.user_id == user_id and (status is None or e.status == status)
        ]

    def active_for_user(self, user_id: str) -> list[ExperienceEntry]:
        return self.list_memories(user_id, status=MemoryStatus.ACTIVE)

    def clear(self) -> None:
        self._entries.clear()

    def clear_user_memories(self, user_id: str) -> None:
        """Remove every memory for one user, regardless of status."""
        self._entries = [e for e in self._entries if e.user_id != user_id]


# Backwards-compatible name used throughout the SDK.
MemoryStore = InMemoryMemoryStore
