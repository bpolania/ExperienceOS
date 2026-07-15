"""Downstream retrieval and context-budget effects.

The transition corpus is a lifecycle oracle, not a retrieval benchmark:
it supplies no relevance judgements and therefore no Recall@K or MRR
denominator. Rather than synthesize one, this module measures what the
corpus *can* support honestly — what the resulting active state does to
retrieval candidates, selection, and context tokens — and reports the
retrieval-quality metrics as unavailable with the reason.

The committed retrieval benchmarks' definitions are not redefined here.
"""

from __future__ import annotations

from experienceos import ExperienceOS
from experienceos.memory.schema import MemoryStatus
from experienceos.memory.transition_integration import (
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
)
from experienceos.providers import MockProvider
from benchmarks.transition_benchmark.lifecycle import CHAIN
from experienceos.context.retrieval import _token_estimate
from benchmarks.transition_benchmark.systems import canonical_planner

_QUERY = "What are my travel preferences?"


def _measure(mode=None) -> dict:
    agent = ExperienceOS(model=MockProvider(), memory_planner=canonical_planner())
    if mode is not None:
        agent.engine.transition_coordinator = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(mode=mode)
        )
    for _, statement in CHAIN[:-1]:
        agent.chat("u", "downstream", statement)
    agent.chat("u", "downstream", _QUERY)

    events = agent.event_bus.history()
    # Only the final query turn describes retrieval for the query. Earlier
    # turns retrieved memories that were active *then*; counting those
    # would report leakage that never happened.
    built = [e for e in events if e.type == "context_built"][-1].payload
    entries = agent.memory_store.list_memories(user_id="u")
    by_id = {e.id: e for e in entries}
    active = [e for e in entries if e.status == MemoryStatus.ACTIVE]
    inactive_ids = {e.id for e in entries if e.status != MemoryStatus.ACTIVE}

    candidates = list(built.get("candidate_memory_ids") or [])
    selected = list(built.get("selected_memory_ids") or [])
    # Reuses the retrieval layer's own token estimate rather than
    # inventing a second convention.
    tokens = sum(
        _token_estimate(by_id[m].text) for m in selected if m in by_id
    )
    return {
        "active_memories": len(active),
        "candidates": len(candidates),
        "selected_memories": int(built.get("selected_memory_count") or 0),
        "skipped_memories": int(built.get("skipped_memory_count") or 0),
        "context_tokens": tokens,
        "selection_rate": (
            round(len(selected) / len(candidates), 4) if candidates else None
        ),
        "inactive_retrieved": sum(1 for m in candidates if m in inactive_ids),
        "inactive_selected": sum(1 for m in selected if m in inactive_ids),
        # The corpus carries no relevance judgements, so these cannot be
        # computed without inventing an oracle.
        "recall_at_1": None,
        "recall_at_3": None,
        "mrr": None,
        "unavailable_reason": (
            "the transition corpus supplies no relevance judgements; "
            "Recall@K and MRR have no defensible denominator here and are "
            "not synthesized"
        ),
    }


def run() -> dict:
    reference = _measure(None)
    adopted = _measure(TransitionIntegrationMode.CANDIDATE)
    return {
        "cases": 1,
        "query": _QUERY,
        "reference": reference,
        "adopted": adopted,
        "note": (
            "candidate mode is non-mutating, so downstream state equals the "
            "reference; this measures that transition diagnostics do not "
            "disturb retrieval or the context budget"
        ),
    }
