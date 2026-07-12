"""Phase 11 artifact validators (additive; v1/v2 validators untouched).

Validates the committed Phase 11 lifecycle and external artifacts:
structure, run identity, the four-system matrix, lifecycle-safety
zeros, the Phase 9 reference lock (the reference system must reproduce
the historical `experienceos_hybrid_full_v2` metrics exactly), and
fused/gate-shadow canonical equivalence (only gate diagnostics may
differ; `gate_affected_selection` must be zero everywhere).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from benchmarks.artifacts.validation import validate_artifact_dir
from benchmarks.contract import SystemId
from benchmarks.external.longmemeval.validation import (
    validate_external_artifact,
)
from benchmarks.phase11 import (
    EXTERNAL_RUN_ID,
    LIFECYCLE_RUN_ID,
    PHASE11_SYSTEMS,
)

LIFECYCLE_MANIFEST_HASH = (
    "0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb"
)

HISTORICAL_FULL_V2 = SystemId.EXPERIENCEOS_HYBRID_FULL_V2
REFERENCE_ID = SystemId.EXPERIENCEOS_HYBRID_FULL_V2_REFERENCE
FUSED_ID = SystemId.EXPERIENCEOS_FUSED_RETRIEVAL_V1
GATE_ID = SystemId.EXPERIENCEOS_GATE_SHADOW_V1

V2_LIFECYCLE_DIR = "benchmarks/results/committed/lifecycle-v2-ablation"
V2_EXTERNAL_DIR = "benchmarks/results/committed/longmemeval-50-subset-v2"

# Hard adoption-gate zeros for current-context retrieval (numerators).
LIFECYCLE_MUST_BE_ZERO = (
    "inactive_contamination_rate",
    "forgotten_response_contamination_rate",
)

# Derived metrics computed RELATIVE TO OTHER SYSTEMS IN THE SAME RUN
# (not system behavior). Phase 9 ran full_history in its matrix; the
# Phase 11 matrix deliberately does not, so this cell is undefined
# (denominator 0, undefined_count 50) there — the honest recording.
# It is excluded from the reference lock; all behavioral metrics must
# still match exactly.
RUN_COMPOSITION_RELATIVE_METRICS = (
    "external_token_reduction_vs_full_history",
)

_PERSONAL_PATH = re.compile(r"/Users/|/home/|C:\\\\Users", re.IGNORECASE)


class Phase11ValidationError(AssertionError):
    pass


def _fail(message: str):
    raise Phase11ValidationError(message)


def _load(path: Path):
    return json.loads(path.read_text())


def _check_no_personal_paths(directory: Path):
    for name in ("cases.jsonl", "aggregate.json"):
        candidate = directory / name
        if candidate.exists() and _PERSONAL_PATH.search(
            candidate.read_text()
        ):
            _fail(f"personal path found in {name}")


def _gate_affected_selection_total(directory: Path) -> int:
    """Sum gate_affected_selection over every per-case record."""
    total = 0
    cases = (directory / "cases.jsonl").read_text()
    for line in cases.split("\n"):
        if not line.strip():
            continue
        record = json.loads(line)
        for holder in (
            record.get("case", {}).get("diagnostics", {}).get(
                "gate_shadow_v1", {}
            ),
            record.get("case", {}).get("extraction", {}) or {},
        ):
            value = holder.get("gate_affected_selection")
            if value is not None:
                total += int(value)
    return total


def _reference_lock(phase11_metrics, historical_metrics, label):
    comparable_phase11 = {
        name: cell
        for name, cell in phase11_metrics.items()
        if name not in RUN_COMPOSITION_RELATIVE_METRICS
    }
    comparable_historical = {
        name: cell
        for name, cell in historical_metrics.items()
        if name not in RUN_COMPOSITION_RELATIVE_METRICS
    }
    if comparable_phase11 != comparable_historical:
        drifted = sorted(
            name
            for name in set(comparable_phase11)
            | set(comparable_historical)
            if comparable_phase11.get(name)
            != comparable_historical.get(name)
        )
        _fail(
            f"{label}: reference does not reproduce Phase 9 "
            f"({len(drifted)} drifting metrics: {drifted[:6]}...)"
        )


def _gate_equivalence(metrics, label):
    fused = metrics.get(FUSED_ID)
    gated = metrics.get(GATE_ID)
    if fused != gated:
        drifted = sorted(
            name
            for name in set(fused or {}) | set(gated or {})
            if (fused or {}).get(name) != (gated or {}).get(name)
        )
        _fail(
            f"{label}: gate-shadow canonical metrics differ from fused "
            f"({drifted[:6]})"
        )


def validate_phase11_lifecycle(path: str) -> None:
    directory = Path(path)
    validate_artifact_dir(directory)
    config = _load(directory / "run_config.json")
    if config.get("run_id") != LIFECYCLE_RUN_ID:
        _fail(f"unexpected run_id {config.get('run_id')!r}")
    if tuple(config.get("systems", ())) != PHASE11_SYSTEMS:
        _fail("run systems do not match the Phase 11 matrix")
    provenance = (directory / "provenance.json").read_text()
    if LIFECYCLE_MANIFEST_HASH not in provenance:
        _fail("frozen lifecycle manifest hash missing from provenance")
    _check_no_personal_paths(directory)

    aggregate = _load(directory / "aggregate.json")
    metrics = aggregate["metrics"]
    for system_id in PHASE11_SYSTEMS:
        if system_id not in metrics:
            _fail(f"missing aggregate metrics for {system_id}")
        for metric_name in LIFECYCLE_MUST_BE_ZERO:
            cell = metrics[system_id].get(metric_name, {})
            if cell.get("numerator", 0) != 0:
                _fail(
                    f"LIFECYCLE SAFETY FAILURE: {system_id} "
                    f"{metric_name} numerator is "
                    f"{cell.get('numerator')} (must be 0)"
                )

    historical = _load(Path(V2_LIFECYCLE_DIR) / "aggregate.json")
    _reference_lock(
        metrics[REFERENCE_ID],
        historical["metrics"][HISTORICAL_FULL_V2],
        "lifecycle",
    )
    _gate_equivalence(metrics, "lifecycle")

    affected = _gate_affected_selection_total(directory)
    if affected != 0:
        _fail(
            f"gate affected_selection total is {affected} (must be 0)"
        )


def validate_phase11_external(path: str) -> None:
    directory = Path(path)
    validate_external_artifact(directory, allowed_systems=PHASE11_SYSTEMS)
    config = _load(directory / "external_run_config.json")
    if config.get("run_id") != EXTERNAL_RUN_ID:
        _fail(f"unexpected run_id {config.get('run_id')!r}")
    if tuple(config.get("systems", ())) != PHASE11_SYSTEMS:
        _fail("run systems do not match the Phase 11 matrix")
    _check_no_personal_paths(directory)

    aggregate = _load(directory / "aggregate.json")
    metrics = aggregate["metrics"]
    for system_id in PHASE11_SYSTEMS:
        if system_id not in metrics:
            _fail(f"missing aggregate metrics for {system_id}")

    historical = _load(Path(V2_EXTERNAL_DIR) / "aggregate.json")
    _reference_lock(
        metrics[REFERENCE_ID],
        historical["metrics"][HISTORICAL_FULL_V2],
        "external",
    )
    _gate_equivalence(metrics, "external")

    affected = _gate_affected_selection_total(directory)
    if affected != 0:
        _fail(
            f"gate affected_selection total is {affected} (must be 0)"
        )


def validate_cross_consistency_phase11(
    lifecycle_dir: str, external_dir: str
) -> None:
    lifecycle = _load(Path(lifecycle_dir) / "provenance.json")
    external = _load(Path(external_dir) / "external_provenance.json")
    lifecycle_commit = lifecycle.get("repository_commit")
    external_commit = external.get("repository_commit")
    if lifecycle_commit != external_commit:
        _fail(
            "lifecycle and external artifacts were generated at "
            f"different commits ({lifecycle_commit} vs {external_commit})"
        )


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        command = argv[0]
        if command == "lifecycle":
            validate_phase11_lifecycle(argv[1])
            print("RESULT: phase11 lifecycle validation passed")
        elif command == "external":
            validate_phase11_external(argv[1])
            print("RESULT: phase11 external validation passed")
        elif command == "consistency":
            validate_cross_consistency_phase11(argv[1], argv[2])
            print("RESULT: phase11 consistency validation passed")
        else:
            print(f"unknown command {command!r}")
            return 2
    except Phase11ValidationError as exc:
        print(f"PHASE11 VALIDATION FAILED: {exc}")
        return 1
    except (IndexError, FileNotFoundError, KeyError) as exc:
        print(f"PHASE11 VALIDATION ERROR: {type(exc).__name__}: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
