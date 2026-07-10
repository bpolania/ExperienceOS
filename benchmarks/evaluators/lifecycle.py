"""Lifecycle evaluators: memory-write, update/correction, forgetting.

All scoring uses the fixed Prompt 1 numerator/denominator definitions
against evidence from the FINAL turn (the oracle describes the current
message) plus final memory state. Proposals, rejections, applied
actions, and final state are scored as the distinct layers they are.
"""

from __future__ import annotations

from benchmarks.contract import ExpectedAction
from benchmarks.evaluators.records import contribution, undefined
from benchmarks.evaluators.resolve import matches_ref, resolve_ref


def _value_ok(constraint, text: str) -> bool:
    if constraint is None:
        return True
    body = text.lower()
    if any(t.lower() not in body for t in constraint.must_include_all):
        return False
    if constraint.must_include_any and not any(
        t.lower() in body for t in constraint.must_include_any
    ):
        return False
    if any(t.lower() in body for t in constraint.must_exclude):
        return False
    return True


def final_turn(result):
    return result.turns[-1] if result.turns else None


def expected_actions(case, action):
    return [
        a for a in case.expected.memory_actions if a.action == action
    ]


def memory_write_contributions(case, result):
    """Creation precision/recall, kind, duplicates, non-durable."""
    out = []
    turn = final_turn(result)
    if turn is None:
        return out
    expected = case.expected
    expected_creates = expected_actions(case, ExpectedAction.CREATE)
    applied_creates = [
        a for a in turn.applied_actions if a.action == "create"
    ]
    none_expected = bool(expected_actions(case, ExpectedAction.NONE))

    if expected_creates or none_expected or applied_creates:
        matched = []
        remaining = list(expected_creates)
        for action in applied_creates:
            hit = next(
                (
                    e
                    for e in remaining
                    if _value_ok(e.value, action.text or "")
                ),
                None,
            )
            if hit is not None:
                remaining.remove(hit)
                matched.append((action, hit))
        out.append(
            contribution(
                "memory_creation_precision",
                len(matched),
                len(applied_creates),
                applied=len(applied_creates),
            )
            if applied_creates
            else undefined(
                "memory_creation_precision", "no applied creations"
            )
        )
        if expected_creates:
            out.append(
                contribution(
                    "memory_creation_recall",
                    len(matched),
                    len(expected_creates),
                )
            )
            if matched:
                correct_kind = sum(
                    1
                    for action, exp in matched
                    if exp.kind is None or action.kind == exp.kind
                )
                out.append(
                    contribution(
                        "correct_memory_kind_rate",
                        correct_kind,
                        len(matched),
                    )
                )

    # Duplicate evidence: rejected duplicates + duplicate active state.
    proposals = list(turn.proposals)
    rejected_duplicates = [
        r
        for r in turn.rejected_actions
        if r.rejected_reason == "duplicate_of_active"
    ]
    duplicates_accepted = 0
    if "duplicate" in case.tags and case.expected.final_state_exact:
        # The oracle pins exactly one record per slot; extra active
        # matches are accepted duplicates.
        for ref in expected.active:
            actual = sum(
                1 for e in result.final_active if matches_ref(ref, e.text)
            )
            duplicates_accepted += max(0, actual - 1)
    write_attempts = len(proposals) or len(applied_creates)
    if write_attempts or rejected_duplicates:
        out.append(
            contribution(
                "duplicate_proposal_rate",
                len(rejected_duplicates) + duplicates_accepted,
                max(write_attempts, len(rejected_duplicates) + duplicates_accepted),
            )
        )
    duplicate_pressure = len(rejected_duplicates) + duplicates_accepted
    if duplicate_pressure:
        out.append(
            contribution(
                "duplicate_acceptance_rate",
                duplicates_accepted,
                duplicate_pressure,
            )
        )
    elif "duplicate" in case.tags:
        out.append(
            undefined(
                "duplicate_acceptance_rate", "no duplicate proposals made"
            )
        )

    if "non-durable" in case.tags:
        out.append(
            contribution(
                "non_durable_rejection_rate",
                1 if not applied_creates else 0,
                1,
            )
        )
    return out


def update_contributions(case, result):
    if case.category != "update":
        return []
    out = []
    turn = final_turn(result)
    if turn is None:
        return out
    expected = case.expected
    expected_supersedes = expected_actions(case, ExpectedAction.SUPERSEDE)
    if not expected_supersedes:
        return out  # scoped-coexistence case scores via memory-write

    proposed_update = any(
        p.action in ("supersede", "forget") for p in turn.proposals
    )
    out.append(
        contribution("update_detection_accuracy", 1 if proposed_update else 0, 1)
    )

    applied_supersedes = [
        a for a in turn.applied_actions if a.action == "supersede"
    ]
    if applied_supersedes:
        correct_target = sum(
            1
            for a in applied_supersedes
            if any(
                e.target and matches_ref(e.target, a.text or "")
                for e in expected_supersedes
            )
        )
        out.append(
            contribution(
                "correct_update_target_rate",
                correct_target,
                len(applied_supersedes),
            )
        )
    else:
        out.append(
            undefined("correct_update_target_rate", "no applied updates")
        )

    active = [(e.memory_id, e.text) for e in result.final_active]
    superseded = [(e.memory_id, e.text) for e in result.final_superseded]
    old_retired = all(
        resolve_ref(ref, superseded).status == "resolved"
        or resolve_ref(ref, active).status == "unresolved"
        for ref in expected.superseded
    )
    new_active = all(
        resolve_ref(ref, active).status == "resolved"
        for ref in expected.active
    )
    out.append(
        contribution(
            "supersession_accuracy",
            1 if (old_retired and new_active and expected.superseded) else 0,
            1,
        )
    )

    replacement_creates = [
        a for a in turn.applied_actions if a.action == "create"
    ]
    expected_creates = expected_actions(case, ExpectedAction.CREATE)
    if replacement_creates:
        good = sum(
            1
            for a in replacement_creates
            if any(
                _value_ok(e.value, a.text or "") for e in expected_creates
            )
        )
        out.append(
            contribution(
                "new_value_accuracy", good, len(replacement_creates)
            )
        )
    else:
        out.append(undefined("new_value_accuracy", "no applied replacements"))

    if expected.superseded:
        deactivated = sum(
            1
            for ref in expected.superseded
            if resolve_ref(ref, active).status == "unresolved"
        )
        out.append(
            contribution(
                "old_value_deactivation_rate",
                deactivated,
                len(expected.superseded),
            )
        )
        conflict = any(
            resolve_ref(ref, active).status != "unresolved"
            for ref in expected.superseded
        ) and any(
            resolve_ref(ref, active).status == "resolved"
            for ref in expected.active
        )
        out.append(
            contribution(
                "conflicting_active_memory_rate", 1 if conflict else 0, 1
            )
        )
    return out


def forgetting_contributions(case, result):
    if case.category != "forgetting":
        return []
    out = []
    turn = final_turn(result)
    if turn is None:
        return out
    expected = case.expected
    expected_forgets = expected_actions(case, ExpectedAction.FORGET)

    if expected_forgets:
        out.append(
            contribution(
                "forget_detection_accuracy",
                1 if any(p.action == "forget" for p in turn.proposals) else 0,
                1,
            )
        )
        applied_forgets = [
            a for a in turn.applied_actions if a.action == "forget"
        ]
        if applied_forgets:
            correct = sum(
                1
                for a in applied_forgets
                if any(
                    e.target and matches_ref(e.target, a.text or "")
                    for e in expected_forgets
                )
            )
            out.append(
                contribution(
                    "correct_forget_target_rate",
                    correct,
                    len(applied_forgets),
                )
            )
        else:
            out.append(
                undefined("correct_forget_target_rate", "no applied forgets")
            )

    if expected.forgotten:
        active = [(e.memory_id, e.text) for e in result.final_active]
        forgotten = [(e.memory_id, e.text) for e in result.final_forgotten]
        # Resurrection requires a forget that actually APPLIED and a
        # record matching the ref back in active state with nothing
        # left forgotten. A restatement (new record beside the still-
        # forgotten one) does not count; neither does a forget that
        # never happened (that is a detection failure, not
        # resurrection).
        applied_forget_texts = [
            a.text or ""
            for t in result.turns
            for a in t.applied_actions
            if a.action == "forget"
        ]
        resurrected = sum(
            1
            for ref in expected.forgotten
            if any(matches_ref(ref, text) for text in applied_forget_texts)
            and resolve_ref(ref, active).status != "unresolved"
            and resolve_ref(ref, forgotten).status == "unresolved"
        )
        out.append(
            contribution(
                "memory_resurrection_rate",
                resurrected,
                len(expected.forgotten),
            )
        )
        # Post-forget exclusion on the final answer turn, when the
        # final turn is an answer (no forget expected on it).
        if not expected_forgets:
            memory_context = " ".join(turn.context_messages[1:-1]).lower()
            leaked = any(
                all(t.lower() in memory_context for t in ref.match_terms)
                for ref in expected.forgotten
                if ref.match_terms
            )
            out.append(
                contribution(
                    "forgotten_exclusion_rate", 0 if leaked else 1, 1
                )
            )

    if expected.active:  # unrelated survivors
        active = [(e.memory_id, e.text) for e in result.final_active]
        preserved = sum(
            1
            for ref in expected.active
            if resolve_ref(ref, active).status == "resolved"
        )
        out.append(
            contribution(
                "unrelated_preservation_rate",
                preserved,
                len(expected.active),
            )
        )
    return out
