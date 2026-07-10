"""Operational evaluators: fallback/containment contributions per case
plus raw latency and count samples for run-level aggregation.

Percentiles are computed at aggregation with the contract's
nearest-rank helper; samples below MIN_PERCENTILE_SAMPLES are flagged
low-sample, never hidden.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution, undefined


def operational_contributions(case, result):
    out = []
    turns = result.turns
    if not turns:
        return out
    fallback_turns = sum(1 for t in turns if t.fallbacks)
    out.append(
        contribution("fallback_rate", fallback_turns, len(turns))
    )
    rejections = sum(len(t.rejected_actions) for t in turns)
    duplicates_accepted = 0  # accepted invalids surface via lifecycle
    invalid_pressure = rejections + duplicates_accepted
    if invalid_pressure:
        out.append(
            contribution(
                "rejection_containment_rate", rejections, invalid_pressure
            )
        )
    return out


def latency_samples(result) -> dict:
    """Stage -> list of millisecond samples across turns."""
    samples: dict = {}
    for turn in result.turns:
        for record in turn.latencies:
            samples.setdefault(record.stage, []).append(
                record.milliseconds
            )
    return samples


def operational_counts(result) -> dict:
    return {
        "provider_request_count": result.provider_request_count,
        "local_model_invocation_count": result.local_model_invocation_count,
        "retry_count": result.retry_count,
        "fallback_count": sum(len(t.fallbacks) for t in result.turns),
        "rejection_count": sum(
            len(t.rejected_actions) for t in result.turns
        ),
    }
