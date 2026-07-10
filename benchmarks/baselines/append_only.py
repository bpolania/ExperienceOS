"""Append-only memory baseline.

Question it answers: what happens when durable-looking statements are
stored but old memories are never deactivated?

Behavior: user messages matching the shared documented durability
heuristic are stored verbatim as always-active records. Nothing is
ever updated, superseded, forgotten, or deduplicated — corrections
append a second record beside the first, forget requests change
nothing (they are commands, not durable statements, so they are not
stored either), and exact or paraphrased duplicates both accumulate.

Context strategy (documented before any benchmark result): when more
records exist than the memory budget, supply the MOST RECENT records
first — a reasonable append-only cap that favors newer statements
without understanding that they supersede older ones. All records are
reported as candidates; those beyond the budget are skipped and
visible.
"""

from __future__ import annotations

from benchmarks.baselines.common import (
    BaselineSystem,
    TurnPlan,
    estimate_kind,
    looks_durable,
)
from benchmarks.contract import CandidateRecord, SystemId


class AppendOnlyBaseline(BaselineSystem):
    system_id = SystemId.APPEND_ONLY
    memory_policy_label = "append_only_heuristic"

    def retrieval_description(self) -> str:
        return (
            "append-only: most-recent-first within the memory budget; "
            "no lifecycle filtering, no deduplication"
        )

    def _plan_turn(self, turn_index, session_id, message) -> TurnPlan:
        plan = TurnPlan()
        # Retrieval BEFORE writing: the new statement influences later
        # turns, matching the shared benchmark convention.
        limit = self.memory_limit()
        newest_first = sorted(
            self.records, key=lambda r: -r.created_turn
        )
        for rank, record in enumerate(newest_first, start=1):
            selected = rank <= limit
            plan.candidates.append(
                CandidateRecord(
                    memory_id=record.record_id,
                    text=record.text,
                    rank=rank,
                    score=float(record.created_turn),
                    selected=selected,
                    reason=(
                        "most-recent-first within budget"
                        if selected
                        else "beyond memory budget"
                    ),
                )
            )
            if selected:
                plan.memory_context.append(record.text)

        if looks_durable(message):
            record = self._new_record(
                text=message,
                kind=estimate_kind(message),
                created_turn=turn_index,
            )
            self.records.append(record)
            plan.writes.append(record)
        return plan
