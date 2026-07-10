"""Offline ExperienceOS adapter smoke: execution integrity only.

    PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_rules --all
    PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_local --scripted
    PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_local --real-local

Default runs are fully offline: deterministic provider, no
credentials, no network, no real local model, no artifacts. Never
presents aggregate benchmark results.
"""

from __future__ import annotations

import argparse

from benchmarks.adapters.common import run_adapter_case
from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
from benchmarks.adapters.scripted_policy import SCRIPTED_PROPOSALS
from benchmarks.contract import CaseStatus, validate_case_result
from benchmarks.scenarios.loader import load_dataset, load_manifest

REPRESENTATIVE_PREFIXES = (
    "creation_001",
    "creation_004",
    "creation_005",
    "updates_002",
    "updates_005",
    "forgetting_001",
    "forgetting_005",
    "retrieval_002",
    "context_001",
    "context_003",
    "containment_001",
    "containment_004",
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--system", choices=ADAPTER_SYSTEM_IDS, default="experienceos_rules"
    )
    parser.add_argument("--scenario", help="scenario ID prefix")
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="local adapter: only the scripted containment fixtures",
    )
    parser.add_argument(
        "--real-local",
        action="store_true",
        help="local adapter: use the environment-configured real GGUF "
        "runner (never default; no downloads)",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest()
    scenarios = load_dataset(manifest)
    if args.scenario:
        scenarios = [
            s
            for s in scenarios
            if s.case.scenario_id.startswith(args.scenario)
        ]
    elif args.scripted:
        scenarios = [
            s for s in scenarios if s.case.scenario_id in SCRIPTED_PROPOSALS
        ]
    elif not args.all:
        scenarios = [
            s
            for s in scenarios
            if s.case.scenario_id.startswith(REPRESENTATIVE_PREFIXES)
        ]
    if not scenarios:
        raise SystemExit("no scenarios selected")

    local_mode = "real" if args.real_local else "scripted"
    completed = skipped = failed = 0
    proposals = rejections = fallbacks = applied = 0
    real_local_used = False
    for scenario in scenarios:
        system = create_system(args.system, local_mode=local_mode)
        result = run_adapter_case(
            system, scenario, allow_local=args.real_local
        )
        validate_case_result(result)
        result.to_payload()
        if result.status == CaseStatus.SKIPPED:
            skipped += 1
            continue
        if result.status != CaseStatus.PASSED:
            failed += 1
            print(
                f"EXECUTION FAILURE {scenario.case.scenario_id}: "
                f"{result.failure_reason}"
            )
            continue
        completed += 1
        for turn in result.turns:
            proposals += len(turn.proposals)
            rejections += len(turn.rejected_actions)
            fallbacks += len(turn.fallbacks)
            applied += len(turn.applied_actions)
        real_local_used = real_local_used or bool(
            result.diagnostics.get("real_model_used")
        )

    print(f"dataset: {manifest['dataset_version']}")
    print(f"manifest hash: {manifest['manifest_hash']}")
    print(f"system exercised: {args.system}")
    print(f"adapter mode: {local_mode if args.system == 'experienceos_local' else 'rules'}")
    print(f"scenarios exercised: {len(scenarios)}")
    print(f"cases completed: {completed}")
    print(f"cases skipped: {skipped}")
    print(f"cases failed: {failed}")
    print(f"proposal records: {proposals}")
    print(f"rejection records: {rejections}")
    print(f"fallback records: {fallbacks}")
    print(f"applied-action records: {applied}")
    print("schema validation: all emitted results validated")
    print("network access used: no")
    print("real provider used: no (deterministic offline provider)")
    print(f"real local model used: {'yes' if real_local_used else 'no'}")
    if failed:
        print("RESULT: ADAPTER SMOKE FAILED")
        return 1
    print(
        "RESULT: adapter smoke passed (execution integrity only — "
        "not benchmark results)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
