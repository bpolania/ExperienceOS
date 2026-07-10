"""Phase 9 coverage-selection evaluator: v2-only contributions.

Reads the coverage diagnostics counters a v2 adapter records per case
(``result.diagnostics["coverage_v2"]``) and converts them into raw
metric contributions. Systems without coverage diagnostics — every
v1 system and the earlier v2 ablations — contribute nothing, so their
evaluation output is byte-identical.

All coverage_v2 metrics are neutral/observational: case outcomes are
still judged by the unchanged Phase 8 metrics.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution


def coverage_v2_contributions(case, result):
    counters = result.diagnostics.get("coverage_v2")
    if not isinstance(counters, dict):
        return []

    def count(key) -> float:
        value = counters.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    selected = count("selected_total")
    selections = count("selections")
    evidence = {
        "scenario_id": case.scenario_id,
        "selection_strategy": counters.get("selection_strategy"),
        "selection_strategy_version": counters.get(
            "selection_strategy_version"
        ),
    }
    return [
        contribution(
            "query_facet_coverage_v2",
            count("query_facets_covered"),
            count("query_facets_total"),
            **evidence,
        ),
        contribution(
            "redundant_selection_rate_v2",
            count("selected_redundant"), selected, **evidence,
        ),
        contribution(
            "positive_utility_selection_rate_v2",
            selected - 0.0, selected, **evidence,
        ),
        contribution(
            "coverage_stop_rate_v2",
            count("stopped_no_positive_utility"), selections, **evidence,
        ),
        contribution(
            "distinct_source_session_rate_v2",
            count("distinct_source_sessions_selected"), selected, **evidence,
        ),
        contribution(
            "conflict_warning_selection_rate_v2",
            count("selected_with_conflict_warning"), selections, **evidence,
        ),
    ]
