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
from benchmarks.action_replacement import adoption as adoption_eval

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULT_DIR = REPO_ROOT / "benchmarks/results/committed/action-replacement"
REPORT_DIR = REPO_ROOT / "benchmarks/results/committed/report-action-replacement"
ADOPTION_DIR = REPO_ROOT / "benchmarks/results/committed/action-replacement-adoption"
ADOPTION_REPORT_DIR = (
    REPO_ROOT / "benchmarks/results/committed/report-action-replacement-adoption"
)

CONTRACT = REPO_ROOT / "docs/action_replacement_contract.md"
CORPUS_ROOT = REPO_ROOT / "benchmarks/annotations/transition-verification"
FROZEN_GATE_SUMMARY = (
    REPO_ROOT
    / "benchmarks/results/committed/report-transition-verification/gate_summary.json"
)


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


# --- adoption gate re-evaluation --------------------------------------------


def _adoption_report(evaluation: dict) -> dict:
    return {
        "classification": evaluation["classification"],
        "classification_rationale": evaluation["classification_rationale"],
        "duplicate_metrics": evaluation["duplicate_metrics"],
        "stale_pairs": evaluation["stale_pairs"],
        "gate1": evaluation["gate1"],
        "gate6": evaluation["gate6"],
        "tally": evaluation["tally"],
        "blocking_gates": evaluation["blocking_gates"],
        "additional_conditions_all_pass": evaluation[
            "additional_conditions_all_pass"
        ],
        "canonical_controller": evaluation["canonical_controller"],
        "runtime_default": evaluation["runtime_default"],
    }


def _adoption_readme(evaluation: dict) -> str:
    m = evaluation["duplicate_metrics"]
    t = evaluation["tally"]
    g1 = evaluation["gate1"]
    lines = [
        "# Action Replacement — Adoption Gate Re-Evaluation",
        "",
        f"## Classification: **{evaluation['classification']}**",
        "",
        evaluation["classification_rationale"],
        "",
        f"- Duplicate pairs: reference **{m['reference']}**, append "
        f"**{m['append']}**, replacement **{m['replacement']}**",
        f"- Supersede-bearing class: **{m['supersede_bearing_append']} → "
        f"{m['supersede_bearing_replacement']}**",
        f"- Pure-create residual (out of scope): **{m['pure_create_residual']}**",
        f"- Gates: **{t['passed']} pass / {t['failed']} fail / "
        f"{t['inconclusive']} inconclusive** (unchanged framework)",
        f"- Blocking gates {evaluation['blocking_gates']['numbers']}: "
        f"all pass = **{evaluation['blocking_gates']['all_pass']}**",
        f"- Gate 1: **{g1['replacement_decision'].upper()}** "
        f"(threshold: {g1['threshold']}); the class is eliminated but 4 "
        f"residual pairs vs reference 0 keep the overall gate failed",
        f"- Gate 6: **{evaluation['gate6']['replacement_decision'].upper()}** "
        f"(non-blocking)",
        f"- Canonical controller: **{evaluation['canonical_controller']}**; "
        f"runtime default: **{evaluation['runtime_default']}**",
        "",
        "The transition path is **not adopted**: a failed quality gate (Gate 1) "
        "blocks adoption even though every blocking safety gate passes. Gate "
        "definitions, thresholds, and frozen evidence are unchanged; the "
        "overall frozen metric is reported alongside the supersede-bearing "
        "class metric and is not split to hide the residual.",
        "",
        "Regenerate: `./scripts/run_benchmarks.sh run-action-replacement-adoption`  ",
        "Verify: `./scripts/run_benchmarks.sh validate-action-replacement-adoption`",
        "",
    ]
    return "\n".join(lines)


def _frozen_references() -> dict:
    return {
        "frozen_gate_summary_digest": _file_digest(FROZEN_GATE_SUMMARY),
        "transition_contract_commit": _commit(
            REPO_ROOT / "docs/transition_verification_contract.md"
        ),
        "action_replacement_contract_commit": _commit(CONTRACT),
        "corpus_commit": _commit(CORPUS_ROOT),
    }


def _adoption_manifest(directory: Path, content_digest: str) -> dict:
    base = _manifest(
        directory, content_digest,
        "./scripts/run_benchmarks.sh run-action-replacement-adoption",
        "./scripts/run_benchmarks.sh validate-action-replacement-adoption",
    )
    base["frozen_references"] = _frozen_references()
    return base


def write_adoption(evaluation: dict | None = None) -> tuple[Path, Path]:
    evaluation = evaluation if evaluation is not None else adoption_eval.evaluate()
    verification = json.loads((RESULT_DIR / "summary.json").read_text())
    headline = json.loads(
        (REPO_ROOT / "benchmarks/results/committed/report-transition-verification"
         / "headline_metrics.json").read_text()
    )
    systems = adoption_eval.systems(headline, verification)

    _write(ADOPTION_DIR / "systems.json", {"systems": systems})
    _write(ADOPTION_DIR / "gate_evaluation.json", {
        "gates": evaluation["gates"],
        "tally": evaluation["tally"],
        "blocking_gates": evaluation["blocking_gates"],
        "gate1": evaluation["gate1"],
        "gate6": evaluation["gate6"],
        "additional_conditions": evaluation["additional_conditions"],
    })
    _write(ADOPTION_DIR / "classification.json", {
        "classification": evaluation["classification"],
        "classification_rationale": evaluation["classification_rationale"],
        "classification_inputs": evaluation["classification_inputs"],
        "canonical_controller": evaluation["canonical_controller"],
        "runtime_default": evaluation["runtime_default"],
        "duplicate_metrics": evaluation["duplicate_metrics"],
        "stale_pairs": evaluation["stale_pairs"],
        "downstream_context": evaluation["downstream_context"],
        "latency": evaluation["latency"],
    })
    _write(
        ADOPTION_DIR / "manifest.json",
        _adoption_manifest(ADOPTION_DIR, _digest(evaluation)),
    )

    report = _adoption_report(evaluation)
    _write(ADOPTION_REPORT_DIR / "report.json", report)
    ADOPTION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (ADOPTION_REPORT_DIR / "README.md").write_text(
        _adoption_readme(evaluation), encoding="utf-8"
    )
    _write(
        ADOPTION_REPORT_DIR / "manifest.json",
        _adoption_manifest(ADOPTION_REPORT_DIR, _digest(report)),
    )
    return ADOPTION_DIR, ADOPTION_REPORT_DIR


def validate(directory: Path) -> bool:
    """Re-verify a committed directory's file digests, then confirm the
    live evaluation still reproduces the committed content digest."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, digest in manifest["file_digests"].items():
        actual = _file_digest(directory / name)
        if actual != digest:
            raise ValueError(f"file digest mismatch for {name} in {directory}")
    if directory == RESULT_DIR:
        recomputed = _digest(verify_all())
    elif directory == REPORT_DIR:
        recomputed = _digest(_report(verify_all()))
    elif directory == ADOPTION_DIR:
        recomputed = _digest(adoption_eval.evaluate())
    elif directory == ADOPTION_REPORT_DIR:
        recomputed = _digest(_adoption_report(adoption_eval.evaluate()))
    else:
        raise ValueError(f"unknown artifact directory {directory}")
    if recomputed != manifest["content_digest"]:
        raise ValueError(f"content digest not reproduced for {directory}")
    return True
