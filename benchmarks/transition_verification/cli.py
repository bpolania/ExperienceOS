"""Command-line entry for the transition-verification evaluation.

Commands:
  evaluate    verify oracle-derived and adversarial proposals
  repeat      run twice and prove the verification signature is identical

Fully offline and deterministic: no provider, no model, no credentials,
no network, no writes to the corpus, and no lifecycle mutation.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmarks.transition_verification.evaluation import (
    evaluate_corpus,
    verification_signature,
)


def _summarize(name: str, data: dict) -> list:
    latency = data["latency"]
    lines = [
        f"{name}:",
        f"  records={data['records']}",
        f"  correct proposals (oracle-derived): "
        f"{data['correct_accepted']}/{data['correct_evaluated']} accepted",
        f"  adversarial proposals: "
        f"{data['adversarial_rejected']}/{data['adversarial_evaluated']} rejected",
        f"  canonical eligibility correct: "
        f"{data['canonical_eligibility_correct']['correct']}"
        f"/{data['canonical_eligibility_correct']['total']}",
        "  checks:",
    ]
    for check, counts in sorted(data["checks"].items()):
        lines.append(f"    {check}: {counts['passed']}/{counts['total']}")
    lines.append("  adversarial by category:")
    for category, counts in sorted(data["adversarial_by_category"].items()):
        lines.append(
            f"    {category}: {counts['rejected']}/{counts['total']}"
        )
    if latency.get("count"):
        lines.append(
            f"  latency: n={latency['count']} "
            f"median={latency['median_ms']:.4f}ms "
            f"p95={latency['p95_ms']:.4f}ms max={latency['max_ms']:.4f}ms"
        )
    return lines


def _strip(value):
    if isinstance(value, dict) and "correct_results" in value:
        return {
            key: (
                [o.to_record() for o in item]
                if key in ("correct_results", "adversarial_results")
                else item
            )
            for key, item in value.items()
        }
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="transition-verification")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate", help="verify against the frozen corpus")
    evaluate.add_argument("--json", action="store_true")
    sub.add_parser("repeat", help="prove deterministic repeatability")
    args = parser.parse_args(argv)

    if args.command == "repeat":
        first = verification_signature()
        second = verification_signature()
        if first != second:
            print("RESULT: transition verification is NOT deterministic")
            return 1
        print(f"RESULT: {len(first)} verifications reproduced identically")
        return 0

    data = evaluate_corpus()
    if args.json:
        print(json.dumps({k: _strip(v) for k, v in data.items()},
                         indent=2, sort_keys=True))
        return 0

    lines = ["proposal source: oracle_derived (measures the verifier, "
             "not controller precision or recall)", ""]
    for partition in ("historical_scored", "development_only"):
        lines.extend(_summarize(partition, data[partition]))
    lines.append(
        f"unresolved diagnostics (never scored): "
        f"{len(data['unresolved_diagnostics'])}"
    )
    lines.append(f"excluded records (never scored): {data['excluded_records']}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
