"""Deterministic committed artifacts for replacement verification.

Content digests reuse the suite's canonical serialization; the recorded
result carries no wall-clock timing and no runtime UUIDs (memory ids are
mapped to stable first-seen labels upstream), so the artifacts are
byte-reproducible. The frozen corpus and contract are consumed only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from benchmarks.contract.serialization import canonical_json, stable_dump
from benchmarks.action_replacement import BENCHMARK_VERSION, SCHEMA_VERSION
from benchmarks.action_replacement.verification import verify_all

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULT_DIR = REPO_ROOT / "benchmarks/results/committed/action-replacement"
REPORT_DIR = REPO_ROOT / "benchmarks/results/committed/report-action-replacement"

CONTRACT = REPO_ROOT / "docs/action_replacement_contract.md"
CORPUS_ROOT = REPO_ROOT / "benchmarks/annotations/transition-verification"


def _digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(directory: Path, content_digest: str, regen: str, verify: str) -> dict:
    files = sorted(
        p.name for p in directory.iterdir()
        if p.is_file() and p.name != "manifest.json"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "content_digest": content_digest,
        "code_commit": _commit(),
        "contract_commit": _commit(CONTRACT),
        "corpus_commit": _commit(CORPUS_ROOT),
        "regeneration_command": regen,
        "verification_command": verify,
        "environment": "offline; mock provider; no model, credentials, or network",
        "file_digests": {name: _file_digest(directory / name) for name in files},
    }


def _report(data: dict) -> dict:
    summary = data["summary"]
    rows = [
        {
            "case_id": r["case_id"],
            "transition_class": r["transition_class"],
            "append_duplicate_pairs": r["append_duplicate_pairs"],
            "replacement_duplicate_pairs": r["replacement_duplicate_pairs"],
            "canonical_effect": r["canonical_effect"],
            "planner_suppressed": r["planner_suppressed"],
            "lineage_ok": r["lineage_ok"],
        }
        for r in data["cases"]
        if r["append_duplicate_pairs"] or r["replacement_duplicate_pairs"]
        or r["planner_suppressed"]
    ]
    return {"headline": summary, "comparison": rows}


def _readme(data: dict) -> str:
    s = data["summary"]
    lines = [
        "# Governed Action Replacement — Applied-State Verification",
        "",
        "Measured by running the frozen historical transition corpus "
        "through the real governed pipeline (planner, manager, verifier, "
        "matcher, plan builder, authorization, engine). No frozen evidence "
        "is modified and no adoption decision is made.",
        "",
        f"- Cases: **{s['case_count']}** "
        f"({s['supersede_bearing']} supersede-bearing, "
        f"{s['pure_create']} pure-create, {s['no_transition']} no-transition)",
        f"- Semantic duplicate pairs: **{s['append_duplicate_pairs_total']} "
        f"(append) → {s['replacement_duplicate_pairs_total']} (replacement)**, "
        f"a reduction of **{s['duplicate_reduction']}**",
        f"- Supersede-bearing duplicates: "
        f"**{s['supersede_bearing_append_duplicates']} → "
        f"{s['supersede_bearing_replacement_duplicates']}**",
        f"- Pure-create residual duplicates (out of scope): "
        f"**{s['pure_create_residual_duplicates']}**",
        f"- Replacements applied: {s['replacements_applied']}; "
        f"lineage correct {s['applied_lineage_correct']}/"
        f"{s['applied_lineage_correct'] + s['applied_lineage_broken']}; "
        f"seeded memories lost {s['applied_seeded_memories_lost']}; "
        f"transition create present exactly once "
        f"{s['applied_transition_create_present_once']}/"
        f"{s['replacements_applied']}",
        "",
        "Gate 1 (semantic duplicate active-memory count) is reported as "
        "measured for the supersede-bearing class only; the pure-create "
        "residual is a separate, out-of-scope class and is not folded in. "
        "This document makes no adoption decision.",
        "",
        f"Regenerate: `./scripts/run_benchmarks.sh run-action-replacement`  ",
        f"Verify: `./scripts/run_benchmarks.sh validate-action-replacement`",
        "",
    ]
    return "\n".join(lines)


def write(data: dict | None = None) -> tuple[Path, Path]:
    data = data if data is not None else verify_all()
    content_digest = _digest(data)

    _write(RESULT_DIR / "results.json", {"cases": data["cases"]})
    _write(RESULT_DIR / "summary.json", data["summary"])
    _write(
        RESULT_DIR / "manifest.json",
        _manifest(
            RESULT_DIR, content_digest,
            "./scripts/run_benchmarks.sh run-action-replacement",
            "./scripts/run_benchmarks.sh validate-action-replacement",
        ),
    )

    report = _report(data)
    _write(REPORT_DIR / "report.json", report)
    (REPORT_DIR).mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "README.md").write_text(_readme(data), encoding="utf-8")
    _write(
        REPORT_DIR / "manifest.json",
        _manifest(
            REPORT_DIR, _digest(report),
            "./scripts/run_benchmarks.sh run-action-replacement",
            "./scripts/run_benchmarks.sh validate-action-replacement",
        ),
    )
    return RESULT_DIR, REPORT_DIR


def validate(directory: Path) -> bool:
    """Re-verify a committed directory's file digests, then confirm the
    live verification still reproduces the committed content digest."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, digest in manifest["file_digests"].items():
        actual = _file_digest(directory / name)
        if actual != digest:
            raise ValueError(f"file digest mismatch for {name} in {directory}")
    # Reproduce the content digest from a fresh run.
    data = verify_all()
    if directory == RESULT_DIR:
        recomputed = _digest(data)
    else:
        recomputed = _digest(_report(data))
    if recomputed != manifest["content_digest"]:
        raise ValueError(f"content digest not reproduced for {directory}")
    return True
