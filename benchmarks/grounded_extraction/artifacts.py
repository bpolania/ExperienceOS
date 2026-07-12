"""Deterministic artifact writing and validation for the benchmark.

Writes the three committed result directories with a stable file set, a
per-file sha256 manifest, and a latency-excluded normalized digest,
reusing the established serialization and digest helpers. Overwrite
protection refuses to clobber an existing directory whose content
differs; a clean regeneration into a temporary directory supports the
two-run digest-equality check.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from benchmarks.artifacts.writer import normalized_digest
from benchmarks.contract.serialization import canonical_json, stable_dump

ARTIFACT_SCHEMA_VERSION = "1"


class OverwriteError(RuntimeError):
    """Refusing to overwrite an existing committed directory."""


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, data) -> None:
    path.write_text(stable_dump(data))


def _write_jsonl(path: Path, rows) -> None:
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows))


def _write_text(path: Path, text: str) -> None:
    path.write_text(text if text.endswith("\n") else text + "\n")


def _digest_payload(result):
    """The normalized-digest input: behavior only, latency excluded."""
    return normalized_digest(
        result["per_case"],
        {
            "aggregates": result["aggregates"],
            "grounding_ablation": result["grounding_ablation"],
            "lifecycle_ablation": result["lifecycle_ablation"],
            "fixture_smoke": result["fixture_smoke"],
            "optional_runs": result["optional_runs"],
            "external": result["external"],
            "gates": result.get("gates"),
        },
    )


def _manifest(directory: Path, files, digest) -> dict:
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "files": {
            name: {"sha256": _file_sha256(directory / name)}
            for name in sorted(files)
        },
        "normalized_result_digest": digest,
    }


def _guard(directory: Path, manifest: dict, overwrite: bool) -> None:
    existing = directory / "artifact_manifest.json"
    if directory.exists() and existing.exists() and not overwrite:
        import json
        prior = json.loads(existing.read_text())
        if prior.get("normalized_result_digest") == manifest[
                "normalized_result_digest"]:
            return  # identical content — idempotent
        raise OverwriteError(
            f"{directory} exists with a different digest; pass overwrite=True "
            "only after reconciling")


def write_ablation_dir(result, output: Path, overwrite=False) -> str:
    """Write the lifecycle extraction + ablation directory."""
    output.mkdir(parents=True, exist_ok=True)
    digest = _digest_payload(result)
    _write_json(output / "run_config.json", {
        "run_schema_version": result["run_schema_version"],
        "dataset_id": result["dataset_id"],
        "systems": result["systems"],
        "system_config_digests": {
            a["system_id"]: a["system_config_digest"]
            for a in result["aggregates"]},
    })
    _write_jsonl(output / "cases.jsonl", result["per_case"])
    _write_json(output / "aggregates.json", result["aggregates"])
    _write_json(output / "ablation_grounding.json",
                result["grounding_ablation"])
    _write_json(output / "ablation_lifecycle.json",
                result["lifecycle_ablation"])
    _write_json(output / "fixture_smoke.json", result["fixture_smoke"])
    _write_json(output / "optional_runs.json", result["optional_runs"])
    _write_text(output / "README.md", _ablation_readme(result, digest))
    files = [
        "run_config.json", "cases.jsonl", "aggregates.json",
        "ablation_grounding.json", "ablation_lifecycle.json",
        "fixture_smoke.json", "optional_runs.json", "README.md",
    ]
    manifest = _manifest(output, files, digest)
    _guard(output, manifest, overwrite)
    _write_json(output / "artifact_manifest.json", manifest)
    return digest


def write_external_dir(result, output: Path, overwrite=False) -> str:
    """Write the external classification directory."""
    output.mkdir(parents=True, exist_ok=True)
    ext = result["external"]
    digest = _digest_payload(result)
    summary = {k: v for k, v in ext.items() if k != "cases"}
    _write_json(output / "external_classification.json", summary)
    _write_jsonl(output / "external_cases.jsonl", ext["cases"])
    _write_text(output / "README.md", _external_readme(ext))
    files = ["external_classification.json", "external_cases.jsonl",
             "README.md"]
    manifest = _manifest(output, files, digest)
    _guard(output, manifest, overwrite)
    _write_json(output / "artifact_manifest.json", manifest)
    return digest


def write_report_dir(result, report_data, comparison_md, comparison_csv,
                     output: Path, overwrite=False) -> str:
    """Write the report data, comparison tables, and gate directory."""
    output.mkdir(parents=True, exist_ok=True)
    digest = _digest_payload(result)
    _write_json(output / "report_data.json", report_data)
    _write_json(output / "adoption_gates.json", result["gates"])
    _write_text(output / "comparison_table.md", comparison_md)
    _write_text(output / "comparison_table.csv", comparison_csv)
    _write_text(output / "README.md", _report_readme(digest))
    files = ["report_data.json", "adoption_gates.json",
             "comparison_table.md", "comparison_table.csv", "README.md"]
    manifest = _manifest(output, files, digest)
    _guard(output, manifest, overwrite)
    _write_json(output / "report_manifest.json", manifest)
    return digest


def validate_dir(output: Path) -> dict:
    """Re-validate a committed directory's manifest against disk."""
    import json
    manifest_name = ("report_manifest.json"
                     if (output / "report_manifest.json").exists()
                     else "artifact_manifest.json")
    manifest = json.loads((output / manifest_name).read_text())
    for name, meta in manifest["files"].items():
        actual = _file_sha256(output / name)
        if actual != meta["sha256"]:
            raise ValueError(f"{output/name}: sha256 mismatch")
    return manifest


def _ablation_readme(result, digest) -> str:
    aggs = {a["system_id"]: a for a in result["aggregates"]}
    grd = aggs.get("experienceos_grounded_rules_v1", {})
    cm = grd.get("creation_metrics", {})
    return (
        "# Grounded Extraction Ablation Evidence\n\n"
        "Frozen lifecycle runs for the grounded-extraction systems. "
        "Primary extraction aggregates are computed here on the "
        "`experienceos-lifecycle-v1` annotations; the external subset is "
        "classified separately. Development fixtures appear only as a "
        "smoke section and are never mixed into these aggregates.\n\n"
        f"Normalized result digest: `{digest}`\n\n"
        "Systems: canonical reference (grounded extraction disabled) and "
        "deterministic grounded extraction (benchmark-only adopted, "
        "isolated state). No controller is adopted; no default behavior "
        "changes.\n\n"
        "Latency fields are excluded from the digest per the established "
        "convention.\n")


def _external_readme(ext) -> str:
    return (
        "# Grounded Extraction External Classification\n\n"
        "Classification-only view of the "
        "`longmemeval-50-subset-v1` questions for the grounded-extraction "
        "benchmark. The frozen external artifacts retain only "
        "digests/previews of source text, so no exact single-message "
        "extraction oracle can be built; every case is classification-only "
        "and excluded from the primary extraction aggregates. This is not "
        "an official LongMemEval score.\n\n"
        f"Total cases: {ext['total_cases']}. "
        f"Classification counts: {ext['classification_counts']}.\n")


def _report_readme(digest) -> str:
    return (
        "# Grounded Extraction Report Data\n\n"
        "Digest-locked report data, comparison tables, and adoption-gate "
        "evaluation for the grounded-extraction benchmark. See "
        "`docs/grounded_extraction_report.md` for the human-readable "
        "report.\n\n"
        f"Normalized result digest: `{digest}`\n")
