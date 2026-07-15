"""Command-line entry for the transition benchmark.

Commands:
  run        generate the committed transition-verification artifacts
  ablation   generate the committed transition-ablation artifacts
  report     generate report data and docs/transition_verification_report.md
  validate   re-verify a committed directory's manifest and digests
  smoke      bounded offline check of systems, gates, and safety
  repeat     run twice and prove deterministic content is identical

Offline and deterministic by default: mock provider only, no model, no
credentials, no network, and no change to any runtime default.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.transition_benchmark import artifacts as artifact_module
from benchmarks.transition_benchmark import report as report_module
from benchmarks.transition_benchmark.runner import evaluate, run


def _run_all():
    data = run(include_ablations=True)
    gates = evaluate(data)
    return data, gates


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="transition-benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("ablation")
    sub.add_parser("report")
    validate = sub.add_parser("validate")
    validate.add_argument("directory")
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--json", action="store_true")
    sub.add_parser("repeat")
    args = parser.parse_args(argv)

    if args.command == "validate":
        artifact_module.validate(Path(args.directory))
        print(f"RESULT: {args.directory} artifact validation passed")
        return 0

    if args.command == "repeat":
        first, _ = _run_all()
        second, _ = _run_all()
        a = artifact_module._digest(
            {"cases": first["per_case"], "aggregate": first["systems"]}
        )
        b = artifact_module._digest(
            {"cases": second["per_case"], "aggregate": second["systems"]}
        )
        if a != b:
            print("RESULT: transition benchmark is NOT deterministic")
            return 1
        print(f"RESULT: two runs produced identical content ({a[:16]})")
        return 0

    data, gates = _run_all()

    if args.command == "run":
        path = artifact_module.write_verification(data, gates)
        artifact_module.validate(path)
        print(f"RESULT: wrote and validated {path}")
        return 0
    if args.command == "ablation":
        path = artifact_module.write_ablation(data)
        artifact_module.validate(path)
        print(f"RESULT: wrote and validated {path}")
        return 0
    if args.command == "report":
        path = report_module.write(data, gates)
        artifact_module.validate(path)
        print(f"RESULT: wrote and validated {path}")
        print(f"RESULT: wrote {report_module.REPORT_PATH}")
        return 0

    # smoke
    summary = {
        "systems": len(data["system_specs"]),
        "optional_unavailable": len(data["optional_systems"]),
        "historical_cases": data["partitions"]["historical_scored"]["records"],
        "development_cases": data["partitions"]["development_fixtures"]["records"],
        "gates_passed": gates["passed"],
        "gates_failed": gates["failed"],
        "gates_inconclusive": gates["inconclusive"],
        "classification": gates["classification"],
        "safety": data["safety"],
        "authorization": data["authorization"],
        "ablations": data["ablations"]["count"],
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print("transition benchmark smoke (offline; default mode unchanged)")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
