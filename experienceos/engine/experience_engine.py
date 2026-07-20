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
        transition_coordinator=None,
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
        # Optional transition integration seam. None (the default) keeps
        # every existing path identical: no controller runs, no verifier
        # runs, and no integration event is emitted.
        self.transition_coordinator = transition_coordinator

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
                # Additive; empty for legacy/disabled paths.
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
        # Structural planner origin (seam audit): the admitted planner
        # actions, captured before any extraction or transition append,
        # are the only replacement candidates. Provenance is kept by this
        # snapshot, never inferred from the mixed list later.
        admitted_planner_actions = tuple(valid_actions)

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

        # Transition integration: runs after the canonical plan is
        # validated and before the sole mutation boundary, exactly like
        # the extraction seam. Disabled does nothing; shadow, candidate,
        # and verify-only never touch valid_actions; only an authorized
        # adopted action is merged, and it passes the SAME lifecycle
        # check and the SAME application path.
        transition_event = None
        if (
            self.transition_coordinator is not None
            and self.transition_coordinator.enabled
        ):
            transition_event = self._evaluate_transition(
                user_id, session_id, message, memories, active_ids,
                retired_ids, valid_actions, admitted_planner_actions,
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
        if transition_event is not None:
            emit(
                EventType.TRANSITION_INTEGRATION_EVALUATED,
                transition_event,
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

    def _evaluate_transition(
        self, user_id, session_id, message, memories, active_ids,
        retired_ids, valid_actions, planner_actions,
    ) -> dict:
        """Run the transition coordinator and interpret its decision.

        Disabled never reaches here. Shadow, candidate, and verify-only
        never touch ``valid_actions`` (they may compute a non-mutating
        replacement projection for diagnostics). In adopted mode, when a
        matching replacement authorization is present, the uniquely
        matched planner create is suppressed and the transition sequence
        replaces it (governed action replacement); otherwise the existing
        append path runs unchanged. Every mutation still goes through the
        same admission check and the sole application boundary.
        """
        from experienceos.memory.transition_integration import (
            CanonicalActionEffect,
            CanonicalEffectStatus,
            TransitionIntegrationMode,
            TransitionIntegrationRequest,
        )
        from experienceos.memory.transition_verification import (
            EvidenceMode,
            TransitionSourceEvidence,
            build_before_state,
        )

        request_id = f"{session_id}:{len(self.event_bus.history())}"
        evidence = TransitionSourceEvidence(
            source_statement=message,
            source_event_id=request_id,
            session_id=session_id,
            evidence_mode=EvidenceMode.GROUNDED_VALID,
            provenance_ref="user_asserted",
        )
        request = TransitionIntegrationRequest(
            statement=message,
            evidence=evidence,
            before_state=build_before_state(memories, user_id=user_id),
            request_id=request_id,
            user_id=user_id,
            existing_actions=tuple(valid_actions),
        )
        result = self.transition_coordinator.evaluate(request)
        payload = result.to_record()
        payload["action_applied"] = False
        payload["replacement"] = {"attempted": False}

        is_adopted_add = (
            result.effective_mode == TransitionIntegrationMode.ADOPTED
            and result.canonical_action_effect == CanonicalActionEffect.ACTION_ADDED
            and bool(result.generated_actions)
        )

        # Shadow / candidate: a non-mutating replacement projection, for
        # diagnostics only. Never touches valid_actions.
        if result.effective_mode in (
            TransitionIntegrationMode.SHADOW,
            TransitionIntegrationMode.CANDIDATE,
        ):
            payload["replacement"] = self._replacement_projection(
                planner_actions, result, request, message,
            )
            return payload

        if not is_adopted_add:
            return payload

        config = getattr(self.transition_coordinator, "config", None)
        repl_auths = getattr(config, "replacement_authorizations", ())
        runtime_authority = getattr(config, "runtime_authority", None)
        sequence = tuple(result.generated_actions)
        supersede_bearing = any(
            a.action == SUPERSEDE for a in sequence
        ) and any(a.action == CREATE for a in sequence)

        # Governed replacement is attempted for a supersede-bearing
        # transition when a replacement authority exists: either a static
        # replacement authorization, or a bounded runtime authority that
        # can issue the plan-bound receipt inside _governed_replacement.
        if (repl_auths or runtime_authority is not None) and supersede_bearing:
            handled = self._governed_replacement(
                planner_actions, valid_actions, sequence, result, request,
                message, memories, active_ids, retired_ids, repl_auths, payload,
            )
            if handled:
                return payload
            # Not a replacement scenario (matcher said none needed) — fall
            # through to the existing append path.

        self._transition_append(
            sequence, valid_actions, memories, active_ids, retired_ids, payload,
        )
        return payload

    def _transition_append(
        self, sequence, valid_actions, memories, active_ids, retired_ids, payload,
    ) -> None:
        """The existing add-not-replace behavior, factored unchanged.

        The linked supersede + create enter the canonical list together or
        neither does, after the same admission check every controller
        action already faces.
        """
        from experienceos.memory.transition_integration import (
            CanonicalActionEffect,
            CanonicalEffectStatus,
        )

        rejections = []
        for action in sequence:
            reason = self._extraction_reject_reason(
                action, memories, active_ids, retired_ids, valid_actions
            )
            if reason is not None:
                rejections.append(reason)
        if rejections:
            payload["canonical_action_effect"] = (
                CanonicalActionEffect.LIFECYCLE_REJECTED
            )
            payload["canonical_effect_status"] = (
                CanonicalEffectStatus.AUTHORIZED_NOT_APPLIED
            )
            payload["lifecycle_rejection_reason"] = rejections[0]
            payload["manager_admitted"] = False
            payload["action_applied"] = False
        else:
            for action in sequence:
                valid_actions.append(action)
            payload["canonical_action_effect"] = CanonicalActionEffect.APPLIED
            payload["canonical_effect_status"] = CanonicalEffectStatus.APPLIED
            payload["lifecycle_rejection_reason"] = None
            payload["manager_admitted"] = True
            payload["action_applied"] = True

    def _replacement_projection(
        self, planner_actions, result, request, message,
    ) -> dict:
        """Non-mutating replacement projection for shadow/candidate.

        Uses the pure translation to obtain the sequence a supersession
        would need, then the pure matcher and plan builder. Nothing is
        applied and valid_actions is never touched.
        """
        from experienceos.memory.action_replacement import (
            CONTEXT_CANDIDATE, CONTEXT_SHADOW, build_replacement,
        )
        from experienceos.memory.transition_integration import (
            TransitionIntegrationMode, translate_transition,
        )

        verification = result.verification
        proposal = result.proposal
        if (
            proposal is None
            or verification is None
            or not getattr(verification, "accepted", False)
        ):
            return {"attempted": False, "reason": "no_verified_proposal"}
        # Source the sequence a supersession would need: generated actions
        # if present, else the coordinator's own translation, else a fresh
        # pure translation. Shadow re-translates; candidate reuses its.
        sequence = tuple(getattr(result, "generated_actions", ()) or ())
        if not sequence:
            translation = getattr(result, "translation", None)
            if translation is not None and getattr(translation, "succeeded", False):
                sequence = tuple(getattr(translation, "actions", ()) or ())
        if not sequence:
            translation = translate_transition(
                proposal, verification, request.before_state
            )
            sequence = tuple(translation.actions) if translation.succeeded else ()
        if not sequence:
            return {"attempted": False, "reason": "no_translation"}
        context = (
            CONTEXT_SHADOW
            if result.effective_mode == TransitionIntegrationMode.SHADOW
            else CONTEXT_CANDIDATE
        )
        decision, plan = build_replacement(
            planner_actions, sequence,
            verification_accepted=True,
            transition_type=result.transition_type or "",
            source_digest=request.source_digest(),
            before_state_digest=request.before_state.digest(),
            verified_transition_id=str(
                getattr(proposal, "proposal_id", "") or ""
            ),
            context=context,
        )
        return {
            "attempted": True,
            "applied": False,
            "matcher_decision": decision.decision,
            "plan_status": plan.status,
            "plan_digest": plan.plan_digest,
            "canonical_effect": plan.canonical_effect,
            "projected_action_list_digest": plan.projected_action_list_digest,
            "original_action_list_digest": plan.original_action_list_digest,
        }

    def _governed_replacement(
        self, planner_actions, valid_actions, sequence, result, request,
        message, memories, active_ids, retired_ids, repl_auths, payload,
    ) -> bool:
        """Attempt an authorized replacement in adopted mode.

        Returns True when the replacement path handled the outcome
        (applied, or failed-closed to planner fallback), and False when it
        is not a replacement scenario (the caller then appends as before).
        Never appends both creates: a failed replacement leaves the
        canonical planner list untouched.
        """
        from experienceos.memory.transition_integration import (
            CanonicalActionEffect, CanonicalEffectStatus,
        )
        from experienceos.memory.action_replacement import (
            CONTEXT_CANDIDATE, NO_REPLACEMENT_NEEDED, PLAN_READY,
            authorize_replacement, build_replacement,
        )

        proposal = result.proposal
        before_digest = request.before_state.digest()
        transition_id = str(getattr(proposal, "proposal_id", "") or "")
        decision, plan = build_replacement(
            planner_actions, sequence,
            verification_accepted=bool(
                getattr(result.verification, "accepted", False)
            ),
            transition_type=result.transition_type or "",
            source_digest=request.source_digest(),
            before_state_digest=before_digest,
            verified_transition_id=transition_id,
            context=CONTEXT_CANDIDATE,
        )

        repl = {
            "attempted": True,
            "applied": False,
            "matcher_decision": decision.decision,
            "plan_status": plan.status,
            "plan_digest": plan.plan_digest,
            "canonical_effect": plan.canonical_effect,
            "original_action_list_digest": plan.original_action_list_digest,
            "projected_action_list_digest": plan.projected_action_list_digest,
            "authorization_status": None,
            "fallback_used": False,
            "fallback_reason": None,
        }

        # Not a replacement scenario (e.g. a pure create): let the caller
        # append as before. This leaves the residual pure-create class.
        if decision.decision == NO_REPLACEMENT_NEEDED:
            payload["replacement"] = {**repl, "attempted": False,
                                      "reason": "no_replacement_needed"}
            return False

        def fallback(reason: str, *, effect=CanonicalActionEffect.AUTHORIZATION_DENIED):
            # Planner-only fallback: never append the transition sequence,
            # never suppress a planner action.
            payload["canonical_action_effect"] = effect
            payload["canonical_effect_status"] = (
                CanonicalEffectStatus.ELIGIBLE_NOT_AUTHORIZED
            )
            payload["manager_admitted"] = False
            payload["action_applied"] = False
            payload["replacement"] = {
                **repl, "applied": False, "fallback_used": True,
                "fallback_reason": reason,
            }

        if plan.status != PLAN_READY or plan.binding() is None:
            fallback(f"plan_{plan.status}",
                     effect=CanonicalActionEffect.LIFECYCLE_REJECTED)
            return True

        # Runtime replacement receipt: this path runs only for an
        # already-authorized adopted supersede (is_adopted_add,
        # supersede-bearing), and the plan is built from that exact
        # transition sequence, so a configured bounded authority may issue
        # the plan-bound receipt. It is only an additional candidate; the
        # existing exact ``authorize_replacement`` validator still decides.
        runtime_authority = getattr(
            getattr(self.transition_coordinator, "config", None),
            "runtime_authority", None,
        )
        candidates = list(repl_auths)
        runtime_repl_issued = False
        if runtime_authority is not None:
            try:
                runtime_repl = runtime_authority.authorize_replacement(plan)
            except Exception:  # noqa: BLE001 — contained; fall back to static
                runtime_repl = None
            if runtime_repl is not None:
                candidates.append(runtime_repl)
                runtime_repl_issued = True
        repl["runtime_replacement_receipt_issued"] = runtime_repl_issued

        auth = authorize_replacement(plan, tuple(candidates))
        repl["authorization_status"] = auth.to_record()
        if not auth.authorized:
            fallback(auth.reason)
            return True

        # Authorized. Admit the inserted sequence atomically against the
        # surviving actions (the matched create removed), then rewrite.
        matched_index = plan.matched_occurrence.occurrence_index
        extraction_part = list(valid_actions[len(planner_actions):])
        survivors = [
            a for i, a in enumerate(planner_actions) if i != matched_index
        ] + extraction_part
        rejections = [
            reason
            for action in sequence
            if (
                reason := self._extraction_reject_reason(
                    action, memories, active_ids, retired_ids, survivors
                )
            )
            is not None
        ]
        if rejections:
            fallback(rejections[0], effect=CanonicalActionEffect.LIFECYCLE_REJECTED)
            payload["lifecycle_rejection_reason"] = rejections[0]
            return True

        rewritten = list(plan.projected_actions) + extraction_part
        valid_actions[:] = rewritten
        payload["canonical_action_effect"] = CanonicalActionEffect.ACTION_REPLACED
        payload["canonical_effect_status"] = CanonicalEffectStatus.APPLIED
        payload["manager_admitted"] = True
        payload["action_applied"] = True
        payload["lifecycle_rejection_reason"] = None
        payload["replacement"] = {
            **repl, "applied": True,
            "authorization_status": auth.to_record(),
            "suppressed_occurrence_index": matched_index,
            "final_action_count": len(rewritten),
        }
        return True

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
