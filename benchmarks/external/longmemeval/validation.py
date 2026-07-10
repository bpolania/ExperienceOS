"""External artifact validation. Never reruns systems."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmarks.external.longmemeval.evaluate import external_metric
from benchmarks.external.longmemeval.runner import (
    ARTIFACT_FILES,
    EXTERNAL_SYSTEMS,
)
from benchmarks.external.longmemeval.schema import REQUIRED_DISPLAY_LABEL

REQUIRED_FILES = (*ARTIFACT_FILES, "artifact_manifest.json", "README.md")

# Secret-like markers are forbidden everywhere. Personal-path markers
# are forbidden in METADATA files only: official conversation CONTENT
# may legitimately mention paths like /home/... — that is dataset
# content, not an operator-path leak.
import re as _re

# Token-shaped patterns, not bare substrings ("risk-" must not trip).
SECRET_PATTERNS = tuple(
    _re.compile(p)
    for p in (
        r"api_key",
        r"\bsk-[A-Za-z0-9]{16,}",
        r"\bhf_[A-Za-z0-9]{16,}",
        r"Authorization: Bearer",
    )
)
PATH_MARKERS = ("/Users/", "/home/", "\\Users\\")
METADATA_FILES = (
    "external_run_config.json",
    "external_provenance.json",
    "external_manifest.json",
    "aggregate.json",
    "artifact_manifest.json",
    "failures.json",
    "README.md",
)


class ExternalArtifactError(ValueError):
    pass


def _jsonl_lines(path: Path) -> list[str]:
    """JSONL is newline-delimited ONLY: never use splitlines(), which
    also splits on U+2028/U+2029 that official chat content contains
    inside JSON strings."""
    return [
        line for line in path.read_text().split("\n") if line.strip()
    ]


def _fail(message: str):
    raise ExternalArtifactError(message)


def validate_external_artifact(
    path: str | Path, allow_staging: bool = False
) -> dict:
    path = Path(path)
    if not path.is_dir():
        _fail(f"not a directory: {path}")
    if path.name.endswith(".incomplete") and not allow_staging:
        _fail("incomplete external artifact cannot be canonical")
    for name in REQUIRED_FILES:
        if not (path / name).exists():
            _fail(f"missing required external file: {name}")

    artifact_manifest = json.loads(
        (path / "artifact_manifest.json").read_text()
    )
    if artifact_manifest["display_label"] != REQUIRED_DISPLAY_LABEL:
        _fail(
            "external artifact must use the exact display label "
            f"{REQUIRED_DISPLAY_LABEL!r}"
        )
    for name, info in artifact_manifest["files"].items():
        actual = hashlib.sha256((path / name).read_bytes()).hexdigest()
        if actual != info["sha256"]:
            _fail(f"file hash mismatch for {name}")

    subset_manifest = json.loads(
        (path / "external_manifest.json").read_text()
    )
    selected_ids = [e["question_id"] for e in subset_manifest["selected"]]
    provenance = json.loads(
        (path / "external_provenance.json").read_text()
    )
    if provenance["subset_manifest_hash"] != subset_manifest["manifest_hash"]:
        _fail("provenance subset hash does not match embedded manifest")

    cases = [
        json.loads(line)
        for line in _jsonl_lines(path / "cases.jsonl")
    ]
    if artifact_manifest["case_run_count"] != len(cases):
        _fail("case_run_count mismatch")
    synthetic = artifact_manifest["synthetic_data"]
    if synthetic and "committed" in str(path.resolve()) and (
        "fixture" not in path.name
    ):
        _fail(
            "synthetic fixture output cannot be promoted as a canonical "
            "committed subset artifact"
        )
    for record in cases:
        if record["system_id"] not in EXTERNAL_SYSTEMS:
            _fail(f"unknown external system {record['system_id']!r}")
        if not synthetic and record["question_id"] not in selected_ids:
            _fail(
                f"case {record['question_id']!r} is not in the committed "
                "subset manifest"
            )
        if record["question_id"].startswith(
            ("creation_", "updates_", "forgetting_", "retrieval_",
             "context_", "containment_")
        ):
            _fail(
                "custom lifecycle scenario record found in external "
                f"artifact: {record['question_id']}"
            )

    contributions = [
        json.loads(line)
        for line in _jsonl_lines(path / "metric_contributions.jsonl")
    ]
    for contribution in contributions:
        definition = external_metric(contribution["metric"])
        if contribution["proxy"] != definition.proxy:
            _fail(
                f"proxy label mismatch for {contribution['metric']}"
            )

    aggregate = json.loads((path / "aggregate.json").read_text())
    if aggregate.get("official_evaluation") is not False:
        _fail("external aggregate must declare official_evaluation false")
    _recompute(aggregate, contributions)

    for name in REQUIRED_FILES:
        body = (path / name).read_text()
        for pattern in SECRET_PATTERNS:
            if pattern.search(body):
                _fail(
                    f"{name} contains secret-like content "
                    f"({pattern.pattern})"
                )
        if name in METADATA_FILES:
            for marker in PATH_MARKERS:
                if marker in body:
                    _fail(
                        f"{name} contains personal path marker {marker!r}"
                    )

    from benchmarks.external.longmemeval.runner import _normalized_digest

    digest = _normalized_digest(cases, aggregate)
    if digest != artifact_manifest["normalized_result_digest"]:
        _fail("normalized external digest mismatch")
    return {
        "case_runs": len(cases),
        "contributions": len(contributions),
        "synthetic_data": synthetic,
        "normalized_result_digest": digest,
    }


def _recompute(aggregate, contributions) -> None:
    sums: dict = {}
    for c in contributions:
        if not c["applicable"]:
            continue
        cell = sums.setdefault(c["system_id"], {}).setdefault(
            c["metric"], [0.0, 0.0]
        )
        cell[0] += c["numerator"]
        cell[1] += c["denominator"]
    for system, cells in sums.items():
        for name, (num, den) in cells.items():
            stored = aggregate["metrics"].get(system, {}).get(name)
            if stored is None:
                _fail(f"aggregate missing {system}/{name}")
            if (
                abs(stored["numerator"] - num) > 1e-9
                or abs(stored["denominator"] - den) > 1e-9
            ):
                _fail(
                    f"external aggregate recomputation mismatch for "
                    f"{system}/{name}"
                )


def main(argv=None) -> int:
    import sys

    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(
            "usage: python -m benchmarks.external.longmemeval.validation "
            "<result-dir>"
        )
        return 2
    try:
        summary = validate_external_artifact(Path(argv[0]))
    except ExternalArtifactError as exc:
        print(f"EXTERNAL ARTIFACT INVALID: {exc}")
        return 1
    print(f"case runs: {summary['case_runs']}")
    print(f"metric contributions: {summary['contributions']}")
    print(f"synthetic data: {summary['synthetic_data']}")
    print(f"normalized digest: {summary['normalized_result_digest']}")
    print("aggregate recomputation: matched")
    print("RESULT: external artifact validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
