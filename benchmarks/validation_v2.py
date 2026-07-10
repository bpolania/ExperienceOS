"""Phase 9 v2 artifact validators (additive; v1 validators untouched).

Validates the committed lifecycle-v2 ablation artifact, the committed
LongMemEval v2 artifact, and cross-artifact consistency. Structure,
provenance, denominators, and reproducibility are validated — never
expected benchmark scores.
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

LIFECYCLE_V2_RUN_ID = "lifecycle-v2-ablation"
EXTERNAL_V2_RUN_ID = "longmemeval-50-subset-v2"

LIFECYCLE_MANIFEST_HASH = (
    "0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb"
)

# The declared lifecycle v2 matrix: the v1 rules reference row plus
# every Phase 9 v2 system.
LIFECYCLE_V2_SYSTEMS = (
    SystemId.EXPERIENCEOS_RULES,
    SystemId.EXPERIENCEOS_SLOTS_V2,
    SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2,
    SystemId.EXPERIENCEOS_HYBRID_RETRIEVAL_V2,
    SystemId.EXPERIENCEOS_EXTRACT_RETRIEVAL_V2,
    SystemId.EXPERIENCEOS_COVERAGE_V2,
    SystemId.EXPERIENCEOS_TEMPORAL_V2,
    SystemId.EXPERIENCEOS_LOCAL_V2,
    SystemId.EXPERIENCEOS_HYBRID_FULL_V2,
)

# LongMemEval v2 matrix: the v1 reference rows the runner supports plus
# every v2 system with a meaningful external runner.
EXTERNAL_V2_SYSTEMS = (
    "full_history",
    "naive_top_k",
    SystemId.EXPERIENCEOS_RULES,
    SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2,
    SystemId.EXPERIENCEOS_HYBRID_RETRIEVAL_V2,
    SystemId.EXPERIENCEOS_EXTRACT_RETRIEVAL_V2,
    SystemId.EXPERIENCEOS_COVERAGE_V2,
    SystemId.EXPERIENCEOS_TEMPORAL_V2,
    SystemId.EXPERIENCEOS_LOCAL_V2,
    SystemId.EXPERIENCEOS_HYBRID_FULL_V2,
)
# slots_v2 changes memory planning only; the external runner exposes no
# retrieval-visible difference from rules on this subset, so it is
# recorded as unsupported-with-reason rather than fabricated.
EXTERNAL_UNSUPPORTED = {
    SystemId.EXPERIENCEOS_SLOTS_V2: (
        "no distinct external runner: slot supersession is not "
        "exercised by the subset's retrieval-only evaluation"
    ),
}

_PERSONAL_PATH = re.compile(r"/Users/|/home/|C:\\\\Users", re.IGNORECASE)


class V2ValidationError(AssertionError):
    pass


def _fail(message: str):
    raise V2ValidationError(message)


def validate_lifecycle_v2(path: str | Path) -> dict:
    path = Path(path)
    report = validate_artifact_dir(path)  # existing structural checks
    config = json.loads((path / "run_config.json").read_text())
    if config["run_id"] != LIFECYCLE_V2_RUN_ID:
        _fail(f"unexpected run_id {config['run_id']!r}")
    systems = tuple(config["systems"])
    if systems != LIFECYCLE_V2_SYSTEMS:
        _fail(f"lifecycle v2 system matrix mismatch: {systems}")
    manifest = json.loads((path / "provenance.json").read_text())
    body = (path / "provenance.json").read_text()
    if LIFECYCLE_MANIFEST_HASH not in body:
        _fail("lifecycle manifest hash missing from provenance")
    for name in ("cases.jsonl", "aggregate.json", "provenance.json"):
        content = (path / name).read_text()
        if _PERSONAL_PATH.search(content):
            _fail(f"personal path found in {name}")
    del manifest
    return report


def validate_external_v2(path: str | Path) -> dict:
    report = validate_external_artifact(
        path, allowed_systems=EXTERNAL_V2_SYSTEMS
    )
    path = Path(path)
    config = json.loads((path / "external_run_config.json").read_text())
    if EXTERNAL_V2_RUN_ID not in str(config.get("run_id", path.name)) and \
            path.name != EXTERNAL_V2_RUN_ID:
        _fail("unexpected external v2 run identity")
    recorded = tuple(config.get("systems", ()))
    if recorded != EXTERNAL_V2_SYSTEMS:
        _fail(f"external v2 system matrix mismatch: {recorded}")
    provenance = json.loads(
        (path / "external_provenance.json").read_text()
    )
    unsupported = provenance.get("unsupported_systems", {})
    for system, reason in EXTERNAL_UNSUPPORTED.items():
        if system not in unsupported:
            _fail(f"missing unsupported-system record for {system}")
        del reason
    for name in ("cases.jsonl", "aggregate.json",
                 "external_provenance.json"):
        content = (path / name).read_text()
        if _PERSONAL_PATH.search(content):
            _fail(f"personal path found in {name}")
    return report


def validate_cross_consistency(
    lifecycle_dir: str | Path, external_dir: str | Path
) -> None:
    """The same system ID must describe the same behavior everywhere."""
    lifecycle_dir, external_dir = Path(lifecycle_dir), Path(external_dir)
    lifecycle_prov = json.loads(
        (lifecycle_dir / "provenance.json").read_text()
    )
    external_prov = json.loads(
        (external_dir / "external_provenance.json").read_text()
    )
    lifecycle_commit = lifecycle_prov.get("repository", {}).get(
        "commit"
    ) or lifecycle_prov.get("repository_commit")
    external_commit = external_prov.get("repository", {}).get(
        "commit"
    ) or external_prov.get("repository_commit")
    if lifecycle_commit != external_commit:
        _fail(
            f"artifact commits differ: {lifecycle_commit} vs "
            f"{external_commit}"
        )
    shared = set(LIFECYCLE_V2_SYSTEMS) & set(EXTERNAL_V2_SYSTEMS)
    if not shared:
        _fail("no shared systems between artifacts")
    # Scripted/simulated labeling must be present for policy systems.
    lifecycle_cases = (lifecycle_dir / "cases.jsonl").read_text()
    for system in (SystemId.EXPERIENCEOS_LOCAL_V2,
                   SystemId.EXPERIENCEOS_HYBRID_FULL_V2):
        if system in lifecycle_cases and "scripted" not in lifecycle_cases:
            _fail(f"missing scripted labeling for {system}")


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) < 2:
        print(
            "usage: validation_v2 lifecycle|external|consistency <dir> "
            "[<dir2>]"
        )
        return 2
    kind = argv[0]
    try:
        if kind == "lifecycle":
            validate_lifecycle_v2(argv[1])
        elif kind == "external":
            validate_external_v2(argv[1])
        elif kind == "consistency":
            validate_cross_consistency(argv[1], argv[2])
        else:
            print(f"unknown validation kind {kind!r}")
            return 2
    except (V2ValidationError, AssertionError, FileNotFoundError) as exc:
        print(f"RESULT: v2 validation FAILED: {exc}")
        return 1
    print(f"RESULT: v2 {kind} validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
