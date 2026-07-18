"""Leakage-source classification rules for stale-answer failures.

Pure, testable decision functions that separate an upstream lifecycle
state-generation failure from a downstream leakage of a clean state, and
that resist the common misclassifications (an active obsolete memory
correctly exposed by retrieval is not a retrieval error; a single
upstream error propagating through later stages is not MIXED; context
exposure is independent of the primary root cause; an evaluator error
requires direct answer evidence). Analysis only — no runtime coupling,
no mutation.
"""

from __future__ import annotations

# Primary root-cause classes.
EXTRACTION_INTENT_ERROR = "EXTRACTION_INTENT_ERROR"
VALIDATION_INTENT_LOSS = "VALIDATION_INTENT_LOSS"
GOVERNANCE_MATCHING_ERROR = "GOVERNANCE_MATCHING_ERROR"
GOVERNANCE_ACTION_ERROR = "GOVERNANCE_ACTION_ERROR"
TRANSITION_APPLICATION_ERROR = "TRANSITION_APPLICATION_ERROR"
LIFECYCLE_STATE_GENERATION_ERROR = "LIFECYCLE_STATE_GENERATION_ERROR"
DOWNSTREAM_LEAKAGE = "DOWNSTREAM_LEAKAGE"
MODEL_OR_EVALUATION_ONLY = "MODEL_OR_EVALUATION_ONLY"
EVALUATOR_ERROR = "EVALUATOR_ERROR"
MIXED = "MIXED"

# Downstream classes.
STORE_STATE_ERROR = "STORE_STATE_ERROR"
ELIGIBILITY_ERROR = "ELIGIBILITY_ERROR"
RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
SELECTION_ERROR = "SELECTION_ERROR"
CONTEXT_RENDERING_ERROR = "CONTEXT_RENDERING_ERROR"
HISTORY_LEAKAGE = "HISTORY_LEAKAGE"
PROMPT_AUTHORITY_ERROR = "PROMPT_AUTHORITY_ERROR"
MODEL_REINTRODUCTION = "MODEL_REINTRODUCTION"
DOWNSTREAM_NONE = "NONE"

# Five-way context exposure.
STALE_IN_SELECTED_MEMORY_CONTEXT = "STALE_IN_SELECTED_MEMORY_CONTEXT"
STALE_ONLY_IN_RAW_HISTORY = "STALE_ONLY_IN_RAW_HISTORY"
STALE_ABSENT_FROM_ALL_CONTEXT = "STALE_ABSENT_FROM_ALL_CONTEXT"
CURRENT_AND_STALE_BOTH_PRESENT = "CURRENT_AND_STALE_BOTH_PRESENT"
EVALUATOR_FALSE_POSITIVE = "EVALUATOR_FALSE_POSITIVE"
MULTIPLE_CONTEXT_PATHS = "MULTIPLE_CONTEXT_PATHS"

# Correct-state-ever values.
YES, NO, PARTIALLY = "YES", "NO", "PARTIALLY"


def correct_state_ever(*, obsolete_inactive_before_retrieval: bool,
                       current_present: bool) -> str:
    """Did the governed lifecycle ever contain the correct current state?

    YES: obsolete reached its expected inactive state and current is
    present. PARTIALLY: current is present but obsolete also remained
    active. NO: obsolete remained active with no authoritative current.
    """
    if obsolete_inactive_before_retrieval and current_present:
        return YES
    if current_present:
        return PARTIALLY
    return NO


def is_retrieval_error(*, obsolete_inactive: bool,
                       obsolete_in_candidates: bool) -> bool:
    """RETRIEVAL_ERROR only when a correctly-INACTIVE obsolete memory still
    entered the retrieval candidates. An ACTIVE obsolete memory appearing
    in candidates is correct exposure, not a retrieval error."""
    return obsolete_inactive and obsolete_in_candidates


def is_selection_error(*, obsolete_inactive: bool,
                       obsolete_selected: bool) -> bool:
    """SELECTION_ERROR only when an ineligible (inactive) obsolete memory
    was selected. Selecting an ACTIVE obsolete memory is not a selection
    error."""
    return obsolete_inactive and obsolete_selected


def is_mixed(independent_causal_defects: int) -> bool:
    """MIXED only with two or more INDEPENDENT causal defects. A single
    upstream error propagating downstream is not MIXED."""
    return independent_causal_defects >= 2


def evaluator_error_supported(*, answer_used_stale: bool,
                              has_direct_answer_evidence: bool) -> bool:
    """EVALUATOR_ERROR requires direct answer evidence that the answer did
    not actually use the stale value under a correct reading."""
    return (not answer_used_stale) and has_direct_answer_evidence


def primary_root_cause(*, answer_used_stale: bool,
                       has_direct_answer_evidence: bool,
                       obsolete_inactive_before_retrieval: bool,
                       state_generation_stage: str,
                       independent_causal_defects: int = 1) -> str:
    """Classify the primary cause of the flagged stale-answer failure.

    - If the answer did not actually use the stale value (with direct
      evidence), the flagged failure is an evaluator artifact.
    - If the answer used a stale value that was never taken out of active
      state, the cause is the upstream state-generation stage.
    - MIXED only for two or more independent defects.
    """
    if is_mixed(independent_causal_defects):
        return MIXED
    if evaluator_error_supported(
        answer_used_stale=answer_used_stale,
        has_direct_answer_evidence=has_direct_answer_evidence,
    ):
        return EVALUATOR_ERROR
    if not obsolete_inactive_before_retrieval:
        # The correct current-only state never existed; the obsolete value
        # was still active. This is an upstream state-generation failure,
        # not downstream leakage.
        return state_generation_stage
    return DOWNSTREAM_LEAKAGE


def five_way_context(*, evaluator_false_positive: bool,
                     stale_in_selected_memory: bool,
                     current_in_context: bool,
                     stale_in_raw_history: bool) -> str:
    """Where the stale value was exposed to the model (independent of the
    primary root cause)."""
    if evaluator_false_positive:
        return EVALUATOR_FALSE_POSITIVE
    if stale_in_selected_memory and current_in_context:
        return CURRENT_AND_STALE_BOTH_PRESENT
    if stale_in_selected_memory:
        return STALE_IN_SELECTED_MEMORY_CONTEXT
    if stale_in_raw_history:
        return STALE_ONLY_IN_RAW_HISTORY
    return STALE_ABSENT_FROM_ALL_CONTEXT


def downstream_can_distinguish_active(*, obsolete_active: bool,
                                      current_active: bool,
                                      distinguishing_metadata: bool) -> bool:
    """Can an allowed downstream correction tell an obsolete ACTIVE memory
    from a valid ACTIVE memory using existing general metadata? Only when
    such distinguishing metadata exists."""
    if not (obsolete_active and current_active):
        return True
    return distinguishing_metadata
