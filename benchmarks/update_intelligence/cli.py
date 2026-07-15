"""Command-line entry for the update-intelligence evaluation.

Commands:
  evaluate    measure controller proposals on the frozen corpus
  repeat      run twice and prove the proposal signature is identical

Fully offline and deterministic: no provider, no model, no credentials,
no network, no corpus writes, and no lifecycle mutation.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmarks.update_intelligence.evaluation import (
    evaluate_corpus,
    proposal_signature,
)


def _summarize(name: str, data: dict) -> list:
    coverage = data["coverage"]
    accuracy = data["transition_accuracy"]
    strict = data["transition_accuracy_strict"]
    target = data["target"]
    verification = data["verification"]
    effect = data["effect_vs_oracle"]
    latency = data["latency"]
    lines = [
        f"{name}:",
        f"  records={data['records']} applicable={data['applicable']} "
        f"forget_boundary={data['forget_boundary_cases']}",
        f"  coverage: proposals={coverage['proposals']} "
        f"(rejection={coverage['rejection_proposals']}) "
        f"abstentions={coverage['abstentions']}/{coverage['total']}",
        f"  transition accuracy: {accuracy['correct']}/{accuracy['total']}"
        f"  (strict label equality: {strict['correct']}/{strict['total']})",
        f"  macro F1: {data['macro_f1']}",
        f"  target: {target['correct']}/{target['cases_requiring_target']} correct, "
        f"wrong={target['wrong']} spurious={target['spurious_targets']}",
        f"  duplicates: {data['duplicates']['correct']}/{data['duplicates']['cases']}"
        f" (created instead={data['duplicates']['created_instead']})",
        f"  supersession: {data['supersession']['correct']}"
        f"/{data['supersession']['cases']} "
        f"(target {data['supersession']['correct_target']}"
        f"/{data['supersession']['cases']}, "
        f"false={data['supersession']['false_supersessions']})",
        f"  coexistence: {data['coexistence']['correct']}"
        f"/{data['coexistence']['cases']} "
        f"(false={data['coexistence']['false_coexistence']})",
        f"  verifier: accepted={verification['accepted']}"
        f"/{verification['verified']} rejected={verification['rejected']} "
        f"eligible={verification['canonical_effect_eligible']} "
        f"applied={verification['action_applied']}",
        f"  forget boundary: handed_off="
        f"{data['forget_boundary']['handed_off']}"
        f"/{data['forget_boundary']['cases']} "
        f"positive_creations={data['forget_boundary']['positive_creations']}",
        "  lifecycle effect vs oracle:",
        f"    controller: {effect['controller']['correct']}"
        f"/{effect['controller']['total']}",
        f"    reference (experienceos_hybrid_full_v2_reference): "
        f"{effect['reference']['correct']}/{effect['reference']['total']}",
        "  per-label precision/recall/F1:",
    ]
    for label, stats in sorted(data["per_label"].items()):
        lines.append(
            f"    {label}: P={stats['precision']} R={stats['recall']} "
            f"F1={stats['f1']} (tp={stats['tp']} fp={stats['fp']} fn={stats['fn']})"
        )
    lines.append("  safety:")
    for key, value in sorted(data["safety"].items()):
        lines.append(f"    {key}: {value}")
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
    parser = argparse.ArgumentParser(prog="update-intelligence")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate", help="measure on the frozen corpus")
    evaluate.add_argument("--json", action="store_true")
    sub.add_parser("repeat", help="prove deterministic repeatability")
    args = parser.parse_args(argv)

    if args.command == "repeat":
        first = proposal_signature()
        second = proposal_signature()
        if first != second:
            print("RESULT: update proposals are NOT deterministic")
            return 1
        print(f"RESULT: {len(first)} proposals reproduced identically")
        return 0

    data = evaluate_corpus()
    if args.json:
        print(json.dumps({k: _strip(v) for k, v in data.items()},
                         indent=2, sort_keys=True))
        return 0

    lines = [
        "controller: experienceos_transition_rules_v1 (proposal-only; "
        "not canonical, not adopted)",
        "",
    ]
    for partition in ("historical_scored", "development_only"):
        lines.extend(_summarize(partition, data[partition]))
        lines.append("")
    lines.append(
        f"unresolved records (never scored): {data['unresolved_records']}"
    )
    lines.append(f"excluded records (never scored): {data['excluded_records']}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
