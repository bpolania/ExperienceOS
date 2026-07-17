"""Offline CLI for governed-replacement applied-state verification."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmarks.action_replacement import artifacts
from benchmarks.action_replacement.adoption import evaluate
from benchmarks.action_replacement.verification import verify_all
from benchmarks.contract.serialization import canonical_json


def _repeat(fn) -> int:
    first = canonical_json(fn())
    second = canonical_json(fn())
    if first != second:
        print("RESULT: NOT deterministic", file=sys.stderr)
        return 1
    import hashlib

    print(f"RESULT: deterministic ({hashlib.sha256(first.encode()).hexdigest()[:16]})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="action_replacement")
    parser.add_argument(
        "command",
        choices=[
            "run", "validate", "repeat",
            "run-adoption", "validate-adoption", "repeat-adoption",
        ],
    )
    parser.add_argument("directory", nargs="?")
    args = parser.parse_args(argv)

    if args.command == "run":
        for path in artifacts.write():
            print(f"wrote {path}")
        return 0

    if args.command == "run-adoption":
        for path in artifacts.write_adoption():
            print(f"wrote {path}")
        return 0

    if args.command == "validate":
        targets = (
            [Path(args.directory)] if args.directory
            else [artifacts.RESULT_DIR, artifacts.REPORT_DIR]
        )
        for directory in targets:
            artifacts.validate(directory)
            print(f"RESULT: {directory} verification passed")
        return 0

    if args.command == "validate-adoption":
        targets = (
            [Path(args.directory)] if args.directory
            else [artifacts.ADOPTION_DIR, artifacts.ADOPTION_REPORT_DIR]
        )
        for directory in targets:
            artifacts.validate(directory)
            print(f"RESULT: {directory} verification passed")
        return 0

    if args.command == "repeat":
        return _repeat(verify_all)

    if args.command == "repeat-adoption":
        return _repeat(evaluate)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
