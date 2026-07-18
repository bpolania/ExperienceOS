"""Deterministic report builder over the committed live-campaign records.

Reads raw_case_results.jsonl + scoring_results.jsonl + aggregate_by_system.json
(single live sample) and the frozen Phase 17 evidence (read-only), and
emits the derived comparison artifacts. Pure over already-recorded data;
no live calls, no secrets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "benchmarks/results/committed/canonical-lifecycle-activation-live"
FROZEN = REPO / "benchmarks/results/committed/competitive-viability"

GENUINE = [
    "context_005_active_and_inactive_versions",
    "retrieval_008_stale_would_mislead",
    "containment_002_supersede_inactive_target",
    "forgetting_005_forgotten_leakage_check",
]
FALSE_POSITIVES = [
    "updates_001_preference_replacement_cross_session",
    "updates_003_instruction_replacement",
    "updates_008_repeated_correction_chain",
    "context_006_minimal_context_sufficient",
    "forgetting_002_paraphrased_forget",
]
SYSTEMS = ["canonical_experienceos_qwen", "deterministic_experienceos",
           "stateless", "full_history", "naive_top_k", "append_only"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load():
    scored = [json.loads(l) for l in (OUT / "scoring_results.jsonl").open()]
    raw = [json.loads(l) for l in (OUT / "raw_case_results.jsonl").open()]
    live = json.loads((OUT / "aggregate_by_system.json").read_text())
    frozen = json.loads((FROZEN / "scoring_evidence.json").read_text())["aggregate_by_system"]
    return scored, raw, live, frozen


def pct(a, k):
    v = a.get(k, {})
    return v.get("numerator"), v.get("denominator"), v.get("percentage")


def aggregate_metrics(live, frozen):
    metrics = ["final_answer_accuracy", "current_information_accuracy",
               "stale_information_use_rate", "preference_adherence_accuracy",
               "unsupported_claim_rate", "abstention_accuracy"]
    out = {}
    for s in SYSTEMS:
        out[s] = {}
        for m in metrics:
            fn, fd, fp = pct(frozen[s], m)
            ln, ld, lp = pct(live[s], m)
            out[s][m] = {
                "phase17": {"numerator": fn, "denominator": fd, "percentage": fp},
                "phase20_live": {"numerator": ln, "denominator": ld, "percentage": lp},
                "delta_points": (round(lp - fp, 2) if lp is not None and fp is not None
                                 else None),
            }
    return out


def competitive(live):
    canon = live["canonical_experienceos_qwen"]["final_answer_accuracy"]["percentage"]
    baselines = {s: live[s]["final_answer_accuracy"]["percentage"]
                 for s in SYSTEMS if s != "canonical_experienceos_qwen"}
    strongest = max(baselines, key=baselines.get)
    gap = round(baselines[strongest] - canon, 2)
    within = gap <= 5.0
    equals_or_exceeds = canon >= baselines[strongest]
    decision = ("COMPETITIVE_VIABILITY_DEMONSTRATED" if equals_or_exceeds
                else "COMPETITIVE_VIABILITY_COMPARABLE_WITH_NOTES" if within
                else "COMPETITIVE_VIABILITY_NOT_YET_DEMONSTRATED")
    return {
        "canonical_final_answer_accuracy_pct": canon,
        "baselines_final_answer_accuracy_pct": baselines,
        "strongest_baseline": strongest,
        "strongest_baseline_pct": baselines[strongest],
        "gap_points": gap,
        "within_five_point_comparability_heuristic": within,
        "equals_or_exceeds_strongest": equals_or_exceeds,
        "competitive_decision": decision,
        "notes": [
            "single live sample per system (as in frozen Phase 17); live model "
            "outputs are stochastic and not byte-reproducible",
            "all six systems rerun in the same campaign under one shared "
            "response model (qwen-plus), so the comparison is internally aligned",
        ],
    }


def phase18_followup(scored):
    def verdict(cid):
        r = next((r for r in scored if r["case_id"] == cid
                  and r["system_id"] == "canonical_experienceos_qwen"), None)
        v = (r.get("verdict") or {}) if r else {}
        return r, v
    rows = []
    for cid in GENUINE + FALSE_POSITIVES:
        r, v = verdict(cid)
        genuine = cid in GENUINE
        correct = v.get("correct")
        uses_stale = v.get("uses_stale_information")
        if genuine:
            outcome = ("fixed_by_lifecycle_activation" if correct and not uses_stale
                       else "unchanged_genuine_stale_failure")
        else:
            outcome = ("evaluator_false_positive_resolved"
                       if correct and not uses_stale
                       else "evaluator_false_positive_remains")
        rows.append({
            "case_id": cid,
            "phase18_classification": "genuine_stale_answer" if genuine
                else "evaluator_false_positive",
            "phase20_live_correct": correct,
            "phase20_live_uses_stale": uses_stale,
            "phase20_scoring_method": r["method"] if r else None,
            "phase20_outcome_classification": outcome,
        })
    return {"cases": rows}


def genuine_audit(scored, raw):
    rows = []
    for cid in GENUINE:
        s = next((r for r in scored if r["case_id"] == cid
                  and r["system_id"] == "canonical_experienceos_qwen"), None)
        rec = next((r for r in raw if r["case_id"] == cid
                    and r["system_id"] == "canonical_experienceos_qwen"), None)
        v = (s.get("verdict") or {}) if s else {}
        exe = (rec or {}).get("execution") or {}
        rows.append({
            "case_id": cid,
            "final_superseded": [m["text"] for m in exe.get("final_superseded", [])],
            "final_forgotten": [m["text"] for m in exe.get("final_forgotten", [])],
            "final_answer_excerpt": (exe.get("turns", [{}])[-1].get("response") or "")[:300],
            "scoring_method": s["method"] if s else None,
            "verdict_correct": v.get("correct"),
            "verdict_uses_current": v.get("uses_current_information"),
            "verdict_uses_stale": v.get("uses_stale_information"),
        })
    return {"cases": rows}


def integrity():
    files = ["viability_manifest.json", "stale_failure_evidence.json",
             "stale_leakage_classification.json", "execution_summary.json",
             "scoring_evidence.json", "README.md"]
    return {"note": "frozen Phase 17/18 inputs, read-only; unchanged by the live run",
            "files": [{"path": str((FROZEN / f).relative_to(REPO)),
                       "sha256": sha256(FROZEN / f)} for f in files]}


def main():
    scored, raw, live, frozen = load()
    (OUT / "aggregate_metrics.json").write_text(
        json.dumps(aggregate_metrics(live, frozen), indent=1, sort_keys=True) + "\n")
    (OUT / "competitive_decision.json").write_text(
        json.dumps(competitive(live), indent=1, sort_keys=True) + "\n")
    (OUT / "phase18_followup_live.json").write_text(
        json.dumps(phase18_followup(scored), indent=1, sort_keys=True) + "\n")
    (OUT / "four_genuine_case_audit_live.json").write_text(
        json.dumps(genuine_audit(scored, raw), indent=1, sort_keys=True) + "\n")
    (OUT / "integrity_manifest.json").write_text(
        json.dumps(integrity(), indent=1, sort_keys=True) + "\n")
    print("built reports;", json.dumps(competitive(live)["competitive_decision"]))


if __name__ == "__main__":
    main()
