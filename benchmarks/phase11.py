"""Phase 11 retrieval benchmark generation (Prompt 7).

Deterministic, offline generation of the Phase 11 artifacts: the
frozen lifecycle scenarios and the pinned LongMemEval 50-case subset
run over the four Phase 11 systems (Phase 9 reference, embedding-only,
fused, fused+gate-shadow), all using the deterministic test embedding
provider. Historical Phase 8/9 artifact directories are never written.

    PYTHONPATH=. python -m benchmarks.phase11 lifecycle --output <dir>
    PYTHONPATH=. python -m benchmarks.phase11 external --output <dir> \
        [--data-path benchmarks/data/external/longmemeval/...]
    PYTHONPATH=. python -m benchmarks.phase11 consistency <dir-a> <dir-b>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.contract import SystemId

PHASE11_SYSTEMS = (
    SystemId.EXPERIENCEOS_HYBRID_FULL_V2_REFERENCE,
    SystemId.EXPERIENCEOS_EMBEDDING_ONLY_V1,
    SystemId.EXPERIENCEOS_FUSED_RETRIEVAL_V1,
    SystemId.EXPERIENCEOS_GATE_SHADOW_V1,
)

LIFECYCLE_RUN_ID = "phase11-retrieval-ablation"
EXTERNAL_RUN_ID = "phase11-semantic-retrieval"
LIFECYCLE_COMMITTED = "benchmarks/results/committed/phase11-retrieval-ablation"
EXTERNAL_COMMITTED = "benchmarks/results/committed/phase11-semantic-retrieval"
DEFAULT_DATA_PATH = (
    "benchmarks/data/external/longmemeval/longmemeval_s_cleaned.json"
)


def run_lifecycle(
    output_dir: str,
    run_id: str = LIFECYCLE_RUN_ID,
    overwrite: bool = False,
) -> Path:
    from benchmarks.artifacts.writer import write_artifacts
    from benchmarks.runner.config import RunConfig
    from benchmarks.runner.execute import execute_run

    config = RunConfig(
        profile="full-offline",
        output_dir=output_dir,
        run_id=run_id,
        systems=PHASE11_SYSTEMS,
        overwrite=overwrite,
    )
    output = execute_run(config)
    execution_failures = len(
        output.failures.get("system_execution_failures", [])
    ) + len(output.failures.get("evaluator_failures", []))
    if execution_failures:
        raise RuntimeError(
            f"phase11 lifecycle run had {execution_failures} execution/"
            "evaluator failures; artifacts not written"
        )
    return write_artifacts(output)


def run_external(
    output_dir: str,
    data_path: str = DEFAULT_DATA_PATH,
    run_id: str = EXTERNAL_RUN_ID,
    overwrite: bool = False,
) -> Path:
    from benchmarks.external.longmemeval.loader import (
        load_manifest,
        load_selected_cases,
    )
    from benchmarks.external.longmemeval.runner import (
        execute_external,
        write_external_artifacts,
    )

    manifest = load_manifest()
    cases = load_selected_cases(data_path, manifest)
    runs, failures = execute_external(cases, systems=PHASE11_SYSTEMS)
    if failures.get("system_execution_failures"):
        raise RuntimeError(
            "phase11 external run had execution failures: "
            f"{len(failures['system_execution_failures'])}"
        )
    return write_external_artifacts(
        output_dir=output_dir,
        mode="offline-structural",
        data_file=data_path,
        cases=cases,
        runs=runs,
        failures=failures,
        manifest=manifest,
        overwrite=overwrite,
        systems=PHASE11_SYSTEMS,
        run_id=run_id,
    )


def normalized_digest_of(artifact_dir: str) -> str:
    manifest = json.loads(
        (Path(artifact_dir) / "artifact_manifest.json").read_text()
    )
    return manifest["normalized_result_digest"]


def check_consistency(dir_a: str, dir_b: str) -> bool:
    """Double-run reproducibility: identical normalized digests."""
    digest_a = normalized_digest_of(dir_a)
    digest_b = normalized_digest_of(dir_b)
    print(f"run A digest: {digest_a}")
    print(f"run B digest: {digest_b}")
    return digest_a == digest_b


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    lifecycle = sub.add_parser("lifecycle")
    lifecycle.add_argument("--output", default=LIFECYCLE_COMMITTED)
    lifecycle.add_argument("--run-id", default=LIFECYCLE_RUN_ID)
    lifecycle.add_argument("--overwrite", action="store_true")
    external = sub.add_parser("external")
    external.add_argument("--output", default=EXTERNAL_COMMITTED)
    external.add_argument("--data-path", default=DEFAULT_DATA_PATH)
    external.add_argument("--run-id", default=EXTERNAL_RUN_ID)
    external.add_argument("--overwrite", action="store_true")
    consistency = sub.add_parser("consistency")
    consistency.add_argument("dir_a")
    consistency.add_argument("dir_b")
    args = parser.parse_args(argv)

    if args.command == "lifecycle":
        artifact_dir = run_lifecycle(
            args.output, run_id=args.run_id, overwrite=args.overwrite
        )
        print(f"artifacts: {artifact_dir}")
        print(f"digest: {normalized_digest_of(str(artifact_dir))}")
        print("RESULT: phase11 lifecycle run completed")
        return 0
    if args.command == "external":
        artifact_dir = run_external(
            args.output,
            data_path=args.data_path,
            run_id=args.run_id,
            overwrite=args.overwrite,
        )
        print(f"artifacts: {artifact_dir}")
        print(f"digest: {normalized_digest_of(str(artifact_dir))}")
        print("RESULT: phase11 external run completed")
        return 0
    if args.command == "consistency":
        if check_consistency(args.dir_a, args.dir_b):
            print("RESULT: phase11 double-run digests match")
            return 0
        print("RESULT: PHASE11 DOUBLE-RUN DIGEST MISMATCH")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
