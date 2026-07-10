"""Aggregation: raw numerator/denominator sums per system and metric.

Never averages per-case percentages; never produces a composite
score. F1 is derived from AGGREGATE precision and recall.
``token_reduction_vs_full_history`` and
``answers_per_1k_memory_tokens`` are synthesized here, where the
full-history reference and case outcomes exist. Latency percentiles
use the contract's nearest-rank helper with low-sample flags.
"""

from __future__ import annotations

from benchmarks.contract import (
    MIN_PERCENTILE_SAMPLES,
    metric as metric_definition,
    percentile,
    ratio,
)

_SORTED = sorted


def _empty_cell():
    return {
        "numerator": 0.0,
        "denominator": 0.0,
        "value": None,
        "sample_count": 0,
        "undefined_count": 0,
        "excluded_count": 0,
        "failed_case_count": 0,
        "skipped_case_count": 0,
    }


def aggregate_run(records) -> dict:
    """records: list of dicts with keys scenario_id, system_id, group,
    category, status, outcome, contributions (payload dicts),
    accounting (payload or None), latency_samples, counts."""
    by_system: dict = {}
    latency: dict = {}
    counts: dict = {}
    outcomes: dict = {}

    for record in records:
        system = record["system_id"]
        cell_map = by_system.setdefault(system, {})
        outcome_map = outcomes.setdefault(system, {})
        outcome_map[record["outcome"]] = (
            outcome_map.get(record["outcome"], 0) + 1
        )
        if record["outcome"] == "skipped":
            continue
        for payload in record["contributions"]:
            cell = cell_map.setdefault(payload["metric"], _empty_cell())
            if not payload["applicable"]:
                cell["undefined_count"] += 1
                continue
            cell["numerator"] += payload["numerator"]
            cell["denominator"] += payload["denominator"]
            cell["sample_count"] += 1
        if record["outcome"] in ("failed", "execution_failed"):
            for payload in record["contributions"]:
                cell = cell_map.setdefault(payload["metric"], _empty_cell())
                cell["failed_case_count"] += 1
        stage_map = latency.setdefault(system, {})
        for stage, samples in record["latency_samples"].items():
            stage_map.setdefault(stage, []).extend(samples)
        count_map = counts.setdefault(system, {})
        for key, value in record["counts"].items():
            count_map[key] = count_map.get(key, 0) + value

    # Derived metrics.
    _derive_f1(by_system)
    _derive_full_history_reduction(by_system, records)
    _derive_answers_per_1k(by_system, records)

    metrics_out: dict = {}
    for system, cells in _SORTED(by_system.items()):
        metrics_out[system] = {}
        for name, cell in _SORTED(cells.items()):
            definition = metric_definition(name)
            cell["value"] = ratio(cell["numerator"], cell["denominator"])
            metrics_out[system][name] = {
                **cell,
                "group": definition.group,
                "numerator_definition": definition.numerator,
                "denominator_definition": definition.denominator,
            }

    latency_out: dict = {}
    for system, stages in _SORTED(latency.items()):
        latency_out[system] = {}
        for stage, samples in _SORTED(stages.items()):
            ordered = sorted(samples)
            latency_out[system][stage] = {
                "count": len(ordered),
                "mean_ms": sum(ordered) / len(ordered) if ordered else None,
                "min_ms": ordered[0] if ordered else None,
                "max_ms": ordered[-1] if ordered else None,
                "p50_ms": percentile(ordered, 50) if ordered else None,
                "p95_ms": percentile(ordered, 95) if ordered else None,
                "low_sample_warning": len(ordered)
                < MIN_PERCENTILE_SAMPLES,
            }

    return {
        "metrics": metrics_out,
        "latency": latency_out,
        "operational_counts": {
            s: dict(_SORTED(c.items())) for s, c in _SORTED(counts.items())
        },
        "case_outcomes": {
            s: dict(_SORTED(o.items())) for s, o in _SORTED(outcomes.items())
        },
        "composite_score": None,  # deliberately: no composite exists
    }


def _derive_f1(by_system):
    for cells in by_system.values():
        precision = cells.get("memory_creation_precision")
        recall = cells.get("memory_creation_recall")
        if not precision or not recall:
            continue
        p = ratio(precision["numerator"], precision["denominator"])
        r = ratio(recall["numerator"], recall["denominator"])
        cell = cells.setdefault("memory_creation_f1", _empty_cell())
        if p is None or r is None or (p + r) == 0:
            cell["undefined_count"] += 1
            continue
        cell["numerator"] = 2 * p * r
        cell["denominator"] = p + r
        cell["sample_count"] = min(
            precision["sample_count"], recall["sample_count"]
        )


def _derive_full_history_reduction(by_system, records):
    fh_tokens = {
        r["scenario_id"]: r["accounting"]["total_context_tokens"]
        for r in records
        if r["system_id"] == "full_history"
        and r["accounting"]
        and r["outcome"] not in ("skipped", "execution_failed")
    }
    for record in records:
        system = record["system_id"]
        if system == "full_history":
            continue
        if record["outcome"] in ("skipped", "execution_failed"):
            continue
        cell = by_system.setdefault(system, {}).setdefault(
            "token_reduction_vs_full_history", _empty_cell()
        )
        reference = fh_tokens.get(record["scenario_id"])
        accounting = record["accounting"]
        if reference is None or not accounting:
            cell["undefined_count"] += 1
            continue
        cell["numerator"] += reference - accounting["total_context_tokens"]
        cell["denominator"] += reference
        cell["sample_count"] += 1


def _derive_answers_per_1k(by_system, records):
    for record in records:
        if record["outcome"] in ("skipped", "execution_failed"):
            continue
        accounting = record["accounting"]
        cell = by_system.setdefault(record["system_id"], {}).setdefault(
            "answers_per_1k_memory_tokens", _empty_cell()
        )
        if not accounting or not accounting["memory_context_tokens"]:
            cell["undefined_count"] += 1  # zero tokens: undefined, not ∞
            continue
        cell["numerator"] += 1000 if record["outcome"] == "passed" else 0
        cell["denominator"] += accounting["memory_context_tokens"]
        cell["sample_count"] += 1


def aggregate_by_group(records) -> dict:
    """Numerator/denominator sums per (system, scenario group, metric)."""
    out: dict = {}
    for record in records:
        if record["outcome"] == "skipped":
            continue
        group_map = out.setdefault(record["system_id"], {}).setdefault(
            record["group"], {}
        )
        for payload in record["contributions"]:
            if not payload["applicable"]:
                continue
            cell = group_map.setdefault(
                payload["metric"],
                {"numerator": 0.0, "denominator": 0.0},
            )
            cell["numerator"] += payload["numerator"]
            cell["denominator"] += payload["denominator"]
    for system, groups in out.items():
        for group, cells in groups.items():
            for name, cell in cells.items():
                cell["value"] = ratio(
                    cell["numerator"], cell["denominator"]
                )
    return out
