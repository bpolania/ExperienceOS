"""Deterministic committed artifacts for the transition benchmark.

Content digests reuse the suite's own `normalize_for_digest`, which
strips exactly the known-nondeterministic fields (measured latency,
timestamps, runtime UUIDs mapped by first-seen order) and leaves every
behavioral field untouched. Latency is recorded beside the deterministic
content, never inside its digest.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from benchmarks.artifacts.writer import normalize_for_digest
from benchmarks.contract.serialization import canonical_json, stable_dump
from benchmarks.transition_benchmark import BENCHMARK_VERSION, SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFICATION_DIR = REPO_ROOT / "benchmarks/results/committed/transition-verification"
ABLATION_DIR = REPO_ROOT / "benchmarks/results/committed/transition-ablation"
REPORT_DIR = REPO_ROOT / "benchmarks/results/committed/report-transition-verification"

CORPUS_ROOT = REPO_ROOT / "benchmarks/annotations/transition-verification"


def _digest(value) -> str:
    import hashlib

    normalized = normalize_for_digest(value)
    return hashlib.sha256(
        canonical_json(normalized).encode("utf-8")
    ).hexdigest()


def _commit(path=None) -> str:
    try:
        args = ["git", "log", "-1", "--format=%H"]
        if path:
            args += ["--", str(path)]
        return subprocess.run(
            args, cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_dump(data) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8"
    )


def _file_digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(directory: Path, extra: dict) -> dict:
    # latency.json holds measured wall-clock, which is real but not
    # byte-reproducible; it is deliberately outside the digest set.
    files = sorted(
        p.name for p in directory.iterdir()
        if p.is_file() and p.name not in ("manifest.json", "latency.json")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "code_commit": _commit(),
        "contract_commit": _commit(
            REPO_ROOT / "docs/transition_verification_contract.md"
        ),
        "corpus_commit": _commit(CORPUS_ROOT),
        "regeneration_command": "./scripts/run_benchmarks.sh transition-benchmark",
        "verification_command": (
            "./scripts/run_benchmarks.sh transition-benchmark-verify"
        ),
        "environment": "offline; mock provider; no model, credentials, or network",
        "file_digests": {name: _file_digest(directory / name) for name in files},
        **extra,
    }


def _comparison_rows(data) -> list:
    rows = []
    for system_id, metrics in data["systems"].items():
        actual = metrics["lifecycle_actual"]
        projected = metrics["lifecycle_projected"]
        rows.append(
            {
                "system_id": system_id,
                "reference_level": next(
                    s["reference_level"] for s in data["system_specs"]
                    if s["system_id"] == system_id
                ),
                "classification_correct": metrics["classification"]["correct"],
                "classification_total": metrics["classification"]["total"],
                "target_correct": metrics["target"]["correct"],
                "target_total": metrics["target"]["total"],
                "target_wrong": metrics["target"]["wrong"],
                "actual_duplicate_pairs": actual["duplicate_pairs"],
                "actual_stale_pairs": actual["stale_pairs"],
                "actual_created": actual["created"],
                "targets_deactivated": actual["targets_deactivated"]["correct"],
                "preservation_correct": actual["preservation"]["correct"],
                "projected_duplicate_pairs": projected["duplicate_pairs"],
                "projected_stale_pairs": projected["stale_pairs"],
                "actions_applied": metrics["actions_applied"],
            }
        )
    return rows


def _csv(rows) -> str:
    if not rows:
        return ""
    header = list(rows[0].keys())
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(row[k]) for k in header))
    return "\n".join(lines) + "\n"


def _markdown(rows) -> str:
    if not rows:
        return ""
    header = list(rows[0].keys())
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[k]) for k in header) + " |")
    return "\n".join(lines) + "\n"


def write_verification(data, gates) -> Path:
    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    per_case = sorted(data["per_case"], key=lambda r: (r["system_id"], r["case_id"]))
    _write_jsonl(VERIFICATION_DIR / "per-case.jsonl", per_case)

    aggregate = {
        "schema_version": SCHEMA_VERSION,
        "systems": data["systems"],
        "partitions": data["partitions"],
        "safety": data["safety"],
        "authorization": data["authorization"],
    }
    _write(VERIFICATION_DIR / "aggregate.json", aggregate)
    _write(VERIFICATION_DIR / "systems.json", {"systems": data["system_specs"]})
    _write_jsonl(
        VERIFICATION_DIR / "lifecycle-chains.jsonl",
        [
            {"system_id": sid, **chain}
            for sid, chain in data["lifecycle"]["systems"].items()
        ],
    )
    _write(VERIFICATION_DIR / "downstream.json", data["downstream"])
    _write(VERIFICATION_DIR / "latency.json", data["latency"])
    _write(VERIFICATION_DIR / "adoption-gates.json", gates)

    rows = _comparison_rows(data)
    (VERIFICATION_DIR / "comparison.csv").write_text(_csv(rows), encoding="utf-8")
    (VERIFICATION_DIR / "comparison.md").write_text(
        "# Transition benchmark comparison\n\n"
        "Historical-scored partition. `actual` is what a system really did to "
        "memory through the real manager and engine; `projected` is what its "
        "proposal would do if it alone governed state. Non-mutating modes leave "
        "those different by design.\n\n" + _markdown(rows),
        encoding="utf-8",
    )
    (VERIFICATION_DIR / "README.md").write_text(
        _readme_verification(data, gates), encoding="utf-8"
    )
    _write(
        VERIFICATION_DIR / "manifest.json",
        _manifest(
            VERIFICATION_DIR,
            {
                "content_digest": _digest(
                    {"cases": per_case, "aggregate": aggregate}
                ),
                "case_count": len(per_case),
                "partition_counts": {
                    name: block["records"]
                    for name, block in data["partitions"].items()
                },
                "system_ids": sorted(data["systems"]),
                "optional_systems": data["optional_systems"],
                "nondeterministic_files": ["latency.json"],
                "latency_excluded_from_digest": True,
            },
        ),
    )
    return VERIFICATION_DIR


def write_ablation(data) -> Path:
    ABLATION_DIR.mkdir(parents=True, exist_ok=True)
    ablations = data["ablations"]["ablations"]
    _write_jsonl(ABLATION_DIR / "per-case.jsonl", ablations)
    _write(
        ABLATION_DIR / "aggregate.json",
        {"schema_version": SCHEMA_VERSION, "count": data["ablations"]["count"]},
    )
    _write(ABLATION_DIR / "ablations.json", {"ablations": ablations})
    _write(
        ABLATION_DIR / "safety.json",
        {
            **data["ablations"]["safety"],
            "authorization": data["authorization"],
            "lifecycle_safety": data["safety"],
        },
    )
    rows = [
        {
            "ablation_id": a["ablation_id"],
            "disabled_component": a["disabled_component"],
            "applicable_cases": a["applicable_cases"],
            "classification_correct": a["metrics"].get("classification_correct", ""),
            "safety_failures": a["safety_failures"],
            "runtime_eligible": a["runtime_eligible"],
            "action_applied": a["action_applied"],
        }
        for a in ablations
    ]
    (ABLATION_DIR / "contribution.csv").write_text(_csv(rows), encoding="utf-8")
    (ABLATION_DIR / "contribution.md").write_text(
        "# Transition ablation contributions\n\n"
        "Every ablation is benchmark-only, non-mutating, and cannot reach "
        "adopted action insertion.\n\n" + _markdown(rows),
        encoding="utf-8",
    )
    (ABLATION_DIR / "README.md").write_text(
        "# Transition ablations\n\n"
        "Benchmark-only diagnostics. None of these is selectable from SDK "
        "configuration, none appears in demo or dashboard startup, and none "
        "can produce a canonical action: `runtime_eligible` and "
        "`action_applied` are false for every ablation.\n\n"
        "Ablations are implemented in benchmark adapters. The identity, "
        "verifier, and controller code they measure is the committed code, "
        "unchanged.\n\n"
        "Regenerate: `./scripts/run_benchmarks.sh transition-ablation`\n"
        "Verify: `./scripts/run_benchmarks.sh transition-ablation-verify`\n",
        encoding="utf-8",
    )
    _write(
        ABLATION_DIR / "manifest.json",
        _manifest(
            ABLATION_DIR,
            {
                "content_digest": _digest({"ablations": ablations}),
                "ablation_count": len(ablations),
                "regeneration_command": (
                    "./scripts/run_benchmarks.sh transition-ablation"
                ),
                "verification_command": (
                    "./scripts/run_benchmarks.sh transition-ablation-verify"
                ),
            },
        ),
    )
    return ABLATION_DIR


def validate(directory: Path) -> bool:
    """Re-verify a committed directory's manifest and file digests."""
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, digest in manifest["file_digests"].items():
        actual = _file_digest(directory / name)
        if actual != digest:
            raise ValueError(f"{directory.name}/{name}: digest mismatch")
    return True


def _readme_verification(data, gates) -> str:
    reference = data["systems"]["experienceos_hybrid_full_v2_reference"]
    adopted = data["systems"]["experienceos_transition_adopted_v1"]
    return (
        "# Transition verification benchmark\n\n"
        f"Adoption classification: **{gates['classification']}**\n\n"
        f"{gates['rationale']}\n\n"
        "This classification does not change the runtime default, which "
        "remains `disabled`. No controller is canonical.\n\n"
        "## Systems\n\n"
        "Every system runs against its own isolated in-memory store seeded "
        "from the same frozen before-state, through the real "
        "`ExperienceManager` and `ExperienceEngine`. The oracle scores "
        "output; it never generates it.\n\n"
        "## Headline (historical-scored, 28 cases)\n\n"
        f"- reference: {reference['lifecycle_actual']['stale_pairs']} stale "
        f"active pairs, {reference['lifecycle_actual']['duplicate_pairs']} "
        f"duplicate pairs\n"
        f"- adopted (isolated): "
        f"{adopted['lifecycle_actual']['stale_pairs']} stale, "
        f"{adopted['lifecycle_actual']['duplicate_pairs']} duplicate pairs\n\n"
        f"Gates: {gates['passed']} passed, {gates['failed']} failed, "
        f"{gates['inconclusive']} inconclusive, {gates['unavailable']} "
        f"unavailable.\n\n"
        "Latency is measured and recorded beside the deterministic content; "
        "it is excluded from content digests.\n\n"
        "Regenerate: `./scripts/run_benchmarks.sh transition-benchmark`\n"
        "Verify: `./scripts/run_benchmarks.sh transition-benchmark-verify`\n"
    )
