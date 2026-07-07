"""Memory schema: the shape of accumulated experience."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


class MemoryStatus:
    """Lifecycle states for a memory.

    ACTIVE memories are candidates for context. SUPERSEDED memories were
    replaced by newer experience; FORGOTTEN memories were explicitly
    removed by the user. Both are kept as visible history and never
    injected into context.
    """

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


class MemoryKind:
    """What kind of experience a memory captures.

    The default planner detects all three: preferences ("I prefer ..."),
    facts ("My home airport is ..."), and instructions ("Always ...").
    """

    PREFERENCE = "preference"
    FACT = "fact"
    INSTRUCTION = "instruction"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ExperienceEntry:
    """One unit of accumulated experience."""

    user_id: str
    text: str
    kind: str = MemoryKind.PREFERENCE
    status: str = MemoryStatus.ACTIVE
    source_session_id: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    metadata: dict = field(default_factory=dict)

    def to_record(self) -> dict:
        """Flat, JSON-friendly representation (timestamps as ISO-8601)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "kind": self.kind,
            "text": self.text,
            "status": self.status,
            "source_session_id": self.source_session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_record(cls, record: dict) -> "ExperienceEntry":
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            kind=record["kind"],
            text=record["text"],
            status=record["status"],
            source_session_id=record["source_session_id"],
            created_at=datetime.fromisoformat(record["created_at"]),
            updated_at=datetime.fromisoformat(record["updated_at"]),
            metadata=dict(record.get("metadata") or {}),
        )
