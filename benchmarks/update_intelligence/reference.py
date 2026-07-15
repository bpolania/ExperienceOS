"""Canonical reference behavior on the frozen transition corpus.

The comparison anchor is the existing canonical planner
(`experienceos_hybrid_full_v2_reference`), reproduced here by running the
real `SemanticMemoryPlanner` — the deterministic component that actually
plans lifecycle actions in that composition — over the same before-state
and source statement the controller sees.

The planner is pure: it reads entries and returns actions, touching no
store. Nothing here applies an action.

Comparison is on **lifecycle effect**, not on transition labels: the
planner has no transition taxonomy, so forcing its actions into one
would measure translation rather than behavior. An effect signature is
(created count, superseded ids, forgotten ids), which both systems and
the frozen oracle can express exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from experienceos.memory.planner import CREATE, FORGET, SUPERSEDE
from experienceos.memory.schema import ExperienceEntry
from experienceos.memory.semantic_planner import SemanticMemoryPlanner

REFERENCE_SYSTEM_ID = "experienceos_hybrid_full_v2_reference"
REFERENCE_VERSION = "1"


@dataclass(frozen=True)
class EffectSignature:
    """The durable lifecycle effect of a plan, proposal, or oracle."""

    created: int = 0
    superseded: frozenset = frozenset()
    forgotten: frozenset = frozenset()

    @property
    def mutating(self) -> bool:
        return bool(self.created or self.superseded or self.forgotten)

    def to_record(self) -> dict:
        return {
            "created": self.created,
            "superseded": sorted(self.superseded),
            "forgotten": sorted(self.forgotten),
        }


def oracle_effect(record) -> EffectSignature:
    transition = record["expected_transition"]
    return EffectSignature(
        created=len(transition.get("created") or ()),
        superseded=frozenset(
            r["logical_id"] for r in transition["superseded_refs"]
        ),
        forgotten=frozenset(
            r["logical_id"] for r in transition["forgotten_refs"]
        ),
    )


def proposal_effect(proposal) -> EffectSignature:
    if proposal is None:
        return EffectSignature()
    return EffectSignature(
        created=len(proposal.created),
        superseded=frozenset(proposal.superseded_ids),
        forgotten=frozenset(proposal.forgotten_ids),
    )


def _entries(record) -> list:
    """Frozen before-state as planner-shaped entries.

    The logical id becomes the entry id so planner actions can be
    compared against the oracle's logical references directly.
    """
    entries = []
    for memory in record["before_state"]:
        entry = ExperienceEntry(
            user_id="reference-user",
            text=memory.get("canonical_text") or "",
            kind=memory["kind"],
            status=memory["lifecycle_state"],
            source_session_id="reference-session",
        )
        entry.id = memory["memory_ref"]["logical_id"]
        entries.append(entry)
    return entries


def reference_effect(record, planner: SemanticMemoryPlanner) -> EffectSignature:
    """The canonical planner's lifecycle effect for one record."""
    actions = planner.plan_memory_actions(
        user_id="reference-user",
        session_id="reference-session",
        message=record.get("source_statement") or "",
        existing=_entries(record),
    )
    return EffectSignature(
        created=sum(1 for a in actions if a.action == CREATE),
        superseded=frozenset(
            a.memory_id for a in actions if a.action == SUPERSEDE and a.memory_id
        ),
        forgotten=frozenset(
            a.memory_id for a in actions if a.action == FORGET and a.memory_id
        ),
    )


def build_planner() -> SemanticMemoryPlanner:
    return SemanticMemoryPlanner()
