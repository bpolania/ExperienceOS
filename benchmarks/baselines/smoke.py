"""Offline baseline smoke: execution integrity, never benchmark results.

Runs baselines against committed lifecycle scenarios with the
deterministic offline provider, validates every emitted CaseResult,
and prints a bounded summary. Creates no artifacts, uses no network,
no credentials, and no local model.

    PYTHONPATH=. python -m benchmarks.baselines.smoke --all
    PYTHONPATH=. python -m benchmarks.baselines.smoke \
        --system stateless --scenario creation_001
"""

from __future__ import annotations

import argparse

from benchmarks.baselines.common import run_case
from benchmarks.baselines.factory import BASELINE_SYSTEM_IDS, create_baseline
from benchmarks.contract import CaseStatus, validate_case_result
from benchmarks.scenarios.loader import load_dataset, load_manifest

# One representative scenario per major group for the default run.
REPRESENTATIVE_PREFIXES = (
    "creation_001",
    "creation_004",
    "updates_001",
    "forgetting_001",
    "forgetting_005",
    "retrieval_003",
    "retrieval_008",
    "context_001",
    "containment_001",
    "containment_005",
)


def select_scenarios(scenarios, prefix: str | None, everything: bool):
    if prefix:
        matched = [
            s for s in scenarios if s.case.scenario_id.startswith(prefix)
        ]
        if not matched:
            raise SystemExit(f"no scenario matches prefix {prefix!r}")
        return matched
    if everything:
        return scenarios
    return [
        s
        for s in scenarios
        if s.case.scenario_id.startswith(REPRESENTATIVE_PREFIXES)
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", choices=BASELINE_SYSTEM_IDS)
    parser.add_argument("--scenario", help="scenario ID prefix")
    parser.add_argument(
        "--all", action="store_true", help="all 40 scenarios per system"
    )
    args = parser.parse_args(argv)

    manifest = load_manifest()
    scenarios = select_scenarios(load_dataset(manifest), args.scenario, args.all)
    systems = (args.system,) if args.system else BASELINE_SYSTEM_IDS

    completed = skipped = failed = 0
    for system_id in systems:
        for scenario in scenarios:
            result = run_case(create_baseline(system_id), scenario)
            validate_case_result(result)
            result.to_payload()  # must serialize cleanly
            if result.status == CaseStatus.SKIPPED:
                skipped += 1
            elif result.status == CaseStatus.PASSED:
                completed += 1
            else:
                failed += 1
                print(
                    f"EXECUTION FAILURE {system_id} "
                    f"{scenario.case.scenario_id}: {result.failure_reason}"
                )

    print(f"dataset: {manifest['dataset_version']}")
    print(f"manifest hash: {manifest['manifest_hash']}")
    print(f"systems exercised: {', '.join(systems)}")
    print(f"scenarios exercised per system: {len(scenarios)}")
    print(f"cases completed: {completed}")
    print(f"cases skipped: {skipped}")
    print(f"cases failed: {failed}")
    print("schema validation: all emitted results validated")
    print("network access used: no")
    print("real provider used: no (deterministic offline provider)")
    print("local model used: no")
    if failed:
        print("RESULT: BASELINE SMOKE FAILED")
        return 1
    print("RESULT: baseline smoke passed (execution integrity only — "
          "not benchmark results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
