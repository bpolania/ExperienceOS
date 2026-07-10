"""Raw artifact writing: atomic, validated, deterministic.

Layout per run directory:

    run_config.json          resolved configuration
    provenance.json          Prompt 1 provenance (safe)
    execution_manifest.json  ordered case-system runs with statuses
    cases.jsonl              one {case, evaluation} record per line
    metric_contributions.jsonl  one contribution record per line
    aggregate.json           raw numerator/denominator aggregation
    failures.json            every failure/skip/deferral (explicit
                             empty lists when none)
    artifact_manifest.json   file hashes, record counts, normalized
                             result digest, artifact schema version
    README.md                what this artifact is and is not

Writing goes to `<output>.incomplete` first, every artifact is
re-validated, then the directory is atomically promoted. Existing
output is never overwritten unless explicitly requested. Interrupted
writes leave only the clearly-marked incomplete directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from benchmarks.contract import canonical_json, stable_dump
from benchmarks.evaluators import aggregate_by_group, aggregate_run
from benchmarks.runner.execute import RunOutput, build_provenance

ARTIFACT_SCHEMA_VERSION = "1"

ARTIFACT_FILES = (
    "run_config.json",
    "provenance.json",
    "execution_manifest.json",
    "cases.jsonl",
    "metric_contributions.jsonl",
    "aggregate.json",
    "failures.json",
)

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00")


def normalize_for_digest(data) -> object:
    """Normalized structural view: strips only known-nondeterministic
    fields (timestamps, measured latency, runtime UUIDs mapped by
    first-seen order). Behavioral fields — actions, kinds, values,
    targets, rejection/fallback reasons, candidate order, selection
    state, context text, responses, constraint outcomes, numerators,
    denominators, statuses — are untouched."""
    body = canonical_json(data)
    seen: dict = {}

    def _sub(match):
        return seen.setdefault(match.group(0), f"mem-{len(seen):04d}")

    body = _UUID.sub(_sub, body)
    body = _TS.sub("<timestamp>", body)
    parsed = json.loads(body)
    _strip_latency(parsed)
    return parsed


def _strip_latency(node):
    if isinstance(node, dict):
        for key in ("latencies", "latency_samples"):
            if key in node:
                node[key] = []
        for key in ("mean_ms", "min_ms", "max_ms", "p50_ms", "p95_ms"):
            if key in node:
                node[key] = None
        if "milliseconds" in node:
            node["milliseconds"] = None
        for value in node.values():
            _strip_latency(value)
    elif isinstance(node, list):
        for item in node:
            _strip_latency(item)


def normalized_digest(case_records: list, aggregate: dict) -> str:
    normalized = normalize_for_digest(
        {"cases": case_records, "aggregate": aggregate}
    )
    return hashlib.sha256(
        canonical_json(normalized).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_artifacts(output: RunOutput, readme_extra: str = "") -> Path:
    final_dir = Path(output.config.output_dir)
    if final_dir.exists():
        if not output.config.overwrite:
            raise FileExistsError(
                f"output directory exists: {final_dir} "
                "(pass overwrite to replace it)"
            )
        shutil.rmtree(final_dir)
    staging = final_dir.parent / (final_dir.name + ".incomplete")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    case_lines = []
    contribution_lines = []
    records = []
    for run in output.case_runs:
        case_lines.append(
            {
                "case": run.result.to_payload(),
                "evaluation": run.evaluation.to_payload(),
            }
        )
        for c in run.evaluation.contributions:
            contribution_lines.append(
                {
                    "scenario_id": run.scenario_id,
                    "system_id": run.system_id,
                    **c.to_payload(),
                }
            )
        records.append(run.record())

    aggregate = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "suite_version": output.config.suite_version,
        "profile": output.config.profile,
        **aggregate_run(records),
        "by_scenario_group": aggregate_by_group(records),
    }

    provenance = build_provenance(output)

    _write(staging / "run_config.json", output.config.to_payload())
    _write(staging / "provenance.json", provenance.to_payload())
    _write(
        staging / "execution_manifest.json",
        {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "runs": output.execution_order,
        },
    )
    _write_jsonl(staging / "cases.jsonl", case_lines)
    _write_jsonl(
        staging / "metric_contributions.jsonl", contribution_lines
    )
    _write(staging / "aggregate.json", aggregate)
    _write(staging / "failures.json", output.failures)

    digest = normalized_digest(case_lines, aggregate)
    manifest = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "files": {
            name: {
                "sha256": _file_sha256(staging / name),
                "records": (
                    sum(
                        1
                        for _ in (staging / name)
                        .read_text()
                        .strip()
                        .splitlines()
                    )
                    if name.endswith(".jsonl")
                    else 1
                ),
            }
            for name in ARTIFACT_FILES
        },
        "case_run_count": len(output.case_runs),
        "normalized_result_digest": digest,
    }
    _write(staging / "artifact_manifest.json", manifest)
    (staging / "README.md").write_text(_readme(output, digest, readme_extra))

    from benchmarks.artifacts.validation import validate_artifact_dir

    validate_artifact_dir(staging, allow_staging=True)

    staging.replace(final_dir)
    return final_dir


def _write(path: Path, data) -> None:
    path.write_text(stable_dump(data), encoding="utf-8")


def _write_jsonl(path: Path, lines) -> None:
    body = "".join(canonical_json(line) + "\n" for line in lines)
    path.write_text(body, encoding="utf-8")


def _readme(output: RunOutput, digest: str, extra: str) -> str:
    config = output.config
    return f"""# Benchmark raw artifact: {config.run_id}

Produced by `python -m benchmarks.runner.cli run --profile {config.profile}`
in **{config.response_provider_mode}** mode (deterministic offline
provider; no network, no credentials, no real local model).

- Suite: {config.suite_version} · profile: {config.profile}
- Systems: {", ".join(config.systems)}
- Local-policy mode: {config.local_policy_mode} — the
  `experienceos_local` numbers are **scripted-plus-fallback offline
  results, NOT a real-GGUF score** (see provenance.json).
- Response-inclusion metrics reflect the deterministic echo provider
  applied equally to all systems; model-scored cases are deferred.
- Normalized result digest: `{digest}`

This artifact contains raw comparative evidence only: per-case
results, metric contributions with fixed numerators/denominators, and
aggregation. It is **not** a LongMemEval result, contains no LLM-judge
scores, and carries no final comparative interpretation — the
judge-facing report is produced separately.
{extra}"""
