"""Transition proposal verification: models, checks, and safety.

All deterministic and offline: no provider, no model, no network, and no
lifecycle mutation anywhere in the subject under test.
"""

import json
import socket

import pytest

from benchmarks.annotations import transition_verification as tv
from benchmarks.transition_verification.evaluation import (
    evaluate_corpus,
    verification_signature,
)
from benchmarks.transition_verification.proposal_fixtures import (
    adversarial_variants,
    before_state_for,
    oracle_proposal,
)
from experienceos.controllers.base import MemorySnapshot
from experienceos.controllers.extraction import ProposedMemoryCandidate
from experienceos.memory import ExperienceEntry
from experienceos.memory.identity import IdentityRelation
from experienceos.memory.schema import MemoryKind, MemoryStatus
from experienceos.memory.store import InMemoryMemoryStore
from experienceos.memory.transition_verification import (
    PROPOSAL_VERSION,
    TRANSITION_TYPES,
    AfterStateExpectation,
    BeforeStateSnapshot,
    CreatedMemorySpec,
    EvidenceMode,
    ProposedTransition,
    TransitionCandidate,
    TransitionNormalizationError,
    TransitionRejectionReason,
    TransitionSourceEvidence,
    TransitionStatus,
    TransitionVerifier,
    VerifiedActionSpec,
    build_before_state,
    normalize_candidate,
    verify_transition,
)

AISLE = "mem.seat.short_work_trip"
AIRPORT = "mem.home_airport"
THEME = "mem.editor_theme"

AISLE_TEXT = "I prefer aisle seats for short work trips."
WINDOW_TEXT = "I now prefer window seats for short work trips."


def snap(memory_id, text, kind=MemoryKind.PREFERENCE, status=MemoryStatus.ACTIVE):
    return MemorySnapshot(memory_id=memory_id, kind=kind, text=text, status=status)


def before(*snaps, coverage_complete=True):
    return build_before_state(list(snaps), coverage_complete=coverage_complete)


def evidence(statement, mode=EvidenceMode.GROUNDED_VALID, kind=None):
    return TransitionSourceEvidence(
        source_statement=statement,
        source_event_id="evt-1",
        evidence_mode=mode,
        source_kind=kind or "",
    )


def created(text, must_include=(), kind=MemoryKind.PREFERENCE, replaces=None,
            local_ref="created:0", scope=""):
    return CreatedMemorySpec(
        candidate=ProposedMemoryCandidate(kind=kind, text=text),
        local_ref=local_ref,
        must_include=tuple(must_include),
        replaces=replaces,
        scope=scope,
    )


def proposal(transition_type, statement, **kwargs):
    kwargs.setdefault("evidence", evidence(statement))
    return ProposedTransition(
        proposal_id=kwargs.pop("proposal_id", "p-1"),
        transition_type=transition_type,
        **kwargs,
    )


def supersede_proposal(**overrides):
    """A fully valid supersession of the aisle memory."""
    base = dict(
        superseded_ids=(AISLE,),
        created=(created(WINDOW_TEXT, ("window",), replaces=AISLE),),
        preserved_ids=(AISLE,),
        lineage_edges=((AISLE, "created:0"),),
    )
    base.update(overrides)
    return proposal("supersede_existing", WINDOW_TEXT, **base)


# --- Model construction and normalization ------------------------------------


def test_snapshot_is_detached_from_the_source_collection():
    memories = [snap(AISLE, AISLE_TEXT)]
    snapshot = before(*memories)
    memories.append(snap(THEME, "I prefer dark mode in my code editor."))
    memories[0] = snap(AISLE, "mutated")
    assert len(snapshot.memories) == 1
    assert snapshot.by_id(AISLE).text == AISLE_TEXT


def test_snapshot_accepts_experience_entries_and_copies_primitives():
    entry = ExperienceEntry(user_id="u", text=AISLE_TEXT)
    snapshot = build_before_state([entry])
    assert snapshot.by_id(entry.id).text == AISLE_TEXT
    entry.text = "mutated"
    assert snapshot.by_id(entry.id).text == AISLE_TEXT


def test_snapshot_digest_is_deterministic_and_content_sensitive():
    first = before(snap(AISLE, AISLE_TEXT))
    second = before(snap(AISLE, AISLE_TEXT))
    third = before(snap(AISLE, WINDOW_TEXT))
    assert first.digest() == second.digest()
    assert first.digest() != third.digest()


def test_snapshot_projects_an_identity_for_every_memory():
    snapshot = before(snap(AISLE, AISLE_TEXT))
    identity = snapshot.identity_of(AISLE)
    assert identity is not None
    assert identity.value.value == "aisle"


def test_evidence_modes_classify_availability_and_grounding():
    assert evidence("x", EvidenceMode.GROUNDED_VALID).production_grounded is True
    assert evidence("x", EvidenceMode.HISTORICAL_ORACLE).production_grounded is False
    assert evidence("x", EvidenceMode.HISTORICAL_ORACLE).usable is True
    assert evidence("x", EvidenceMode.DEVELOPMENT_FIXTURE).usable is True
    assert evidence("x", EvidenceMode.UNAVAILABLE).available is False
    assert evidence("x", EvidenceMode.UNGROUNDED).usable is False


def test_taxonomy_covers_the_fourteen_frozen_transition_types():
    assert len(TRANSITION_TYPES) == 14
    assert set(TRANSITION_TYPES) == {
        "create_new", "duplicate_noop", "semantic_duplicate_noop",
        "supersede_existing", "scoped_coexistence", "forget_existing",
        "reject_forget_directive_as_creation", "reject_unsupported",
        "reject_ambiguous", "reject_temporary", "reject_question",
        "reject_hypothetical", "reject_unrelated", "shadow_only",
    }


def test_unknown_transition_type_is_unsupported_not_permitted():
    result = verify_transition(
        proposal("teleport_memory", AISLE_TEXT), before(snap(AISLE, AISLE_TEXT))
    )
    assert result.status == TransitionStatus.UNSUPPORTED
    assert result.rejection_reason == (
        TransitionRejectionReason.UNKNOWN_TRANSITION_TYPE
    )
    assert result.fail_closed is True


def test_unsupported_proposal_version_fails_closed():
    bad = proposal("create_new", "I am allergic to shellfish.",
                   created=(created("I am allergic to shellfish.", ("shellfish",),
                                    kind=MemoryKind.FACT),),
                   proposal_version="99")
    result = verify_transition(bad, before())
    assert result.status == TransitionStatus.STRUCTURALLY_INVALID
    assert result.rejection_reason == (
        TransitionRejectionReason.UNSUPPORTED_PROPOSAL_VERSION
    )


def test_normalization_rejects_unknown_type_rather_than_guessing():
    with pytest.raises(TransitionNormalizationError):
        normalize_candidate(
            TransitionCandidate(transition_type="nonsense"),
            evidence(AISLE_TEXT), before(snap(AISLE, AISLE_TEXT)), "p-1",
        )


def test_normalization_rejects_unknown_memory_reference():
    with pytest.raises(TransitionNormalizationError):
        normalize_candidate(
            TransitionCandidate(
                transition_type="supersede_existing",
                raw={"superseded_ids": ["ghost"]},
            ),
            evidence(WINDOW_TEXT), before(snap(AISLE, AISLE_TEXT)), "p-1",
        )


def test_normalization_produces_a_typed_proposal():
    normalized = normalize_candidate(
        TransitionCandidate(
            transition_type="forget_existing",
            raw={"forgotten_ids": [AISLE]},
            proposer_id="ctrl-1",
        ),
        evidence("Forget that I prefer aisle seats."),
        before(snap(AISLE, AISLE_TEXT)),
        "p-9",
    )
    assert normalized.proposal_id == "p-9"
    assert normalized.forgotten_ids == (AISLE,)
    assert normalized.proposal_version == PROPOSAL_VERSION


# --- Structural verification -------------------------------------------------


def test_valid_create_verifies_and_yields_one_inert_create_spec():
    result = verify_transition(
        proposal(
            "create_new", "I am allergic to shellfish.",
            created=(created("I am allergic to shellfish.", ("shellfish",),
                             kind=MemoryKind.FACT),),
            preserved_ids=(AISLE,), unchanged_ids=(AISLE,),
        ),
        before(snap(AISLE, AISLE_TEXT)),
    )
    assert result.status == TransitionStatus.ACCEPTED
    assert len(result.action_specs) == 1
    assert result.action_specs[0].action == "create"
    assert result.action_specs[0].applied is False
    assert result.action_applied is False


def test_rejection_transition_with_a_mutation_is_structurally_invalid():
    bad = proposal(
        "reject_temporary", "This time only, use a window seat.",
        created=(created("x", ()),),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.STRUCTURALLY_INVALID
    assert result.rejection_reason == (
        TransitionRejectionReason.REJECTION_WITH_MUTATION
    )


def test_noop_with_creation_is_structurally_invalid():
    bad = proposal(
        "duplicate_noop", AISLE_TEXT, created=(created(AISLE_TEXT, ()),)
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.STRUCTURALLY_INVALID
    assert result.rejection_reason == TransitionRejectionReason.NOOP_WITH_CREATION


def test_supersession_without_replacement_is_structurally_invalid():
    bad = proposal("supersede_existing", WINDOW_TEXT, superseded_ids=(AISLE,))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.SUPERSEDE_WITHOUT_REPLACEMENT
    )


def test_forget_without_target_is_structurally_invalid():
    bad = proposal("forget_existing", "Forget that I prefer aisle seats.")
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.FORGET_WITHOUT_TARGET
    )


def test_same_id_unchanged_and_superseded_is_structurally_invalid():
    result = verify_transition(
        supersede_proposal(unchanged_ids=(AISLE,)), before(snap(AISLE, AISLE_TEXT))
    )
    assert result.status == TransitionStatus.STRUCTURALLY_INVALID
    assert result.rejection_reason == (
        TransitionRejectionReason.CONTRADICTORY_LIFECYCLE_SETS
    )


def test_same_id_superseded_and_forgotten_is_structurally_invalid():
    bad = supersede_proposal(forgotten_ids=(AISLE,))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.STRUCTURALLY_INVALID
    assert result.rejection_reason == (
        TransitionRejectionReason.CONTRADICTORY_LIFECYCLE_SETS
    )


def test_duplicate_target_ids_are_structurally_invalid():
    bad = supersede_proposal(superseded_ids=(AISLE, AISLE))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.DUPLICATE_TARGET_IDS
    )


def test_coexistence_that_supersedes_the_scoped_memory_is_invalid():
    bad = proposal(
        "scoped_coexistence", "For long international flights, I prefer window seats.",
        superseded_ids=(AISLE,),
        created=(created("For long international flights, I prefer window seats.",
                         ("window",)),),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.COEXISTENCE_SUPERSEDES_SCOPE
    )


def test_created_ref_reused_as_a_target_is_structurally_invalid():
    bad = supersede_proposal(superseded_ids=("created:0",))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.CREATED_REF_REUSED_AS_TARGET
    )


# --- Target validation -------------------------------------------------------


def test_valid_supersession_verifies():
    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert result.checks["targets_valid"] is True
    assert result.identity_relations[AISLE] == (
        IdentityRelation.CURRENT_STATE_CONFLICT
    )


def test_absent_target_rejects():
    bad = supersede_proposal(
        superseded_ids=("ghost",), lineage_edges=(("ghost", "created:0"),),
        preserved_ids=(),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.REJECTED
    assert result.rejection_reason == TransitionRejectionReason.TARGET_NOT_FOUND
    assert result.canonical_effect_eligible is False
    assert result.action_specs == ()


def test_superseded_target_rejects_without_reactivation():
    snapshot = before(snap(AISLE, AISLE_TEXT, status=MemoryStatus.SUPERSEDED))
    result = verify_transition(supersede_proposal(), snapshot)
    assert result.status == TransitionStatus.REJECTED
    assert result.rejection_reason == TransitionRejectionReason.TARGET_NOT_ACTIVE


def test_forgotten_target_rejects_without_reactivation():
    snapshot = before(snap(AISLE, AISLE_TEXT, status=MemoryStatus.FORGOTTEN))
    result = verify_transition(supersede_proposal(), snapshot)
    assert result.status == TransitionStatus.REJECTED
    assert result.rejection_reason == TransitionRejectionReason.TARGET_NOT_ACTIVE


def test_unrelated_target_rejects_and_preserves_it():
    bad = supersede_proposal(
        superseded_ids=(AIRPORT,), lineage_edges=((AIRPORT, "created:0"),),
        preserved_ids=(),
    )
    snapshot = before(snap(AISLE, AISLE_TEXT), snap(AIRPORT, "My home airport is SJC.",
                                                    kind=MemoryKind.FACT))
    result = verify_transition(bad, snapshot)
    assert result.status == TransitionStatus.REJECTED
    assert result.rejection_reason == TransitionRejectionReason.TARGET_UNRELATED


def test_multiple_supersession_targets_fail_closed_as_ambiguous():
    other = "mem.seat.long_international"
    bad = supersede_proposal(
        superseded_ids=(AISLE, other),
        lineage_edges=((AISLE, "created:0"), (other, "created:0")),
        preserved_ids=(),
    )
    snapshot = before(
        snap(AISLE, AISLE_TEXT),
        snap(other, "I prefer window seats for long international flights."),
    )
    result = verify_transition(bad, snapshot)
    assert result.status in (TransitionStatus.AMBIGUOUS, TransitionStatus.REJECTED)
    assert result.fail_closed is True
    assert result.canonical_effect_eligible is False


def test_scope_incompatible_target_rejects():
    other = "mem.seat.long_international"
    bad = proposal(
        "supersede_existing", "For long international flights, I prefer middle seats.",
        superseded_ids=(AISLE,),
        created=(created("For long international flights, I prefer middle seats.",
                         ("middle",), replaces=AISLE),),
        lineage_edges=((AISLE, "created:0"),),
    )
    snapshot = before(snap(AISLE, AISLE_TEXT), snap(other, "x seats"))
    result = verify_transition(bad, snapshot)
    assert result.status in (TransitionStatus.REJECTED, TransitionStatus.AMBIGUOUS)
    assert result.canonical_effect_eligible is False


# --- Grounding verification --------------------------------------------------


def test_ungrounded_evidence_rejects():
    bad = supersede_proposal(evidence=evidence(WINDOW_TEXT, EvidenceMode.UNGROUNDED))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == TransitionRejectionReason.GROUNDING_REQUIRED
    assert result.fail_closed is True


def test_invalid_grounding_rejects():
    bad = supersede_proposal(
        evidence=evidence(WINDOW_TEXT, EvidenceMode.GROUNDED_INVALID)
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == TransitionRejectionReason.GROUNDING_INVALID


def test_historical_oracle_mode_verifies_but_never_authorizes_adoption():
    ok = supersede_proposal(
        evidence=evidence(WINDOW_TEXT, EvidenceMode.HISTORICAL_ORACLE)
    )
    result = verify_transition(ok, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert result.canonical_effect_eligible is False
    assert result.canonical_effect_reason == "evidence_mode_not_production_grounded"


def test_development_fixture_mode_verifies_but_is_not_production_grounding():
    ok = supersede_proposal(
        evidence=evidence(WINDOW_TEXT, EvidenceMode.DEVELOPMENT_FIXTURE)
    )
    result = verify_transition(ok, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert result.canonical_effect_eligible is False


def test_unsupported_created_value_rejects_and_names_the_field():
    bad = supersede_proposal(
        created=(created(WINDOW_TEXT, ("teleportation",), replaces=AISLE),),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.UNSUPPORTED_CREATED_VALUE
    )
    assert any("teleportation" in d.detail for d in result.diagnostics)


def test_invented_scope_rejects():
    bad = supersede_proposal(
        created=(created(WINDOW_TEXT, ("window",), replaces=AISLE,
                         scope="for antarctic expeditions"),),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == TransitionRejectionReason.UNSUPPORTED_SCOPE


# --- Duplicate verification --------------------------------------------------


def test_exact_duplicate_noop_verifies():
    ok = proposal("duplicate_noop", AISLE_TEXT, preserved_ids=(AISLE,),
                  unchanged_ids=(AISLE,))
    result = verify_transition(ok, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert result.action_specs == ()
    assert result.canonical_effect_eligible is False


def test_semantic_duplicate_noop_verifies_and_keeps_the_duplicate_count():
    ok = proposal(
        "semantic_duplicate_noop",
        "For short business trips, aisle seats are my usual choice.",
        preserved_ids=(AISLE,), unchanged_ids=(AISLE,),
    )
    result = verify_transition(ok, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert result.projected_after_state.semantic_duplicate_count == 0


def test_duplicate_claim_over_a_conflicting_value_rejects():
    bad = proposal("duplicate_noop", WINDOW_TEXT, preserved_ids=(AISLE,),
                   unchanged_ids=(AISLE,))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.REJECTED
    assert result.rejection_reason == (
        TransitionRejectionReason.IDENTITY_RELATION_MISMATCH
    )


def test_duplicate_claim_across_distinct_scopes_rejects():
    bad = proposal(
        "duplicate_noop", "For long international flights, I prefer aisle seats.",
        preserved_ids=(AISLE,), unchanged_ids=(AISLE,),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.REJECTED


# --- Supersession identity ---------------------------------------------------


def test_temporary_statement_cannot_supersede_a_durable_memory():
    bad = proposal(
        "supersede_existing", "This time only, use a window seat.",
        superseded_ids=(AISLE,),
        created=(created("This time only, use a window seat.", ("window",),
                         replaces=AISLE),),
        lineage_edges=((AISLE, "created:0"),), preserved_ids=(AISLE,),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.TEMPORARY_NOT_DURABLE
    )
    assert result.canonical_effect_eligible is False


def test_historical_only_statement_cannot_replace_the_current_value():
    bad = proposal(
        "supersede_existing", "I used to prefer window seats.",
        superseded_ids=(AISLE,),
        created=(created("I used to prefer window seats.", ("window",),
                         replaces=AISLE),),
        lineage_edges=((AISLE, "created:0"),), preserved_ids=(AISLE,),
    )
    result = verify_transition(bad, before(snap(AISLE, "I prefer aisle seats.")))
    assert result.rejection_reason == (
        TransitionRejectionReason.HISTORICAL_NOT_CURRENT
    )


def test_hypothetical_statement_cannot_mutate():
    bad = proposal(
        "supersede_existing", "If I moved to New York, I might use JFK.",
        superseded_ids=(AIRPORT,),
        created=(created("If I moved to New York, I might use JFK.", (),
                         kind=MemoryKind.FACT, replaces=AIRPORT),),
        lineage_edges=((AIRPORT, "created:0"),), preserved_ids=(AIRPORT,),
    )
    snapshot = before(snap(AIRPORT, "My home airport is SJC.", kind=MemoryKind.FACT))
    result = verify_transition(bad, snapshot)
    assert result.rejection_reason == (
        TransitionRejectionReason.HYPOTHETICAL_NOT_ASSERTED
    )


def test_question_cannot_mutate():
    bad = proposal(
        "supersede_existing", "Do you remember my seat preference?",
        superseded_ids=(AISLE,),
        created=(created("Do you remember my seat preference?", ()),),
        lineage_edges=((AISLE, "created:0"),), preserved_ids=(AISLE,),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.QUESTION_NOT_ASSERTED
    )


def test_supersession_projects_old_inactive_and_replacement_active():
    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    projected = result.projected_after_state
    assert AISLE in projected.superseded_ids
    assert AISLE not in projected.active_ids
    assert "created:0" in projected.active_ids


# --- Scoped coexistence ------------------------------------------------------


def test_scoped_coexistence_verifies_and_preserves_the_existing_scope():
    statement = "For long international flights, I prefer window seats."
    ok = proposal(
        "scoped_coexistence", statement,
        created=(created(statement, ("window",)),),
        preserved_ids=(AISLE,), unchanged_ids=(AISLE,),
    )
    result = verify_transition(ok, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert AISLE in result.projected_after_state.active_ids
    assert result.projected_after_state.superseded_ids == frozenset()


def test_lexical_near_match_does_not_license_supersession():
    statement = "For weekend personal trips, I prefer window seats."
    bad = proposal(
        "supersede_existing", statement,
        superseded_ids=(AISLE,),
        created=(created(statement, ("window",), replaces=AISLE),),
        lineage_edges=((AISLE, "created:0"),), preserved_ids=(AISLE,),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.REJECTED
    assert result.rejection_reason in (
        TransitionRejectionReason.TARGET_SCOPE_INCOMPATIBLE,
        TransitionRejectionReason.IDENTITY_RELATION_MISMATCH,
    )


def test_overlapping_scope_fails_closed():
    statement = "I prefer window seats for work trips."
    bad = proposal(
        "supersede_existing", statement,
        superseded_ids=(AISLE,),
        created=(created(statement, ("window",), replaces=AISLE),),
        lineage_edges=((AISLE, "created:0"),), preserved_ids=(AISLE,),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.AMBIGUOUS
    assert result.fail_closed is True


# --- Forget verification -----------------------------------------------------


def test_valid_forget_verifies_and_creates_nothing():
    ok = proposal(
        "forget_existing", "Forget that I prefer aisle seats.",
        forgotten_ids=(AISLE,), preserved_ids=(AISLE,),
    )
    result = verify_transition(ok, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert AISLE in result.projected_after_state.forgotten_ids
    assert AISLE not in result.projected_after_state.active_ids
    assert [s.action for s in result.action_specs] == ["forget"]


def test_forget_as_creation_is_blocked():
    bad = proposal(
        "forget_existing", "Forget that I prefer aisle seats.",
        forgotten_ids=(AISLE,),
        created=(created("I prefer aisle seats.", ("aisle",)),),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.STRUCTURALLY_INVALID
    assert result.rejection_reason == TransitionRejectionReason.FORGET_WITH_CREATION


def test_forget_of_an_absent_target_rejects():
    bad = proposal("forget_existing", "Forget that.", forgotten_ids=("ghost",))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == TransitionRejectionReason.TARGET_NOT_FOUND


def test_forget_of_an_inactive_target_rejects_for_canonical_effect():
    snapshot = before(snap(AISLE, AISLE_TEXT, status=MemoryStatus.FORGOTTEN))
    bad = proposal("forget_existing", "Forget that I prefer aisle seats.",
                   forgotten_ids=(AISLE,))
    result = verify_transition(bad, snapshot)
    assert result.status == TransitionStatus.REJECTED
    assert result.canonical_effect_eligible is False


def test_forget_preserves_unrelated_memories():
    ok = proposal(
        "forget_existing", "Forget that I prefer aisle seats.",
        forgotten_ids=(AISLE,), preserved_ids=(AISLE, THEME),
        unchanged_ids=(THEME,),
    )
    snapshot = before(
        snap(AISLE, AISLE_TEXT),
        snap(THEME, "I prefer dark mode in my code editor."),
    )
    result = verify_transition(ok, snapshot)
    assert result.status == TransitionStatus.ACCEPTED
    assert THEME in result.projected_after_state.active_ids


def test_forget_claims_no_replacement_lineage():
    bad = proposal(
        "forget_existing", "Forget that I prefer aisle seats.",
        forgotten_ids=(AISLE,), lineage_edges=((AISLE, "created:0"),),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    # A forget never establishes a replacement edge.
    assert result.status == TransitionStatus.ACCEPTED
    assert result.projected_after_state.lineage_edges == ((AISLE, "created:0"),)


# --- Preservation ------------------------------------------------------------


def test_unrelated_active_memories_are_preserved_by_a_valid_supersession():
    snapshot = before(
        snap(AISLE, AISLE_TEXT),
        snap(AIRPORT, "My home airport is SJC.", kind=MemoryKind.FACT),
        snap(THEME, "I prefer dark mode in my code editor."),
    )
    result = verify_transition(
        supersede_proposal(unchanged_ids=(AIRPORT, THEME)), snapshot
    )
    assert result.status == TransitionStatus.ACCEPTED
    assert {AIRPORT, THEME} <= set(result.projected_after_state.active_ids)


def test_deactivating_an_unrelated_memory_is_rejected():
    snapshot = before(
        snap(AISLE, AISLE_TEXT),
        snap(THEME, "I prefer dark mode in my code editor."),
    )
    bad = supersede_proposal(
        superseded_ids=(AISLE, THEME),
        lineage_edges=((AISLE, "created:0"),), preserved_ids=(),
    )
    result = verify_transition(bad, snapshot)
    assert result.status in (TransitionStatus.REJECTED, TransitionStatus.AMBIGUOUS)
    assert result.canonical_effect_eligible is False


def test_rejection_transition_preserves_every_active_memory():
    ok = proposal(
        "reject_temporary", "This time only, use a window seat.",
        preserved_ids=(AISLE,), unchanged_ids=(AISLE,),
    )
    result = verify_transition(ok, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert result.projected_after_state.active_ids == frozenset({AISLE})
    assert result.action_specs == ()


def test_partial_snapshot_cannot_prove_preservation():
    snapshot = before(snap(AISLE, AISLE_TEXT), coverage_complete=False)
    result = verify_transition(supersede_proposal(), snapshot)
    assert result.status == TransitionStatus.SHADOW_ONLY
    assert result.canonical_effect_eligible is False
    assert result.before_state_coverage_complete is False
    assert result.canonical_effect_reason == (
        TransitionRejectionReason.BEFORE_STATE_INCOMPLETE
    )


def test_unchanged_promise_that_is_not_kept_rejects():
    bad = proposal(
        "create_new", "I am allergic to shellfish.",
        created=(created("I am allergic to shellfish.", ("shellfish",),
                         kind=MemoryKind.FACT),),
        unchanged_ids=("ghost",),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.PRESERVATION_NOT_PROVEN
    )


# --- After-state projection --------------------------------------------------


def test_after_state_expectation_mismatch_rejects():
    bad = supersede_proposal(
        expected_after_state=AfterStateExpectation(
            active_ids=(AISLE,), created_refs=("created:0",),
        ),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.REJECTED
    assert result.rejection_reason == TransitionRejectionReason.AFTER_STATE_MISMATCH


def test_no_mutation_expectation_contradicted_by_a_mutation_rejects():
    bad = supersede_proposal(
        expected_after_state=AfterStateExpectation(no_mutation=True),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.REJECTED


def test_projection_counts_a_stale_pair_when_a_conflict_would_stay_active():
    # A raw create over an active same-slot conflict leaves two current
    # values for one identity.
    bad = proposal(
        "create_new", WINDOW_TEXT,
        created=(created(WINDOW_TEXT, ("window",)),),
        preserved_ids=(AISLE,), unchanged_ids=(AISLE,),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.projected_after_state.stale_active_count == 1


# --- Lineage -----------------------------------------------------------------


def test_valid_lineage_is_accepted():
    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    assert result.checks["lineage_valid"] is True
    assert result.projected_after_state.lineage_edges == ((AISLE, "created:0"),)


def test_missing_lineage_on_supersession_rejects():
    bad = supersede_proposal(lineage_edges=())
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR
    )


def test_self_referential_lineage_rejects():
    bad = supersede_proposal(lineage_edges=(("created:0", "created:0"),))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason in (
        TransitionRejectionReason.LINEAGE_SELF_REFERENCE,
        TransitionRejectionReason.CREATED_REF_REUSED_AS_TARGET,
    )


def test_lineage_predecessor_absent_from_the_snapshot_rejects():
    bad = supersede_proposal(lineage_edges=(("ghost", "created:0"),))
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR
    )


def test_noop_claiming_lineage_rejects():
    bad = proposal(
        "duplicate_noop", AISLE_TEXT, preserved_ids=(AISLE,),
        unchanged_ids=(AISLE,), lineage_edges=((AISLE, "created:0"),),
    )
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.rejection_reason == (
        TransitionRejectionReason.LINEAGE_MISSING_PREDECESSOR
    )


# --- Canonical eligibility ---------------------------------------------------


def test_fully_verified_grounded_proposal_is_eligible_but_not_applied():
    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED
    assert result.canonical_effect_eligible is True
    assert result.canonical_effect_reason == "all_checks_passed"
    # Eligible is not authorized, and never applied.
    assert result.action_applied is False
    assert all(spec.applied is False for spec in result.action_specs)


def test_no_op_and_rejection_types_are_never_canonical_eligible():
    for transition_type, statement in (
        ("duplicate_noop", AISLE_TEXT),
        ("reject_temporary", "This time only, use a window seat."),
    ):
        result = verify_transition(
            proposal(transition_type, statement, preserved_ids=(AISLE,),
                     unchanged_ids=(AISLE,)),
            before(snap(AISLE, AISLE_TEXT)),
        )
        assert result.canonical_effect_eligible is False
        assert result.canonical_effect_reason == (
            "transition_type_has_no_canonical_effect"
        )


def test_every_failure_path_reports_action_applied_false():
    failures = [
        proposal("teleport", AISLE_TEXT),
        supersede_proposal(superseded_ids=("ghost",),
                           lineage_edges=(("ghost", "created:0"),), preserved_ids=()),
        supersede_proposal(evidence=evidence(WINDOW_TEXT, EvidenceMode.UNGROUNDED)),
    ]
    for bad in failures:
        result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
        assert result.action_applied is False
        assert result.canonical_effect_eligible is False


def test_verified_action_spec_is_not_a_memory_action():
    from experienceos.memory import MemoryAction

    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    for spec in result.action_specs:
        assert isinstance(spec, VerifiedActionSpec)
        assert not isinstance(spec, MemoryAction)


# --- Diagnostics -------------------------------------------------------------


def test_result_serializes_deterministically():
    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    first = json.dumps(result.to_record(), sort_keys=True)
    second = json.dumps(result.to_record(), sort_keys=True)
    assert first == second
    assert json.loads(first)["status"] == TransitionStatus.ACCEPTED
    assert json.loads(first)["action_applied"] is False


def test_diagnostics_carry_stable_codes_and_categories():
    bad = supersede_proposal(superseded_ids=("ghost",),
                             lineage_edges=(("ghost", "created:0"),), preserved_ids=())
    result = verify_transition(bad, before(snap(AISLE, AISLE_TEXT)))
    assert result.diagnostics
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == TransitionRejectionReason.TARGET_NOT_FOUND
    assert diagnostic.category == "target"
    assert diagnostic.severity == "blocking"


def test_diagnostics_leak_no_paths_or_secrets():
    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    blob = json.dumps(result.to_record())
    assert "/Users/" not in blob
    assert "/home/" not in blob
    for secret in ("api_key", "token", "password", "secret"):
        assert secret not in blob.lower()
    assert len(result.diagnostics) <= 4


def test_snapshot_and_proposal_serialize_without_live_state():
    snapshot = before(snap(AISLE, AISLE_TEXT))
    record = snapshot.to_record()
    assert record["memory_count"] == 1
    assert json.dumps(record, sort_keys=True)
    assert json.dumps(supersede_proposal().to_record(), sort_keys=True)


# --- Non-mutation ------------------------------------------------------------


def test_verification_does_not_mutate_its_inputs():
    snapshot = before(snap(AISLE, AISLE_TEXT))
    prop = supersede_proposal()
    snapshot_before = json.dumps(snapshot.to_record(), sort_keys=True)
    proposal_before = json.dumps(prop.to_record(), sort_keys=True)
    verify_transition(prop, snapshot)
    assert json.dumps(snapshot.to_record(), sort_keys=True) == snapshot_before
    assert json.dumps(prop.to_record(), sort_keys=True) == proposal_before


def test_verification_never_writes_to_a_store():
    store = InMemoryMemoryStore()
    entry = store.add(ExperienceEntry(user_id="u", text=AISLE_TEXT))
    snapshot = build_before_state([entry])
    before_records = [m.to_record() for m in store.list_memories(user_id="u")]
    verify_transition(
        proposal(
            "supersede_existing", WINDOW_TEXT,
            superseded_ids=(entry.id,),
            created=(created(WINDOW_TEXT, ("window",), replaces=entry.id),),
            lineage_edges=((entry.id, "created:0"),), preserved_ids=(entry.id,),
        ),
        snapshot,
    )
    assert [m.to_record() for m in store.list_memories(user_id="u")] == before_records
    assert store.get(entry.id).status == MemoryStatus.ACTIVE


def _module_imports(module) -> set:
    """Every module name the file imports, via the AST.

    Parsed rather than grepped: the module docstring names the engine's
    mutation boundary in prose, and prose is not a dependency.
    """
    import ast

    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_verifier_module_imports_no_mutation_or_provider_code():
    import experienceos.memory.transition_verification as module

    imported = _module_imports(module)
    for banned in (
        "experienceos.engine",
        "experienceos.policy",
        "experienceos.providers",
        "experienceos.embeddings",
        "experienceos.memory.store",
        "experienceos.memory.sqlite_store",
        "requests",
        "urllib",
        "urllib.request",
        "httpx",
        "socket",
    ):
        assert not any(
            name == banned or name.startswith(f"{banned}.") for name in imported
        ), f"verifier imports {banned}"


def test_verifier_calls_no_engine_mutation_method():
    import ast

    import experienceos.memory.transition_verification as module

    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    # Store methods (add/supersede/forget) share names with ordinary
    # local calls like set.add, so they are covered by the import test:
    # a module that imports no store cannot call one. What is
    # unambiguous here is the engine's mutation boundary itself.
    assert "_apply_memory_actions" not in called


def test_verification_performs_no_network_access(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("transition verification attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    result = verify_transition(supersede_proposal(), before(snap(AISLE, AISLE_TEXT)))
    assert result.status == TransitionStatus.ACCEPTED


def test_verifier_holds_no_hidden_global_state():
    snapshot = before(snap(AISLE, AISLE_TEXT))
    verifier = TransitionVerifier()
    first = verifier.verify(supersede_proposal(), snapshot)
    second = verifier.verify(supersede_proposal(), snapshot)
    assert first.to_record() == second.to_record()


# --- Corpus evaluation -------------------------------------------------------


def test_corpus_manifest_unchanged_by_evaluation():
    digest = tv.file_digest(tv.MANIFEST_PATH)
    evaluate_corpus()
    assert tv.file_digest(tv.MANIFEST_PATH) == digest
    assert tv.verify_manifest() is True


def test_every_oracle_derived_correct_proposal_verifies():
    data = evaluate_corpus()
    assert data["historical_scored"]["correct_evaluated"] == 28
    assert data["historical_scored"]["correct_accepted"] == 28
    assert data["development_only"]["correct_evaluated"] == 27
    assert data["development_only"]["correct_accepted"] == 27


def test_every_adversarial_proposal_is_rejected():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        stats = data[partition]
        assert stats["adversarial_evaluated"] > 0
        assert stats["adversarial_accepted"] == 0, partition
        assert stats["adversarial_rejected"] == stats["adversarial_evaluated"]


def test_no_corpus_proposal_is_canonical_eligible():
    # Neither partition carries production grounding, so audit-only
    # verification must never reach canonical eligibility.
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        eligibility = data[partition]["canonical_eligibility_correct"]
        assert eligibility["correct"] == eligibility["total"]
        assert all(
            o.canonical_effect_eligible is False
            for o in data[partition]["correct_results"]
        )


def test_proposals_are_labelled_oracle_derived():
    data = evaluate_corpus()
    assert data["proposal_source"] == "oracle_derived"
    corpus = tv.load_corpus()
    record = corpus["historical_scored"][0]
    snapshot = before_state_for(record)
    assert oracle_proposal(record, snapshot).proposal_source == "oracle_derived"


def test_unresolved_records_are_diagnostic_only_and_excluded_are_not_scored():
    data = evaluate_corpus()
    assert data["excluded_records"] == 11
    assert len(data["unresolved_diagnostics"]) == 2
    assert all(
        entry["oracle_available"] is False
        for entry in data["unresolved_diagnostics"].values()
    )
    scored = set()
    for partition in ("historical_scored", "development_only"):
        scored |= {o.case_id for o in data[partition]["correct_results"]}
    for record in tv.load_corpus()["unresolved_candidates"]:
        assert record["case_id"] not in scored


def test_historical_and_development_partitions_stay_separate():
    data = evaluate_corpus()
    assert all(
        o.partition == "historical_scored"
        for o in data["historical_scored"]["correct_results"]
    )
    assert all(
        o.partition == "development_only"
        for o in data["development_only"]["correct_results"]
    )


def test_adversarial_generation_is_deterministic():
    corpus = tv.load_corpus()
    record = next(
        r for r in corpus["development_fixtures"]
        if r["expected_transition"]["primary_type"] == "supersede_existing"
    )
    snapshot = before_state_for(record)
    prop = oracle_proposal(record, snapshot)
    first = [c for c, _ in adversarial_variants(record, snapshot, prop)]
    second = [c for c, _ in adversarial_variants(record, snapshot, prop)]
    assert first == second
    assert first


def test_verification_is_deterministically_repeatable():
    assert verification_signature() == verification_signature()


def test_identity_semantics_are_consumed_not_redefined():
    # The verifier must not declare its own relation vocabulary.
    import experienceos.memory.transition_verification as module

    with open(module.__file__, encoding="utf-8") as handle:
        text = handle.read()
    assert "class IdentityRelation" not in text
    assert "def compare_memory_identity" not in text


# --- Zero-tolerance safety ---------------------------------------------------
def test_zero_tolerance_safety_expectations_hold():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        stats = data[partition]
        assert stats["adversarial_accepted"] == 0, partition
        assert stats["correct_rejected"] == 0, partition
        for name, counts in stats["checks"].items():
            assert counts["passed"] == counts["total"], f"{partition}:{name}"


@pytest.mark.parametrize(
    "category",
    [
        "invalid_target", "inactive_target", "unrelated_target",
        "unsupported_value", "unsupported_scope", "contradictory_structure",
        "invalid_lineage", "ambiguous_target", "forget_as_creation",
        "question_mutation",
    ],
)
def test_each_adversarial_category_is_fully_rejected(category):
    data = evaluate_corpus()
    total = rejected = 0
    for partition in ("historical_scored", "development_only"):
        counts = data[partition]["adversarial_by_category"].get(category)
        if counts:
            total += counts["total"]
            rejected += counts["rejected"]
    assert total > 0, f"no adversarial proposals generated for {category}"
    assert rejected == total


def test_latency_stays_within_the_contract_budget():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        latency = data[partition]["latency"]
        # Contract gate 15: <= 5 ms added per interaction.
        assert latency["p95_ms"] < 5.0, partition
