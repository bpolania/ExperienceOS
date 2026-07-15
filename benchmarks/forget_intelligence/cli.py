"""Command-line entry for the forget-intelligence evaluation.

Commands:
  evaluate    measure forget classification and targeting on the corpus
  repeat      run twice and prove the forget signature is identical

Fully offline and deterministic: no provider, no model, no credentials,
no network, no corpus writes, and no lifecycle mutation.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmarks.forget_intelligence.evaluation import (
    evaluate_corpus,
    forget_signature,
)


def _summarize(name: str, data: dict) -> list:
    classification = data["classification"]
    target = data["target"]
    creation = data["creation_prevention"]
    verification = data["verification"]
    latency = data["latency"]
    lines = [
        f"{name}:",
        f"  records={data['records']} forget_applicable={data['applicable']} "
        f"abstention_cases={data['abstention_cases']}",
        f"  classification: {classification['correct']}/{classification['total']}"
        f"  macro F1: {data['macro_f1']}",
        f"  abstained on non-forget sources: {data['abstained']}"
        f"/{data['abstention_cases']}",
        f"  target: {target['correct']}/{target['cases_requiring_target']} correct "
        f"(exact={target['exact']} semantic={target['semantic']} "
        f"scoped={target['scoped']} wrong={target['wrong']} "
        f"spurious={target['spurious']})",
        f"  creation prevention: {creation['positive_creations']} creations and "
        f"{creation['supersessions']} supersessions from "
        f"{creation['affirmative_directives']} affirmative directives",
        f"  verifier: accepted={verification['accepted']}"
        f"/{verification['verified']} rejected={verification['rejected']} "
        f"eligible={verification['canonical_effect_eligible']} "
        f"applied={verification['action_applied']}",
        "  by directive type:",
    ]
    for directive, counts in sorted(data["by_directive"].items()):
        lines.append(f"    {directive}: {counts['correct']}/{counts['total']}")
    lines.append("  per-label precision/recall/F1:")
    for label, stats in sorted(data["per_label"].items()):
        lines.append(
            f"    {label}: P={stats['precision']} R={stats['recall']} "
            f"F1={stats['f1']} (tp={stats['tp']} fp={stats['fp']} fn={stats['fn']})"
        )
    lines.append("  safety:")
    for key, value in sorted(data["safety"].items()):
        lines.append(f"    {key}: {value}")
    reference = data["reference"]["forgot_correct_target"]
    lines.append(
        f"  reference (experienceos_hybrid_full_v2_reference) forgot the "
        f"oracle target: {reference['correct']}/{reference['total']}"
    )
    if latency.get("count"):
        lines.append(
            f"  latency: n={latency['count']} median={latency['median_ms']}ms "
            f"p95={latency['p95_ms']}ms max={latency['max_ms']}ms"
        )
        for stage, stats in data["stage_latency"].items():
            if stats.get("count"):
                lines.append(
                    f"    {stage}: median={stats['median_ms']}ms "
                    f"p95={stats['p95_ms']}ms"
                )
    return lines


def _strip(value):
    if isinstance(value, dict) and "outcomes" in value:
        return {
            key: ([o.to_record() for o in item] if key == "outcomes" else item)
            for key, item in value.items()
        }
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="forget-intelligence")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate", help="measure on the frozen corpus")
    evaluate.add_argument("--json", action="store_true")
    sub.add_parser("repeat", help="prove deterministic repeatability")
    args = parser.parse_args(argv)

    if args.command == "repeat":
        first = forget_signature()
        second = forget_signature()
        if first != second:
            print("RESULT: forget proposals are NOT deterministic")
            return 1
        print(f"RESULT: {len(first)} forget proposals reproduced identically")
        return 0

    data = evaluate_corpus()
    if args.json:
        print(json.dumps({k: _strip(v) for k, v in data.items()},
                         indent=2, sort_keys=True))
        return 0

    lines = [
        "controller: experienceos_forget_rules_v1 (proposal-only; not "
        "canonical, not adopted; bulk forgetting unsupported)",
        "",
    ]
    for partition in ("historical_scored", "development_only"):
        lines.extend(_summarize(partition, data[partition]))
        lines.append("")
    lines.append(f"unresolved records (never scored): {data['unresolved_records']}")
    lines.append(f"excluded records (never scored): {data['excluded_records']}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
