"""Command-line entry for the semantic-identity evaluation.

Commands:
  evaluate    measure the identity layer on the frozen corpus
  repeat      run twice and prove the relation signature is identical

Fully offline and deterministic: no provider, no model, no credentials,
no network, and no writes to the corpus.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmarks.semantic_identity.evaluation import (
    evaluate_corpus,
    relation_signature,
)


def _summarize(partition: str, data: dict) -> list:
    accuracy = data["relation_accuracy"]
    latency = data["latency"]
    lines = [
        f"{partition}:",
        f"  records={data['records']} applicable={data['applicable']} "
        f"not_applicable={data['not_applicable']}",
        f"  relation accuracy: {accuracy['correct']}/{accuracy['total']}",
        f"  fallback (ambiguous): {data['fallback']['ambiguous']}"
        f"/{data['fallback']['total']}",
    ]
    for relation, counts in sorted(data["by_relation"].items()):
        lines.append(
            f"    {relation}: {counts['correct']}/{counts['total']}"
        )
    lines.append("  safety:")
    for name, count in sorted(data["safety"].items()):
        lines.append(f"    {name}: {count}")
    lines.append("  projection:")
    projection = data["projection"]
    lines.append(
        f"    projected={projection['projected']}/{projection['total']} "
        f"mean_completeness={projection['mean_completeness']}"
    )
    lines.append("  field accuracy (vs annotated before-state):")
    for name, counts in sorted(data["field_accuracy"].items()):
        lines.append(f"    {name}: {counts['correct']}/{counts['total']}")
    if latency.get("count"):
        lines.append(
            f"  latency: n={latency['count']} "
            f"median={latency['median_ms']:.4f}ms "
            f"p95={latency['p95_ms']:.4f}ms max={latency['max_ms']:.4f}ms"
        )
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="semantic-identity")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate", help="measure on the frozen corpus")
    evaluate.add_argument(
        "--json", action="store_true", help="emit the raw metric record"
    )
    sub.add_parser("repeat", help="prove deterministic repeatability")
    args = parser.parse_args(argv)

    if args.command == "repeat":
        first = relation_signature()
        second = relation_signature()
        if first != second:
            print("RESULT: identity relations are NOT deterministic")
            return 1
        print(f"RESULT: {len(first)} relations reproduced identically")
        return 0

    data = evaluate_corpus()
    if args.json:
        payload = {
            key: _strip(value)
            for key, value in data.items()
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    lines = []
    for partition in ("historical_scored", "development_only"):
        lines.extend(_summarize(partition, data[partition]))
    lines.append(
        f"unresolved diagnostics (never scored): "
        f"{len(data['unresolved_diagnostics'])}"
    )
    lines.append(f"excluded records (never scored): {data['excluded_records']}")
    print("\n".join(lines))
    return 0


def _strip(value):
    """Drop the live result objects from the JSON view."""
    if isinstance(value, dict) and "results" in value:
        return {k: v for k, v in value.items() if k != "results"}
    return value


if __name__ == "__main__":
    sys.exit(main())
