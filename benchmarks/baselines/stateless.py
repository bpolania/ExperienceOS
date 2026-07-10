"""Stateless agent baseline.

Question it answers: what happens when an agent receives only the
current request and has no accumulated experience?

Behavior: no transcript, no memory records, no retrieval, no
selection, no memory context. Every turn reaches the provider as
system instructions plus the current message, and the provider itself
is invoked statelessly. Earlier-session preferences are unavailable
unless the user restates them.
"""

from __future__ import annotations

from benchmarks.baselines.common import BaselineSystem, TurnPlan
from benchmarks.contract import SystemId


class StatelessBaseline(BaselineSystem):
    system_id = SystemId.STATELESS
    memory_policy_label = "none"

    def retrieval_description(self) -> str:
        return "none: no stored experience to retrieve"

    def _plan_turn(self, turn_index, session_id, message) -> TurnPlan:
        return TurnPlan()
