"""Curated, committable scoring evidence.

Sanitized aggregate and per-case answer-quality evidence: structured
verdicts, method assignment, counts, denominators, and artifact hashes —
never raw answer text, provider payloads, or secrets. Produces
answer-quality evidence only; contains no competitive-profile fields.
"""

from __future__ import annotations

from experiments.competitive_viability.scoring import (
    EVALUATOR_VERSION,
    JUDGE_PROMPT_VERSION,
    VERDICT_FIELDS,
)
from experiments.competitive_viability.scoring.campaign import (
    aggregate_by_system,
    judge_usage,
    method_distribution,
)
from experiments.competitive_viability.scoring.judge import _SYSTEM_PROMPT


def _rate(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percentage": round(100.0 * numerator / denominator, 2)
        if denominator else None,
    }


def category_aggregate(score_records, category_by_case) -> dict:
    """Final-answer accuracy by frozen category (counts only)."""
    cats = {}
    for sr in score_records:
        if sr.verdict is None or sr.exclusion_status is not None:
            continue
        cat = category_by_case.get(sr.case_id, "unknown")
        bucket = cats.setdefault(cat, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if sr.verdict.get("correct") is True:
            bucket["correct"] += 1
    return {c: _rate(v["correct"], v["total"]) for c, v in sorted(cats.items())}


def _method_assignment(criteria_by_case) -> dict:
    assignment = {cid: c.method for cid, c in sorted(criteria_by_case.items())}
    counts = {}
    for method in assignment.values():
        counts[method] = counts.get(method, 0) + 1
    return {"per_case": assignment, "counts": counts}


def _per_case_verdicts(score_records) -> list:
    """Bounded per-case verdicts: ids, method, verdict, hashes — no text."""
    out = []
    for sr in score_records:
        out.append({
            "case_id": sr.case_id,
            "system_id": sr.system_id,
            "method": sr.method,
            "verdict": sr.verdict,
            "exclusion_reason": sr.exclusion_reason,
            "source_record_hash": sr.source_record_hash[:16],
            "judge_output_status": sr.judge_output_status,
        })
    return out


def build_committed_evidence(
    score_records, *, freeze, criteria_by_case, category_by_case,
    artifact_hashes,
) -> dict:
    excluded = [r for r in score_records if r.exclusion_status is not None]
    exclusion_counts = {}
    for r in excluded:
        exclusion_counts[r.exclusion_reason] = (
            exclusion_counts.get(r.exclusion_reason, 0) + 1
        )
    return {
        "note": (
            "answer-quality evidence only; no competitive profile, ranking, "
            "or go/no-go decision"
        ),
        "scoring_config": {
            k: v for k, v in freeze.items()
            if k not in ("git_commit",)
        },
        "git_commit": freeze.get("git_commit"),
        "evaluator_version": EVALUATOR_VERSION,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "judge_system_prompt": _SYSTEM_PROMPT,
        "verdict_fields": list(VERDICT_FIELDS),
        "method_assignment": _method_assignment(criteria_by_case),
        "method_distribution": method_distribution(score_records),
        "judge_usage": judge_usage(score_records),
        "score_counts": {
            "total_score_records": len(score_records),
            "scored": sum(
                1 for r in score_records
                if r.verdict is not None and r.exclusion_status is None
            ),
            "excluded": len(excluded),
            "exclusion_counts": exclusion_counts,
        },
        "aggregate_by_system": aggregate_by_system(score_records),
        "category_answer_accuracy": category_aggregate(
            score_records, category_by_case
        ),
        "per_case_verdicts": _per_case_verdicts(score_records),
        "artifact_hashes": artifact_hashes,
    }
