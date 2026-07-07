"""SQLite-backed memory store: accumulated experience survives restarts.

Standard-library sqlite3 only — no ORM, no migrations framework. The
schema bootstraps itself on first use.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from experienceos.memory.schema import ExperienceEntry, MemoryStatus, _utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experience_entries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experience_entries_user_status
ON experience_entries(user_id, status);
CREATE INDEX IF NOT EXISTS idx_experience_entries_user_created
ON experience_entries(user_id, created_at);
"""


class SQLiteMemoryStore:
    """Same interface as InMemoryMemoryStore, persisted to a local file."""

    def __init__(self, db_path: str | Path = "experienceos.sqlite3"):
        self.db_path = str(db_path)
        parent = Path(self.db_path).resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: Streamlit reruns execute on different
        # threads while the store lives in session state.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add(self, memory: ExperienceEntry) -> ExperienceEntry:
        record = memory.to_record()
        self._conn.execute(
            """
            INSERT INTO experience_entries
                (id, user_id, kind, text, status, source_session_id,
                 created_at, updated_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["user_id"],
                record["kind"],
                record["text"],
                record["status"],
                record["source_session_id"],
                record["created_at"],
                record["updated_at"],
                json.dumps(record["metadata"]),
            ),
        )
        self._conn.commit()
        return memory

    def get(self, memory_id: str) -> ExperienceEntry | None:
        row = self._conn.execute(
            "SELECT * FROM experience_entries WHERE id = ?", (memory_id,)
        ).fetchone()
        return self._entry_from_row(row) if row else None

    def list_memories(
        self, user_id: str, *, status: str | None = None
    ) -> list[ExperienceEntry]:
        query = "SELECT * FROM experience_entries WHERE user_id = ?"
        params: list = [user_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at, rowid"
        rows = self._conn.execute(query, params).fetchall()
        return [self._entry_from_row(row) for row in rows]

    def active_for_user(self, user_id: str) -> list[ExperienceEntry]:
        return self.list_memories(user_id, status=MemoryStatus.ACTIVE)

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
        self._conn.execute(
            """
            UPDATE experience_entries
            SET status = ?, updated_at = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                memory.status,
                memory.updated_at.isoformat(),
                json.dumps(memory.metadata),
                memory.id,
            ),
        )
        self._conn.commit()
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
        self._conn.execute(
            """
            UPDATE experience_entries
            SET status = ?, updated_at = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                memory.status,
                memory.updated_at.isoformat(),
                json.dumps(memory.metadata),
                memory.id,
            ),
        )
        self._conn.commit()
        return memory

    def clear(self) -> None:
        self._conn.execute("DELETE FROM experience_entries")
        self._conn.commit()

    def clear_user_memories(self, user_id: str) -> None:
        """Remove every memory for one user, regardless of status."""
        self._conn.execute(
            "DELETE FROM experience_entries WHERE user_id = ?", (user_id,)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> ExperienceEntry:
        return ExperienceEntry.from_record(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "kind": row["kind"],
                "text": row["text"],
                "status": row["status"],
                "source_session_id": row["source_session_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metadata": json.loads(row["metadata_json"]),
            }
        )
