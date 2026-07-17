"""Tests for end-to-end final-answer scoring.

Offline and deterministic: deterministic/rule scoring runs on fixed
examples; the judge is exercised with stub providers (canned/malformed/
raising) — no live call. Covers method assignment, deterministic scoring
of every verdict field, judge blinding/schema/retry/failure preservation,
campaign orchestration, exclusions, aggregation denominators, secret
exclusion, and non-mutation of raw evidence.
"""

from __future__ import annotations

import json

from benchmarks.scenarios.loader import load_dataset, load_manifest
from experiments.competitive_viability.scoring import (
    METHOD_DETERMINISTIC,
    METHOD_JUDGE,
    VERDICT_FIELDS,
)
from experiments.competitive_viability.scoring.criteria import (
    build_case_criteria,
    deterministic_verdict,
    normalize,
)
from experiments.competitive_viability.scoring.judge import (
    BlindedJudge,
    JudgeCriteria,
    assign_candidate_ids,
    build_judge_request,
    judge_input_hash,
    parse_judge_output,
    request_mentions_system,
)
from experiments.competitive_viability.scoring.campaign import (
    EXCLUDE_JUDGE_FAILURE,
    aggregate_by_system,
    freeze_manifest,
    judge_usage,
    method_distribution,
    score_records,
    source_record_hash,
)

_CASES = {s.case.scenario_id: s.case for s in load_dataset(load_manifest())}


def _criteria(case_id):
    return build_case_criteria(_CASES[case_id])


# -- criteria / method assignment --------------------------------------------


def test_method_assignment_deterministic_vs_judge():
    # updates_002 has must_exclude -> deterministic; abstention -> judge;
    # creation_002 has no response criteria -> judge.
    assert _criteria("updates_002_fact_correction").method == METHOD_DETERMINISTIC
    assert _criteria("retrieval_007_correct_abstention").method == METHOD_JUDGE
    assert _criteria("creation_002_durable_user_fact").method == METHOD_JUDGE


# -- deterministic scorer: every field ---------------------------------------


def test_deterministic_current_value_present_is_correct():
    c = _criteria("retrieval_008_stale_would_mislead")  # any Pixel 9, excl Pixel 6
    verdict, mask, _ = deterministic_verdict(c, "Your current phone is the Pixel 9.")
    assert verdict["correct"] is True
    assert verdict["uses_current_information"] is True
    assert verdict["uses_stale_information"] is False
    assert verdict["unsupported_claim"] is False


def test_deterministic_stale_value_detected():
    c = _criteria("retrieval_008_stale_would_mislead")
    verdict, mask, _ = deterministic_verdict(c, "You use the Pixel 6.")
    assert verdict["uses_stale_information"] is True
    assert verdict["unsupported_claim"] is True   # forbidden value surfaced
    assert verdict["correct"] is False


def test_deterministic_missing_expected_value_is_incorrect():
    c = _criteria("retrieval_001_one_relevant_among_many")  # must_include_any pytest
    verdict, _, _ = deterministic_verdict(c, "I will help with your project.")
    assert verdict["correct"] is False
    assert verdict["uses_current_information"] is False


def test_deterministic_non_applicable_fields_are_null():
    c = _criteria("updates_002_fact_correction")  # only must_exclude
    verdict, mask, _ = deterministic_verdict(c, "You work from the new office.")
    assert verdict["uses_current_information"] is None
    assert mask["uses_current_information"] is False
    assert verdict["abstention_correct"] is None


def test_normalize_is_casefold_whitespace():
    assert normalize("  Pixel   9 ") == "pixel 9"


# -- judge: schema, blinding, retry, failure ---------------------------------


def _judge_json(**over):
    base = {
        "correct": True, "uses_current_information": None,
        "uses_stale_information": False, "follows_user_preferences": None,
        "unsupported_claim": False, "abstention_correct": None,
        "reason_codes": ["SUPPORTED_CLAIM"],
    }
    base.update(over)
    return json.dumps(base)


class _StubJudge:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return self._outputs.pop(0)


def test_valid_judge_output_parses():
    verdict, codes, err = parse_judge_output(_judge_json())
    assert err is None and verdict["correct"] is True
    assert codes == ["SUPPORTED_CLAIM"]


def test_judge_rejects_extra_keys_and_bad_fields():
    assert parse_judge_output('{"correct": true, "x": 1}')[2] is not None
    assert parse_judge_output(_judge_json(correct="yes"))[2] is not None
    assert parse_judge_output("not json")[2] == "malformed_json"


def test_judge_rejects_unknown_reason_codes():
    assert parse_judge_output(_judge_json(reason_codes=["NOPE"]))[2] == (
        "bad_reason_codes"
    )


def test_judge_one_bounded_retry_then_failure():
    j = BlindedJudge(_StubJudge(["garbage", "still bad"]))
    result = j.judge([{"role": "user", "content": "x"}])
    assert result["status"] == "malformed"
    assert result["retries"] == 1  # exactly one retry


def test_judge_retry_recovers():
    j = BlindedJudge(_StubJudge(["garbage", _judge_json()]))
    result = j.judge([{"role": "user", "content": "x"}])
    assert result["status"] == "ok"
    assert result["retries"] == 1


def test_judge_provider_error_is_bounded_failure():
    class _Boom:
        def complete(self, m):
            raise RuntimeError("down")

    result = BlindedJudge(_Boom()).judge([{"role": "user", "content": "x"}])
    assert result["status"] == "provider_error"
    assert result["verdict"] is None


def test_judge_request_carries_no_system_identity():
    messages = build_judge_request(
        "cand-abc", "What phone do I use?", ["I got a Pixel 9."],
        JudgeCriteria(("pixel 9",), ("pixel 6",), (), False),
        "You use the Pixel 9.",
    )
    labels = [
        "canonical_experienceos_qwen", "deterministic_experienceos",
        "stateless", "full_history", "naive_top_k", "append_only",
        "experienceos", "qwen_update",
    ]
    assert request_mentions_system(messages, labels) is False


def test_candidate_ids_are_opaque_and_reproducible():
    keys = [("a", "c1"), ("b", "c1"), ("a", "c2")]
    one = assign_candidate_ids(keys, seed=7)
    two = assign_candidate_ids(keys, seed=7)
    assert one == two  # reproducible ordering + ids
    ids = [a["candidate_id"] for a in one]
    assert all(i.startswith("cand-") for i in ids)
    # no system label embedded in the opaque id
    assert all("stateless" not in i and "a" != i for i in ids)


# -- campaign orchestration over synthetic records ---------------------------


def _record(system_id, case_id, status, answer="ok"):
    return {
        "system_id": system_id, "case_id": case_id, "status": status,
        "execution": {"turns": [
            {"message": "setup", "response": "r0"},
            {"message": "the question", "response": answer},
        ]} if status == "completed" else None,
    }


def test_no_score_records_for_not_applicable():
    records = [
        _record("s1", "updates_002_fact_correction", "completed"),
        _record("s1", "creation_002_durable_user_fact", "not_applicable"),
    ]
    crit = {c: _criteria(c) for c in
            ("updates_002_fact_correction", "creation_002_durable_user_fact")}
    scored, _ = score_records(records, crit, run_id="r", timestamp="t")
    # Only the completed deterministic case produced a score record.
    assert len(scored) == 1
    assert scored[0].case_id == "updates_002_fact_correction"


def test_one_score_per_completed_record_and_traceability():
    records = [_record("s1", "updates_002_fact_correction", "completed",
                       "you work from the office")]
    crit = {"updates_002_fact_correction":
            _criteria("updates_002_fact_correction")}
    scored, _ = score_records(records, crit, run_id="r", timestamp="t")
    assert len(scored) == 1
    sr = scored[0]
    assert sr.source_record_hash == source_record_hash(records[0])
    assert sr.method == METHOD_DETERMINISTIC


def test_judge_failure_is_preserved_and_excluded_no_substitution():
    records = [_record("s1", "creation_002_durable_user_fact", "completed")]
    crit = {"creation_002_durable_user_fact":
            _criteria("creation_002_durable_user_fact")}
    judge = BlindedJudge(_StubJudge(["bad", "bad"]))
    scored, tasks = score_records(records, crit, run_id="r", judge=judge,
                                 judge_model="qwen-plus", timestamp="t")
    sr = scored[0]
    assert sr.verdict is None  # no substituted verdict
    assert sr.exclusion_reason == EXCLUDE_JUDGE_FAILURE
    assert sr.judge_output_status == "malformed"
    assert len(tasks) == 1


def test_no_judge_available_records_explicit_failure():
    records = [_record("s1", "creation_002_durable_user_fact", "completed")]
    crit = {"creation_002_durable_user_fact":
            _criteria("creation_002_durable_user_fact")}
    scored, _ = score_records(records, crit, run_id="r", timestamp="t")
    assert scored[0].exclusion_reason == EXCLUDE_JUDGE_FAILURE
    assert scored[0].judge_output_status == "not_run"


def test_aggregate_denominators_use_applicability_masks():
    # One deterministic stale case (excl value absent) -> correct.
    records = [_record("s1", "updates_002_fact_correction", "completed",
                       "you work from the new office")]
    crit = {"updates_002_fact_correction":
            _criteria("updates_002_fact_correction")}
    scored, _ = score_records(records, crit, run_id="r", timestamp="t")
    agg = aggregate_by_system(scored)["s1"]
    # current-info not applicable for a must_exclude-only case: denom 0.
    assert agg["current_information_accuracy"]["denominator"] == 0
    assert agg["stale_information_use_rate"]["denominator"] == 1
    assert agg["final_answer_accuracy"] == {
        "numerator": 1, "denominator": 1, "percentage": 100.0,
    }


def test_method_distribution_and_judge_usage():
    records = [
        _record("s1", "updates_002_fact_correction", "completed", "new office"),
        _record("s1", "creation_002_durable_user_fact", "completed"),
    ]
    crit = {c: _criteria(c) for c in
            ("updates_002_fact_correction", "creation_002_durable_user_fact")}
    judge = BlindedJudge(_StubJudge([_judge_json()]))
    scored, _ = score_records(records, crit, run_id="r", judge=judge,
                             judge_model="qwen-plus", timestamp="t")
    dist = method_distribution(scored)
    assert dist[METHOD_DETERMINISTIC] == 1 and dist[METHOD_JUDGE] == 1
    usage = judge_usage(scored)
    assert usage["judge_records"] == 1 and usage["judge_ok"] == 1


# -- freeze manifest, secrets, no mutation -----------------------------------


def test_freeze_manifest_has_no_secrets():
    fm = freeze_manifest(
        viability_manifest_hash="h", raw_records_hash="rh",
        judge_model="qwen-plus", judge_seed=1, git_commit="g",
    )
    blob = json.dumps(fm).lower()
    assert "api_key" not in blob and "authorization" not in blob
    assert fm["judge_parameters"]["temperature"] == 0.0


def test_scoring_does_not_mutate_raw_records():
    records = [_record("s1", "updates_002_fact_correction", "completed", "x")]
    before = json.dumps(records, sort_keys=True)
    crit = {"updates_002_fact_correction":
            _criteria("updates_002_fact_correction")}
    score_records(records, crit, run_id="r", timestamp="t")
    assert json.dumps(records, sort_keys=True) == before


def test_score_record_serializes():
    records = [_record("s1", "updates_002_fact_correction", "completed", "x")]
    crit = {"updates_002_fact_correction":
            _criteria("updates_002_fact_correction")}
    scored, _ = score_records(records, crit, run_id="r", timestamp="t")
    payload = json.loads(json.dumps(scored[0].to_payload()))
    for key in ("run_id", "case_id", "system_id", "source_record_hash",
                "method", "verdict", "applicability_mask"):
        assert key in payload


def test_verdict_field_set_is_frozen():
    assert set(VERDICT_FIELDS) == {
        "correct", "uses_current_information", "uses_stale_information",
        "follows_user_preferences", "unsupported_claim", "abstention_correct",
    }


# -- curated committed evidence ----------------------------------------------


def test_committed_evidence_has_no_answers_or_secrets():
    from experiments.competitive_viability.scoring.evidence import (
        build_committed_evidence,
    )

    records = [_record("s1", "updates_002_fact_correction", "completed",
                       "you work from the new office")]
    crit = {"updates_002_fact_correction":
            _criteria("updates_002_fact_correction")}
    scored, _ = score_records(records, crit, run_id="r", timestamp="t")
    freeze = freeze_manifest(
        viability_manifest_hash="h", raw_records_hash="rh",
        judge_model="qwen-plus", judge_seed=1, git_commit="g")
    evidence = build_committed_evidence(
        scored, freeze=freeze, criteria_by_case=crit,
        category_by_case={"updates_002_fact_correction": "update"},
        artifact_hashes={"score_records": "abc"})
    blob = json.dumps(evidence).lower()
    assert "api_key" not in blob and "authorization" not in blob
    # No raw candidate-answer text in curated evidence.
    assert "you work from the new office" not in blob
    assert "competitive" not in evidence or "no competitive" in evidence["note"]
    # Structured, auditable fields present.
    assert evidence["score_counts"]["scored"] == 1
    assert "aggregate_by_system" in evidence
    assert "category_answer_accuracy" in evidence


def test_committed_evidence_carries_no_profile_decision():
    from experiments.competitive_viability.scoring.evidence import (
        build_committed_evidence,
    )

    records = [_record("s1", "updates_002_fact_correction", "completed", "x")]
    crit = {"updates_002_fact_correction":
            _criteria("updates_002_fact_correction")}
    scored, _ = score_records(records, crit, run_id="r", timestamp="t")
    freeze = freeze_manifest(viability_manifest_hash="h", raw_records_hash="rh",
                            judge_model="q", judge_seed=1, git_commit="g")
    evidence = build_committed_evidence(
        scored, freeze=freeze, criteria_by_case=crit,
        category_by_case={}, artifact_hashes={})
    for banned in ("go_no_go", "recommendation", "viability_demonstrated",
                   "profile_decision", "competitively_superior"):
        assert banned not in json.dumps(evidence).lower()
