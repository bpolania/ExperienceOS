"""Naive top-K retrieval baseline.

Question it answers: how far can simple lexical and recency retrieval
go without lifecycle protections?

Storage: the same shared durability heuristic as append-only — every
durable-looking statement is stored as an always-active record;
corrections and duplicates accumulate; forget requests change nothing.

Ranking (fixed weights, declared here and in tests, never tuned per
scenario):

    score = OVERLAP_WEIGHT * |content_words(query) ∩ content_words(record)|
          + RECENCY_WEIGHT * (created_turn / max_created_turn)

- No domain tags: the repository has no deterministic tag derivation
  that would not borrow production code, so the formula stays purely
  lexical + recency (documented limitation: wrong-domain lexical
  matches can rank, and zero-overlap safety memories can lose).
- Zero-overlap behavior: recency alone decides — the newest record
  wins, deterministically.
- Tie-breaker: lower record ID (insertion order) wins, stable.
- Selection: top min(K, context_budget) ranked records enter context;
  the rest are skipped candidates with visible score components.
- No lifecycle: stale, corrected, and forgotten-in-spirit values
  remain fully eligible candidates forever.
"""

from __future__ import annotations

from benchmarks.baselines.common import (
    BaselineSystem,
    TurnPlan,
    content_words,
    estimate_kind,
    looks_durable,
)
from benchmarks.contract import CandidateRecord, SystemId

OVERLAP_WEIGHT = 1.0
RECENCY_WEIGHT = 0.5


class NaiveTopKBaseline(BaselineSystem):
    system_id = SystemId.NAIVE_TOP_K
    memory_policy_label = "naive_top_k_heuristic"

    def retrieval_description(self) -> str:
        return (
            f"naive top-K: {OVERLAP_WEIGHT}*word_overlap + "
            f"{RECENCY_WEIGHT}*normalized_recency, insertion-order "
            "tie-break, no lifecycle filtering"
        )

    def _score(self, query_words: set, record) -> tuple[float, float, float]:
        overlap = float(len(query_words & content_words(record.text)))
        max_turn = max((r.created_turn for r in self.records), default=0)
        recency = record.created_turn / max_turn if max_turn else 0.0
        score = OVERLAP_WEIGHT * overlap + RECENCY_WEIGHT * recency
        return score, overlap, recency

    def _plan_turn(self, turn_index, session_id, message) -> TurnPlan:
        plan = TurnPlan()
        query_words = content_words(message)
        limit = self.memory_limit()

        scored = []
        for record in self.records:
            score, overlap, recency = self._score(query_words, record)
            scored.append((score, record, overlap, recency))
        scored.sort(key=lambda item: (-item[0], item[1].record_id))

        for rank, (score, record, overlap, recency) in enumerate(
            scored, start=1
        ):
            selected = rank <= limit
            plan.candidates.append(
                CandidateRecord(
                    memory_id=record.record_id,
                    text=record.text,
                    rank=rank,
                    score=round(score, 6),
                    selected=selected,
                    reason=(
                        f"overlap={overlap:g} recency={recency:.3f} "
                        f"weights=({OVERLAP_WEIGHT},{RECENCY_WEIGHT})"
                        + ("" if selected else "; beyond K/budget")
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
