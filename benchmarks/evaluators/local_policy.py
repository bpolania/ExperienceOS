"""Local-policy evaluators (experienceos_local only).

Preserve the separations the contract demands: proposal correctness ≠
structural validity ≠ engine containment ≠ fallback correctness ≠
applied action ≠ final-state corruption. Fallback-sourced actions are
never counted as local-model correctness; a rejected proposal is
containment success, not corruption; a clean final state never erases
a wrong proposal (proposal metrics score the proposal itself).

Modes (from adapter diagnostics) stay separate: scripted, unavailable
fallback, and real. The offline canonical run is scripted-plus-
fallback — never a real-GGUF accuracy result.
"""

from __future__ import annotations

from benchmarks.contract import ExpectedAction
from benchmarks.evaluators.records import contribution, undefined
from benchmarks.evaluators.resolve import matches_ref


def _local_proposals(turns):
    return [
        p
        for t in turns
        for p in t.proposals
        if p.decision_source == "local_model"
    ]


def local_policy_contributions(case, result):
    out = []
    turns = result.turns
    if not turns:
        return out
    invocations = result.local_model_invocation_count
    local_proposals = _local_proposals(turns)
    final = turns[-1]

    # Structural validity: completed generations whose decisions parsed
    # into manager-accepted proposals (malformed generations complete
    # but produce a fallback instead of local proposals).
    if invocations:
        malformed_turns = sum(
            1
            for t in turns
            if t.fallbacks
            and any(f.reason == "invalid_output" for f in t.fallbacks)
        )
        out.append(
            contribution(
                "local_valid_proposal_rate",
                invocations - malformed_turns,
                invocations,
            )
        )
    else:
        out.append(
            undefined(
                "local_valid_proposal_rate",
                "no completed local-model generations in this mode",
            )
        )

    expected = [
        a
        for a in case.expected.memory_actions
        if a.action != ExpectedAction.NONE
    ]
    final_local = [
        p for p in final.proposals if p.decision_source == "local_model"
    ]
    if expected and invocations:
        expected_types = {a.action for a in expected}
        correct_type = any(
            p.action in expected_types for p in final_local
        )
        out.append(
            contribution(
                "local_correct_action_type_rate",
                1 if correct_type else 0,
                1,
            )
        )

    targeted = [
        p
        for p in final_local
        if p.action in ("supersede", "forget") and p.target_memory_id
    ]
    if targeted:
        entries = [
            (e.memory_id, e.text)
            for e in (
                *result.final_active,
                *result.final_superseded,
                *result.final_forgotten,
            )
        ]
        expected_targets = [
            a.target for a in case.expected.memory_actions if a.target
        ]
        correct = 0
        for p in targeted:
            text = next(
                (t for mid, t in entries if mid == p.target_memory_id), ""
            )
            if any(matches_ref(ref, text) for ref in expected_targets):
                correct += 1
        out.append(
            contribution("local_correct_target_rate", correct, len(targeted))
        )

    if expected:
        # Post-containment correctness: applied actions match the
        # oracle's expected action types with satisfying values.
        applied = final.applied_actions
        ok = bool(applied) and all(
            any(
                a.action == e.action
                and (
                    e.value is None
                    or _value_ok(e.value, a.text or "")
                )
                for e in expected
            )
            for a in applied
        )
        out.append(
            contribution(
                "local_applied_action_accuracy", 1 if ok else 0, 1
            )
        )
        accuracy_metric = (
            "local_paraphrase_accuracy"
            if "paraphrase" in case.tags
            else "local_explicit_wording_accuracy"
        )
        out.append(
            contribution(accuracy_metric, 1 if ok else 0, 1)
        )

    # State corruption: an expected-active memory lost, or a forgotten
    # memory silently reactivated. Rejected proposals are containment.
    active = [(e.memory_id, e.text) for e in result.final_active]
    forgotten = [(e.memory_id, e.text) for e in result.final_forgotten]
    corrupted = any(
        not any(matches_ref(ref, text) for _, text in active)
        for ref in case.expected.active
    ) or any(
        any(matches_ref(ref, text) for _, text in active)
        and not any(matches_ref(ref, text) for _, text in forgotten)
        for ref in case.expected.forgotten
    )
    out.append(
        contribution(
            "local_state_corruption_rate", 1 if corrupted else 0, 1
        )
    )
    return out


def _value_ok(constraint, text: str) -> bool:
    body = text.lower()
    if any(t.lower() not in body for t in constraint.must_include_all):
        return False
    if constraint.must_include_any and not any(
        t.lower() in body for t in constraint.must_include_any
    ):
        return False
    return not any(t.lower() in body for t in constraint.must_exclude)
