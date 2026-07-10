"""Context-efficiency evaluators.

All per-case values come from the contract's ContextAccounting record
(same approximation method across systems in offline runs). Ratios
with zero denominators are undefined per the suite-wide rule — a
stateless system's zero memory tokens never produce infinity.
``token_reduction_vs_full_history`` and
``answers_per_1k_memory_tokens`` are synthesized at aggregation, where
the full-history reference and case outcomes exist.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution, undefined
from benchmarks.evaluators.resolve import matches_ref


def context_contributions(case, result):
    out = []
    accounting = result.context_accounting
    if accounting is None or not result.turns:
        return out
    k = (
        min(case.context_budget, case.selection_k)
        if case.selection_k
        else case.context_budget
    )
    out.append(
        contribution(
            "context_budget_utilization",
            accounting.selected_memory_count,
            k,
        )
    )
    if accounting.total_context_tokens:
        out.append(
            contribution(
                "memory_token_share",
                accounting.memory_context_tokens or 0,
                accounting.total_context_tokens,
            )
        )

    relevant_refs = list(case.expected.selected)
    turn = result.turns[-1]
    selected = [c for c in turn.candidates if c.selected]
    if relevant_refs and selected:
        selected_chars = sum(len(c.text) for c in selected)
        relevant_chars = sum(
            len(c.text)
            for c in selected
            if any(matches_ref(ref, c.text) for ref in relevant_refs)
        )
        if selected_chars:
            out.append(
                contribution(
                    "relevant_token_share", relevant_chars, selected_chars
                )
            )

    if accounting.compressed_summary_count:
        compressed = accounting.memory_context_chars
        original = compressed + accounting.compression_saved_chars
        out.append(
            contribution("compression_ratio", compressed, original)
        )
    elif case.expected.compression_expected:
        out.append(
            undefined(
                "compression_ratio",
                "compression expected but did not occur",
            )
        )
    return out
