"""Deterministic update intelligence: intent, targeting, and safety.

All deterministic and offline: no provider, no model, no network, and no
lifecycle mutation anywhere in the subject under test.
"""

import json
import socket

import pytest

from benchmarks.annotations import transition_verification as tv
from benchmarks.update_intelligence.evaluation import (
    evaluate_corpus,
    is_classification_applicable,
    is_forget_boundary,
    proposal_signature,
)
from benchmarks.update_intelligence.reference import (
    build_planner,
    oracle_effect,
    reference_effect,
)
from experienceos.controllers.base import MemorySnapshot
from experienceos.memory import ExperienceEntry
from experienceos.memory.schema import MemoryKind, MemoryStatus
from experienceos.memory.store import InMemoryMemoryStore
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    TransitionStatus,
    build_before_state,
)
from experienceos.memory.update_intelligence import (
    UPDATE_CONTROLLER_ID,
    DeterministicUpdateController,
    TargetResolutionStatus,
    UpdateControllerConfig,
    UpdateIntentType,
    propose_update_transition,
)

AISLE = "mem.seat.short_work_trip"
AIRPORT = "mem.home_airport"
THEME = "mem.editor_theme"
DRINK = "mem.morning_drink"

AISLE_TEXT = "I prefer aisle seats for short work trips."
CONTROLLER = DeterministicUpdateController()


def snap(memory_id, text, kind=MemoryKind.PREFERENCE, status=MemoryStatus.ACTIVE):
    return MemorySnapshot(memory_id=memory_id, kind=kind, text=text, status=status)


def before(*snaps, coverage_complete=True):
    return build_before_state(list(snaps), coverage_complete=coverage_complete)


def evidence(statement, mode=EvidenceMode.GROUNDED_VALID):
    return TransitionSourceEvidence(
        source_statement=statement, source_event_id="evt-1", evidence_mode=mode
    )


def propose(statement, *snaps, controller=None, mode=EvidenceMode.GROUNDED_VALID):
    return (controller or CONTROLLER).propose(
        statement, evidence(statement, mode), before(*snaps)
    )


def seat_state():
    return snap(AISLE, AISLE_TEXT)


# --- Intent classification ----------------------------------------------------


@pytest.mark.parametrize(
    "statement,expected",
    [
        ("I prefer aisle seats for short work trips.", UpdateIntentType.DURABLE_ASSERTION),
        ("I now prefer window seats for short work trips.", UpdateIntentType.DIRECT_REPLACEMENT),
        ("Use SFO instead of SJC for my work flights.", UpdateIntentType.INSTEAD_OF_REPLACEMENT),
        ("I switched from Chrome to Firefox.", UpdateIntentType.SWITCHED_FROM_TO),
        ("I used to prefer aisle seats, but now I prefer window seats.", UpdateIntentType.USED_TO_NOW),
        ("Actually, make it window.", UpdateIntentType.CORRECTION),
        ("This time only, use a window seat.", UpdateIntentType.TEMPORARY_EXCEPTION),
        ("I used to prefer window seats.", UpdateIntentType.HISTORICAL_ONLY),
        ("If I moved to New York, I might use JFK.", UpdateIntentType.HYPOTHETICAL),
        ("Do you remember my seat preference?", UpdateIntentType.QUESTION),
        ("Forget that I prefer aisle seats.", UpdateIntentType.FORGET_DIRECTIVE),
        ("Don't forget that I prefer aisle seats.", UpdateIntentType.NEGATIVE_FORGET),
        ("Plan a short work trip to New York.", UpdateIntentType.TASK_REQUEST),
        ("Update my airport.", UpdateIntentType.VALUELESS_UPDATE_REQUEST),
        ("Always start my emails with a short friendly greeting.", UpdateIntentType.DURABLE_ASSERTION),
    ],
)
def test_intent_classification(statement, expected):
    result = propose(statement, seat_state())
    assert result.intent.intent_type == expected


def test_no_longer_now_is_a_replacement_not_a_forget():
    result = propose(
        "I no longer prefer aisle seats; I prefer window seats.", seat_state()
    )
    assert result.intent.intent_type == UpdateIntentType.NO_LONGER_NOW
    assert result.intent.pattern.old_value


def test_intent_classification_is_deterministic():
    first = propose("I now prefer window seats for short work trips.", seat_state())
    second = propose("I now prefer window seats for short work trips.", seat_state())
    assert first.intent.to_record() == second.intent.to_record()


# --- Pattern extraction -------------------------------------------------------


def test_instead_of_extracts_old_value_and_does_not_project_it_as_new():
    result = propose("Use SFO instead of SJC for my work flights.", seat_state())
    assert result.intent.pattern.old_value == "sjc"
    assert result.identity.value.value == "sfo"


def test_switched_from_to_extracts_both_values():
    result = propose("I switched from Chrome to Firefox.", seat_state())
    assert result.intent.pattern.old_value == "chrome"
    assert result.intent.pattern.new_value == "firefox"


def test_used_to_now_separates_historical_from_current():
    result = propose(
        "I used to prefer aisle seats, but now I prefer window seats.", seat_state()
    )
    assert result.intent.pattern.old_value == "aisle"
    assert result.identity.value.value == "window"
    assert result.identity.historical_value == "aisle"


def test_valueless_request_records_the_topic_and_no_value():
    result = propose("Change my seat preference.", seat_state())
    assert result.intent.pattern.topic == "seat"
    assert not result.identity.value.known


# --- Candidate identity -------------------------------------------------------


def test_controller_reuses_identity_and_declares_no_relation_vocabulary():
    import experienceos.memory.update_intelligence as module

    with open(module.__file__, encoding="utf-8") as handle:
        text = handle.read()
    assert "class IdentityRelation" not in text
    assert "def compare_memory_identity" not in text
    assert "def project_text" not in text


def test_projection_diagnostics_are_preserved():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.identity.target_key() is not None
    assert result.identity.semantic_key() is not None
    assert result.identity.completeness == 1.0


def test_unknown_identity_does_not_become_a_confident_supersession():
    result = propose("Change my seat preference.", seat_state())
    assert result.transition_type != "supersede_existing"
    assert result.proposal.superseded_ids == ()


# --- Target resolution --------------------------------------------------------


def test_one_current_state_conflict_resolves_one_target():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.target.status == TargetResolutionStatus.CONFLICT_TARGET
    assert result.target.target_id == AISLE
    assert result.proposal.superseded_ids == (AISLE,)


def test_multiple_plausible_targets_fail_closed():
    other = "mem.seat.long_international"
    result = propose(
        "Change my seat preference.",
        seat_state(),
        snap(other, "I prefer window seats for long international flights."),
    )
    assert result.target.status == TargetResolutionStatus.MULTIPLE_TARGETS
    assert result.transition_type == "reject_ambiguous"
    assert result.proposal.superseded_ids == ()


def test_no_active_memory_means_no_target():
    result = propose("I prefer aisle seats for short work trips.")
    assert result.transition_type == "create_new"
    assert result.proposal.superseded_ids == ()


def test_inactive_memory_is_never_selected_as_a_target():
    result = propose(
        "I now prefer window seats for short work trips.",
        snap(AISLE, AISLE_TEXT, status=MemoryStatus.SUPERSEDED),
    )
    assert result.proposal is None or result.proposal.superseded_ids == ()
    assert result.transition_type in (None, "create_new")


def test_unrelated_memories_are_not_selected_as_targets():
    result = propose(
        "I am allergic to shellfish.",
        seat_state(),
        snap(THEME, "I prefer dark mode in my code editor."),
    )
    assert result.transition_type == "create_new"
    assert result.proposal.superseded_ids == ()
    assert set(result.proposal.unchanged_ids) == {AISLE, THEME}


def test_explicit_old_value_mismatch_rejects_rather_than_retargets():
    # The source replaces JFK, but the only active airport memory holds
    # SJC: the proposal would be naming the wrong memory.
    result = propose(
        "Use SFO instead of JFK for my work flights.",
        snap(AIRPORT, "Use SJC for my work flights.", kind=MemoryKind.INSTRUCTION),
    )
    assert result.target.status == TargetResolutionStatus.OLD_VALUE_MISMATCH
    assert result.transition_type == "reject_unsupported"
    assert result.proposal.superseded_ids == ()


def test_explicit_old_value_match_permits_supersession():
    result = propose(
        "Use SFO instead of SJC for my work flights.",
        snap(AIRPORT, "Use SJC for my work flights.", kind=MemoryKind.INSTRUCTION),
    )
    assert result.transition_type == "supersede_existing"
    assert result.proposal.superseded_ids == (AIRPORT,)


# --- Duplicate proposals ------------------------------------------------------


def test_exact_restatement_is_a_duplicate_noop():
    result = propose(AISLE_TEXT, seat_state())
    assert result.transition_type == "duplicate_noop"
    assert result.proposal.created == ()
    assert result.proposal.superseded_ids == ()


def test_semantic_restatement_is_a_semantic_duplicate_noop():
    result = propose(
        "For short business trips, aisle seats are my usual choice.", seat_state()
    )
    assert result.transition_type == "semantic_duplicate_noop"
    assert result.proposal.created == ()


def test_different_scope_is_not_a_duplicate():
    result = propose(
        "For long international flights, I prefer aisle seats.", seat_state()
    )
    assert result.transition_type == "scoped_coexistence"


def test_different_value_is_not_a_duplicate():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.transition_type == "supersede_existing"


def test_duplicate_proposal_never_creates_a_second_memory():
    result = propose(AISLE_TEXT, seat_state())
    assert result.verification.projected_after_state.created_refs == ()
    assert result.verification.projected_after_state.active_ids == frozenset({AISLE})


# --- Supersession proposals ---------------------------------------------------


def test_supersession_proposal_has_target_created_value_and_lineage():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    proposal = result.proposal
    assert proposal.superseded_ids == (AISLE,)
    assert proposal.created[0].must_include
    assert proposal.lineage_edges == ((AISLE, "created:0"),)
    assert proposal.created[0].replaces == AISLE


def test_supersession_preserves_unrelated_memories():
    result = propose(
        "I now prefer window seats for short work trips.",
        seat_state(),
        snap(THEME, "I prefer dark mode in my code editor."),
        snap(AIRPORT, "My home airport is SJC.", kind=MemoryKind.FACT),
    )
    assert result.transition_type == "supersede_existing"
    assert set(result.proposal.unchanged_ids) == {THEME, AIRPORT}
    assert AISLE not in result.proposal.unchanged_ids


def test_correction_resolves_a_single_obvious_target():
    result = propose("Actually, make it window.", seat_state())
    assert result.transition_type == "supersede_existing"
    assert result.proposal.superseded_ids == (AISLE,)


def test_supersession_projects_one_current_value():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    projected = result.verification.projected_after_state
    assert AISLE in projected.superseded_ids
    assert "created:0" in projected.active_ids
    assert projected.stale_active_count == 0


# --- Repeated correction chain ------------------------------------------------


def test_repeated_correction_chain_keeps_one_active_value_and_stable_identity():
    # Three independent calls over three explicit snapshots; the
    # controller holds no state between them.
    steps = [
        ("I now prefer window seats for short work trips.", "v1", AISLE_TEXT),
        ("Actually, back to aisle for short work trips.", "v2",
         "I now prefer window seats for short work trips."),
        ("I now prefer middle seats for short work trips.", "v3",
         "I prefer aisle seats for short work trips."),
    ]
    target_keys = set()
    for statement, memory_id, current_text in steps:
        snapshot = before(snap(memory_id, current_text))
        result = CONTROLLER.propose(statement, evidence(statement), snapshot)
        assert result.transition_type == "supersede_existing", statement
        assert result.proposal.superseded_ids == (memory_id,)
        assert result.verification.status == TransitionStatus.ACCEPTED
        projected = result.verification.projected_after_state
        # Exactly one current value survives: the replacement.
        assert projected.active_ids == frozenset({"created:0"})
        assert projected.stale_active_count == 0
        # The slot being corrected is what must stay stable across the
        # chain. The *statement's* own key is not always available: an
        # elliptical correction ("back to aisle") names a value but no
        # attribute, so identity refuses it a key and the target is
        # resolved against the active set by value domain instead.
        target_keys.add(snapshot.identity_of(memory_id).target_key())
    assert len(target_keys) == 1


def test_elliptical_correction_has_no_statement_key_but_still_resolves():
    result = propose("Actually, back to aisle for short work trips.",
                     snap(AISLE, "I now prefer window seats for short work trips."))
    assert result.identity.target_key() is None
    assert result.target.status == TargetResolutionStatus.CONFLICT_TARGET
    assert result.proposal.superseded_ids == (AISLE,)


# --- Scoped coexistence -------------------------------------------------------


def test_distinct_supported_scope_coexists():
    result = propose(
        "For long international flights, I prefer window seats.", seat_state()
    )
    assert result.transition_type == "scoped_coexistence"
    assert result.proposal.superseded_ids == ()
    assert AISLE in result.proposal.unchanged_ids


def test_work_versus_personal_scope_coexists():
    result = propose(
        "For weekend personal trips, I prefer window seats.", seat_state()
    )
    assert result.transition_type == "scoped_coexistence"
    assert result.proposal.superseded_ids == ()


def test_same_scope_conflict_supersedes_rather_than_coexisting():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.transition_type == "supersede_existing"


def test_overlapping_scope_fails_closed():
    result = propose("I prefer window seats for work trips.", seat_state())
    assert result.transition_type == "reject_ambiguous"
    assert result.proposal.superseded_ids == ()


def test_lexical_near_match_does_not_supersede_a_scoped_memory():
    result = propose(
        "For weekend personal trips, I prefer window seats.", seat_state()
    )
    assert result.proposal.superseded_ids == ()
    assert result.verification.status == TransitionStatus.ACCEPTED


# --- Create-new ---------------------------------------------------------------


def test_unrelated_durable_addition_creates_and_preserves():
    result = propose(
        "I am allergic to shellfish.",
        seat_state(),
        snap(THEME, "I prefer dark mode in my code editor."),
    )
    assert result.transition_type == "create_new"
    assert set(result.proposal.unchanged_ids) == {AISLE, THEME}


def test_same_slot_conflict_never_creates_a_second_current_value():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.transition_type != "create_new"
    assert result.verification.projected_after_state.stale_active_count == 0


@pytest.mark.parametrize(
    "statement",
    [
        "This time only, use a window seat.",
        "I used to prefer window seats.",
        "Do you remember my seat preference?",
        "If I moved to New York, I might use JFK.",
        "Forget that I prefer aisle seats.",
    ],
)
def test_non_durable_sources_never_create(statement):
    result = propose(statement, seat_state())
    created = result.proposal.created if result.proposal else ()
    assert created == ()
    assert result.transition_type != "create_new"


# --- Rejections and abstentions -----------------------------------------------


@pytest.mark.parametrize(
    "statement,expected",
    [
        ("This time only, use a window seat.", "reject_temporary"),
        ("I used to prefer window seats.", "reject_unsupported"),
        ("If I moved to New York, I might use JFK.", "reject_hypothetical"),
        ("Do you remember my seat preference?", "reject_question"),
        ("Change my seat preference.", "reject_unsupported"),
        ("Plan a short work trip to New York.", "reject_unsupported"),
    ],
)
def test_rejection_proposals_use_frozen_transition_types(statement, expected):
    result = propose(statement, seat_state())
    assert result.transition_type == expected
    assert result.proposal.superseded_ids == ()
    assert result.proposal.created == ()


def test_temporary_statement_preserves_the_current_durable_value():
    result = propose("This time only, use a window seat.", seat_state())
    assert result.verification.projected_after_state.active_ids == frozenset({AISLE})


def test_historical_only_statement_preserves_the_current_value():
    result = propose(
        "I used to be based in the Denver office.",
        snap("mem.office", "I am based in the Austin office.", kind=MemoryKind.FACT),
    )
    assert result.transition_type == "reject_unsupported"
    assert result.verification.projected_after_state.active_ids == frozenset(
        {"mem.office"}
    )


def test_unusable_evidence_abstains_rather_than_proposing():
    result = propose(
        "I now prefer window seats for short work trips.", seat_state(),
        mode=EvidenceMode.UNGROUNDED,
    )
    assert result.abstained is True
    assert result.proposal is None
    assert result.abstention_reason == "evidence_unusable"


def test_abstention_is_not_reported_as_a_proposal():
    result = propose(
        "Forget that I prefer aisle seats.", seat_state()
    )
    assert result.abstained is True
    assert result.transition_type is None


# --- Forget boundary ----------------------------------------------------------


def test_affirmative_forget_hands_off_and_creates_nothing():
    result = propose("Forget that I prefer aisle seats.", seat_state())
    assert result.intent.intent_type == UpdateIntentType.FORGET_DIRECTIVE
    assert result.abstained is True
    assert result.abstention_reason == "forget_directive_detected"
    assert result.proposal is None


def test_negative_forget_produces_no_forget_and_no_duplicate_creation():
    result = propose("Don't forget that I prefer aisle seats.", seat_state())
    assert result.intent.intent_type == UpdateIntentType.NEGATIVE_FORGET
    assert result.transition_type in ("duplicate_noop", "semantic_duplicate_noop")
    assert result.proposal.forgotten_ids == ()
    assert result.proposal.created == ()


def test_forget_question_is_a_question_not_a_mutation():
    result = propose("Can you forget my seat preference?", seat_state())
    assert result.transition_type == "reject_question"
    assert result.proposal.forgotten_ids == ()


def test_controller_resolves_no_forget_targets():
    # Formal forget targeting is out of scope: the controller must not
    # emit a forget proposal for any source.
    for statement in (
        "Forget that I prefer aisle seats.",
        "Forget everything about travel.",
        "Forget my seat thing.",
    ):
        result = propose(statement, seat_state())
        assert result.proposal is None or result.proposal.forgotten_ids == ()


# --- Verifier integration -----------------------------------------------------


def test_every_actionable_proposal_is_verified():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.verification is not None
    assert result.verification.status == TransitionStatus.ACCEPTED


def test_verifier_rejection_remains_visible_and_blocks_eligibility():
    class RejectingVerifier:
        def verify(self, proposal, before_state):
            from experienceos.memory.transition_verification import (
                TransitionVerificationResult,
            )

            return TransitionVerificationResult(
                proposal_id=proposal.proposal_id,
                transition_type=proposal.transition_type,
                status=TransitionStatus.REJECTED,
                rejection_reason="target_not_found",
            )

    controller = DeterministicUpdateController(verifier=RejectingVerifier())
    result = controller.propose(
        "I now prefer window seats for short work trips.",
        evidence("I now prefer window seats for short work trips."),
        before(seat_state()),
    )
    assert result.verification.status == TransitionStatus.REJECTED
    assert result.verification.rejection_reason == "target_not_found"
    assert result.canonical_effect_eligible is False
    # The controller must not silently retry as a different transition.
    assert result.transition_type == "supersede_existing"


def test_grounded_evidence_can_reach_eligibility_but_never_application():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.canonical_effect_eligible is True
    assert result.action_applied is False
    assert result.verification.action_applied is False


def test_audit_only_evidence_is_never_canonical_eligible():
    for mode in (EvidenceMode.HISTORICAL_ORACLE, EvidenceMode.DEVELOPMENT_FIXTURE):
        result = propose(
            "I now prefer window seats for short work trips.", seat_state(), mode=mode
        )
        assert result.verification.status == TransitionStatus.ACCEPTED
        assert result.canonical_effect_eligible is False


def test_verification_can_be_disabled_without_claiming_acceptance():
    controller = DeterministicUpdateController(
        config=UpdateControllerConfig(verify=False)
    )
    result = controller.propose(
        AISLE_TEXT, evidence(AISLE_TEXT), before(seat_state())
    )
    assert result.verification is None
    assert result.canonical_effect_eligible is False


# --- Non-mutation -------------------------------------------------------------


def test_controller_does_not_mutate_its_inputs():
    snapshot = before(seat_state())
    snapshot_before = json.dumps(snapshot.to_record(), sort_keys=True)
    CONTROLLER.propose(
        "I now prefer window seats for short work trips.",
        evidence("I now prefer window seats for short work trips."),
        snapshot,
    )
    assert json.dumps(snapshot.to_record(), sort_keys=True) == snapshot_before


def test_controller_never_writes_to_a_store():
    store = InMemoryMemoryStore()
    entry = store.add(ExperienceEntry(user_id="u", text=AISLE_TEXT))
    snapshot = build_before_state([entry])
    records = [m.to_record() for m in store.list_memories(user_id="u")]
    CONTROLLER.propose(
        "I now prefer window seats for short work trips.",
        evidence("I now prefer window seats for short work trips."),
        snapshot,
    )
    assert [m.to_record() for m in store.list_memories(user_id="u")] == records
    assert store.get(entry.id).status == MemoryStatus.ACTIVE


def test_controller_module_imports_no_mutation_or_provider_code():
    import ast

    import experienceos.memory.update_intelligence as module

    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in (
        "experienceos.engine",
        "experienceos.policy",
        "experienceos.providers",
        "experienceos.embeddings",
        "experienceos.memory.store",
        "experienceos.memory.sqlite_store",
        "requests",
        "urllib",
        "httpx",
        "socket",
    ):
        assert not any(
            n == banned or n.startswith(f"{banned}.") for n in imported
        ), f"controller imports {banned}"


def test_controller_is_stateless_across_calls():
    first = propose("I now prefer window seats for short work trips.", seat_state())
    propose("I am allergic to shellfish.", seat_state())
    second = propose("I now prefer window seats for short work trips.", seat_state())
    assert first.proposal.to_record() == second.proposal.to_record()


def test_controller_performs_no_network_access(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("update controller attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    result = propose("I now prefer window seats for short work trips.", seat_state())
    assert result.transition_type == "supersede_existing"


def test_module_api_is_available_without_a_verifier_instance():
    result = propose_update_transition(
        AISLE_TEXT, evidence(AISLE_TEXT), before(seat_state())
    )
    assert result.transition_type == "duplicate_noop"
    assert result.controller_id == UPDATE_CONTROLLER_ID


# --- Diagnostics --------------------------------------------------------------


def test_diagnostics_are_structured_stable_and_bounded():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    codes = [d.code for d in result.diagnostics]
    assert "intent_classified" in codes
    assert "target_resolved" in codes
    assert "verifier_status" in codes
    assert len(result.diagnostics) <= 6


def test_result_serializes_deterministically():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    first = json.dumps(result.to_record(), sort_keys=True)
    second = json.dumps(result.to_record(), sort_keys=True)
    assert first == second
    assert json.loads(first)["action_applied"] is False


def test_diagnostics_leak_no_paths_or_secrets():
    result = propose("I now prefer window seats for short work trips.", seat_state())
    blob = json.dumps(result.to_record())
    assert "/Users/" not in blob
    assert "/home/" not in blob
    for secret in ("api_key", "password", "secret"):
        assert secret not in blob.lower()


def test_candidate_diagnostics_are_bounded():
    controller = DeterministicUpdateController(
        config=UpdateControllerConfig(max_candidate_diagnostics=2)
    )
    result = controller.propose(
        "I am allergic to shellfish.",
        evidence("I am allergic to shellfish."),
        before(
            seat_state(),
            snap(THEME, "I prefer dark mode in my code editor."),
            snap(AIRPORT, "My home airport is SJC.", kind=MemoryKind.FACT),
            snap(DRINK, "I prefer tea in the morning."),
        ),
    )
    assert len(result.target.candidates) <= 2


# --- Corpus evaluation --------------------------------------------------------


def test_corpus_manifest_unchanged_by_evaluation():
    digest = tv.file_digest(tv.MANIFEST_PATH)
    evaluate_corpus()
    assert tv.file_digest(tv.MANIFEST_PATH) == digest
    assert tv.verify_manifest() is True


def test_applicability_excludes_forget_boundary_cases():
    corpus = tv.load_corpus()
    historical = [r for r in corpus["historical_scored"] if is_classification_applicable(r)]
    development = [
        r for r in corpus["development_fixtures"] if is_classification_applicable(r)
    ]
    assert len(historical) == 24
    assert len(development) == 24
    assert sum(1 for r in corpus["historical_scored"] if is_forget_boundary(r)) == 4
    assert sum(1 for r in corpus["development_fixtures"] if is_forget_boundary(r)) == 3


def test_measured_transition_accuracy_matches_the_reported_result():
    data = evaluate_corpus()
    assert data["historical_scored"]["transition_accuracy"] == {
        "correct": 24, "total": 24,
    }
    assert data["development_only"]["transition_accuracy"] == {
        "correct": 24, "total": 24,
    }
    # One development fixture is labelled `duplicate_noop` while the
    # controller emits the more specific `semantic_duplicate_noop`.
    assert data["development_only"]["transition_accuracy_strict"] == {
        "correct": 23, "total": 24,
    }


def test_measured_target_accuracy_is_complete():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        target = data[partition]["target"]
        assert target["correct"] == target["cases_requiring_target"]
        assert target["wrong"] == 0
        assert target["spurious_targets"] == 0


def test_every_corpus_proposal_is_accepted_by_the_verifier():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        verification = data[partition]["verification"]
        assert verification["accepted"] == verification["verified"]
        assert verification["rejected"] == 0
        assert verification["action_applied"] == 0


def test_forget_boundary_creates_nothing_positive():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        boundary = data[partition]["forget_boundary"]
        assert boundary["positive_creations"] == 0
        assert boundary["handed_off"] == boundary["cases"]


def test_zero_tolerance_safety_expectations_hold():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        for key, value in data[partition]["safety"].items():
            assert value == 0, f"{partition}:{key}={value}"


def test_unresolved_and_excluded_records_are_not_scored():
    data = evaluate_corpus()
    assert data["excluded_records"] == 11
    assert data["unresolved_records"] == 2
    scored = set()
    for partition in ("historical_scored", "development_only"):
        scored |= {o.case_id for o in data[partition]["outcomes"]}
    for record in tv.load_corpus()["unresolved_candidates"]:
        assert record["case_id"] not in scored


def test_partitions_are_reported_separately():
    data = evaluate_corpus()
    assert all(
        o.partition == "historical_scored"
        for o in data["historical_scored"]["outcomes"]
    )
    assert all(
        o.partition == "development_only"
        for o in data["development_only"]["outcomes"]
    )


def test_controller_output_is_independent_of_the_expected_oracle():
    # The controller only ever sees the statement, the evidence, and the
    # before-state; nothing derived from `expected_transition`.
    import inspect

    import experienceos.memory.update_intelligence as module

    source = inspect.getsource(module)
    assert "expected_transition" not in source
    assert "benchmarks" not in source


def test_evaluation_is_deterministically_repeatable():
    assert proposal_signature() == proposal_signature()


def test_reference_evaluation_is_deterministic_and_read_only():
    corpus = tv.load_corpus()
    planner = build_planner()
    record = next(
        r for r in corpus["development_fixtures"]
        if r["source_case_id"] == "direct_replacement-01"
    )
    first = reference_effect(record, planner)
    second = reference_effect(record, planner)
    assert first.to_record() == second.to_record()
    assert oracle_effect(record).superseded == {"fx.travel.seat.short_work_trip"}


def test_latency_stays_within_the_contract_budget():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        latency = data[partition]["latency"]
        # Contract gate 15: <= 5 ms mean added per interaction.
        assert latency["p95_ms"] < 5.0, partition
