"""Stateful lifecycle chains.

Single-turn classification cannot show whether accumulated experience
stays current, so each chain runs a seeded agent through an ordered
conversation and records what memory looks like at every turn.

Reference and transition systems start from the same seeded state and
receive the same turns. Everything runs in an isolated in-memory store.
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
from benchmarks.transition_benchmark.systems import (
    CANDIDATE_ID,
    REFERENCE_ID,
    _pairs,
    canonical_planner,
)

#: One ordered chain covering the lifecycle the product claims to manage.
CHAIN = (
    ("create", "I prefer aisle seats for short work trips."),
    ("exact_restatement", "I prefer aisle seats for short work trips."),
    ("semantic_restatement", "For short business trips, aisle seats are my usual choice."),
    ("current_update", "I now prefer window seats for short work trips."),
    ("second_correction", "Actually, back to aisle for short work trips."),
    ("scoped_addition", "For long international flights, I prefer window seats."),
    ("unrelated_addition", "I am allergic to shellfish."),
    ("affirmative_forget", "Forget that I prefer aisle seats."),
    ("restatement_after_forget", "I prefer aisle seats for short work trips."),
    ("retrieval", "What are my travel preferences?"),
)


def _agent(mode=None):
    agent = ExperienceOS(model=MockProvider(), memory_planner=canonical_planner())
    if mode is not None:
        agent.engine.transition_coordinator = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(mode=mode)
        )
    return agent


def _snapshot(agent):
    entries = agent.memory_store.list_memories(user_id="u")
    active = [e for e in entries if e.status == MemoryStatus.ACTIVE]
    duplicates, stale = _pairs(active)
    return {
        "active": len(active),
        "superseded": sum(1 for e in entries if e.status == MemoryStatus.SUPERSEDED),
        "forgotten": sum(1 for e in entries if e.status == MemoryStatus.FORGOTTEN),
        "duplicate_pairs": duplicates,
        "stale_pairs": stale,
    }


def _run_chain(system_id, mode):
    agent = _agent(mode)
    turns = []
    for name, statement in CHAIN:
        agent.chat("u", "chain", statement)
        turns.append({"turn": name, "statement": statement, **_snapshot(agent)})
    final = _snapshot(agent)
    return {
        "system_id": system_id,
        "turns": turns,
        "final": final,
    }


def run() -> dict:
    """Reference vs transition candidate over the same chain."""
    reference = _run_chain(REFERENCE_ID, None)
    candidate = _run_chain(CANDIDATE_ID, TransitionIntegrationMode.CANDIDATE)
    return {
        "chains": 1,
        "turns": len(CHAIN),
        "systems": {
            REFERENCE_ID: reference,
            CANDIDATE_ID: candidate,
        },
        "note": (
            "candidate mode is non-mutating by design, so its lifecycle state "
            "matches the reference exactly; the difference it would make is "
            "reported as projected state in the per-case results, not here"
        ),
    }
