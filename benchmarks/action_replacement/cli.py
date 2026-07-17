"""Offline CLI for governed-replacement applied-state verification."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmarks.action_replacement import artifacts
from benchmarks.action_replacement.verification import verify_all
from benchmarks.contract.serialization import canonical_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="action_replacement")
    parser.add_argument(
        "command", choices=["run", "validate", "repeat"]
    )
    parser.add_argument("directory", nargs="?")
    args = parser.parse_args(argv)

    if args.command == "run":
        result_dir, report_dir = artifacts.write()
        print(f"wrote {result_dir}")
        print(f"wrote {report_dir}")
        return 0

    if args.command == "validate":
        target = args.directory
        targets = (
            [Path(target)] if target
            else [artifacts.RESULT_DIR, artifacts.REPORT_DIR]
        )
        for directory in targets:
            artifacts.validate(directory)
            print(f"RESULT: {directory} verification passed")
        return 0

    if args.command == "repeat":
        first = canonical_json(verify_all())
        second = canonical_json(verify_all())
        if first != second:
            print("RESULT: verification is NOT deterministic", file=sys.stderr)
            return 1
        import hashlib

        digest = hashlib.sha256(first.encode()).hexdigest()[:16]
        print(f"RESULT: deterministic ({digest})")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
