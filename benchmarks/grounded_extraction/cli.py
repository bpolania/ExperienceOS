"""Command-line entry for the grounded-extraction benchmark.

Commands:
  run [--output DIR] [--overwrite]   generate the three committed dirs
  validate DIR                        re-verify manifests + digests
  report                              (re)write docs/grounded_extraction_report.md
  smoke                               quick in-memory run, no writes
  consistency DIR_A DIR_B             two-run digest equality check

The default run is fully offline and deterministic: no provider beyond
the mock, no model, no credentials, no network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmarks.grounded_extraction.annotations import REPO_ROOT
from benchmarks.grounded_extraction.artifacts import (
    validate_dir,
    write_ablation_dir,
    write_external_dir,
    write_report_dir,
)
from benchmarks.grounded_extraction.report import (
    build_report_data,
    comparison_csv,
    comparison_markdown,
    render_report,
)
from benchmarks.grounded_extraction.runner import run_all

ABLATION_DIR = "grounded-extraction-ablation"
EXTERNAL_DIR = "grounded-extraction"
REPORT_DIR = "report-grounded-extraction"
REPORT_DOC = REPO_ROOT / "docs/grounded_extraction_report.md"


def _write_all(output: Path, overwrite: bool):
    result = run_all()
    report_data = build_report_data(result)
    digest_a = write_ablation_dir(
        result, output / ABLATION_DIR, overwrite=overwrite)
    digest_e = write_external_dir(
        result, output / EXTERNAL_DIR, overwrite=overwrite)
    digest_r = write_report_dir(
        result, report_data, comparison_markdown(result),
        comparison_csv(result), output / REPORT_DIR, overwrite=overwrite)
    return result, (digest_a, digest_e, digest_r)


def cmd_run(args):
    output = Path(args.output)
    result, digests = _write_all(output, args.overwrite)
    REPORT_DOC.write_text(render_report(result))
    print(f"ablation dir: {output / ABLATION_DIR}")
    print(f"external dir: {output / EXTERNAL_DIR}")
    print(f"report dir:   {output / REPORT_DIR}")
    print(f"report doc:   {REPORT_DOC}")
    print(f"digests: {digests[0]}")
    print("RESULT: grounded extraction benchmark generated")
    return 0


def cmd_validate(args):
    root = Path(args.directory)
    for name in (ABLATION_DIR, EXTERNAL_DIR, REPORT_DIR):
        directory = root / name if (root / name).exists() else root
        manifest = validate_dir(directory)
        print(f"{directory}: digest "
              f"{manifest['normalized_result_digest'][:16]}… OK")
        if directory == root:
            break
    print("RESULT: grounded extraction artifact validation passed")
    return 0


def cmd_report(args):
    result = run_all()
    REPORT_DOC.write_text(render_report(result))
    print(f"wrote {REPORT_DOC}")
    print("RESULT: grounded extraction report regenerated")
    return 0


def cmd_smoke(args):
    result = run_all()
    grd = next(a for a in result["aggregates"]
               if a["system_id"].endswith("rules_v1"))
    print("proposal recall:",
          grd["creation_metrics"]["recall"])
    print("durable creation recall:",
          grd["creation_metrics"]["durable_creation_recall"])
    print("duplicate active memories:",
          grd["safety_metrics"]["duplicate_active_memories"])
    print("gates passed:",
          f"{result['gates']['passed']}/{result['gates']['gate_count']}")
    print("RESULT: grounded extraction smoke passed")
    return 0


def cmd_consistency(args):
    from benchmarks.grounded_extraction.artifacts import validate_dir as vd
    a = vd(Path(args.dir_a))
    b = vd(Path(args.dir_b))
    da = a["normalized_result_digest"]
    db = b["normalized_result_digest"]
    print(f"digest A: {da}")
    print(f"digest B: {db}")
    if da != db:
        print("RESULT: digests differ")
        return 1
    print("RESULT: grounded extraction consistency validation passed")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="benchmarks.grounded_extraction.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="generate committed artifacts")
    run.add_argument(
        "--output",
        default=str(REPO_ROOT / "benchmarks/results/committed"))
    run.add_argument("--overwrite", action="store_true")
    run.set_defaults(func=cmd_run)

    validate = sub.add_parser("validate", help="re-verify a directory")
    validate.add_argument("directory")
    validate.set_defaults(func=cmd_validate)

    report = sub.add_parser("report", help="regenerate the report doc")
    report.set_defaults(func=cmd_report)

    smoke = sub.add_parser("smoke", help="in-memory run, no writes")
    smoke.set_defaults(func=cmd_smoke)

    cons = sub.add_parser("consistency", help="two-run digest equality")
    cons.add_argument("dir_a")
    cons.add_argument("dir_b")
    cons.set_defaults(func=cmd_consistency)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
