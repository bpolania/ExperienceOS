"""Experience engine: orchestrates the interaction lifecycle.

Every step is published to the event bus so the experience layer's
work is visible.

Prior active memories are retrieved and injected into context BEFORE
new memories are planned from the current message — so a memory created
now influences later interactions, which keeps the cross-session
experience story clear.
"""

from __future__ import annotations

from dataclasses import asdict

from experienceos.context.builder import ContextBuilder, ContextBuildResult
from experienceos.events.bus import EventBus
from experienceos.events.schema import EventType
from experienceos.memory.planner import (
    CREATE,
    FORGET,
    SUPERSEDE,
    MemoryAction,
    MemoryPlanner,
    _normalized_text,
)
from experienceos.policy.base import PolicyContext
from experienceos.policy.manager import ExperienceManager
from experienceos.policy.rule_based import RuleBasedMemoryPolicy
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.store import MemoryStore
from experienceos.memory.tags import assign_tags, domain_for
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
        experience_manager: ExperienceManager | None = None,
    ):
        self.model = model
        self.event_bus = event_bus
        self.context_builder = context_builder
        self.memory_store = memory_store
        self.memory_planner = memory_planner or MemoryPlanner()
        self.experience_manager = experience_manager or ExperienceManager(
            RuleBasedMemoryPolicy(self.memory_planner)
        )

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
        raw = self.context_builder.build_context(
            user_id, session_id, message, memories=memories
        )
        if isinstance(raw, ContextBuildResult):
            build = raw
        else:
            # Custom builders may still return a plain message list; treat
            # everything they received as selected.
            build = ContextBuildResult(
                messages=list(raw or []),
                selected_memories=list(memories),
                skipped_memories=[],
                candidate_memories=list(memories),
            )
        context_messages = build.messages
        emit(
            EventType.CONTEXT_BUILT,
            {
                "context_messages": context_messages,
                "count": len(context_messages),
                "memory_count": len(build.candidate_memories),
                "candidate_memory_ids": [m.id for m in build.candidate_memories],
                "selected_memory_ids": [m.id for m in build.selected_memories],
                "skipped_memory_ids": [m.id for m in build.skipped_memories],
                "selected_memory_count": len(build.selected_memories),
                "skipped_memory_count": len(build.skipped_memories),
                "memory_budget": build.memory_budget,
                "selection_records": [asdict(r) for r in build.selection_records],
                "compressed_summaries": [s.to_payload() for s in build.summaries],
            },
        )

        result = self.experience_manager.plan(
            PolicyContext(
                user_id=user_id,
                session_id=session_id,
                message=message,
                active_memories=memories,
            )
        )
        # Lifecycle validation: a policy can never re-target inactive
        # memory. Supersede/forget targets must belong to this
        # interaction's active snapshot; invalid targets are skipped
        # and reported, never mutated. Creates that duplicate an active
        # memory are likewise skipped — unless every matching memory is
        # being retired in this same batch (a replacement, not a copy).
        active_ids = {m.id for m in memories}
        retired_ids = {
            a.memory_id
            for a in result.actions
            if a.action in (SUPERSEDE, FORGET) and a.memory_id in active_ids
        }
        valid_actions: list[MemoryAction] = []
        rejected_actions: list[tuple[MemoryAction, str]] = []
        for action in result.actions:
            if (
                action.action in (SUPERSEDE, FORGET)
                and action.memory_id not in active_ids
            ):
                rejected_actions.append((action, "target_not_active"))
                continue
            if action.action == CREATE:
                matching_ids = [
                    m.id
                    for m in memories
                    if m.kind == action.kind
                    and _normalized_text(m.text) == _normalized_text(action.text)
                ]
                if matching_ids and not all(
                    mid in retired_ids for mid in matching_ids
                ):
                    rejected_actions.append((action, "duplicate_of_active"))
                    continue
            valid_actions.append(action)

        planned = []
        for action, decision in zip(result.actions, result.decisions):
            entry = {
                **self._describe_action(action),
                "confidence": decision.confidence,
                "explanation": decision.explanation,
                "decision_source": decision.decision_source,
            }
            if decision.fallback_reason is not None:
                entry["fallback_reason"] = decision.fallback_reason
            planned.append(entry)
        emit(
            EventType.MEMORY_ACTION_PLANNED,
            {
                "planned_actions": planned,
                "policy": {
                    "mode": result.policy_mode,
                    "decision_source": result.decision_source,
                    "fallback_used": result.fallback_used,
                    "fallback_reason": result.fallback_reason,
                },
                "rejected_actions": [
                    {
                        **self._describe_action(action),
                        "rejected_reason": reason,
                    }
                    for action, reason in rejected_actions
                ],
            },
        )
        self._apply_memory_actions(valid_actions, user_id, session_id, emit)

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
        if action.action == FORGET:
            return {
                "action": action.action,
                "memory_id": action.memory_id,
                "text": action.text,
                "reason": action.reason,
                "request": action.request,
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
            tags = assign_tags(entry.text)
            if tags:
                entry.metadata["tags"] = tags
                entry.metadata["domain"] = domain_for(tags)
            if action.replaces:
                entry.metadata["replaces"] = action.replaces
                if action.reason:
                    entry.metadata["update_reason"] = action.reason
                replacement_for[action.replaces] = entry
            new_entries.append(entry)

        for action in actions:
            if action.action == SUPERSEDE:
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
            elif action.action == FORGET:
                before = self.memory_store.get(action.memory_id)
                previous_status = before.status if before else None
                forgotten = self.memory_store.forget(
                    action.memory_id, reason=action.reason
                )
                emit(
                    EventType.MEMORY_FORGOTTEN,
                    {
                        "memory_id": forgotten.id,
                        "previous_status": previous_status,
                        "status": forgotten.status,
                        "text": forgotten.text,
                        "reason": action.reason,
                        "request": action.request,
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
