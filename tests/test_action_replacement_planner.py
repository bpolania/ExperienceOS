"""Tests for the deterministic replacement planner.

The planner answers only "which planner action would be replaced?" It
never applies anything. These tests pin its identity arithmetic, its
matching decisions, its purity (no store/engine/manager, immutable
outputs), and its diagnostics.
"""

from __future__ import annotations

import dataclasses

import pytest

from experienceos.memory.planner import CREATE, SUPERSEDE, MemoryAction
from experienceos.memory.action_replacement import (
    ActionReplacementPlanner,
    NO_REPLACEMENT_NEEDED,
    OccurrenceIdentity,
    REJECTED_BEFORE_STATE,
    REJECTED_INTERNAL,
    REJECTED_MULTIPLE_MATCHES,
    REJECTED_NO_MATCH,
    REJECTED_SCOPE_CONFLICT,
    REJECTED_UNRELATED_ACTION,
    REJECTED_UNSUPPORTED,
    REJECTED_VERIFICATION,
    REPLACEMENT_READY,
    ReplacementDecision,
    VerifiedTransition,
    action_content_digest,
    action_list_digest,
    occurrence_identity,
    planner_action_identity,
)

# Verified texts: different normalized text, same semantic identity.
PLANNER_NEW = "I prefer window seats for work trips."
TRANSITION_NEW = "I now prefer window seats for work trips."
OLD_VALUE = "I prefer aisle seats for work trips."
UNRELATED = "I am based in the Denver office."


def _create(text: str, **kw) -> MemoryAction:
    return MemoryAction(action=CREATE, kind="preference", text=text, **kw)


def _supersede(memory_id: str, text: str) -> MemoryAction:
    return MemoryAction(
        action=SUPERSEDE, kind="preference", memory_id=memory_id, text=text
    )


def _transition(**overrides) -> VerifiedTransition:
    base = dict(
        accepted=True,
        transition_type="supersede_existing",
        supersede_action=_supersede("old.seat", OLD_VALUE),
        replacement_create=_create(TRANSITION_NEW, replaces="old.seat"),
        target_memory_ids=("old.seat",),
        source_digest="src-digest",
        before_state_digest="bs-1",
    )
    base.update(overrides)
    return VerifiedTransition(**base)


# ======================================================================
# Identity
# ======================================================================


def test_content_digest_is_deterministic() -> None:
    action = _create(PLANNER_NEW)
    assert action_content_digest(action) == action_content_digest(action)


def test_content_digest_is_metadata_order_independent() -> None:
    a = _create(PLANNER_NEW, metadata={"scope": "work", "a": 1, "b": 2})
    b = _create(PLANNER_NEW, metadata={"b": 2, "a": 1, "scope": "work"})
    assert action_content_digest(a) == action_content_digest(b)


def test_omitted_and_explicit_null_fields_collide() -> None:
    implicit = _create(PLANNER_NEW)
    explicit = _create(PLANNER_NEW, memory_id=None, replaces=None)
    assert action_content_digest(implicit) == action_content_digest(explicit)


def test_scope_participates_in_content_digest() -> None:
    general = _create(PLANNER_NEW, metadata={"scope": "general"})
    scoped = _create(PLANNER_NEW, metadata={"scope": "work"})
    same = _create(PLANNER_NEW, metadata={"scope": "work"})
    assert action_content_digest(general) != action_content_digest(scoped)
    assert action_content_digest(scoped) == action_content_digest(same)


def test_duplicate_occurrences_share_content_but_differ_in_index() -> None:
    a = _create(PLANNER_NEW)
    b = _create(PLANNER_NEW)
    list_digest = action_list_digest([a, b])
    ia = occurrence_identity(a, 0, list_digest)
    ib = occurrence_identity(b, 1, list_digest)
    assert ia.content_digest == ib.content_digest
    assert ia != ib
    assert ia.occurrence_index != ib.occurrence_index


def test_occurrence_identity_is_stable() -> None:
    a = _create(PLANNER_NEW)
    list_digest = action_list_digest([a])
    first = planner_action_identity(a, 0, list_digest, semantic_key="k")
    second = planner_action_identity(a, 0, list_digest, semantic_key="k")
    assert first == second
    assert isinstance(first.occurrence, OccurrenceIdentity)


# ======================================================================
# Matching
# ======================================================================


def test_semantic_match_is_ready() -> None:
    planner = [_create(PLANNER_NEW), _create(UNRELATED)]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert decision.decision == REPLACEMENT_READY
    assert decision.ready
    assert decision.match.action.text == PLANNER_NEW
    assert decision.candidate.planner_occurrence.occurrence_index == 0
    assert decision.candidate.target_memory_ids == ("old.seat",)


def test_exact_match_is_ready() -> None:
    # Planner text identical to the replacement create (exact duplicate).
    planner = [_create(TRANSITION_NEW)]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert decision.decision == REPLACEMENT_READY


def test_planner_mismatch_is_no_match() -> None:
    planner = [_create(UNRELATED)]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert decision.decision == REJECTED_NO_MATCH


def test_multiple_matches_fail_closed() -> None:
    planner = [_create(PLANNER_NEW), _create(TRANSITION_NEW)]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert decision.decision == REJECTED_MULTIPLE_MATCHES
    assert decision.candidate is None


def test_no_planner_actions_is_no_match() -> None:
    decision = ActionReplacementPlanner().plan([], _transition(), "bs-1")
    assert decision.decision == REJECTED_NO_MATCH


def test_extraction_action_is_rejected_not_matched() -> None:
    planner = [_create(UNRELATED)]
    extraction = [_create(TRANSITION_NEW)]
    decision = ActionReplacementPlanner().plan(
        planner, _transition(), "bs-1", extraction_actions=extraction
    )
    assert decision.decision == REJECTED_NO_MATCH  # extraction is not a match
    extraction_diags = [
        d for d in decision.diagnostics if d.candidate_type == "extraction"
    ]
    assert extraction_diags
    assert extraction_diags[0].rejection_reason == "extraction_not_supported"
    assert extraction_diags[0].eligible is False


def test_transition_type_planner_action_is_not_create_match() -> None:
    # A supersede among the planner actions is not a create-like target.
    planner = [_supersede("old.seat", PLANNER_NEW)]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert decision.decision in (REJECTED_UNSUPPORTED, REJECTED_NO_MATCH)
    assert decision.candidate is None


def test_scope_mismatch_is_scope_conflict() -> None:
    planner = [_create("I prefer window seats for personal trips.")]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert decision.decision == REJECTED_SCOPE_CONFLICT


def test_grounding_mismatch_is_rejected() -> None:
    planner = [_create(PLANNER_NEW)]
    decision = ActionReplacementPlanner().plan(
        planner, _transition(source_digest=""), "bs-1"
    )
    assert decision.decision == REJECTED_VERIFICATION
    assert decision.rejection_reason == "source_not_grounded"


def test_before_state_mismatch_is_rejected() -> None:
    planner = [_create(PLANNER_NEW)]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-OTHER")
    assert decision.decision == REJECTED_BEFORE_STATE


def test_unaccepted_verification_is_rejected() -> None:
    planner = [_create(PLANNER_NEW)]
    decision = ActionReplacementPlanner().plan(
        planner, _transition(accepted=False), "bs-1"
    )
    assert decision.decision == REJECTED_VERIFICATION
    assert decision.rejection_reason == "transition_not_accepted"


def test_pure_create_needs_no_replacement() -> None:
    planner = [_create(PLANNER_NEW)]
    decision = ActionReplacementPlanner().plan(
        planner,
        _transition(supersede_action=None),
        "bs-1",
    )
    assert decision.decision == NO_REPLACEMENT_NEEDED


def test_planner_create_replacing_other_target_is_unrelated() -> None:
    # A matched create that itself replaces a different memory is not ours.
    planner = [_create(PLANNER_NEW, replaces="some.other.memory")]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert decision.decision == REJECTED_UNRELATED_ACTION


# ======================================================================
# Purity
# ======================================================================


def test_planner_has_no_mutation_surface() -> None:
    planner = ActionReplacementPlanner()
    for forbidden in ("memory_store", "engine", "experience_manager", "store"):
        assert not hasattr(planner, forbidden)
    for method in ("apply", "apply_memory_actions", "_apply_memory_actions", "mutate"):
        assert not hasattr(planner, method)


def test_planner_module_imports_no_runtime_authority() -> None:
    import experienceos.memory.action_replacement.planner as mod

    globals_names = set(vars(mod))
    for forbidden in ("MemoryStore", "ExperienceEngine", "ExperienceManager"):
        assert forbidden not in globals_names


def test_decision_is_immutable() -> None:
    decision = ActionReplacementPlanner().plan(
        [_create(PLANNER_NEW)], _transition(), "bs-1"
    )
    assert dataclasses.is_dataclass(decision)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.decision = "tampered"  # type: ignore[misc]


def test_plan_does_not_mutate_inputs() -> None:
    planner_actions = [_create(PLANNER_NEW), _create(UNRELATED)]
    snapshot = list(planner_actions)
    ActionReplacementPlanner().plan(planner_actions, _transition(), "bs-1")
    assert planner_actions == snapshot


# ======================================================================
# Diagnostics
# ======================================================================


def test_every_evaluated_planner_action_has_a_diagnostic() -> None:
    planner = [_create(PLANNER_NEW), _create(UNRELATED)]
    decision = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    planner_diags = [
        d for d in decision.diagnostics if d.candidate_type == "planner"
    ]
    assert len(planner_diags) == 2
    for diag in planner_diags:
        assert diag.occurrence_identity is not None
        assert diag.content_digest is not None
        assert diag.semantic_relation is not None


def test_diagnostics_are_deterministic() -> None:
    planner = [_create(PLANNER_NEW), _create(UNRELATED)]
    first = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    second = ActionReplacementPlanner().plan(planner, _transition(), "bs-1")
    assert first.to_record() == second.to_record()


def test_ready_candidate_carries_occurrence_and_semantic_identity() -> None:
    decision = ActionReplacementPlanner().plan(
        [_create(PLANNER_NEW)], _transition(), "bs-1"
    )
    candidate = decision.candidate
    assert candidate.planner_digest == decision.match.identity.content_digest
    assert candidate.planner_occurrence.occurrence_index == 0
    # semantic identity is present and distinct from the content digest
    assert candidate.semantic_key is not None
    assert candidate.semantic_key != candidate.planner_digest
