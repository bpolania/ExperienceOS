"""Event schema. Events make the experience layer observable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class EventType:
    """Event types emitted during one interaction lifecycle."""

    INTERACTION_STARTED = "interaction_started"
    CONTEXT_REQUESTED = "context_requested"
    CONTEXT_BUILT = "context_built"
    MODEL_CALLED = "model_called"
    RESPONSE_RETURNED = "response_returned"
    MEMORY_ACTION_PLANNED = "memory_action_planned"
    MEMORY_CREATED = "memory_created"
    MEMORY_SUPERSEDED = "memory_superseded"
    MEMORY_FORGOTTEN = "memory_forgotten"
    MEMORY_RETRIEVED = "memory_retrieved"
    INTERACTION_COMPLETED = "interaction_completed"
    # Hybrid extraction audit events (emitted only when a hybrid
    # planner is configured; additive for existing consumers).
    MEMORY_EXTRACTION_GATE_PASSED = "memory_extraction_gate_passed"
    MEMORY_EXTRACTION_GATE_REJECTED = "memory_extraction_gate_rejected"
    MEMORY_EXTRACTION_INVOKED = "memory_extraction_invoked"
    MEMORY_CANDIDATE_PROPOSED = "memory_candidate_proposed"
    MEMORY_CANDIDATE_REJECTED = "memory_candidate_rejected"
    MEMORY_CANDIDATE_ACCEPTED = "memory_candidate_accepted"
    MEMORY_EXTRACTION_FAILED_SAFE = "memory_extraction_failed_safe"
    # Grounded-extraction integration (emitted only when an extraction
    # coordinator is configured and enabled; additive for consumers).
    EXTRACTION_INTEGRATION_EVALUATED = "extraction_integration_evaluated"


@dataclass(frozen=True)
class ExperienceEvent:
    """One observable step in the experience layer."""

    type: str
    user_id: str
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
