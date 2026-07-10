"""Generated-report validation: traceability, consistency, labels,
claims, and tamper detection. Never regenerates the report."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path

from benchmarks.contract import metric as lifecycle_metric
from benchmarks.external.longmemeval.evaluate import external_metric
from benchmarks.reporting.load import (
    REPO_ROOT,
    load_spec,
    report_data_digest,
    spec_hash,
)

REQUIRED_LABEL = "LongMemEval 50-case stratified subset"

# Promotional/unsupported wording forbidden in generated prose.
FORBIDDEN_PHRASES = (
    "state of the art",
    "state-of-the-art",
    "best memory system",
    "world's best",
    "industry-leading",
    "production-ready",
    "guaranteed",
    "saves money",
    "cost savings",
    "cheaper",
    "flawless",
    "universally",
    "leaderboard result",
    "official LongMemEval score of",
)


class ReportValidationError(ValueError):
    pass


def _fail(message: str):
    raise ReportValidationError(message)


def validate_claims_text(body: str) -> None:
    lowered = body.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lowered:
            _fail(f"forbidden claim wording present: {phrase!r}")
    # "zero leakage" style claims require an explicit denominator.
    for match in re.finditer(r"zero leakage", lowered):
        _fail("'zero leakage' wording requires explicit n/d rendering")


def validate_report(report_dir: str | Path) -> dict:
    report_dir = Path(report_dir)
    if not report_dir.is_dir():
        _fail(f"not a directory: {report_dir}")
    if report_dir.name.endswith(".incomplete"):
        _fail("incomplete report artifact")
    spec = load_spec()

    manifest = json.loads(
        (report_dir / "artifact_manifest.json").read_text()
    )
    if manifest["report_spec_hash"] != spec_hash():
        _fail("report spec hash mismatch (spec changed after generation)")
    for name, digest in manifest["files"].items():
        path = report_dir / name
        if not path.exists():
            _fail(f"missing report file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            _fail(f"report file hash mismatch: {name} (manual edit?)")

    data = json.loads((report_dir / "report_data.json").read_text())
    if report_data_digest(data) != manifest["report_data_digest"]:
        _fail("report data digest mismatch")
    if data["sources"]["lifecycle"]["digest"] != (
        spec["sources"]["lifecycle"]["required_digest"]
    ):
        _fail("lifecycle source digest mismatch")
    if data["sources"]["external"]["digest"] != (
        spec["sources"]["external"]["required_digest"]
    ):
        _fail("external source digest mismatch")
    if data["sources"]["external"]["display_label"] != REQUIRED_LABEL:
        _fail("external display label incorrect")
    if "scripted" not in data["flags"]["lifecycle_local_mode"]:
        _fail("local-policy mode mislabeled")

    # Metric identity and source separation.
    for table in data["lifecycle_tables"].values():
        for row in table:
            lifecycle_metric(row["metric"])
    for row in data["external_tables"]["headline"]:
        external_metric(row["metric"])
        try:
            lifecycle_metric(row["metric"])
            _fail(
                f"external table uses a lifecycle metric: {row['metric']}"
            )
        except KeyError:
            pass

    # Recompute displayed lifecycle cells from the raw source artifact.
    lifecycle_aggregate = json.loads(
        (
            REPO_ROOT
            / data["sources"]["lifecycle"]["path"]
            / "aggregate.json"
        ).read_text()
    )
    for table in data["lifecycle_tables"].values():
        for row in table:
            for system, cell in row["cells"].items():
                stored = lifecycle_aggregate["metrics"].get(system, {}).get(
                    row["metric"]
                )
                if stored is None:
                    if cell["denominator"] not in (0, 0.0):
                        _fail(
                            f"{system}/{row['metric']}: report shows data "
                            "absent from the source aggregate"
                        )
                    continue
                if (
                    abs(stored["numerator"] - cell["numerator"]) > 1e-9
                    or abs(stored["denominator"] - cell["denominator"])
                    > 1e-9
                ):
                    _fail(
                        f"{system}/{row['metric']}: report value does not "
                        "match the source aggregate"
                    )
                if cell["denominator"] and "%" not in cell["display"]:
                    _fail(
                        f"{system}/{row['metric']}: defined rate rendered "
                        "without a percentage/denominator display"
                    )
                if not cell["denominator"] and not cell[
                    "display"
                ].startswith("N/A"):
                    _fail(
                        f"{system}/{row['metric']}: undefined value not "
                        "rendered as N/A"
                    )

    # Markdown consistency: hash + required sections + claims scan.
    markdown = (
        REPO_ROOT / spec["outputs"]["report_markdown"]
    ).read_text()
    if (
        hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        != manifest["markdown_sha256"]
    ):
        _fail("docs/benchmark_report.md does not match the generated hash")
    validate_claims_text(markdown)
    for required in (
        REQUIRED_LABEL,
        "## 15. Reproduction",
        "## 14. Limitations",
        "scripted-plus-fallback",
        "not an official LongMemEval score",
    ):
        if required not in markdown:
            _fail(f"report missing required content: {required!r}")

    # README consistency: the injected section must match report data.
    from benchmarks.reporting.cli import README_BEGIN, README_END
    from benchmarks.reporting.render import render_readme_section

    readme = (REPO_ROOT / "README.md").read_text()
    if README_BEGIN not in readme:
        _fail("README benchmark evidence markers missing")
    section = readme[
        readme.index(README_BEGIN) + len(README_BEGIN) : readme.index(
            README_END
        )
    ].strip()
    expected = render_readme_section(
        data, spec["systems"]["display"]
    ).strip()
    if section != expected:
        _fail("README benchmark section does not match report data")
    validate_claims_text(section)

    # CSV consistency: parse and spot-verify every numeric row.
    for name in spec["outputs"]["csv_files"]:
        body = (report_dir / name).read_text()
        rows = list(csv.DictReader(io.StringIO(body)))
        if name == "lifecycle_headline.csv":
            index = {
                (row["metric"], system): cell
                for table in ("correctness", "retrieval_downstream")
                for row in data["lifecycle_tables"][table]
                for system, cell in row["cells"].items()
            }
            for entry in rows:
                cell = index[(entry["metric"], entry["system"])]
                if abs(float(entry["numerator"]) - cell["numerator"]) > 1e-9:
                    _fail(f"CSV mismatch in {name}: {entry['metric']}")

    # Safety scan on generated prose and data.
    for name in ("report_data.json", "README.md"):
        body = (report_dir / name).read_text()
        for marker in ("/Users/", "/home/", "api_key"):
            if marker in body:
                _fail(f"{name} contains unsafe marker {marker!r}")

    return {"report_data_digest": manifest["report_data_digest"]}
