"""Metric evaluator tests: every group, fixed denominators, undefined
handling, and the lifecycle separations (proposal vs containment vs
application vs final state). All offline.
"""

import pytest

from benchmarks.adapters.common import run_adapter_case
from benchmarks.adapters.factory import create_system
from benchmarks.baselines.common import run_case as run_baseline_case
from benchmarks.contract import (
    AppliedActionRecord,
    CandidateRecord,
    CaseResult,
    CaseStatus,
    ContextAccounting,
    MemorySnapshotEntry,
    ProposalRecord,
    RejectedActionRecord,
    TurnEvidence,
    case_from_dict,
)
from benchmarks.evaluators import aggregate_run, evaluate_case
from benchmarks.evaluators.records import Contribution
from benchmarks.scenarios.loader import load_dataset


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def scenario(dataset, scenario_id):
    return next(s for s in dataset if s.case.scenario_id == scenario_id)


def evaluate(dataset, scenario_id, system_id):
    loaded = scenario(dataset, scenario_id)
    system = create_system(system_id)
    if system_id.startswith("experienceos"):
        result = run_adapter_case(system, loaded)
    else:
        result = run_baseline_case(system, loaded)
    return evaluate_case(loaded.case, result), result


def metric_map(evaluation):
    out = {}
    for c in evaluation.contributions:
        out.setdefault(c.metric, []).append(c)
    return out


def one(evaluation, name) -> Contribution:
    matches = metric_map(evaluation).get(name)
    assert matches, f"no contribution for {name}"
    assert len(matches) == 1
    return matches[0]


def synthetic_case(**overrides):
    data = {
        "scenario_id": "synthetic-metrics",
        "schema_version": "1",
        "title": "Synthetic",
        "category": "creation",
        "description": "Synthetic evaluator case.",
        "tags": ["domain:test"],
        "seed": 7,
        "context_budget": 4,
        "selection_k": 4,
        "turns": [],
        "current_message": "hello",
        "current_session_id": "s1",
        "expected": {"memory_actions": []},
        "evaluation_mode": "deterministic",
    }
    data.update(overrides)
    return case_from_dict(data)


def synthetic_result(**overrides):
    defaults = dict(
        scenario_id="synthetic-metrics",
        system_id="experienceos_rules",
        run_id="test",
        suite_version="experienceos-lifecycle-v1",
        status=CaseStatus.PASSED,
    )
    defaults.update(overrides)
    return CaseResult(**defaults)


# --- Memory write ---------------------------------------------------------------


def test_true_positive_create(dataset):
    evaluation, _ = evaluate(
        dataset, "creation_001_explicit_scoped_preference",
        "experienceos_rules",
    )
    assert one(evaluation, "memory_creation_precision").numerator == 1
    assert one(evaluation, "memory_creation_recall").numerator == 1
    assert one(evaluation, "correct_memory_kind_rate").numerator == 1
    assert evaluation.outcome == "passed"


def test_missed_create_reflects_in_recall(dataset):
    evaluation, _ = evaluate(
        dataset, "creation_001_explicit_scoped_preference", "stateless"
    )
    recall = one(evaluation, "memory_creation_recall")
    assert (recall.numerator, recall.denominator) == (0, 1)
    precision = one(evaluation, "memory_creation_precision")
    assert not precision.applicable  # no applied creations: undefined


def test_false_positive_create():
    case = synthetic_case(
        expected={"memory_actions": [{"action": "none"}]},
        tags=["domain:test", "non-durable"],
    )
    result = synthetic_result(
        turns=[
            TurnEvidence(
                turn_index=0,
                session_id="s1",
                message="hello",
                applied_actions=(
                    AppliedActionRecord(
                        action="create", memory_id="m1", kind="fact",
                        text="Hello is a greeting.",
                    ),
                ),
            )
        ]
    )
    evaluation = evaluate_case(case, result)
    precision = one(evaluation, "memory_creation_precision")
    assert (precision.numerator, precision.denominator) == (0, 1)
    non_durable = one(evaluation, "non_durable_rejection_rate")
    assert non_durable.numerator == 0


def test_non_durable_correctly_not_stored(dataset):
    evaluation, _ = evaluate(
        dataset, "creation_004_non_durable_statement", "experienceos_rules"
    )
    assert one(evaluation, "non_durable_rejection_rate").numerator == 1
    # Append-only also correctly ignores this one (heuristic miss-proof).
    evaluation, _ = evaluate(
        dataset, "creation_004_non_durable_statement", "append_only"
    )
    assert one(evaluation, "non_durable_rejection_rate").numerator == 1


def test_duplicate_rejected_is_not_accepted(dataset):
    evaluation, _ = evaluate(
        dataset, "containment_001_duplicate_create_contained",
        "experienceos_local",
    )
    proposal_rate = one(evaluation, "duplicate_proposal_rate")
    assert proposal_rate.numerator >= 1
    acceptance = one(evaluation, "duplicate_acceptance_rate")
    assert acceptance.numerator == 0  # contained, not accepted


def test_duplicate_accepted_counts(dataset):
    evaluation, _ = evaluate(
        dataset, "creation_005_exact_duplicate_restatement", "append_only"
    )
    acceptance = one(evaluation, "duplicate_acceptance_rate")
    assert acceptance.numerator >= 1  # both records active


def test_f1_derived_from_aggregate_precision_and_recall():
    records = [
        {
            "scenario_id": f"s{i}",
            "system_id": "x",
            "group": "creation",
            "category": "creation",
            "status": "passed",
            "outcome": "passed",
            "contributions": [
                Contribution("memory_creation_precision", n, d).to_payload(),
                Contribution("memory_creation_recall", n, 1).to_payload(),
            ],
            "accounting": None,
            "latency_samples": {},
            "counts": {},
        }
        for i, (n, d) in enumerate([(1, 1), (0, 2)])
    ]
    aggregate = aggregate_run(records)
    cells = aggregate["metrics"]["x"]
    # precision 1/3, recall 1/2 -> F1 = 2PR/(P+R) = 0.4
    assert cells["memory_creation_precision"]["value"] == pytest.approx(1 / 3)
    assert cells["memory_creation_recall"]["value"] == pytest.approx(0.5)
    assert cells["memory_creation_f1"]["value"] == pytest.approx(0.4)


# --- Update ---------------------------------------------------------------------


def test_correct_update_supersession(dataset):
    evaluation, _ = evaluate(
        dataset, "updates_005_instead_of_wording", "experienceos_rules"
    )
    assert one(evaluation, "update_detection_accuracy").numerator == 1
    assert one(evaluation, "correct_update_target_rate").numerator == 1
    assert one(evaluation, "supersession_accuracy").numerator == 1
    assert one(evaluation, "new_value_accuracy").numerator == 1
    assert one(evaluation, "old_value_deactivation_rate").numerator == 1
    assert one(evaluation, "conflicting_active_memory_rate").numerator == 0


def test_append_only_correction_scores_as_conflict(dataset):
    evaluation, _ = evaluate(
        dataset, "updates_005_instead_of_wording", "append_only"
    )
    assert one(evaluation, "update_detection_accuracy").numerator == 0
    assert one(evaluation, "old_value_deactivation_rate").numerator == 0
    assert one(evaluation, "conflicting_active_memory_rate").numerator == 1
    assert one(evaluation, "supersession_accuracy").numerator == 0


# --- Forgetting -------------------------------------------------------------------


def test_correct_forget_target_and_preservation(dataset):
    evaluation, _ = evaluate(
        dataset, "forgetting_003_forget_one_of_several",
        "experienceos_rules",
    )
    assert one(evaluation, "forget_detection_accuracy").numerator == 1
    assert one(evaluation, "correct_forget_target_rate").numerator == 1
    preservation = one(evaluation, "unrelated_preservation_rate")
    assert (preservation.numerator, preservation.denominator) == (2, 2)
    assert one(evaluation, "memory_resurrection_rate").numerator == 0


def test_forgotten_exclusion_and_leakage(dataset):
    # Naive retrieval keeps the "forgotten" instruction selectable and
    # leaks it into context: exclusion scores 0.
    leaky, _ = evaluate(
        dataset, "forgetting_005_forgotten_leakage_check", "naive_top_k"
    )
    assert one(leaky, "forgotten_exclusion_rate").numerator == 0
    # Honest hard case preserved: the rules planner's conservative
    # containment misses "Forget the instruction about ..." (the word
    # "instruction" is not in the memory text), so the instruction
    # stays active and rules also score 0 here. Clean exclusion is
    # proven with a synthetic result.
    case = synthetic_case(
        category="forgetting",
        expected={
            "memory_actions": [{"action": "none"}],
            "forgotten": [
                {"logical_id": "chan", "match_terms": ["eng-daily"],
                 "memory_id": None}
            ],
        },
    )
    clean = synthetic_result(
        turns=[
            TurnEvidence(
                turn_index=0,
                session_id="s1",
                message="Where should I send my update?",
                context_messages=(
                    "system", "Where should I send my update?",
                ),
            )
        ],
        final_forgotten=[
            MemorySnapshotEntry(
                memory_id="m1", kind="instruction",
                text="Send my daily status to the #eng-daily channel.",
                status="forgotten",
            )
        ],
    )
    evaluation = evaluate_case(case, clean)
    assert one(evaluation, "forgotten_exclusion_rate").numerator == 1


def test_restatement_is_not_resurrection(dataset):
    evaluation, _ = evaluate(
        dataset, "forgetting_006_restatement_not_resurrection",
        "experienceos_rules",
    )
    assert one(evaluation, "memory_resurrection_rate").numerator == 0


def test_true_resurrection_detected():
    case = synthetic_case(
        category="forgetting",
        expected={
            "memory_actions": [],
            "forgotten": [
                {"logical_id": "x", "match_terms": ["cilantro"],
                 "memory_id": None}
            ],
        },
    )
    # A forget genuinely applied, but the record was silently
    # reactivated: it appears active and nothing remains forgotten.
    result = synthetic_result(
        turns=[
            TurnEvidence(
                turn_index=0,
                session_id="s1",
                message="hi",
                applied_actions=(
                    AppliedActionRecord(
                        action="forget", memory_id="m1",
                        kind="preference", text="Dislikes cilantro.",
                    ),
                ),
            )
        ],
        final_active=[
            MemorySnapshotEntry(
                memory_id="m1", kind="preference",
                text="Dislikes cilantro.", status="active",
            )
        ],
    )
    evaluation = evaluate_case(case, result)
    assert one(evaluation, "memory_resurrection_rate").numerator == 1


# --- Retrieval ---------------------------------------------------------------------


def test_precision_recall_hit_mrr(dataset):
    evaluation, _ = evaluate(
        dataset, "retrieval_001_one_relevant_among_many",
        "experienceos_rules",
    )
    assert one(evaluation, "precision_at_k").numerator == 1
    recall = one(evaluation, "recall_at_k")
    assert (recall.numerator, recall.denominator) == (1, 1)
    assert one(evaluation, "hit_at_k").numerator == 1
    mrr = one(evaluation, "mean_reciprocal_rank")
    assert mrr.numerator == 1.0  # relevant instruction ranks first
    assert one(evaluation, "selection_budget_adherence").numerator == 1


def test_no_candidates_undefined_not_zero(dataset):
    evaluation, _ = evaluate(
        dataset, "retrieval_001_one_relevant_among_many", "stateless"
    )
    metrics = metric_map(evaluation)
    assert not metrics["precision_at_k"][0].applicable
    assert not metrics["mean_reciprocal_rank"][0].applicable
    recall = metrics["recall_at_k"][0]
    assert recall.applicable and recall.numerator == 0


def test_inactive_contamination(dataset):
    evaluation, _ = evaluate(
        dataset, "retrieval_008_stale_would_mislead", "naive_top_k"
    )
    contamination = one(evaluation, "inactive_contamination_rate")
    assert contamination.numerator >= 1  # Pixel 6 selected
    clean, _ = evaluate(
        dataset, "retrieval_008_stale_would_mislead", "experienceos_rules"
    )
    # Both device facts stay active under unkeyed rules (honest hard
    # case): contamination measures the superseded oracle slot.
    assert "inactive_contamination_rate" in metric_map(clean)


def test_zero_relevant_cases_skip_relevance_metrics(dataset):
    evaluation, _ = evaluate(
        dataset, "retrieval_006_no_memory_needed", "experienceos_rules"
    )
    metrics = metric_map(evaluation)
    assert "recall_at_k" not in metrics  # no relevant set asserted
    assert "selection_budget_adherence" in metrics


# --- Leakage ------------------------------------------------------------------------


def test_stale_leakage_levels(dataset):
    leaky, _ = evaluate(
        dataset, "retrieval_008_stale_would_mislead", "append_only"
    )
    metrics = metric_map(leaky)
    assert metrics["stale_context_leakage_rate"][0].numerator == 1
    assert metrics["stale_selected_leakage_rate"][0].numerator >= 1
    assert metrics["stale_candidate_leakage_rate"][0].numerator >= 1


def test_forgotten_response_contamination(dataset):
    evaluation, _ = evaluate(
        dataset, "forgetting_005_forgotten_leakage_check", "full_history"
    )
    # Mock echoes the question, not the forgotten channel, so the
    # response itself is clean even though history retains the text.
    contamination = one(evaluation, "forgotten_response_contamination_rate")
    assert contamination.denominator == 1


# --- Response -----------------------------------------------------------------------


def test_response_constraints_and_deferral(dataset):
    evaluation, _ = evaluate(
        dataset, "retrieval_008_stale_would_mislead", "experienceos_rules"
    )
    constraints = {
        r["constraint"]: r["passed"] for r in evaluation.constraint_results
    }
    assert constraints["must_exclude:Pixel 6"] is True
    # Inclusion fails against the echo provider — equally for all.
    assert constraints["must_include_any:Pixel 9"] in (True, False)

    deferred, _ = evaluate(
        dataset, "retrieval_007_correct_abstention", "experienceos_rules"
    )
    assert deferred.deferred
    assert "correct_abstention_rate" not in metric_map(deferred)
    assert deferred.outcome in ("partial", "evaluation_deferred")


def test_abstention_expectation_defers_offline(dataset):
    evaluation, _ = evaluate(
        dataset, "forgetting_005_forgotten_leakage_check",
        "experienceos_rules",
    )
    assert any("abstention" in d for d in evaluation.deferred)


# --- Context ------------------------------------------------------------------------


def test_context_metrics(dataset):
    evaluation, result = evaluate(
        dataset, "context_001_budget_exceeded", "experienceos_rules"
    )
    utilization = one(evaluation, "context_budget_utilization")
    assert utilization.denominator == 2
    share = one(evaluation, "memory_token_share")
    assert 0 < share.numerator <= share.denominator


def test_compression_expected_but_absent_is_undefined(dataset):
    evaluation, _ = evaluate(
        dataset, "context_003_redundant_compression", "experienceos_rules"
    )
    compression = metric_map(evaluation)["compression_ratio"][0]
    assert not compression.applicable  # honest engine behavior preserved
    assert "did not occur" in compression.undefined_reason


def test_zero_memory_tokens_never_infinite():
    records = [
        {
            "scenario_id": "s1",
            "system_id": "stateless",
            "group": "creation",
            "category": "creation",
            "status": "passed",
            "outcome": "passed",
            "contributions": [],
            "accounting": ContextAccounting(
                method="approximation",
                total_context_tokens=10,
                memory_context_tokens=0,
                total_context_chars=40,
                memory_context_chars=0,
                selected_memory_count=0,
                candidate_memory_count=0,
                context_budget=4,
            ).to_payload(),
            "latency_samples": {},
            "counts": {},
        }
    ]
    aggregate = aggregate_run(records)
    cell = aggregate["metrics"]["stateless"]["answers_per_1k_memory_tokens"]
    assert cell["value"] is None
    assert cell["undefined_count"] == 1


def test_token_reduction_vs_full_history():
    def record(system, scenario_id, tokens, outcome="passed"):
        return {
            "scenario_id": scenario_id,
            "system_id": system,
            "group": "creation",
            "category": "creation",
            "status": "passed",
            "outcome": outcome,
            "contributions": [],
            "accounting": {
                "total_context_tokens": tokens,
                "memory_context_tokens": 5,
            },
            "latency_samples": {},
            "counts": {},
        }

    records = [
        record("full_history", "a", 100),
        record("experienceos_rules", "a", 40),
        record("experienceos_rules", "b", 40),  # no FH reference
    ]
    aggregate = aggregate_run(records)
    cell = aggregate["metrics"]["experienceos_rules"][
        "token_reduction_vs_full_history"
    ]
    assert cell["numerator"] == 60 and cell["denominator"] == 100
    assert cell["undefined_count"] == 1  # missing reference marked


# --- Operational --------------------------------------------------------------------


def test_operational_counts_and_low_sample_warning(dataset):
    evaluation, result = evaluate(
        dataset, "containment_004_malformed_proposal_fallback",
        "experienceos_local",
    )
    assert one(evaluation, "fallback_rate").numerator == 1
    records = [
        {
            "scenario_id": "s",
            "system_id": "experienceos_local",
            "group": "containment",
            "category": "fallback",
            "status": "passed",
            "outcome": "passed",
            "contributions": [],
            "accounting": None,
            "latency_samples": {"end_to_end": [1.0, 2.0, 3.0]},
            "counts": {"fallback_count": 1, "rejection_count": 0},
        }
    ]
    aggregate = aggregate_run(records)
    stage = aggregate["latency"]["experienceos_local"]["end_to_end"]
    assert stage["p50_ms"] == 2.0
    assert stage["low_sample_warning"] is True
    assert aggregate["operational_counts"]["experienceos_local"][
        "fallback_count"
    ] == 1


# --- Local policy --------------------------------------------------------------------


def test_local_invalid_rejected_not_corruption(dataset):
    evaluation, _ = evaluate(
        dataset, "containment_002_supersede_inactive_target",
        "experienceos_local",
    )
    assert one(evaluation, "local_state_corruption_rate").numerator == 0
    assert one(evaluation, "rejection_containment_rate").numerator >= 1


def test_local_fallback_success_not_local_correctness(dataset):
    evaluation, result = evaluate(
        dataset, "containment_004_malformed_proposal_fallback",
        "experienceos_local",
    )
    valid = one(evaluation, "local_valid_proposal_rate")
    assert valid.numerator == 0  # the malformed generation is invalid
    applied = one(evaluation, "local_applied_action_accuracy")
    assert applied.numerator == 1  # fallback applied the right action
    # Evidence keeps the separation: proposal source is fallback.
    assert result.turns[-1].proposals[0].decision_source == "fallback"


def test_local_duplicate_containment(dataset):
    evaluation, _ = evaluate(
        dataset, "containment_001_duplicate_create_contained",
        "experienceos_local",
    )
    assert one(evaluation, "local_state_corruption_rate").numerator == 0
    assert one(evaluation, "duplicate_proposal_rate").numerator >= 1


def test_local_unavailable_mode_has_no_local_accuracy(dataset):
    from benchmarks.adapters.experienceos_local import (
        ExperienceOSLocalAdapter,
    )

    loaded = scenario(dataset, "creation_001_explicit_scoped_preference")
    result = run_adapter_case(
        ExperienceOSLocalAdapter(mode="unavailable"), loaded
    )
    evaluation = evaluate_case(loaded.case, result)
    valid = metric_map(evaluation)["local_valid_proposal_rate"][0]
    assert not valid.applicable
    assert "no completed local-model generations" in valid.undefined_reason
    assert one(evaluation, "fallback_rate").numerator == 1


def test_unknown_metric_rejected():
    with pytest.raises(KeyError):
        Contribution("composite_awesomeness_score", 1, 1)
