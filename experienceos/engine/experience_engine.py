"""Experience engine: orchestrates the interaction lifecycle.

Every step is published to the event bus so the experience layer's
work is visible.

Prior active memories are retrieved and injected into context BEFORE
new memories are planned from the current message — so a memory created
now influences later interactions, which keeps the cross-session
experience story clear.
"""

from __future__ import annotations

from experienceos.context.builder import ContextBuilder
from experienceos.events.bus import EventBus
from experienceos.events.schema import EventType
from experienceos.memory.planner import CREATE, SUPERSEDE, MemoryAction, MemoryPlanner
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.store import MemoryStore
from experienceos.providers.base import ModelProvider


class ExperienceEngine:
    """Runs one interaction through memory, context, the model, and events."""

    def __init__(
        self,
        model: ModelProvider,
        event_bus: EventBus,
        context_builder: ContextBuilder,
        memory_store: MemoryStore,
        memory_planner: MemoryPlanner | None = None,
    ):
        self.model = model
        self.event_bus = event_bus
        self.context_builder = context_builder
        self.memory_store = memory_store
        self.memory_planner = memory_planner or MemoryPlanner()

    def run_interaction(
        self,
        user_id: str,
        session_id: str,
        message: str,
    ) -> str:
        def emit(event_type: str, payload: dict | None = None):
            return self.event_bus.emit(event_type, user_id, session_id, payload)

        emit(EventType.INTERACTION_STARTED, {"message": message})

        emit(EventType.CONTEXT_REQUESTED)
        memories = self.memory_store.active_for_user(user_id)
        emit(
            EventType.MEMORY_RETRIEVED,
            {"memory_ids": [m.id for m in memories], "count": len(memories)},
        )
        context_messages = (
            self.context_builder.build_context(
                user_id, session_id, message, memories=memories
            )
            or []
        )
        emit(
            EventType.CONTEXT_BUILT,
            {
                "context_messages": context_messages,
                "count": len(context_messages),
                "memory_count": len(memories),
            },
        )

        actions = self.memory_planner.plan_memory_actions(
            user_id, session_id, message, existing=memories
        )
        emit(
            EventType.MEMORY_ACTION_PLANNED,
            {"planned_actions": [self._describe_action(a) for a in actions]},
        )
        self._apply_memory_actions(actions, user_id, session_id, emit)

        messages = [*context_messages, {"role": "user", "content": message}]
        response = self.model.complete(messages)
        emit(
            EventType.MODEL_CALLED,
            {"provider": self.model.name, "message_count": len(messages)},
        )

        emit(EventType.RESPONSE_RETURNED, {"response": response})
        emit(EventType.INTERACTION_COMPLETED)
        return response

    @staticmethod
    def _describe_action(action: MemoryAction) -> dict:
        if action.action == SUPERSEDE:
            return {
                "action": action.action,
                "memory_id": action.memory_id,
                "text": action.text,
                "reason": action.reason,
            }
        described = {"action": action.action, "kind": action.kind, "text": action.text}
        if action.replaces:
            described["replaces"] = action.replaces
        return described

    def _apply_memory_actions(self, actions, user_id, session_id, emit) -> None:
        """Apply supersedes first (with lineage to their replacements), then creates."""
        new_entries: list[ExperienceEntry] = []
        replacement_for: dict[str, ExperienceEntry] = {}
        for action in actions:
            if action.action != CREATE:
                continue
            entry = ExperienceEntry(
                user_id=user_id,
                text=action.text,
                kind=action.kind,
                status=MemoryStatus.ACTIVE,
                source_session_id=session_id,
            )
            if action.replaces:
                entry.metadata["replaces"] = action.replaces
                if action.reason:
                    entry.metadata["update_reason"] = action.reason
                replacement_for[action.replaces] = entry
            new_entries.append(entry)

        for action in actions:
            if action.action != SUPERSEDE:
                continue
            replacement = replacement_for.get(action.memory_id)
            superseded = self.memory_store.supersede(
                action.memory_id,
                superseded_by=replacement.id if replacement else None,
                reason=action.reason,
            )
            emit(
                EventType.MEMORY_SUPERSEDED,
                {
                    "memory_id": superseded.id,
                    "text": superseded.text,
                    "status": superseded.status,
                    "superseded_by": replacement.id if replacement else None,
                    "reason": action.reason,
                },
            )

        for entry in new_entries:
            self.memory_store.add(entry)
            emit(
                EventType.MEMORY_CREATED,
                {
                    "memory_id": entry.id,
                    "kind": entry.kind,
                    "text": entry.text,
                    "status": entry.status,
                },
            )
