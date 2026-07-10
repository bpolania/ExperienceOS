"""External benchmark CLI.

    python -m benchmarks.external.longmemeval.cli fixture --output DIR
    python -m benchmarks.external.longmemeval.cli prepare --data-path PATH
    python -m benchmarks.external.longmemeval.cli structural \
        --data-path PATH --output DIR [--overwrite]
    python -m benchmarks.external.longmemeval.cli live ...   (opt-in only)
    python -m benchmarks.external.longmemeval.cli validate DIR

No command downloads anything, switches providers silently, or
overwrites results without --overwrite. Missing official data or
credentials produce bounded messages.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmarks.external.longmemeval.loader import (
    ExternalDataError,
    load_fixture_cases,
    load_manifest,
    load_selected_cases,
)
from benchmarks.external.longmemeval.runner import (
    EXTERNAL_SYSTEMS,
    execute_external,
    write_external_artifacts,
)
from benchmarks.external.longmemeval.validation import main as validate_main

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "synthetic_official_shape.json"
)


def _report(runs, failures, artifact_dir, synthetic):
    completed = sum(1 for r in runs if r.status == "completed")
    failed = sum(1 for r in runs if r.status == "execution_failed")
    print(f"systems: {', '.join(EXTERNAL_SYSTEMS)}")
    print(f"case-system runs: {len(runs)}")
    print(f"completed: {completed}")
    print(f"execution failures: {failed}")
    print(f"deferred evaluations: {len(failures['deferred_evaluations'])}")
    print(f"data: {'SYNTHETIC fixtures' if synthetic else 'official'}")
    print("official evaluation: no (structural + labeled proxies)")
    print(f"artifacts: {artifact_dir}")
    if failed:
        print("RESULT: EXTERNAL RUN HAD EXECUTION FAILURES")
        return 1
    print("RESULT: external run completed (evidence only — not an "
          "official LongMemEval score)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fixture = sub.add_parser("fixture")
    fixture.add_argument("--output", required=True)
    fixture.add_argument("--overwrite", action="store_true")

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--data-path", required=True)

    structural = sub.add_parser("structural")
    structural.add_argument("--data-path", required=True)
    structural.add_argument("--output", required=True)
    structural.add_argument("--overwrite", action="store_true")

    live = sub.add_parser("live")
    live.add_argument("--data-path", required=True)
    live.add_argument("--output", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("result_dir")

    args = parser.parse_args(argv)

    if args.command == "validate":
        return validate_main([args.result_dir])

    if args.command == "live":
        print(
            "live mode is opt-in and not implemented as a default path: "
            "it requires QWEN_API_KEY, an explicit fixed model/temperature "
            "configuration, and a documented judge. Configure and extend "
            "deliberately; nothing runs by default."
        )
        return 2

    try:
        if args.command == "fixture":
            cases = load_fixture_cases(FIXTURE_PATH)
            runs, failures = execute_external(cases)
            artifact_dir = write_external_artifacts(
                output_dir=args.output,
                mode="offline-fixture",
                data_file=str(FIXTURE_PATH),
                cases=cases,
                runs=runs,
                failures=failures,
                overwrite=args.overwrite,
            )
            return _report(runs, failures, artifact_dir, synthetic=True)

        if args.command == "prepare":
            manifest = load_manifest()
            cases = load_selected_cases(args.data_path, manifest)
            counts: dict = {}
            for case in cases:
                counts[case.category] = counts.get(case.category, 0) + 1
            print(f"display label: {manifest['display_label']}")
            print(f"subset version: {manifest['subset_version']}")
            print(f"manifest hash: {manifest['manifest_hash']}")
            print(f"source revision: {manifest['source_revision']}")
            print(f"selected cases loaded: {len(cases)}")
            print(f"category counts: {dict(sorted(counts.items()))}")
            print("RESULT: official data prepared (subset loads cleanly)")
            return 0

        if args.command == "structural":
            manifest = load_manifest()
            cases = load_selected_cases(args.data_path, manifest)
            runs, failures = execute_external(cases)
            artifact_dir = write_external_artifacts(
                output_dir=args.output,
                mode="structural-offline",
                data_file=args.data_path,
                cases=cases,
                runs=runs,
                failures=failures,
                manifest=manifest,
                overwrite=args.overwrite,
            )
            return _report(runs, failures, artifact_dir, synthetic=False)
    except ExternalDataError as exc:
        print(f"EXTERNAL DATA UNAVAILABLE: {exc}")
        return 1
    except FileExistsError as exc:
        print(f"REFUSING TO OVERWRITE: {exc}")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
