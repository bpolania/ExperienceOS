"""Benchmark execution: six systems × ordered scenarios → evaluated
records ready for artifact writing.

Ordering is fully deterministic: systems in configured order, then
scenarios in committed profile/manifest order, then ordered turns. A
fresh system instance runs every case; state never crosses case,
system, run, or profile boundaries. With fail_fast false (the
default), failures produce evidence and later cases continue. Low
benchmark scores are never execution failures.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field

from benchmarks.adapters.common import run_adapter_case
from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
from benchmarks.baselines.common import run_case as run_baseline_case
from benchmarks.contract import RunProvenance, assert_provenance_safe
from benchmarks.evaluators import evaluate_case
from benchmarks.evaluators.operational import (
    latency_samples,
    operational_counts,
)
from benchmarks.runner.config import RunConfig
from benchmarks.scenarios.loader import load_dataset, load_manifest


@dataclass
class CaseRun:
    scenario_id: str
    system_id: str
    group: str
    category: str
    result: object
    evaluation: object

    def record(self) -> dict:
        accounting = self.result.context_accounting
        return {
            "scenario_id": self.scenario_id,
            "system_id": self.system_id,
            "group": self.group,
            "category": self.category,
            "status": self.result.status,
            "outcome": self.evaluation.outcome,
            "contributions": [
                c.to_payload() for c in self.evaluation.contributions
            ],
            "accounting": accounting.to_payload() if accounting else None,
            "latency_samples": latency_samples(self.result),
            "counts": operational_counts(self.result),
        }


@dataclass
class RunOutput:
    config: RunConfig
    case_runs: list[CaseRun] = field(default_factory=list)
    execution_order: list[dict] = field(default_factory=list)
    failures: dict = field(default_factory=dict)
    started_at: str = ""
    manifest: dict = field(default_factory=dict)


def _select_scenarios(config: RunConfig):
    manifest = load_manifest()
    scenarios = load_dataset(manifest)
    if config.scenario_ids:
        by_id = {s.case.scenario_id: s for s in scenarios}
        missing = [i for i in config.scenario_ids if i not in by_id]
        if missing:
            raise ValueError(f"profile references unknown scenarios: {missing}")
        scenarios = [by_id[i] for i in config.scenario_ids]
    return manifest, scenarios


def _run_one(system_id: str, scenario, config: RunConfig):
    system = create_system(
        system_id, local_mode=config.local_policy_mode
    )
    if system_id in ADAPTER_SYSTEM_IDS:
        return run_adapter_case(system, scenario, run_id=config.run_id)
    return run_baseline_case(system, scenario, run_id=config.run_id)


def execute_run(config: RunConfig) -> RunOutput:
    manifest, scenarios = _select_scenarios(config)
    output = RunOutput(config=config, manifest=manifest)
    output.started_at = config.timestamp_override or _utc_now()
    failures = {
        "system_execution_failures": [],
        "evaluator_failures": [],
        "unresolved_references": [],
        "ambiguous_references": [],
        "deferred_evaluations": [],
        "skipped_cases": [],
    }

    for system_id in config.systems:
        for scenario in scenarios:
            case = scenario.case
            result = _run_one(system_id, scenario, config)
            evaluation = evaluate_case(case, result)
            run = CaseRun(
                scenario_id=case.scenario_id,
                system_id=system_id,
                group=scenario.group,
                category=case.category,
                result=result,
                evaluation=evaluation,
            )
            output.case_runs.append(run)
            output.execution_order.append(
                {
                    "index": len(output.execution_order),
                    "scenario_id": case.scenario_id,
                    "system_id": system_id,
                    "status": result.status,
                    "outcome": evaluation.outcome,
                }
            )
            _collect_failures(failures, case, result, evaluation)
            if config.fail_fast and evaluation.outcome == "execution_failed":
                output.failures = failures
                return output
    output.failures = failures
    return output


def _collect_failures(failures, case, result, evaluation):
    key = {"scenario_id": case.scenario_id, "system_id": result.system_id}
    if evaluation.outcome == "skipped":
        failures["skipped_cases"].append(
            {**key, "reason": result.skip_reason}
        )
    for item in evaluation.failures:
        if item["type"] == "system_execution_failure":
            failures["system_execution_failures"].append({**key, **item})
        elif item["type"] == "evaluator_failure":
            failures["evaluator_failures"].append({**key, **item})
        elif item["type"] == "ambiguous_reference":
            failures["ambiguous_references"].append({**key, **item})
    for scope_key, resolved in evaluation.resolution.items():
        if resolved["status"] == "unresolved":
            failures["unresolved_references"].append(
                {**key, "reference": scope_key}
            )
    for reason in evaluation.deferred:
        failures["deferred_evaluations"].append({**key, "reason": reason})


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _repository_commit() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return commit, not dirty
    except Exception:  # noqa: BLE001 — provenance degrades explicitly
        return "unknown", False


def build_provenance(output: RunOutput) -> RunProvenance:
    config = output.config
    commit, clean = _repository_commit()
    outcomes = [r.evaluation.outcome for r in output.case_runs]
    statuses = [r.result.status for r in output.case_runs]
    provenance = RunProvenance(
        run_id=config.run_id,
        repository_commit=commit,
        working_tree_clean=clean,
        suite_version=config.suite_version,
        manifest_version=output.manifest["dataset_version"],
        manifest_hash=output.manifest["manifest_hash"],
        run_timestamp_utc=output.started_at,
        provider_name="mock",
        response_model="mock",
        memory_policy=config.memory_policy_mode,
        storage_mode=config.storage_mode,
        retrieval_description="per-system (see system configs)",
        context_budget=0,
        selection_k=None,
        temperature=config.temperature,
        max_output_tokens=config.max_output_tokens,
        seed=0,
        retry_policy=config.retry_policy,
        platform=f"{platform.system().lower()}-{platform.machine()}",
        python_version=(
            f"{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        local_model_name=(
            "scripted-local-proposals"
            if config.local_policy_mode == "scripted"
            else None
        ),
        used_real_provider=False,
        used_real_local_model=False,
        used_mock=True,
        used_fallback=any(
            r.result.turns and any(t.fallbacks for t in r.result.turns)
            for r in output.case_runs
        ),
        evaluator_type="deterministic",
        evaluator_model=None,
        executed_cases=sum(1 for s in statuses if s != "skipped"),
        passed_cases=outcomes.count("passed"),
        failed_cases=outcomes.count("failed")
        + outcomes.count("execution_failed"),
        skipped_cases=outcomes.count("skipped"),
        partial_cases=outcomes.count("partial")
        + outcomes.count("evaluation_deferred"),
        notes=(
            "context budgets and seeds are per-scenario (committed in the "
            "dataset); experienceos_local mode is scripted-plus-fallback "
            "offline, NOT a real-GGUF result",
        ),
    )
    assert_provenance_safe(provenance)
    return provenance
