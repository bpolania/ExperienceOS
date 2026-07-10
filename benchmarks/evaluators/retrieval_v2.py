"""Phase 9 retrieval evaluator: v2-only observational contributions.

Reads the hybrid-retrieval diagnostics counters a v2 adapter records
per case (``result.diagnostics["retrieval_v2"]``) and converts them
into raw metric contributions. Systems without retrieval diagnostics
— every v1 system and the extraction-only ablation — contribute
nothing, so their evaluation output is byte-identical.

All retrieval_v2 metrics are neutral/observational: case outcomes are
still judged by the unchanged Phase 8 metrics.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution


def retrieval_v2_contributions(case, result):
    counters = result.diagnostics.get("retrieval_v2")
    if not isinstance(counters, dict):
        return []

    def count(key) -> float:
        value = counters.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    active = count("active_memories")
    retrievals = count("retrievals")
    passed = active + count("inactive_filtered")
    evidence = {
        "scenario_id": case.scenario_id,
        "retrieval_strategy": counters.get("retrieval_strategy"),
        "retrieval_strategy_version": counters.get(
            "retrieval_strategy_version"
        ),
    }
    return [
        contribution(
            "retrieval_candidate_rate_v2",
            count("lexical_candidates"), active, **evidence,
        ),
        contribution(
            "zero_relevance_exclusion_v2",
            count("zero_relevance_excluded"), active, **evidence,
        ),
        contribution(
            "inactive_candidate_filter_rate_v2",
            count("inactive_filtered"), passed, **evidence,
        ),
        contribution(
            "retrieval_k_compliance_v2",
            count("k_compliant_retrievals"), retrievals, **evidence,
        ),
        contribution(
            "retrieval_budget_compliance_v2",
            count("budget_compliant_retrievals"), retrievals, **evidence,
        ),
        contribution(
            "unresolved_conflict_selection_rate_v2",
            count("unresolved_conflict_retrievals"), retrievals, **evidence,
        ),
    ]
