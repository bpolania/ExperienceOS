"""Report generation and validation CLI.

    python -m benchmarks.reporting.cli generate [--overwrite]
    python -m benchmarks.reporting.cli validate <report-dir>

Generation validates both source artifacts, verifies required
digests, builds report_data.json, renders Markdown/CSVs, injects the
README section between markers, validates claims, and writes
atomically. It never reruns benchmark systems and needs no network,
credentials, or model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from benchmarks.contract import canonical_json, stable_dump
from benchmarks.reporting.build import build_report_data
from benchmarks.reporting.load import (
    REPO_ROOT,
    load_sources,
    load_spec,
    report_data_digest,
    spec_hash,
)
from benchmarks.reporting.render import (
    render_csvs,
    render_markdown,
    render_readme_section,
)

README_BEGIN = "<!-- benchmark-evidence:begin (generated; do not edit) -->"
README_END = "<!-- benchmark-evidence:end -->"


def _commit_state():
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        clean = not subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return commit, clean
    except Exception:  # noqa: BLE001
        return "unknown", False


def generate(overwrite: bool = False, timestamp: str | None = None) -> Path:
    spec = load_spec()
    sources = load_sources(spec)
    commit, clean = _commit_state()
    data = build_report_data(spec, sources, commit, clean)
    data["report_spec_hash"] = spec_hash()
    data["generated_at_utc"] = timestamp or time.strftime(
        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
    )
    data["report_data_digest"] = report_data_digest(data)

    from benchmarks.reporting.validation import validate_claims_text

    markdown = render_markdown(data, spec)
    readme_section = render_readme_section(data, spec["systems"]["display"])
    validate_claims_text(markdown)
    validate_claims_text(readme_section)

    artifact_dir = REPO_ROOT / spec["outputs"]["artifact_dir"]
    if artifact_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"report artifact exists: {artifact_dir} (use --overwrite)"
            )
        shutil.rmtree(artifact_dir)
    staging = artifact_dir.parent / (artifact_dir.name + ".incomplete")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    shutil.copy(
        Path(__file__).resolve().parent / "report_spec.json",
        staging / "report_spec.json",
    )
    (staging / "report_data.json").write_text(
        stable_dump(data), encoding="utf-8"
    )
    for name, body in render_csvs(data).items():
        (staging / name).write_text(body, encoding="utf-8")

    files = {}
    for path in sorted(staging.iterdir()):
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    markdown_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    manifest = {
        "report_version": data["report_version"],
        "report_spec_hash": data["report_spec_hash"],
        "report_data_digest": data["report_data_digest"],
        "markdown_sha256": markdown_hash,
        "files": files,
        "sources": data["sources"],
        "generating_commit": commit,
        "working_tree_clean": clean,
    }
    (staging / "artifact_manifest.json").write_text(
        stable_dump(manifest), encoding="utf-8"
    )
    (staging / "README.md").write_text(
        f"""# Benchmark report artifact ({data['report_version']})

Generated from the two committed raw artifacts (paths and digests in
`artifact_manifest.json`) by `./scripts/run_benchmarks.sh report` at
commit `{commit}`. No benchmark systems were rerun. Generated files
must not be edited manually — `validate-report` detects edits. The
Markdown report lives at `docs/benchmark_report.md`. Custom lifecycle
and LongMemEval evidence stay separate; the external artifact is the
LongMemEval 50-case stratified subset, not an official score; the
local policy mode is scripted-plus-fallback, not a real GGUF run.
""",
        encoding="utf-8",
    )
    staging.replace(artifact_dir)

    report_path = REPO_ROOT / spec["outputs"]["report_markdown"]
    report_path.write_text(markdown, encoding="utf-8")
    _inject_readme(readme_section)

    from benchmarks.reporting.validation import validate_report

    validate_report(artifact_dir)
    print(f"report artifact: {artifact_dir}")
    print(f"markdown report: {report_path}")
    print(f"report data digest: {data['report_data_digest']}")
    print(f"lifecycle source digest: {data['sources']['lifecycle']['digest']}")
    print(f"external source digest: {data['sources']['external']['digest']}")
    print("systems rerun: no · network: no · provider: no · model: no")
    return artifact_dir


def _inject_readme(section: str) -> None:
    readme_path = REPO_ROOT / "README.md"
    body = readme_path.read_text()
    block = f"{README_BEGIN}\n{section}\n{README_END}"
    if README_BEGIN in body:
        start = body.index(README_BEGIN)
        end = body.index(README_END) + len(README_END)
        body = body[:start] + block + body[end:]
    else:
        marker = "## Benchmarking (Phase 8, in progress)"
        if marker in body:
            body = body.replace(marker, f"{block}\n\n{marker}", 1)
        else:
            body += "\n\n" + block + "\n"
    readme_path.write_text(body, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--overwrite", action="store_true")
    val = sub.add_parser("validate")
    val.add_argument("report_dir")
    args = parser.parse_args(argv)

    if args.command == "generate":
        try:
            generate(overwrite=args.overwrite)
        except FileExistsError as exc:
            print(f"REFUSING TO OVERWRITE: {exc}")
            return 1
        print("RESULT: report generated and validated")
        return 0

    from benchmarks.reporting.validation import (
        ReportValidationError,
        validate_report,
    )

    try:
        summary = validate_report(Path(args.report_dir))
    except ReportValidationError as exc:
        print(f"REPORT INVALID: {exc}")
        return 1
    print(f"report data digest: {summary['report_data_digest']}")
    print("README consistency: matched")
    print("claims validation: passed")
    print("RESULT: report validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
