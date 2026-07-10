"""Evaluation records: raw metric contributions and per-case evaluation.

Every metric value in the benchmark is built from Contribution records
— raw numerator/denominator increments tied to a registry metric and
small evidence references. Aggregation sums increments; it never
averages per-case percentages. Undefined contributions carry a reason
and are excluded (and counted) rather than coerced to 0 or 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.contract import metric as metric_definition


@dataclass(frozen=True)
class Contribution:
    """One raw metric contribution from one case-system run."""

    metric: str
    numerator: float
    denominator: float
    applicable: bool = True
    undefined_reason: str | None = None
    evidence: dict = field(default_factory=dict)

    def __post_init__(self):
        metric_definition(self.metric)  # unknown metric names are rejected

    def to_payload(self) -> dict:
        definition = metric_definition(self.metric)
        return {
            "metric": self.metric,
            "group": definition.group,
            "applicable": self.applicable,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "undefined_reason": self.undefined_reason,
            "evidence": dict(sorted(self.evidence.items())),
            "evaluator_type": "deterministic",
            "deterministic": True,
        }


def contribution(metric, numerator, denominator, **evidence) -> Contribution:
    return Contribution(
        metric=metric,
        numerator=float(numerator),
        denominator=float(denominator),
        evidence=evidence,
    )


def undefined(metric, reason, **evidence) -> Contribution:
    return Contribution(
        metric=metric,
        numerator=0.0,
        denominator=0.0,
        applicable=False,
        undefined_reason=reason,
        evidence=evidence,
    )


class CaseOutcome:
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    EXECUTION_FAILED = "execution_failed"
    EVALUATION_DEFERRED = "evaluation_deferred"


@dataclass
class CaseEvaluation:
    """Per-case evaluation: navigation aid plus raw contributions.

    The outcome label is NOT an overall score; the benchmark's
    conclusions come from the aggregate metric table.
    """

    scenario_id: str
    system_id: str
    execution_status: str
    outcome: str = CaseOutcome.PASSED
    eligible: bool = True
    contributions: list[Contribution] = field(default_factory=list)
    constraint_results: list[dict] = field(default_factory=list)
    resolution: dict = field(default_factory=dict)
    deferred: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "system_id": self.system_id,
            "execution_status": self.execution_status,
            "outcome": self.outcome,
            "eligible": self.eligible,
            "contributions": [c.to_payload() for c in self.contributions],
            "constraint_results": list(self.constraint_results),
            "resolution": {
                k: dict(v) for k, v in sorted(self.resolution.items())
            },
            "deferred": list(self.deferred),
            "failures": list(self.failures),
            "notes": list(self.notes),
        }
