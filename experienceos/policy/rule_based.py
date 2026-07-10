"""Rule-based memory policy: the existing deterministic planner, wrapped.

Delegates to MemoryPlanner without reinterpreting any rule behavior —
extraction, classification, deduplication, conflicts, updates, and
forgetting stay exactly where they are.
"""

from __future__ import annotations

from experienceos.memory.planner import MemoryAction, MemoryPlanner
from experienceos.policy.base import (
    DecisionSource,
    MemoryDecisionProposal,
    PolicyContext,
)


class RuleBasedMemoryPolicy:
    """Wraps the deterministic MemoryPlanner as a MemoryPolicy."""

    mode = DecisionSource.RULE_BASED

    def __init__(self, planner: MemoryPlanner | None = None):
        self.planner = planner or MemoryPlanner()

    def plan(self, context: PolicyContext) -> list[MemoryDecisionProposal]:
        actions = self.planner.plan_memory_actions(
            context.user_id,
            context.session_id,
            context.message,
            existing=context.active_memories,
        )
        return [self._to_proposal(action) for action in actions]

    @staticmethod
    def _to_proposal(action: MemoryAction) -> MemoryDecisionProposal:
        """Lossless MemoryAction → proposal mapping.

        ``reason`` round-trips through ``explanation`` (None ↔ "") and
        ``request`` through the whitelisted metadata key, so converting
        back yields a field-for-field identical MemoryAction.
        """
        metadata = {}
        if action.request:
            metadata["request"] = action.request
        if action.metadata:
            metadata["entry_metadata"] = action.metadata
        return MemoryDecisionProposal(
            action=action.action,
            kind=action.kind,
            text=action.text or None,
            target_memory_id=action.memory_id,
            replaces=action.replaces,
            confidence=1.0,
            explanation=action.reason or "",
            decision_source=DecisionSource.RULE_BASED,
            metadata=metadata,
        )
