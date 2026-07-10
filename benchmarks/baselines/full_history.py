"""Full-history prompting baseline.

Question it answers: can supplying the entire transcript preserve
answer quality, and what context cost does that impose?

Behavior: every prior user and assistant turn is prepended, in order,
to every later request. No extraction, no updates, no forgetting, no
lifecycle filtering, no retrieval, no selection, no compression, no
truncation (the fair-comparison contract does not impose a history
budget on this strategy — its context cost IS the measurement).
Corrected, contradicted, and "forgotten" statements all remain in the
transcript forever.

Token accounting: the transcript is conversation history, not
structured memory, so it counts toward total context only;
memory-context tokens are 0 by the documented benchmark convention.
Transcript size is additionally preserved per turn in the context
evidence and in the harness diagnostics.
"""

from __future__ import annotations

from benchmarks.baselines.common import BaselineSystem, TurnPlan
from benchmarks.contract import SystemId


class FullHistoryBaseline(BaselineSystem):
    system_id = SystemId.FULL_HISTORY
    memory_policy_label = "none"

    def retrieval_description(self) -> str:
        return "none: complete transcript supplied every turn"

    def _reset(self) -> None:
        super()._reset()
        self.transcript: list[str] = []

    def _plan_turn(self, turn_index, session_id, message) -> TurnPlan:
        # The current message is appended once by the common flow;
        # only PRIOR turns form the history block.
        return TurnPlan(history_context=list(self.transcript))

    def _after_response(self, turn_index, message, response) -> None:
        self.transcript.append(f"user: {message}")
        self.transcript.append(f"assistant: {response}")
