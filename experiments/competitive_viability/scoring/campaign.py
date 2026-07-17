"""Scoring campaign: freeze, orchestrate, aggregate, write artifacts.

Reads the frozen viability manifest and the raw completed execution
records, applies the frozen method assignment (deterministic first,
blinded judge only where needed), and produces per-(case, system) score
records plus aggregate answer-quality metrics. It never mutates the raw
records or the manifest, never scores not_applicable/failed executions,
and produces no competitive profile or go/no-go decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from experiments.competitive_viability.scoring import (
    EVALUATOR_VERSION,
    JUDGE_PROMPT_VERSION,
    METHOD_DETERMINISTIC,
    METHOD_JUDGE,
    VERDICT_FIELDS,
)
from experiments.competitive_viability.scoring.criteria import (
    build_case_criteria,
    deterministic_verdict,
)
from experiments.competitive_viability.scoring.judge import (
    BlindedJudge,
    JudgeCriteria,
    JUDGE_STATUS_OK,
    assign_candidate_ids,
    build_judge_request,
    judge_input_hash,
)

COMPLETED = "completed"
NOT_APPLICABLE = "not_applicable"

EXCLUDE_NOT_APPLICABLE = "not_applicable_execution"
EXCLUDE_JUDGE_FAILURE = "judge_failure"
EXCLUDE_NOT_SCORABLE = "case_not_scorable"

DEFAULT_JUDGE_SEED = 20260717


def source_record_hash(record) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass
class ScoreRecord:
    run_id: str
    case_id: str
    system_id: str
    source_record_hash: str
    method: str
    verdict: dict | None
    applicability_mask: dict | None
    reason_codes: list
    evaluator_version: str
    criteria_reference: str
    judge_required: bool
    judge_model: str | None
    judge_prompt_version: str | None
    judge_input_hash: str | None
    judge_output_status: str | None
    parse_status: str | None
    retry_count: int
    adjudication_reason: str | None
    exclusion_status: str | None
    exclusion_reason: str | None
    scoring_timestamp: str
    candidate_id: str | None = None
    error: str | None = None

    def to_payload(self) -> dict:
        return dict(self.__dict__)


def _turn_views(record):
    turns = record["execution"]["turns"]
    evidence = [t["message"] for t in turns[:-1]]
    question = turns[-1]["message"]
    answer = turns[-1]["response"] or ""
    return evidence, question, answer


def _judge_criteria(case_criteria) -> JudgeCriteria:
    return JudgeCriteria(
        current_values=case_criteria.current_values,
        stale_values=case_criteria.stale_values,
        forgotten_values=case_criteria.forgotten_values,
        expect_abstention=case_criteria.expect_abstention,
    )


def _mask_from_verdict(verdict) -> dict:
    return {f: (verdict.get(f) is not None) for f in VERDICT_FIELDS}


def score_records(
    records,
    criteria_by_case,
    *,
    run_id,
    judge=None,
    judge_model=None,
    judge_seed=DEFAULT_JUDGE_SEED,
    timestamp="unset",
):
    """Score all completed records; skip not_applicable/failed (no score
    record). Judge requests are blinded and ordered by a seeded shuffle.
    Returns (score_records, judge_tasks) where judge_tasks are the raw
    blinded requests kept locally for traceability."""
    completed = [r for r in records if r["status"] == COMPLETED]
    # Reproducible opaque candidate ids + judge order over judge-eligible
    # completed records only.
    judge_keys = [
        (r["system_id"], r["case_id"]) for r in completed
        if criteria_by_case[r["case_id"]].method == METHOD_JUDGE
    ]
    assignments = assign_candidate_ids(judge_keys, judge_seed)
    candidate_by_key = {tuple(a["key"]): a["candidate_id"] for a in assignments}

    scored = []
    judge_tasks = []
    # Judge in the shuffled order to avoid system-adjacent ordering.
    ordered = {tuple(a["key"]): i for i, a in enumerate(assignments)}

    def sort_key(rec):
        key = (rec["system_id"], rec["case_id"])
        return ordered.get(key, -1)

    for record in sorted(completed, key=sort_key):
        case_id = record["case_id"]
        criteria = criteria_by_case[case_id]
        srh = source_record_hash(record)
        base = dict(
            run_id=run_id, case_id=case_id, system_id=record["system_id"],
            source_record_hash=srh, evaluator_version=EVALUATOR_VERSION,
            criteria_reference=f"scenario:{case_id}:expected",
            adjudication_reason=None, scoring_timestamp=timestamp,
        )
        _, _, answer = _turn_views(record)
        if criteria.method == METHOD_DETERMINISTIC:
            verdict, mask, reasons = deterministic_verdict(criteria, answer)
            scored.append(ScoreRecord(
                method=METHOD_DETERMINISTIC, verdict=verdict,
                applicability_mask=mask, reason_codes=reasons,
                judge_required=False, judge_model=None,
                judge_prompt_version=None, judge_input_hash=None,
                judge_output_status=None, parse_status="deterministic",
                retry_count=0, error=None, exclusion_status=None,
                exclusion_reason=None, **base,
            ))
            continue
        # Blinded judge path.
        evidence, question, ans = _turn_views(record)
        candidate_id = candidate_by_key[(record["system_id"], case_id)]
        messages = build_judge_request(
            candidate_id, question, evidence, _judge_criteria(criteria), ans
        )
        jih = judge_input_hash(messages)
        judge_tasks.append({
            "candidate_id": candidate_id, "judge_input_hash": jih,
            "messages": messages,
        })
        if judge is None:
            # No judge available: preserve as an explicit judge failure.
            scored.append(ScoreRecord(
                method=METHOD_JUDGE, verdict=None, applicability_mask=None,
                reason_codes=[], judge_required=True, judge_model=judge_model,
                judge_prompt_version=JUDGE_PROMPT_VERSION,
                judge_input_hash=jih, judge_output_status="not_run",
                parse_status="not_run", retry_count=0,
                exclusion_status="excluded",
                exclusion_reason=EXCLUDE_JUDGE_FAILURE,
                candidate_id=candidate_id, error="judge_not_available",
                **base,
            ))
            continue
        result = judge.judge(messages)
        if result["status"] == JUDGE_STATUS_OK:
            verdict = result["verdict"]
            scored.append(ScoreRecord(
                method=METHOD_JUDGE, verdict=verdict,
                applicability_mask=_mask_from_verdict(verdict),
                reason_codes=result["reason_codes"], judge_required=True,
                judge_model=judge_model,
                judge_prompt_version=JUDGE_PROMPT_VERSION,
                judge_input_hash=jih, judge_output_status="ok",
                parse_status="ok", retry_count=result["retries"],
                exclusion_status=None, exclusion_reason=None,
                candidate_id=candidate_id, error=None, **base,
            ))
        else:
            scored.append(ScoreRecord(
                method=METHOD_JUDGE, verdict=None, applicability_mask=None,
                reason_codes=[], judge_required=True, judge_model=judge_model,
                judge_prompt_version=JUDGE_PROMPT_VERSION,
                judge_input_hash=jih, judge_output_status=result["status"],
                parse_status=result["status"], retry_count=result["retries"],
                exclusion_status="excluded",
                exclusion_reason=EXCLUDE_JUDGE_FAILURE,
                candidate_id=candidate_id, error=result["error"], **base,
            ))
    return scored, judge_tasks


# -- aggregation --------------------------------------------------------------


def _rate(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percentage": round(100.0 * numerator / denominator, 2)
        if denominator else None,
    }


def _scored(sr) -> bool:
    return sr.verdict is not None and sr.exclusion_status is None


def aggregate_by_system(score_records) -> dict:
    systems = {}
    for sr in score_records:
        systems.setdefault(sr.system_id, []).append(sr)
    out = {}
    for system_id, records in systems.items():
        scored = [r for r in records if _scored(r)]
        excluded = [r for r in records if not _scored(r)]

        def applies(r, field):
            return r.applicability_mask.get(field)

        correct = [r for r in scored if applies(r, "correct")]
        current = [r for r in scored if applies(r, "uses_current_information")]
        stale = [r for r in scored if applies(r, "uses_stale_information")]
        pref = [r for r in scored if applies(r, "follows_user_preferences")]
        abst = [r for r in scored if applies(r, "abstention_correct")]

        out[system_id] = {
            "final_answer_accuracy": _rate(
                sum(1 for r in correct if r.verdict["correct"]), len(correct)
            ),
            "current_information_accuracy": _rate(
                sum(1 for r in current
                    if r.verdict["uses_current_information"] is True
                    and r.verdict.get("uses_stale_information") is not True),
                len(current),
            ),
            "stale_information_use_rate": _rate(
                sum(1 for r in stale
                    if r.verdict["uses_stale_information"] is True),
                len(stale),
            ),
            "preference_adherence_accuracy": _rate(
                sum(1 for r in pref
                    if r.verdict["follows_user_preferences"] is True),
                len(pref),
            ),
            "unsupported_claim_rate": _rate(
                sum(1 for r in scored
                    if r.verdict.get("unsupported_claim") is True),
                len(scored),
            ),
            "abstention_accuracy": _rate(
                sum(1 for r in abst
                    if r.verdict["abstention_correct"] is True),
                len(abst),
            ),
            "scored_records": len(scored),
            "excluded_records": len(excluded),
        }
    return out


def method_distribution(score_records) -> dict:
    dist = {}
    for sr in score_records:
        dist[sr.method] = dist.get(sr.method, 0) + 1
    return dist


def judge_usage(score_records) -> dict:
    judge = [r for r in score_records if r.method == METHOD_JUDGE]
    return {
        "judge_records": len(judge),
        "judge_ok": sum(1 for r in judge if r.judge_output_status == "ok"),
        "judge_failures": sum(
            1 for r in judge if r.exclusion_reason == EXCLUDE_JUDGE_FAILURE
        ),
        "malformed": sum(
            1 for r in judge if r.judge_output_status == "malformed"
        ),
        "total_retries": sum(r.retry_count for r in judge),
    }


def freeze_manifest(*, viability_manifest_hash, raw_records_hash, judge_model,
                    judge_seed, git_commit) -> dict:
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "viability_manifest_hash": viability_manifest_hash,
        "raw_records_hash": raw_records_hash,
        "normalization_rules": "casefold + whitespace-collapse; substring match",
        "rule_definitions": "criteria.deterministic_verdict",
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "judge_model": judge_model,
        "judge_parameters": {"temperature": 0.0},
        "judge_task_ordering_seed": judge_seed,
        "aggregation_formulas": "campaign.aggregate_by_system",
        "exclusion_rules": [
            EXCLUDE_NOT_APPLICABLE, EXCLUDE_JUDGE_FAILURE, EXCLUDE_NOT_SCORABLE,
        ],
        "git_commit": git_commit,
    }
