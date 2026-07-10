"""Retrieval and selection evaluators.

The oracle's ``expected.selected`` refs define the relevant set;
candidates come from the final turn's ranked candidate records.
Systems without structured retrieval (stateless, full-history) leave
candidate-based metrics undefined with a reason — never zero — while
recall still reflects the relevant memories they failed to select.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution, undefined
from benchmarks.evaluators.resolve import matches_ref


def _relevant_flags(refs, candidates):
    """Per-candidate relevance and per-ref hit list."""
    candidate_relevant = [
        any(matches_ref(ref, c.text) for ref in refs) for c in candidates
    ]
    ref_selected = [
        any(
            matches_ref(ref, c.text) and c.selected for c in candidates
        )
        for ref in refs
    ]
    return candidate_relevant, ref_selected


def retrieval_contributions(case, result):
    out = []
    if not result.turns:
        return out
    turn = result.turns[-1]
    relevant_refs = list(case.expected.selected)
    candidates = list(turn.candidates)
    selected = [c for c in candidates if c.selected]
    budget = case.context_budget
    k = min(budget, case.selection_k) if case.selection_k else budget

    # Budget adherence applies to every executed case.
    out.append(
        contribution(
            "selection_budget_adherence",
            1 if len(selected) <= k else 0,
            1,
            selected=len(selected),
            k=k,
        )
    )

    if not relevant_refs:
        return out  # relevance metrics not asserted for this case

    if not candidates:
        reason = "no structured retrieval candidates for this system"
        for name in (
            "precision_at_k",
            "hit_at_k",
            "mean_reciprocal_rank",
            "relevant_selection_rate",
            "irrelevant_rejection_rate",
            "active_utilization_rate",
            "inactive_contamination_rate",
        ):
            out.append(undefined(name, reason))
        # Recall still reflects relevant memories not selected.
        out.append(
            contribution("recall_at_k", 0, len(relevant_refs))
        )
        return out

    candidate_relevant, ref_selected = _relevant_flags(
        relevant_refs, candidates
    )
    selected_relevant = sum(
        1
        for c, rel in zip(candidates, candidate_relevant)
        if c.selected and rel
    )
    out.append(
        contribution(
            "precision_at_k", selected_relevant, len(selected)
        )
        if selected
        else undefined("precision_at_k", "no memories selected")
    )
    out.append(
        contribution(
            "recall_at_k", sum(ref_selected), len(relevant_refs)
        )
    )
    out.append(
        contribution("hit_at_k", 1 if any(ref_selected) else 0, 1)
    )

    ranked = sorted(candidates, key=lambda c: c.rank)
    first_relevant = next(
        (
            c.rank
            for c in ranked
            if any(matches_ref(ref, c.text) for ref in relevant_refs)
        ),
        None,
    )
    out.append(
        contribution(
            "mean_reciprocal_rank",
            (1.0 / first_relevant) if first_relevant else 0,
            1,
        )
    )

    relevant_candidates = sum(candidate_relevant)
    if relevant_candidates:
        out.append(
            contribution(
                "relevant_selection_rate",
                selected_relevant,
                relevant_candidates,
            )
        )
    irrelevant = [
        c
        for c, rel in zip(candidates, candidate_relevant)
        if not rel
    ]
    if irrelevant:
        out.append(
            contribution(
                "irrelevant_rejection_rate",
                sum(1 for c in irrelevant if not c.selected),
                len(irrelevant),
            )
        )

    inactive_refs = [
        *case.expected.superseded,
        *case.expected.forgotten,
    ]
    if selected:
        contaminated = sum(
            1
            for c in selected
            if any(matches_ref(ref, c.text) for ref in inactive_refs)
        )
        out.append(
            contribution(
                "active_utilization_rate",
                len(selected) - contaminated,
                len(selected),
            )
        )
        out.append(
            contribution(
                "inactive_contamination_rate", contaminated, len(selected)
            )
        )
    return out
