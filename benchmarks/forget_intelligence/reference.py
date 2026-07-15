"""Canonical reference forget behavior on the frozen corpus.

The anchor is `experienceos_hybrid_full_v2_reference`, reproduced by
running the real `SemanticMemoryPlanner` — which inherits the canonical
`_plan_forgets` rule layer — over the same before-state and statement
the controller sees. The planner is pure; nothing here applies an action.

The effect signature and planner harness are reused from the
update-intelligence reference rather than rebuilt: it is the same
reference system evaluated on the same corpus, and forking it would
risk two anchors disagreeing about what the reference does.
"""

from __future__ import annotations

from benchmarks.update_intelligence.reference import (
    REFERENCE_SYSTEM_ID,
    REFERENCE_VERSION,
    EffectSignature,
    build_planner,
    oracle_effect,
    reference_effect,
)

__all__ = [
    "REFERENCE_SYSTEM_ID",
    "REFERENCE_VERSION",
    "EffectSignature",
    "build_planner",
    "oracle_effect",
    "reference_effect",
    "reference_forget_effect",
]


def reference_forget_effect(record, planner) -> dict:
    """The reference's forget-relevant behavior for one record.

    Reported as three separable facts rather than one score, because the
    interesting failures differ in kind: forgetting the wrong thing,
    forgetting when asked a question, and creating from a forget clause.
    """
    effect = reference_effect(record, planner)
    oracle = oracle_effect(record)
    return {
        "forgotten": sorted(effect.forgotten),
        "created": effect.created,
        "superseded": sorted(effect.superseded),
        "forgot_correct_target": effect.forgotten == oracle.forgotten,
        "forgot_anything": bool(effect.forgotten),
        "created_anything": bool(effect.created),
    }
