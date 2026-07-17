"""Execution and evidence substrate for the comparison harness.

Drives selected systems over normalized cases through the existing
drivers, wraps each execution in one stable comparison record, and writes
a bounded artifact family (run manifest, per-(case, system) records,
execution summary, error summary). It records execution evidence only —
no competitive metrics, rankings, or conclusions.

Fairness is structural: one injected response provider reaches every
system; token accounting and latency come from the shared execution
records; system identity is not embedded in any judge-visible payload
(no judge runs here); oracle content never enters a record; and a system
failure or unavailability is preserved as its own status, never replaced
by another system's result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks.contract.result import CaseStatus
from experiments.competitive_viability import (
    DEVELOPMENT_ONLY_MARKER,
    HARNESS_SCHEMA_VERSION,
)
from experiments.competitive_viability.systems import (
    REGISTERED_SYSTEM_IDS,
    is_available,
    run_system_case,
    system_spec,
)

# Phase-level execution status vocabulary (distinct from CaseStatus).
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_UNAVAILABLE = "unavailable"
STATUS_UNSCORABLE = "unscorable"
STATUS_NOT_APPLICABLE = "not_applicable"

EXECUTION_MODE_OFFLINE = "offline"
EXECUTION_MODE_LIVE = "live"

_CASE_STATUS_TO_EXECUTION = {
    CaseStatus.PASSED: STATUS_COMPLETED,
    CaseStatus.FAILED: STATUS_FAILED,
    CaseStatus.PARTIAL: STATUS_FAILED,
    CaseStatus.SKIPPED: STATUS_NOT_APPLICABLE,
}

# Keys that must never appear in any recorded config or payload.
_SECRET_KEYS = ("api_key", "authorization", "token", "secret", "password")


@dataclass(frozen=True)
class ComparisonRecord:
    """One stable, serializable record per (case, system) execution.

    Keeps execution evidence, memory/retrieval/context evidence,
    final-answer evidence, and later-scoring evidence separated. Scoring
    fields are explicit ``None`` here — this stage produces no scores.
    """

    schema_version: str
    run_id: str
    system_id: str
    case_id: str
    dataset_id: str
    evidence_classification: str
    execution_mode: str
    response_model: str
    judge_model: str | None
    status: str
    unscorable_reason: str | None
    capabilities: tuple
    case_metadata: dict
    execution: dict | None  # the existing CaseResult payload, or None
    context_tokens: int | None
    full_history_tokens: int | None
    execution_error: str | None
    evaluator_error: str | None
    deterministic_scoring: dict | None = None
    rule_based_scoring: dict | None = None
    judge_scoring: dict | None = None

    def to_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "system_id": self.system_id,
            "case_id": self.case_id,
            "dataset_id": self.dataset_id,
            "evidence_classification": self.evidence_classification,
            "execution_mode": self.execution_mode,
            "response_model": self.response_model,
            "judge_model": self.judge_model,
            "status": self.status,
            "unscorable_reason": self.unscorable_reason,
            "capabilities": list(self.capabilities),
            "case_metadata": self.case_metadata,
            "execution": self.execution,
            "context_tokens": self.context_tokens,
            "full_history_tokens": self.full_history_tokens,
            "execution_error": self.execution_error,
            "evaluator_error": self.evaluator_error,
            "scoring": {
                "deterministic": self.deterministic_scoring,
                "rule_based": self.rule_based_scoring,
                "judge": self.judge_scoring,
            },
        }


def _assert_no_secrets(payload) -> None:
    """Defensive: no secret-bearing key may appear anywhere in a payload."""
    text = json.dumps(payload, default=str).lower()
    for key in _SECRET_KEYS:
        if f'"{key}"' in text:
            raise ValueError(f"refusing to record payload containing {key!r}")


def response_model_config(provider, execution_mode: str) -> dict:
    """Non-secret response-model configuration for the manifest."""
    return {
        "provider_name": getattr(provider, "name", type(provider).__name__),
        "model": getattr(provider, "model", None),
        "temperature": getattr(provider, "temperature", None),
        "timeout": getattr(provider, "timeout", None),
        "execution_mode": execution_mode,
        # deliberately no api_key / endpoint credentials
    }


def _build_record(
    viability_case, result, *, run_id, execution_mode, response_model,
    system_id,
) -> ComparisonRecord:
    spec = system_spec(system_id)
    if result is None:
        return ComparisonRecord(
            schema_version=HARNESS_SCHEMA_VERSION,
            run_id=run_id,
            system_id=system_id,
            case_id=viability_case.case_id,
            dataset_id=viability_case.dataset_source,
            evidence_classification=viability_case.evidence_classification,
            execution_mode=execution_mode,
            response_model=response_model,
            judge_model=None,
            status=STATUS_UNAVAILABLE,
            unscorable_reason=f"system {spec.availability}",
            capabilities=spec.capabilities,
            case_metadata=viability_case.to_metadata(),
            execution=None,
            context_tokens=None,
            full_history_tokens=None,
            execution_error=None,
            evaluator_error=None,
        )
    payload = result.to_payload()
    status = _CASE_STATUS_TO_EXECUTION.get(result.status, STATUS_FAILED)
    accounting = result.context_accounting
    context_tokens = (
        accounting.total_context_tokens if accounting else None
    )
    full_history_tokens = (
        context_tokens if system_id == "full_history" else None
    )
    return ComparisonRecord(
        schema_version=HARNESS_SCHEMA_VERSION,
        run_id=run_id,
        system_id=system_id,
        case_id=viability_case.case_id,
        dataset_id=viability_case.dataset_source,
        evidence_classification=viability_case.evidence_classification,
        execution_mode=execution_mode,
        response_model=response_model,
        judge_model=None,
        status=status,
        unscorable_reason=None,
        capabilities=spec.capabilities,
        case_metadata=viability_case.to_metadata(),
        execution=payload,
        context_tokens=context_tokens,
        full_history_tokens=full_history_tokens,
        execution_error=result.failure_reason,
        evaluator_error=None,
    )


@dataclass
class RunManifest:
    run_id: str
    timestamp: str
    git_commit: str
    schema_version: str
    execution_profile: str
    execution_mode: str
    ordering_policy: str
    token_counting_method: str
    response_model_config: dict
    requested_systems: list
    available_systems: list
    unavailable_systems: list
    requested_cases: list
    incomplete_cases: list
    execution_order: list
    artifact_paths: dict
    environment_capability: dict
    development_only: str = DEVELOPMENT_ONLY_MARKER

    def to_payload(self) -> dict:
        return dict(self.__dict__)


def execute(
    system_ids,
    viability_cases,
    provider,
    *,
    run_id: str,
    execution_mode: str = EXECUTION_MODE_OFFLINE,
    execution_profile: str = "development_smoke",
    out_dir: str | Path | None = None,
    timestamp: str = "unset",
    git_commit: str = "unset",
    environment_capability: dict | None = None,
) -> dict:
    """Run every requested system over every case; write the artifacts.

    One provider is injected into all systems (identical response model).
    Execution order is fixed (systems × cases in the given order) and
    recorded. Failures and unavailability are preserved as statuses.
    Returns an in-memory summary; also writes artifacts when ``out_dir``
    is given.
    """
    response_model = getattr(provider, "model", None) or getattr(
        provider, "name", type(provider).__name__
    )
    records = []
    execution_order = []
    unavailable = [s for s in system_ids if not is_available(s)]
    incomplete = []

    for system_id in system_ids:
        for vcase in viability_cases:
            execution_order.append(
                {"system_id": system_id, "case_id": vcase.case_id}
            )
            result = None
            if is_available(system_id):
                # One shared model reaches every system; run_system_case
                # adapts it to each family's message contract (baselines
                # via the shim, the SDK path natively).
                result = run_system_case(
                    system_id, vcase.scenario, provider, run_id
                )
            record = _build_record(
                vcase, result, run_id=run_id, execution_mode=execution_mode,
                response_model=response_model, system_id=system_id,
            )
            if record.status in (STATUS_FAILED, STATUS_UNAVAILABLE):
                incomplete.append(
                    {"system_id": system_id, "case_id": vcase.case_id,
                     "status": record.status}
                )
            records.append(record)

    manifest = RunManifest(
        run_id=run_id,
        timestamp=timestamp,
        git_commit=git_commit,
        schema_version=HARNESS_SCHEMA_VERSION,
        execution_profile=execution_profile,
        execution_mode=execution_mode,
        ordering_policy="fixed:systems_x_cases",
        token_counting_method="benchmark_context_accounting",
        response_model_config=response_model_config(provider, execution_mode),
        requested_systems=list(system_ids),
        available_systems=[s for s in system_ids if is_available(s)],
        unavailable_systems=unavailable,
        requested_cases=[c.case_id for c in viability_cases],
        incomplete_cases=incomplete,
        execution_order=execution_order,
        artifact_paths={},
        environment_capability=environment_capability or {},
    )

    summary = _summary(records)
    artifacts = {}
    if out_dir is not None:
        artifacts = _write_artifacts(
            out_dir, manifest, records, summary
        )
        manifest.artifact_paths = artifacts
    return {
        "manifest": manifest.to_payload(),
        "records": [r.to_payload() for r in records],
        "summary": summary,
        "artifact_paths": artifacts,
    }


def _summary(records) -> dict:
    by_status = {}
    for record in records:
        by_status[record.status] = by_status.get(record.status, 0) + 1
    return {
        "development_only": DEVELOPMENT_ONLY_MARKER,
        "case_system_executions": len(records),
        "by_status": by_status,
        "execution_failures": by_status.get(STATUS_FAILED, 0),
        "unavailable": by_status.get(STATUS_UNAVAILABLE, 0),
        "completed": by_status.get(STATUS_COMPLETED, 0),
        "evaluator_failures": 0,
    }


def _write_artifacts(out_dir, manifest, records, summary) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    record_payloads = [r.to_payload() for r in records]
    manifest_payload = manifest.to_payload()
    for payload in record_payloads + [manifest_payload]:
        _assert_no_secrets(payload)

    manifest_path = out / "run_manifest.json"
    records_path = out / "records.jsonl"
    summary_path = out / "execution_summary.json"
    errors_path = out / "errors.json"

    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n"
    )
    with records_path.open("w") as handle:
        for payload in record_payloads:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    errors = [
        {"system_id": r.system_id, "case_id": r.case_id,
         "status": r.status, "execution_error": r.execution_error}
        for r in records
        if r.status in (STATUS_FAILED, STATUS_UNAVAILABLE)
    ]
    errors_path.write_text(
        json.dumps({"development_only": DEVELOPMENT_ONLY_MARKER,
                    "errors": errors}, indent=2, sort_keys=True) + "\n"
    )
    return {
        "run_manifest": str(manifest_path),
        "records": str(records_path),
        "execution_summary": str(summary_path),
        "errors": str(errors_path),
    }
