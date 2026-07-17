"""Deterministic bridge from a verified transition to a replacement plan.

Both the engine and its tests call :func:`build_replacement` so the plan
(and therefore its digest and authorization) is reproducible from the
same immutable inputs. This module adds no matching or projection logic
of its own — it assembles the matcher input, runs the pure matcher, and
runs the pure plan builder. It holds no store, engine, or manager and
mutates nothing.
"""

from __future__ import annotations

from experienceos.memory.planner import CREATE, SUPERSEDE
from experienceos.memory.action_replacement.planner import (
    ActionReplacementPlanner,
    VerifiedTransition,
)
from experienceos.memory.action_replacement.plan import (
    CONTEXT_CANDIDATE,
    ReplacementPlanBuilder,
)

_PLANNER = ActionReplacementPlanner()
_BUILDER = ReplacementPlanBuilder()


def build_replacement(
    planner_actions,
    sequence,
    *,
    verification_accepted: bool,
    transition_type: str,
    source_digest: str,
    before_state_digest: str,
    verified_transition_id: str,
    context: str = CONTEXT_CANDIDATE,
):
    """Return (decision, plan) for the given transition replacement sequence.

    The plan is a projection only; nothing is applied. Determinism: the
    same inputs always yield the same plan and plan digest.
    """
    sequence = tuple(sequence)
    supersede = next((a for a in sequence if a.action == SUPERSEDE), None)
    create = next((a for a in sequence if a.action == CREATE), None)
    verified = VerifiedTransition(
        accepted=bool(verification_accepted),
        transition_type=transition_type or "",
        supersede_action=supersede,
        replacement_create=create,
        target_memory_ids=tuple(
            a.memory_id for a in sequence if a.action == SUPERSEDE
        ),
        source_digest=source_digest,
        before_state_digest=before_state_digest,
    )
    decision = _PLANNER.plan(planner_actions, verified, before_state_digest)
    plan = _BUILDER.build(
        planner_actions,
        decision,
        before_state_digest=before_state_digest,
        verified_transition_id=verified_transition_id,
        transition_sequence=sequence,
        context=context,
    )
    return decision, plan
