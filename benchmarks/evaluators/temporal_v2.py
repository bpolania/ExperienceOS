"""Phase 9 temporal/provenance evaluator: v2-only contributions.

Reads the temporal diagnostics counters a v2 adapter records per case
(``result.diagnostics["temporal_v2"]``) and converts them into raw
metric contributions. Systems without temporal diagnostics contribute
nothing, so earlier evaluation output is byte-identical. All
temporal_v2 metrics are neutral/observational.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution


def temporal_v2_contributions(case, result):
    counters = result.diagnostics.get("temporal_v2")
    if not isinstance(counters, dict):
        return []

    def count(key) -> float:
        value = counters.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    turns = count("turns")
    retrievals = count("retrievals")
    detected = count("temporal_expressions_detected")
    evidence = {
        "scenario_id": case.scenario_id,
        "temporal_metadata_version": counters.get(
            "temporal_metadata_version"
        ),
        "assistant_ingestion_enabled": counters.get(
            "assistant_ingestion_enabled"
        ),
    }
    return [
        contribution(
            "temporal_metadata_coverage_v2",
            count("creates_with_temporal"),
            count("creates_with_provenance"),
            **evidence,
        ),
        contribution(
            "temporal_expression_resolution_v2",
            detected - count("temporal_expressions_unresolved"),
            detected,
            **evidence,
        ),
        contribution(
            "historical_query_mode_rate_v2",
            count("mode_historical") + count("mode_as_of")
            + count("mode_timeline"),
            retrievals,
            **evidence,
        ),
        contribution(
            "future_hold_rate_v2",
            count("not_yet_valid_held"), retrievals, **evidence,
        ),
        contribution(
            "assistant_candidate_rejection_v2",
            count("assistant_candidates_rejected"), turns, **evidence,
        ),
        contribution(
            "trusted_ingestion_acceptance_v2",
            count("tool_verified_accepted")
            + count("jointly_confirmed_accepted")
            + count("derivations_created"),
            turns,
            **evidence,
        ),
        contribution(
            "superseded_historical_admission_v2",
            count("superseded_admitted_historical"), retrievals, **evidence,
        ),
    ]
