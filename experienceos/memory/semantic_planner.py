"""SemanticMemoryPlanner: the Phase 9 slots-v2 planning strategy.

Runs the unchanged v1 ``MemoryPlanner`` first (its keyed supersession,
duplicate skipping, and forget handling stay authoritative), then
post-processes the planned creates with semantic identity:

1. attach versioned identity metadata to each create it can normalize;
2. drop creates whose identity duplicates an active memory (a
   paraphrase of an existing value must not create a second record or
   supersede its equivalent);
3. add conservative supersede actions for high-confidence single-value
   conflicts the v1 keyed rules missed, pairing them with the create
   through the existing ``replaces`` lineage channel.

All emitted actions still flow through ExperienceManager validation
and ExperienceEngine lifecycle checks — this planner never touches
storage. v1 behavior is selected by constructing the plain
``MemoryPlanner``; this subclass is opt-in per configuration
(``experienceos_slots_v2`` in the benchmark).
"""

from __future__ import annotations

from dataclasses import replace

from experienceos.memory.planner import (
    CREATE,
    SUPERSEDE,
    MemoryAction,
    MemoryPlanner,
)
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.semantic import (
    CONFLICT_STRATEGY_VERSION,
    METADATA_KEY,
    SEMANTIC_IDENTITY_VERSION,
    Decision,
    SemanticNormalizer,
    identity_of,
    resolve_conflicts,
)


class SemanticMemoryPlanner(MemoryPlanner):
    """v1 planning plus generalized, conservative semantic supersession."""

    semantic_identity_version = SEMANTIC_IDENTITY_VERSION
    conflict_strategy = CONFLICT_STRATEGY_VERSION

    def __init__(self, normalizer: SemanticNormalizer | None = None):
        self.normalizer = normalizer or SemanticNormalizer()

    def plan_memory_actions(
        self,
        user_id: str,
        session_id: str,
        message: str,
        existing: list[ExperienceEntry] | None = None,
    ) -> list[MemoryAction]:
        existing = existing or []
        actions = super().plan_memory_actions(
            user_id, session_id, message, existing
        )
        actions = self._veto_cross_scope_v1_pairs(actions, existing)
        active = [
            e for e in existing if e.status == MemoryStatus.ACTIVE
        ]
        # Targets already retired by v1 keyed rules in this batch are
        # not valid semantic conflict targets.
        retired_ids = {
            a.memory_id for a in actions if a.action == SUPERSEDE
        }
        eligible = [e for e in active if e.id not in retired_ids]

        result: list[MemoryAction] = []
        for action in actions:
            if action.action != CREATE:
                result.append(action)
                continue
            identity = self.normalizer.normalize(action.kind, action.text)
            if identity is None:
                result.append(action)
                continue
            enriched = replace(
                action,
                metadata={METADATA_KEY: identity.to_metadata()},
            )
            if action.replaces:
                # Already part of a v1 keyed supersession pair; keep it,
                # just enriched with identity metadata.
                result.append(enriched)
                continue

            decisions = resolve_conflicts(
                identity, eligible, self.normalizer
            )
            duplicates = [
                d for d in decisions if d.decision == Decision.DUPLICATE
            ]
            supersessions = [
                d for d in decisions if d.decision == Decision.SUPERSEDE
            ]
            if duplicates:
                # Equivalent value already active: no new record, no
                # supersession of the equivalent record.
                continue
            if not supersessions:
                result.append(enriched)
                continue
            # Multiple conflicts supersede together only when every one
            # is an independent high-confidence single-value conflict in
            # the same slot (resolve_conflicts already enforces slot
            # equality and confidence); anything ambiguous coexists.
            for decision in supersessions:
                result.append(
                    MemoryAction(
                        action=SUPERSEDE,
                        kind=action.kind,
                        memory_id=decision.entry.id,
                        text=decision.entry.text,
                        reason=(
                            f"semantic identity v{self.semantic_identity_version} "
                            f"({self.conflict_strategy}): {decision.reason}"
                        ),
                    )
                )
            result.append(
                replace(enriched, replaces=supersessions[0].entry.id)
            )
        return result

    def _veto_cross_scope_v1_pairs(
        self,
        actions: list[MemoryAction],
        existing: list[ExperienceEntry],
    ) -> list[MemoryAction]:
        """Scoped coexistence: drop a v1 keyed supersede pair when both
        sides carry confident identities for the SAME attribute but
        DISTINCT scopes (or historical/current qualifiers). v1's narrow
        domain rules ignore scope; semantic identity restores it. Pairs
        with unknown identity keep the v1 behavior unchanged."""
        by_id = {e.id: e for e in existing}
        vetoed_targets: set[str] = set()
        for action in actions:
            if action.action != CREATE or not action.replaces:
                continue
            old_entry = by_id.get(action.replaces)
            if old_entry is None:
                continue
            new_identity = self.normalizer.normalize(
                action.kind, action.text
            )
            old_identity = identity_of(old_entry, self.normalizer)
            if new_identity is None or old_identity is None:
                continue
            if (
                new_identity.attribute == old_identity.attribute
                and (
                    new_identity.scope != old_identity.scope
                    or new_identity.is_historical()
                    != old_identity.is_historical()
                )
            ):
                vetoed_targets.add(action.replaces)
        if not vetoed_targets:
            return actions
        result = []
        for action in actions:
            if action.action == SUPERSEDE and action.memory_id in vetoed_targets:
                continue
            if action.action == CREATE and action.replaces in vetoed_targets:
                result.append(replace(action, replaces=None, reason=None))
                continue
            result.append(action)
        return result
