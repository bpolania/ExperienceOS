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
        extraction_coordinator=None,
    ):
        self.model = model
        self.event_bus = event_bus
        self.context_builder = context_builder
        self.memory_store = memory_store
        self.memory_planner = memory_planner or MemoryPlanner()
        self.experience_manager = experience_manager or ExperienceManager(
            RuleBasedMemoryPolicy(self.memory_planner)
        )
        # Optional grounded-extraction integration seam. None (the
        # default) keeps every existing path identical: no controller
        # runs and no integration event is emitted.
        self.extraction_coordinator = extraction_coordinator

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
        # Temporal-aware builders may request superseded records too
        # (for explicit historical/as-of retrieval). Their retrieval
        # strategy still lifecycle-filters; forgotten records are
        # NEVER passed. Default False keeps every v1 path identical.
        if getattr(self.context_builder, "wants_inactive_candidates", False):
            memories = [
                *memories,
                *self.memory_store.list_memories(
                    user_id, status=MemoryStatus.SUPERSEDED
                ),
            ]
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
                # Phase 11: additive; empty for legacy/disabled paths.
                "retrieval_diagnostics": getattr(
                    build, "retrieval_diagnostics", {}
                ),
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
        # Hybrid planners buffer bounded extraction audit records;
        # publish them on the same bus. Planners without the hook
        # (the v1 default) are unaffected.
        drain = getattr(self.memory_planner, "drain_extraction_events", None)
        if callable(drain):
            for extraction_event, payload in drain():
                emit(extraction_event, payload)
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
            reason = self._reject_reason(
                action, memories, active_ids, retired_ids
            )
            if reason is not None:
                rejected_actions.append((action, reason))
            else:
                valid_actions.append(action)

        # Grounded-extraction integration: runs after the canonical
        # plan is validated and before the sole mutation boundary. In
        # disabled mode nothing happens; shadow/candidate never touch
        # valid_actions; only an authorized adopted proposal is merged,
        # and it passes the SAME lifecycle check and SAME application.
        extraction_event = None
        if (
            self.extraction_coordinator is not None
            and self.extraction_coordinator.enabled
        ):
            extraction_event = self._evaluate_extraction(
                user_id, session_id, message, memories, active_ids,
                retired_ids, valid_actions,
            )

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
        if extraction_event is not None:
            emit(
                EventType.EXTRACTION_INTEGRATION_EVALUATED,
                extraction_event,
            )
        self._apply_memory_actions(valid_actions, user_id, session_id, emit)

        messages = [*context_messages, {"role": "user", "content": message}]
        response = self.model.complete(messages)
        emit(
            EventType.MODEL_CALLED,
            {"provider": self.model.name, "message_count": len(messages)},
        )

        # Temporal planners may keep bounded assistant context for
        # explicit later confirmation; planners without the hook (all
        # v1 and earlier v2 paths) are unaffected.
        note = getattr(self.memory_planner, "note_assistant_message", None)
        if callable(note):
            note(user_id, session_id, response)

        emit(EventType.RESPONSE_RETURNED, {"response": response})
        emit(EventType.INTERACTION_COMPLETED)
        return response

    @staticmethod
    def _reject_reason(action, memories, active_ids, retired_ids):
        """The single lifecycle-admission check, shared by canonical
        planning and adopted/candidate extraction evaluation. A policy
        can never re-target inactive memory; a create duplicating an
        active memory is rejected unless every match is retired in this
        same batch. Returns a bounded reason or None (admissible)."""
        if (
            action.action in (SUPERSEDE, FORGET)
            and action.memory_id not in active_ids
        ):
            return "target_not_active"
        if action.action == CREATE:
            matching_ids = [
                m.id
                for m in memories
                if m.kind == action.kind
                and _normalized_text(m.text)
                == _normalized_text(action.text)
            ]
            if matching_ids and not all(
                mid in retired_ids for mid in matching_ids
            ):
                return "duplicate_of_active"
        return None

    def _extraction_reject_reason(
        self, action, memories, active_ids, retired_ids, planned
    ):
        """The canonical admission check plus a same-batch dedup: a
        controller create equivalent to a canonical create already in
        this batch must not add a second active memory (contract §14).
        Only applied to controller-originated actions — canonical
        planning is unchanged."""
        reason = self._reject_reason(
            action, memories, active_ids, retired_ids
        )
        if reason is not None:
            return reason
        if action.action == CREATE and any(
            planned_action.action == CREATE
            and planned_action.kind == action.kind
            and _normalized_text(planned_action.text)
            == _normalized_text(action.text)
            for planned_action in planned
        ):
            return "duplicate_of_planned"
        return None

    def _evaluate_extraction(
        self, user_id, session_id, message, memories, active_ids,
        retired_ids, valid_actions,
    ) -> dict:
        """Run the extraction coordinator and interpret its bounded
        decision. Shadow/candidate never mutate; only an authorized,
        lifecycle-admissible adopted action is appended to
        valid_actions (the same list applied by the sole mutation
        boundary). Returns the integration event payload."""
        from experienceos.controllers.extraction import ExtractionEvidence
        from experienceos.memory.extraction_integration import (
            MODE_ADOPTED,
            MODE_CANDIDATE,
            STATUS_AUTHORIZED,
            STATUS_PROPOSED,
        )

        source_id = f"{session_id}:{len(self.event_bus.history())}"
        provenance = "user_asserted"
        evidence = ExtractionEvidence(
            user_text=message,
            provenance_label=provenance,
            metadata={"source_id": source_id, "user_id": user_id},
        )
        outcome = self.extraction_coordinator.evaluate(
            evidence, source_id=source_id, provenance=provenance
        )
        diagnostics = dict(outcome.diagnostics)
        action = outcome.translated_action

        # Candidate mode: non-mutating lifecycle evaluation using the
        # SAME admission check; nothing is applied.
        if outcome.effect_mode == MODE_CANDIDATE and action is not None:
            reason = self._extraction_reject_reason(
                action, memories, active_ids, retired_ids, valid_actions
            )
            diagnostics["lifecycle_evaluation"] = (
                "rejected" if reason else "eligible"
            )
            diagnostics["lifecycle_rejection_reason"] = reason
            diagnostics["duplicate_or_conflict"] = (
                reason if reason and "duplicate" in reason else None
            )
            diagnostics["action_applied"] = False
            diagnostics["canonical_effect"] = False

        # Adopted mode: an authorized, admissible action is merged into
        # the canonical valid_actions list and applied by the engine.
        elif outcome.effect_mode == MODE_ADOPTED and (
            outcome.status == STATUS_AUTHORIZED and action is not None
        ):
            reason = self._extraction_reject_reason(
                action, memories, active_ids, retired_ids, valid_actions
            )
            if reason is None:
                valid_actions.append(action)
                diagnostics["lifecycle_evaluation"] = "eligible"
                diagnostics["action_applied"] = True
                diagnostics["canonical_effect"] = True
            else:
                diagnostics["lifecycle_evaluation"] = "rejected"
                diagnostics["lifecycle_rejection_reason"] = reason
                diagnostics["duplicate_or_conflict"] = (
                    reason if "duplicate" in reason else None
                )
                diagnostics["action_applied"] = False
                diagnostics["canonical_effect"] = False
        # Shadow (and any non-applied path): diagnostics already carry
        # canonical_effect False from the coordinator.
        return diagnostics

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
            if action.metadata:
                entry.metadata.update(action.metadata)
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
