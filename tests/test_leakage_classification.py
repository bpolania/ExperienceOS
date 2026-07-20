"""Tests for stale-answer leakage-source classification.

Verify the classification rules distinguish upstream state-generation
failure from downstream leakage, resist the common misclassifications,
keep context exposure independent of the primary cause, require direct
answer evidence for evaluator errors, and that the committed
classification and frozen Phase 17 evidence are consistent and unchanged.
"""

from __future__ import annotations

import hashlib
import pytest
import json

from experiments.competitive_viability import leakage as LK

COMMITTED = "benchmarks/results/committed/competitive-viability"


# -- 1. state-generation vs downstream leakage -------------------------------


def test_active_obsolete_answer_use_is_state_generation_not_downstream():
    # obsolete never made inactive + answer used it -> upstream cause,
    # never DOWNSTREAM_LEAKAGE.
    cause = LK.primary_root_cause(
        answer_used_stale=True, has_direct_answer_evidence=True,
        obsolete_inactive_before_retrieval=False,
        state_generation_stage=LK.EXTRACTION_INTENT_ERROR)
    assert cause == LK.EXTRACTION_INTENT_ERROR


def test_clean_state_but_stale_answer_is_downstream_leakage():
    cause = LK.primary_root_cause(
        answer_used_stale=True, has_direct_answer_evidence=True,
        obsolete_inactive_before_retrieval=True,
        state_generation_stage=LK.EXTRACTION_INTENT_ERROR)
    assert cause == LK.DOWNSTREAM_LEAKAGE


# -- 2 & 3. retrieval-error only for INACTIVE obsolete ------------------------


def test_active_obsolete_in_candidates_is_not_retrieval_error():
    assert LK.is_retrieval_error(
        obsolete_inactive=False, obsolete_in_candidates=True) is False


def test_inactive_obsolete_in_candidates_is_retrieval_error():
    assert LK.is_retrieval_error(
        obsolete_inactive=True, obsolete_in_candidates=True) is True


def test_active_obsolete_selected_is_not_selection_error():
    assert LK.is_selection_error(
        obsolete_inactive=False, obsolete_selected=True) is False
    assert LK.is_selection_error(
        obsolete_inactive=True, obsolete_selected=True) is True


# -- 4. single upstream propagation is not MIXED -----------------------------


def test_single_upstream_error_is_not_mixed():
    assert LK.is_mixed(1) is False
    assert LK.is_mixed(2) is True
    # one upstream cause propagating (defect count 1) stays its own class
    cause = LK.primary_root_cause(
        answer_used_stale=True, has_direct_answer_evidence=True,
        obsolete_inactive_before_retrieval=False,
        state_generation_stage=LK.EXTRACTION_INTENT_ERROR,
        independent_causal_defects=1)
    assert cause != LK.MIXED


# -- 5. context exposure independent of primary cause ------------------------


def test_context_exposure_independent_of_primary_cause():
    # Same primary cause, different exposure paths.
    a = LK.five_way_context(evaluator_false_positive=False,
                            stale_in_selected_memory=True,
                            current_in_context=True, stale_in_raw_history=False)
    b = LK.five_way_context(evaluator_false_positive=False,
                            stale_in_selected_memory=True,
                            current_in_context=False, stale_in_raw_history=False)
    assert a == LK.CURRENT_AND_STALE_BOTH_PRESENT
    assert b == LK.STALE_IN_SELECTED_MEMORY_CONTEXT
    # evaluator false positive is its own exposure class
    assert LK.five_way_context(
        evaluator_false_positive=True, stale_in_selected_memory=True,
        current_in_context=True, stale_in_raw_history=False
    ) == LK.EVALUATOR_FALSE_POSITIVE


# -- 6. evaluator error requires direct answer evidence ----------------------


def test_evaluator_error_requires_direct_answer_evidence():
    assert LK.evaluator_error_supported(
        answer_used_stale=False, has_direct_answer_evidence=True) is True
    # no direct evidence -> cannot claim evaluator error
    assert LK.evaluator_error_supported(
        answer_used_stale=False, has_direct_answer_evidence=False) is False
    # answer used stale -> not an evaluator error
    assert LK.evaluator_error_supported(
        answer_used_stale=True, has_direct_answer_evidence=True) is False


def test_primary_evaluator_error_when_answer_did_not_use_stale():
    cause = LK.primary_root_cause(
        answer_used_stale=False, has_direct_answer_evidence=True,
        obsolete_inactive_before_retrieval=False,
        state_generation_stage=LK.EXTRACTION_INTENT_ERROR)
    assert cause == LK.EVALUATOR_ERROR


# -- distinguishing obsolete-active from valid-active ------------------------


def test_cannot_distinguish_two_active_memories_without_metadata():
    assert LK.downstream_can_distinguish_active(
        obsolete_active=True, current_active=True,
        distinguishing_metadata=False) is False
    assert LK.downstream_can_distinguish_active(
        obsolete_active=True, current_active=True,
        distinguishing_metadata=True) is True


def test_correct_state_ever_semantics():
    assert LK.correct_state_ever(
        obsolete_inactive_before_retrieval=True, current_present=True) == "YES"
    assert LK.correct_state_ever(
        obsolete_inactive_before_retrieval=False, current_present=True) == (
        "PARTIALLY")
    assert LK.correct_state_ever(
        obsolete_inactive_before_retrieval=False, current_present=False) == "NO"


# -- committed classification consistency ------------------------------------


def _classification():
    return json.load(open(f"{COMMITTED}/stale_leakage_classification.json"))


def test_committed_classification_covers_nine_cases():
    d = _classification()
    assert d["stale_failure_count"] == 9
    assert len(d["cases"]) == 9


def test_committed_classification_matches_rules():
    for c in _classification()["cases"]:
        # every case: obsolete never made inactive (verified upstream)
        assert c["obsolete_state_before_retrieval"] == "active"
        # active obsolete in candidates is never a retrieval error
        assert c["retrieval_error"] is False
        # primary cause is consistent with answer_used_stale
        if c["answer_used_stale_value"]:
            assert c["primary_root_cause"] == LK.EXTRACTION_INTENT_ERROR
        else:
            assert c["primary_root_cause"] == LK.EVALUATOR_ERROR
        # no downstream error attributed
        assert c["downstream_classification"] == LK.DOWNSTREAM_NONE


def test_cross_case_summary_counts():
    s = _classification()["cross_case_summary"]
    assert s["all_obsolete_remained_active"] is True
    assert s["any_memory_superseded_or_forgotten"] is False
    assert s["genuine_stale_answer_count"] == 4
    assert s["evaluator_false_positive_count"] == 5
    assert s["downstream_errors"] == 0
    assert s["downstream_can_distinguish_obsolete_from_valid_active"] is False


# -- frozen prior evidence unchanged ----------------------------------------


def test_frozen_evidence_hashes_unchanged():
    import experiments.competitive_viability.viability_subset as vs
    assert vs.manifest_hash(vs.build_viability_manifest())[:8] == "9c7f3009"
    raw = "benchmarks/results/local/competitive-viability/records.jsonl"
    import os
    if not os.path.exists(raw):
        pytest.skip("local competitive-viability records scratch not present")
    assert hashlib.sha256(open(raw, "rb").read()).hexdigest()[:8] == "bb9c1362"


def test_classification_does_not_reference_a_mutation_api():
    # The analysis module is pure: no store, engine, or mutation symbols.
    import experiments.competitive_viability.leakage as mod
    src = open(mod.__file__).read()
    for forbidden in ("MemoryStore", "ExperienceEngine", ".supersede(",
                      ".forget(", "_apply_memory_actions"):
        assert forbidden not in src
