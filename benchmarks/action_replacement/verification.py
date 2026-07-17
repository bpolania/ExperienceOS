"""Run the historical corpus through append vs governed replacement.

Every measurement is behavioral and deterministic: runtime UUIDs are
mapped to stable first-seen labels (the suite's existing convention),
and no wall-clock timing enters any recorded value. The corpus is
consumed read-only.
"""

from __future__ import annotations

import json
from pathlib import Path

from experienceos.policy.base import PolicyContext
from experienceos.memory.planner import CREATE, FORGET, SUPERSEDE
from experienceos.memory.schema import MemoryStatus
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    build_before_state,
)
from experienceos.memory.transition_integration import (
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    translate_transition,
)
from experienceos.memory.action_replacement import (
    PLAN_READY,
    authorization_from_plan,
    build_replacement,
)
from benchmarks.transition_benchmark import systems as S

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = (
    REPO_ROOT
    / "benchmarks/annotations/transition-verification/historical-scored.jsonl"
)

# Transition classes for the applied-state comparison.
SUPERSEDE_BEARING = "supersede_bearing"
PURE_CREATE = "pure_create"
NO_TRANSITION = "no_transition"


def load_cases() -> list:
    return [
        json.loads(line)
        for line in CORPUS.read_text().splitlines()
        if line.strip()
    ]


def _admitted_planner_actions(agent, statement):
    memories = agent.memory_store.active_for_user("u")
    result = agent.engine.experience_manager.plan(
        PolicyContext(
            user_id="u", session_id="benchmark",
            message=statement, active_memories=memories,
        )
    )
    active_ids = {m.id for m in memories}
    retired = {
        a.memory_id for a in result.actions
        if a.action in (SUPERSEDE, FORGET) and a.memory_id in active_ids
    }
    planner_actions = tuple(
        a for a in result.actions
        if agent.engine._reject_reason(a, memories, active_ids, retired) is None
    )
    before_digest = build_before_state(memories, user_id="u").digest()
    return planner_actions, before_digest


def _route(record, statement):
    """The verified proposal and its translated sequence, or (None, ())."""
    probe = S._seed(record)
    probe.engine.transition_coordinator = S._coordinator(
        TransitionIntegrationMode.SHADOW
    )
    probe.chat("u", "benchmark", statement)
    request_id = f"benchmark:{S._hook_history_length(probe.event_bus.history())}"
    request = TransitionIntegrationRequest(
        statement=statement,
        evidence=TransitionSourceEvidence(
            source_statement=statement, source_event_id=request_id,
            session_id="benchmark", evidence_mode=EvidenceMode.GROUNDED_VALID,
            provenance_ref="user_asserted",
        ),
        before_state=build_before_state(
            [S._entry_from(m) for m in record["before_state"]], user_id="u"
        ),
        request_id=request_id, user_id="u",
    )
    _, controller_result = S._coordinator(
        TransitionIntegrationMode.ADOPTED
    )._route(request)
    proposal = getattr(controller_result, "proposal", None)
    verification = getattr(controller_result, "verification", None)
    if (
        proposal is None
        or verification is None
        or not getattr(verification, "accepted", False)
    ):
        return None, (), request
    translation = translate_transition(proposal, verification, request.before_state)
    return proposal, (translation.actions if translation.succeeded else ()), request


def _applied_measures(agent, record):
    """Deterministic applied-state measures with stable ids.

    Lineage and loss are judged only against changes this run caused —
    memories that were *active in the before-state* and are now
    superseded or forgotten — never against a memory the corpus already
    seeded as superseded.
    """
    seeded = {m["memory_ref"]["logical_id"] for m in record["before_state"]}
    seeded_active = {
        m["memory_ref"]["logical_id"] for m in record["before_state"]
        if m["lifecycle_state"] == MemoryStatus.ACTIVE
    }
    entries = agent.memory_store.list_memories(user_id="u")
    stable = S._stable_ids(entries, seeded)
    active = [e for e in entries if e.status == MemoryStatus.ACTIVE]
    superseded = [e for e in entries if e.status == MemoryStatus.SUPERSEDED]
    forgotten = [e for e in entries if e.status == MemoryStatus.FORGOTTEN]
    duplicates, stale = S._pairs(active)

    # Lineage: memories superseded *this run* point at an active replacement.
    newly_superseded = [e for e in superseded if e.id in seeded_active]
    lineage_ok = True
    for e in newly_superseded:
        replacement_id = e.metadata.get("superseded_by")
        if replacement_id is None or agent.memory_store.get(replacement_id) is None:
            lineage_ok = False

    # A seeded-active memory removed this run without being superseded or
    # forgotten would be collateral loss.
    active_ids = {e.id for e in active}
    superseded_ids = {e.id for e in superseded}
    forgotten_ids = {e.id for e in forgotten}
    lost = sorted(
        stable.get(mid, mid)
        for mid in seeded_active
        if mid not in active_ids
        and mid not in superseded_ids
        and mid not in forgotten_ids
    )
    return {
        "active_ids": tuple(sorted(stable[e.id] for e in active)),
        "superseded_ids": tuple(sorted(stable[e.id] for e in superseded)),
        "duplicate_pairs": duplicates,
        "stale_active_pairs": stale,
        "superseded_count": len(superseded),
        "newly_superseded_count": len(newly_superseded),
        "lineage_ok": lineage_ok,
        "seeded_non_target_lost": tuple(lost),
    }


def verify_case(record) -> dict:
    statement = record.get("source_statement") or ""
    specs = {s.system_id: s for s in S.registry()}

    # Run A — existing add-not-replace behavior (real adopted append).
    append_obs = S.run_case(specs[S.ADOPTED_ID], record)
    append_dup = append_obs.semantic_duplicate_pairs

    # Governed pipeline inputs.
    agent = S._seed(record)
    planner_actions, before_digest = _admitted_planner_actions(agent, statement)
    proposal, sequence, request = _route(record, statement)
    supersede_bearing = bool(sequence) and any(
        a.action == SUPERSEDE for a in sequence
    ) and any(a.action == CREATE for a in sequence)
    has_create = bool(sequence) and any(a.action == CREATE for a in sequence)

    transition_class = (
        SUPERSEDE_BEARING if supersede_bearing
        else PURE_CREATE if has_create
        else NO_TRANSITION
    )

    record_out = {
        "case_id": record["case_id"],
        "transition_class": transition_class,
        "append_duplicate_pairs": append_dup,
        "before_state_digest": before_digest,
        "plan_status": None,
        "plan_digest": None,
        "projected_action_list_digest": None,
        "authorization_status": "not_applicable",
        "canonical_effect": None,
        "planner_suppressed": False,
        "fallback_used": None,
        "transition_create_count": None,
    }

    transition_auth = S._authorization_for(record, statement)

    if supersede_bearing:
        _, plan = build_replacement(
            planner_actions, sequence, verification_accepted=True,
            transition_type=proposal.transition_type,
            source_digest=request.source_digest(),
            before_state_digest=before_digest,
            verified_transition_id=str(proposal.proposal_id or ""),
        )
        replacement_auth = (
            authorization_from_plan(plan) if plan.status == PLAN_READY else None
        )
        final = S._seed(record)
        final.engine.transition_coordinator = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(
                mode=TransitionIntegrationMode.ADOPTED,
                authorizations=(transition_auth,) if transition_auth else (),
                replacement_authorizations=(
                    (replacement_auth,) if replacement_auth else ()
                ),
            )
        )
        final.chat("u", "benchmark", statement)
        event = [
            e for e in final.event_bus.history()
            if e.type == "transition_integration_evaluated"
        ][-1].payload
        repl = event.get("replacement", {})
        measures = _applied_measures(final, record)
        create_text = next(
            (a.text for a in sequence if a.action == CREATE), None
        )
        transition_create_count = sum(
            1 for e in final.memory_store.list_memories("u")
            if e.status == MemoryStatus.ACTIVE and e.text == create_text
        )
        record_out.update({
            "plan_status": plan.status,
            "plan_digest": plan.plan_digest,
            "projected_action_list_digest": plan.projected_action_list_digest,
            "authorization_status": (
                "accepted" if repl.get("applied") else "rejected"
            ),
            "canonical_effect": event.get("canonical_action_effect"),
            "planner_suppressed": bool(repl.get("applied")),
            "fallback_used": bool(repl.get("fallback_used")),
            "transition_create_count": transition_create_count,
        })
    else:
        # Pure-create / no-transition: the governed path yields no
        # replacement; the applied state is the existing behavior.
        final = S._seed(record)
        final.engine.transition_coordinator = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(
                mode=TransitionIntegrationMode.ADOPTED,
                authorizations=(transition_auth,) if transition_auth else (),
            )
        )
        final.chat("u", "benchmark", statement)
        measures = _applied_measures(final, record)

    record_out.update({
        "replacement_duplicate_pairs": measures["duplicate_pairs"],
        "replacement_stale_pairs": measures["stale_active_pairs"],
        "active_ids": list(measures["active_ids"]),
        "superseded_ids": list(measures["superseded_ids"]),
        "superseded_count": measures["superseded_count"],
        "lineage_ok": measures["lineage_ok"],
        "seeded_non_target_lost": list(measures["seeded_non_target_lost"]),
        "duplicate_difference": append_dup - measures["duplicate_pairs"],
    })
    return record_out


def verify_all() -> dict:
    cases = sorted(load_cases(), key=lambda r: r["case_id"])
    records = [verify_case(r) for r in cases]

    def total(field, predicate=lambda r: True):
        return sum(r[field] for r in records if predicate(r))

    supersede = [r for r in records if r["transition_class"] == SUPERSEDE_BEARING]
    pure_create = [r for r in records if r["transition_class"] == PURE_CREATE]
    no_transition = [r for r in records if r["transition_class"] == NO_TRANSITION]
    # Applied replacements — the cases this verification is really about.
    applied = [r for r in records if r["planner_suppressed"]]

    summary = {
        "case_count": len(records),
        "supersede_bearing": len(supersede),
        "pure_create": len(pure_create),
        "no_transition": len(no_transition),
        "append_duplicate_pairs_total": total("append_duplicate_pairs"),
        "replacement_duplicate_pairs_total": total("replacement_duplicate_pairs"),
        "duplicate_reduction": (
            total("append_duplicate_pairs")
            - total("replacement_duplicate_pairs")
        ),
        "supersede_bearing_append_duplicates": sum(
            r["append_duplicate_pairs"] for r in supersede
        ),
        "supersede_bearing_replacement_duplicates": sum(
            r["replacement_duplicate_pairs"] for r in supersede
        ),
        "pure_create_residual_duplicates": sum(
            r["replacement_duplicate_pairs"] for r in pure_create
        ),
        "planner_creates_suppressed": len(applied),
        "replacements_applied": sum(
            1 for r in records if r["authorization_status"] == "accepted"
        ),
        # Lineage and loss are meaningful only where a replacement was
        # actually applied; non-applied cases are existing behavior.
        "applied_lineage_correct": sum(1 for r in applied if r["lineage_ok"]),
        "applied_lineage_broken": sum(1 for r in applied if not r["lineage_ok"]),
        "applied_seeded_memories_lost": sum(
            len(r["seeded_non_target_lost"]) for r in applied
        ),
        "applied_transition_create_present_once": sum(
            1 for r in applied if r["transition_create_count"] == 1
        ),
        "canonical_effects": sorted(
            {r["canonical_effect"] for r in supersede if r["canonical_effect"]}
        ),
    }
    return {
        "schema_version": "1",
        "cases": records,
        "summary": summary,
    }
