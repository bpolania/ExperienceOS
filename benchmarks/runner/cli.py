"""Benchmark runner CLI.

    PYTHONPATH=. python -m benchmarks.runner.cli run --profile quick \
        --output benchmarks/results/local/quick
    PYTHONPATH=. python -m benchmarks.runner.cli run --profile full-offline \
        --output benchmarks/results/local/full
    PYTHONPATH=. python -m benchmarks.runner.cli validate <result-dir>

Exit codes: nonzero only for execution or artifact-integrity
failures — never because a system scored poorly.
"""

from __future__ import annotations

import argparse

from benchmarks.artifacts.validation import main as validate_main
from benchmarks.artifacts.writer import write_artifacts
from benchmarks.runner.config import PROFILES, profile_config
from benchmarks.runner.execute import execute_run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--profile", choices=PROFILES, required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--overwrite", action="store_true")
    run_parser.add_argument("--run-id")
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("result_dir")
    args = parser.parse_args(argv)

    if args.command == "validate":
        return validate_main([args.result_dir])

    overrides = {"overwrite": args.overwrite}
    if args.run_id:
        overrides["run_id"] = args.run_id
    config = profile_config(args.profile, args.output, **overrides)
    output = execute_run(config)
    artifact_dir = write_artifacts(output)

    outcomes: dict = {}
    for entry in output.execution_order:
        outcomes[entry["outcome"]] = outcomes.get(entry["outcome"], 0) + 1
    execution_failures = len(
        output.failures.get("system_execution_failures", [])
    ) + len(output.failures.get("evaluator_failures", []))

    print(f"profile: {config.profile}")
    print(f"systems: {len(config.systems)}")
    print(f"case-system runs: {len(output.execution_order)}")
    print(f"outcomes: {dict(sorted(outcomes.items()))}")
    print(f"execution/evaluator failures: {execution_failures}")
    print(f"artifacts: {artifact_dir}")
    print("network access used: no")
    print("real provider used: no")
    print("real local model used: no")
    if execution_failures:
        print("RESULT: BENCHMARK RUN HAD EXECUTION FAILURES")
        return 1
    print(
        "RESULT: benchmark run completed (raw evidence only — low scores "
        "are results, not failures)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
