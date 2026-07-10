"""Artifact validation: verify a result directory without rerunning.

    PYTHONPATH=. python -m benchmarks.artifacts.validation <result-dir>

Checks files, schemas, hashes, record counts, execution-manifest
consistency, aggregate recomputation from raw contributions, dataset
manifest match, normalized digest, and safety (no secrets, no
personal paths, no incomplete marker).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from benchmarks.contract import (
    KNOWN_SYSTEM_IDS,
    canonical_json,
    metric as metric_definition,
    ratio,
)
from benchmarks.scenarios.loader import load_manifest

REQUIRED_FILES = (
    "run_config.json",
    "provenance.json",
    "execution_manifest.json",
    "cases.jsonl",
    "metric_contributions.jsonl",
    "aggregate.json",
    "failures.json",
    "artifact_manifest.json",
    "README.md",
)

UNSAFE_MARKERS = ("/Users/", "/home/", "\\Users\\", "api_key", "sk-")


class ArtifactValidationError(ValueError):
    pass


def _fail(message: str):
    raise ArtifactValidationError(message)


def validate_artifact_dir(path: Path, allow_staging: bool = False) -> dict:
    path = Path(path)
    if not path.is_dir():
        _fail(f"not a directory: {path}")
    if path.name.endswith(".incomplete") and not allow_staging:
        _fail("incomplete artifact cannot be canonical")

    for name in REQUIRED_FILES:
        if not (path / name).exists():
            _fail(f"missing required artifact file: {name}")

    manifest = json.loads((path / "artifact_manifest.json").read_text())
    for name, info in manifest["files"].items():
        actual = hashlib.sha256((path / name).read_bytes()).hexdigest()
        if actual != info["sha256"]:
            _fail(f"file hash mismatch for {name}")

    cases = [
        json.loads(line)
        for line in (path / "cases.jsonl").read_text().strip().splitlines()
    ]
    contributions = [
        json.loads(line)
        for line in (path / "metric_contributions.jsonl")
        .read_text()
        .strip()
        .splitlines()
    ]
    if manifest["files"]["cases.jsonl"]["records"] != len(cases):
        _fail("cases.jsonl record count mismatch")
    if manifest["files"]["metric_contributions.jsonl"]["records"] != len(
        contributions
    ):
        _fail("metric_contributions.jsonl record count mismatch")
    if manifest["case_run_count"] != len(cases):
        _fail("case_run_count mismatch")

    execution = json.loads(
        (path / "execution_manifest.json").read_text()
    )["runs"]
    if len(execution) != len(cases):
        _fail("execution manifest does not match case count")
    for entry, record in zip(execution, cases):
        if entry["scenario_id"] != record["case"]["scenario_id"]:
            _fail(
                f"execution order mismatch at index {entry['index']}: "
                f"{entry['scenario_id']} vs "
                f"{record['case']['scenario_id']}"
            )
        if entry["system_id"] != record["case"]["system_id"]:
            _fail(f"system order mismatch at index {entry['index']}")

    dataset_manifest = load_manifest()
    known_scenarios = {
        e["scenario_id"] for e in dataset_manifest["scenarios"]
    }
    provenance = json.loads((path / "provenance.json").read_text())
    if provenance["manifest_hash"] != dataset_manifest["manifest_hash"]:
        _fail("provenance manifest hash does not match committed dataset")
    for record in cases:
        if record["case"]["scenario_id"] not in known_scenarios:
            _fail(
                f"unknown scenario in cases: {record['case']['scenario_id']}"
            )
        if record["case"]["system_id"] not in KNOWN_SYSTEM_IDS:
            _fail(f"unknown system: {record['case']['system_id']}")

    for contribution in contributions:
        metric_definition(contribution["metric"])  # raises on unknown
        if contribution["scenario_id"] not in known_scenarios:
            _fail("contribution references unknown scenario")

    _recompute_aggregate(path, contributions)
    _safety_scan(path)

    from benchmarks.artifacts.writer import normalized_digest

    aggregate = json.loads((path / "aggregate.json").read_text())
    digest = normalized_digest(cases, aggregate)
    if digest != manifest["normalized_result_digest"]:
        _fail("normalized result digest mismatch")

    return {
        "files": len(REQUIRED_FILES),
        "case_runs": len(cases),
        "contributions": len(contributions),
        "normalized_result_digest": digest,
    }


def _recompute_aggregate(path: Path, contributions) -> None:
    """Aggregate numerators/denominators must equal recomputation."""
    aggregate = json.loads((path / "aggregate.json").read_text())
    recomputed: dict = {}
    for c in contributions:
        if not c["applicable"]:
            continue
        cell = recomputed.setdefault(c["system_id"], {}).setdefault(
            c["metric"], [0.0, 0.0]
        )
        cell[0] += c["numerator"]
        cell[1] += c["denominator"]
    for system, cells in recomputed.items():
        for name, (num, den) in cells.items():
            stored = aggregate["metrics"].get(system, {}).get(name)
            if stored is None:
                _fail(f"aggregate missing {system}/{name}")
            if (
                abs(stored["numerator"] - num) > 1e-9
                or abs(stored["denominator"] - den) > 1e-9
            ):
                _fail(
                    f"aggregate recomputation mismatch for {system}/{name}: "
                    f"stored {stored['numerator']}/{stored['denominator']}, "
                    f"recomputed {num}/{den}"
                )
            expected_value = ratio(num, den)
            if stored["value"] is None and expected_value is not None:
                _fail(f"aggregate value missing for {system}/{name}")


def _safety_scan(path: Path) -> None:
    for name in REQUIRED_FILES:
        body = (path / name).read_text()
        for marker in UNSAFE_MARKERS:
            if marker in body:
                _fail(f"{name} contains unsafe content marker {marker!r}")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: python -m benchmarks.artifacts.validation <result-dir>")
        return 2
    try:
        summary = validate_artifact_dir(Path(argv[0]))
    except ArtifactValidationError as exc:
        print(f"ARTIFACT INVALID: {exc}")
        return 1
    print(f"artifact files: {summary['files']}")
    print(f"case runs: {summary['case_runs']}")
    print(f"metric contributions: {summary['contributions']}")
    print(
        f"normalized result digest: {summary['normalized_result_digest']}"
    )
    print("aggregate recomputation: matched")
    print("RESULT: artifact validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
