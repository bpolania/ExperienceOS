"""Deterministic benchmark evaluators (Phase 8 Prompt 5).

Metric contributions with fixed numerators/denominators against the
Prompt 1 registry and Prompt 2 oracle. Evaluation runs strictly after
system execution.
"""

from benchmarks.evaluators.aggregate import aggregate_by_group, aggregate_run
from benchmarks.evaluators.evaluate import evaluate_case
from benchmarks.evaluators.records import CaseEvaluation, CaseOutcome, Contribution

__all__ = [
    "CaseEvaluation",
    "CaseOutcome",
    "Contribution",
    "aggregate_by_group",
    "aggregate_run",
    "evaluate_case",
]
