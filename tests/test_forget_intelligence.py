"""Forget-directive classification, target safety, and preservation.

All deterministic and offline: no provider, no model, no network, and no
lifecycle mutation anywhere in the subject under test.
"""

import json
import socket

import pytest

from benchmarks.annotations import transition_verification as tv
from benchmarks.forget_intelligence.evaluation import (
    evaluate_corpus,
    forget_signature,
    is_abstention_case,
    is_forget_applicable,
)
from experienceos.controllers.base import MemorySnapshot
from experienceos.memory import ExperienceEntry
from experienceos.memory.forget_intelligence import (
    FORGET_CONTROLLER_ID,
    DeterministicForgetController,
    ForgetAbstentionReason,
    ForgetControllerConfig,
    ForgetDirectiveType,
    ForgetTargetResolutionStatus,
    propose_forget_transition,
)
from experienceos.memory.schema import MemoryKind, MemoryStatus
from experienceos.memory.store import InMemoryMemoryStore
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    TransitionStatus,
    build_before_state,
)

AISLE = "mem.seat.short_work_trip"
WINDOW = "mem.seat.long_international"
AIRPORT = "mem.work_flight_airport"
THEME = "mem.editor_theme"
CILANTRO = "mem.food.dislike"

AISLE_TEXT = "I prefer aisle seats for short work trips."
WINDOW_TEXT = "I prefer window seats for long international flights."
CONTROLLER = DeterministicForgetController()


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
        ("Forget that I prefer aisle seats.", ForgetDirectiveType.AFFIRMATIVE_TARGETED),
        ("Don't forget that I prefer aisle seats.", ForgetDirectiveType.NEGATIVE_FORGET),
        ("Never forget my SFO preference.", ForgetDirectiveType.NEGATIVE_FORGET),
        ("Can you forget my seat preference?", ForgetDirectiveType.FORGET_CAPABILITY_QUESTION),
        ("Do you remember my seat preference?", ForgetDirectiveType.MEMORY_INSPECTION_QUESTION),
        ("What do you remember about my seat preference?", ForgetDirectiveType.MEMORY_INSPECTION_QUESTION),
        ("If I asked you to forget my seat preference, what would happen?", ForgetDirectiveType.HYPOTHETICAL_FORGET),
        ("Forget everything about travel.", ForgetDirectiveType.BROAD_FORGET),
        ("Forget all my preferences.", ForgetDirectiveType.BROAD_FORGET),
        ("I prefer aisle seats for short work trips.", ForgetDirectiveType.UNRELATED_SOURCE),
        ("My phone is a Pixel 9 now.", ForgetDirectiveType.UNRELATED_SOURCE),
    ],
)
def test_directive_classification(statement, expected):
    result = propose(statement, seat_state())
    assert result.classification.directive_type == expected


def test_forget_without_the_word_forget_is_still_a_directive():
    # The canonical detector recognises removal wording that never says
    # "forget"; a wording gate in front of it would miss real directives.
    result = propose(
        "I don't care about my study schedule preference anymore.",
        snap("mem.study", "I prefer studying in the evening."),
    )
    assert result.classification.directive_type == (
        ForgetDirectiveType.AFFIRMATIVE_TARGETED
    )


def test_removal_with_a_supplied_replacement_is_not_a_forget():
    # "no longer X; I prefer Y" is a supersession. Claiming it here would
    # give one sentence two competing readings.
    result = propose(
        "I no longer prefer aisle seats; I prefer window seats.", seat_state()
    )
    assert result.classification.directive_type == ForgetDirectiveType.UNRELATED_SOURCE
    assert result.abstained is True


def test_classification_is_deterministic():
    first = propose("Forget that I prefer aisle seats.", seat_state())
    second = propose("Forget that I prefer aisle seats.", seat_state())
    assert first.classification.to_record() == second.classification.to_record()


# --- Pattern extraction -------------------------------------------------------


def test_forget_that_payload_is_extracted():
    result = propose("Forget that I prefer aisle seats.", seat_state())
    assert "aisle" in result.classification.pattern.target_text.lower()


def test_forget_my_preference_payload_is_extracted():
    result = propose("Forget my seat preference.", seat_state())
    assert "seat" in result.classification.pattern.target_text.lower()


def test_stop_remembering_payload_is_extracted():
    result = propose(
        "Stop remembering that I prefer aisle seats.", seat_state()
    )
    assert result.classification.affirmative is True
    assert "aisle" in result.classification.pattern.target_text.lower()


def test_trailing_modifier_is_stripped_from_the_payload():
    result = propose("Forget my seat preference entirely.", seat_state())
    assert not result.classification.pattern.target_text.lower().endswith("entirely")


# --- Target description -------------------------------------------------------


def test_target_description_carries_structured_identity():
    result = propose("Forget that I prefer aisle seats.", seat_state())
    description = result.description
    assert description is not None
    assert description.value == "aisle"
    assert description.attribute == "seat"
    assert description.tokens


def test_target_description_marks_unknown_fields_without_inventing_them():
    result = propose("Forget my seat thing.", seat_state())
    assert result.description is not None
    assert "value" in result.description.unknown_fields
    assert result.description.value == "unknown"


def test_target_description_does_not_borrow_scope_from_an_active_memory():
    # The active memory is scoped short_work_trip; the request is not.
    result = propose("Forget that I prefer aisle seats.", seat_state())
    assert result.description.scope_specified is False


# --- Candidate selection and resolution ---------------------------------------


def test_exact_active_target_resolves():
    result = propose("Forget that I don't like cilantro.",
                     snap(CILANTRO, "I don't like cilantro."))
    assert result.transition_type == "forget_existing"
    assert result.proposal.forgotten_ids == (CILANTRO,)
    assert result.target.status in (
        ForgetTargetResolutionStatus.EXACT_TARGET,
        ForgetTargetResolutionStatus.SEMANTIC_TARGET,
    )


def test_semantic_active_target_resolves():
    result = propose("Forget my morning drink preference entirely.",
                     snap("mem.drink", "Actually, I prefer coffee in the morning."))
    assert result.transition_type == "forget_existing"
    assert result.proposal.forgotten_ids == ("mem.drink",)


def test_attribute_only_description_resolves_when_one_memory_matches():
    result = propose("Forget my seat preference.", seat_state())
    assert result.transition_type == "forget_existing"
    assert result.proposal.forgotten_ids == (AISLE,)


def test_attribute_only_ambiguity_fails_closed():
    result = propose("Forget my seat thing.", seat_state(), snap(WINDOW, WINDOW_TEXT))
    assert result.transition_type == "reject_ambiguous"
    assert result.proposal.forgotten_ids == ()
    assert result.target.status == ForgetTargetResolutionStatus.MULTIPLE_TARGETS


def test_ambiguous_result_lists_bounded_candidates():
    result = propose("Forget my seat thing.", seat_state(), snap(WINDOW, WINDOW_TEXT))
    assert result.target.candidates
    assert len(result.target.candidates) <= 4


def test_no_active_match_does_not_guess():
    result = propose("Forget my browser preference.", seat_state())
    assert result.transition_type != "forget_existing"
    assert result.proposal.forgotten_ids == ()


def test_unrelated_memories_are_never_selected():
    result = propose(
        "Forget that I don't like cilantro.",
        snap(CILANTRO, "I don't like cilantro."),
        snap(THEME, "I prefer dark mode in my code editor."),
        snap(AIRPORT, "Use SJC for my work flights.", kind=MemoryKind.INSTRUCTION),
    )
    assert result.proposal.forgotten_ids == (CILANTRO,)
    assert set(result.proposal.unchanged_ids) == {THEME, AIRPORT}


def test_candidate_ordering_is_deterministic():
    first = propose("Forget my seat thing.", seat_state(), snap(WINDOW, WINDOW_TEXT))
    second = propose("Forget my seat thing.", seat_state(), snap(WINDOW, WINDOW_TEXT))
    assert first.target.candidates == second.target.candidates
    assert first.target.scores == second.target.scores


# --- Scoped forget ------------------------------------------------------------


def test_scoped_forget_selects_the_matching_scope_and_preserves_the_other():
    result = propose(
        "Forget my seat preference for short work trips.",
        seat_state(),
        snap(WINDOW, WINDOW_TEXT),
    )
    assert result.transition_type == "forget_existing"
    assert result.proposal.forgotten_ids == (AISLE,)
    assert WINDOW in result.proposal.unchanged_ids


def test_unscoped_request_over_several_scopes_is_ambiguous():
    result = propose(
        "Forget my seat preference.", seat_state(), snap(WINDOW, WINDOW_TEXT)
    )
    assert result.transition_type == "reject_ambiguous"
    assert result.proposal.forgotten_ids == ()


def test_scoped_forget_preserves_every_other_scope_in_projection():
    result = propose(
        "Forget my seat preference for short work trips.",
        seat_state(),
        snap(WINDOW, WINDOW_TEXT),
    )
    projected = result.verification.projected_after_state
    assert WINDOW in projected.active_ids
    assert AISLE in projected.forgotten_ids


# --- Inactive targets ---------------------------------------------------------


def test_forgotten_only_match_yields_no_canonical_forget():
    result = propose(
        "Forget that I don't like cilantro.",
        snap(CILANTRO, "I don't like cilantro.", status=MemoryStatus.FORGOTTEN),
    )
    assert result.transition_type != "forget_existing"
    assert result.canonical_effect_eligible is False


def test_superseded_only_match_yields_no_canonical_forget():
    result = propose(
        "Forget that I don't like cilantro.",
        snap(CILANTRO, "I don't like cilantro.", status=MemoryStatus.SUPERSEDED),
    )
    assert result.transition_type != "forget_existing"
    assert result.proposal.forgotten_ids == ()


def test_repeated_forget_of_an_already_forgotten_memory_is_not_repeated():
    snapshot = before(
        snap(CILANTRO, "I don't like cilantro.", status=MemoryStatus.FORGOTTEN)
    )
    result = CONTROLLER.propose(
        "Forget that I don't like cilantro.",
        evidence("Forget that I don't like cilantro."),
        snapshot,
    )
    assert result.proposal.forgotten_ids == ()
    assert result.canonical_effect_eligible is False


def test_active_match_wins_over_an_inactive_one():
    result = propose(
        "Forget my morning drink preference entirely.",
        snap("mem.drink.old", "I prefer tea in the morning.",
             status=MemoryStatus.SUPERSEDED),
        snap("mem.drink.new", "Actually, I prefer coffee in the morning."),
    )
    assert result.proposal.forgotten_ids == ("mem.drink.new",)


def test_no_proposal_ever_reactivates_an_inactive_memory():
    result = propose(
        "Forget that I don't like cilantro.",
        snap(CILANTRO, "I don't like cilantro.", status=MemoryStatus.FORGOTTEN),
        snap(AISLE, AISLE_TEXT),
    )
    projected = result.verification.projected_after_state
    assert CILANTRO not in projected.active_ids


# --- Negative forget ----------------------------------------------------------


def test_negative_forget_produces_no_forget_and_no_creation():
    result = propose("Don't forget that I prefer aisle seats.", seat_state())
    assert result.transition_type in ("duplicate_noop", "semantic_duplicate_noop")
    assert result.proposal.forgotten_ids == ()
    assert result.proposal.created == ()


def test_negative_forget_over_an_exact_memory_is_a_no_op():
    result = propose("Don't forget that I don't like cilantro.",
                     snap(CILANTRO, "I don't like cilantro."))
    assert result.transition_type in ("duplicate_noop", "semantic_duplicate_noop")
    assert result.verification.projected_after_state.active_ids == frozenset({CILANTRO})


def test_negative_forget_of_an_absent_memory_hands_off_without_creating():
    result = propose("Don't forget that I use Firefox.", seat_state())
    assert result.abstained is True
    assert result.abstention_reason == ForgetAbstentionReason.UPDATE_HANDOFF
    assert result.proposal is None


# --- Questions and hypotheticals -----------------------------------------------


@pytest.mark.parametrize(
    "statement,expected",
    [
        ("Can you forget my seat preference?", "reject_question"),
        ("Could you remove my airport preference?", "reject_question"),
        ("Do you remember my seat preference?", "reject_question"),
        ("If I asked you to forget my seat preference, what would happen?",
         "reject_hypothetical"),
        ("Suppose I wanted you to forget my seat preference.",
         "reject_hypothetical"),
    ],
)
def test_questions_and_hypotheticals_never_mutate(statement, expected):
    result = propose(statement, seat_state())
    assert result.transition_type == expected
    assert result.proposal.forgotten_ids == ()
    assert result.proposal.created == ()
    assert result.verification.projected_after_state.active_ids == frozenset({AISLE})


def test_polite_question_grammar_is_not_permission_to_mutate():
    result = propose("Could you forget my seat preference?", seat_state())
    assert result.transition_type == "reject_question"
    assert result.canonical_effect_eligible is False


# --- Broad and ambiguous ------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "Forget everything about travel.",
        "Forget all my preferences.",
        "Delete everything you know about me.",
    ],
)
def test_broad_requests_fail_closed_without_partial_deletion(statement):
    result = propose(statement, seat_state(), snap(WINDOW, WINDOW_TEXT))
    assert result.transition_type == "reject_unsupported"
    assert result.proposal.forgotten_ids == ()
    assert result.target.status == ForgetTargetResolutionStatus.BROAD_UNSUPPORTED


def test_broad_request_never_selects_a_subset():
    result = propose("Forget everything about travel.", seat_state(),
                     snap(WINDOW, WINDOW_TEXT))
    projected = result.verification.projected_after_state
    assert projected.active_ids == frozenset({AISLE, WINDOW})


def test_no_proposal_ever_forgets_more_than_one_memory():
    for statement in (
        "Forget that I prefer aisle seats.",
        "Forget my seat preference.",
        "Forget everything about travel.",
        "Forget my seat preference and my airport preference.",
    ):
        result = propose(statement, seat_state(), snap(WINDOW, WINDOW_TEXT),
                         snap(AIRPORT, "Use SJC for my work flights.",
                              kind=MemoryKind.INSTRUCTION))
        forgotten = result.proposal.forgotten_ids if result.proposal else ()
        assert len(forgotten) <= 1, statement


# --- Proposal construction ----------------------------------------------------


def test_forget_proposal_has_one_target_no_creation_and_no_lineage():
    result = propose("Forget that I don't like cilantro.",
                     snap(CILANTRO, "I don't like cilantro."))
    proposal = result.proposal
    assert proposal.forgotten_ids == (CILANTRO,)
    assert proposal.created == ()
    assert proposal.superseded_ids == ()
    assert proposal.lineage_edges == ()


def test_forget_proposal_preserves_the_target_as_audit_state():
    result = propose("Forget that I don't like cilantro.",
                     snap(CILANTRO, "I don't like cilantro."))
    assert CILANTRO in result.proposal.preserved_ids
    projected = result.verification.projected_after_state
    assert CILANTRO in projected.forgotten_ids


def test_proposal_construction_is_deterministic():
    first = propose("Forget that I prefer aisle seats.", seat_state())
    second = propose("Forget that I prefer aisle seats.", seat_state())
    assert first.proposal.to_record() == second.proposal.to_record()


def test_controller_never_constructs_a_created_memory_for_any_forget_source():
    for statement in (
        "Forget that I prefer aisle seats.",
        "Forget my seat preference.",
        "Forget everything about travel.",
        "Can you forget my seat preference?",
        "Don't forget that I prefer aisle seats.",
        "If I asked you to forget my seat preference, what would happen?",
    ):
        result = propose(statement, seat_state())
        created = result.proposal.created if result.proposal else ()
        assert created == (), statement


# --- Forget-as-creation prevention --------------------------------------------


def test_historical_forget_as_creation_case_creates_nothing():
    # The committed grounded-extraction false positive: a forget
    # directive that was previously read as a positive preference.
    result = propose(
        "Forget that I prefer morning flights.",
        snap("mem.flight_time", "I prefer morning flights."),
    )
    assert result.transition_type == "forget_existing"
    assert result.proposal.created == ()
    assert result.proposal.superseded_ids == ()
    assert result.proposal.forgotten_ids == ("mem.flight_time",)


def test_scoped_forget_wording_creates_nothing():
    result = propose(
        "Forget my seat preference for short work trips.", seat_state()
    )
    assert result.proposal.created == ()
    assert result.proposal.superseded_ids == ()


# --- Verifier integration -----------------------------------------------------


def test_every_actionable_proposal_is_verified():
    result = propose("Forget that I don't like cilantro.",
                     snap(CILANTRO, "I don't like cilantro."))
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
                rejection_reason="target_not_active",
            )

    controller = DeterministicForgetController(verifier=RejectingVerifier())
    result = controller.propose(
        "Forget that I prefer aisle seats.",
        evidence("Forget that I prefer aisle seats."),
        before(seat_state()),
    )
    assert result.verification.status == TransitionStatus.REJECTED
    assert result.canonical_effect_eligible is False
    # The controller does not retry as a different transition.
    assert result.transition_type == "forget_existing"


def test_grounded_evidence_can_reach_eligibility_but_never_application():
    result = propose("Forget that I don't like cilantro.",
                     snap(CILANTRO, "I don't like cilantro."))
    assert result.canonical_effect_eligible is True
    assert result.authorized is False
    assert result.action_applied is False
    assert result.verification.action_applied is False


def test_audit_only_evidence_is_never_canonical_eligible():
    for mode in (EvidenceMode.HISTORICAL_ORACLE, EvidenceMode.DEVELOPMENT_FIXTURE):
        result = propose("Forget that I don't like cilantro.",
                         snap(CILANTRO, "I don't like cilantro."), mode=mode)
        assert result.verification.status == TransitionStatus.ACCEPTED
        assert result.canonical_effect_eligible is False


def test_unusable_evidence_abstains():
    result = propose("Forget that I prefer aisle seats.", seat_state(),
                     mode=EvidenceMode.UNGROUNDED)
    assert result.abstained is True
    assert result.abstention_reason == ForgetAbstentionReason.EVIDENCE_UNUSABLE
    assert result.proposal is None


# --- Preservation -------------------------------------------------------------


def test_only_the_target_changes_in_projected_state():
    result = propose(
        "Forget that I don't like cilantro.",
        snap(CILANTRO, "I don't like cilantro."),
        seat_state(),
        snap(THEME, "I prefer dark mode in my code editor."),
        snap(AIRPORT, "Use SJC for my work flights.", kind=MemoryKind.INSTRUCTION),
    )
    projected = result.verification.projected_after_state
    assert projected.active_ids == frozenset({AISLE, THEME, AIRPORT})
    assert projected.forgotten_ids == frozenset({CILANTRO})


def test_rejection_preserves_all_state():
    result = propose("Forget my seat thing.", seat_state(), snap(WINDOW, WINDOW_TEXT))
    projected = result.verification.projected_after_state
    assert projected.active_ids == frozenset({AISLE, WINDOW})
    assert projected.forgotten_ids == frozenset()


# --- Non-mutation -------------------------------------------------------------


def test_controller_does_not_mutate_its_inputs():
    snapshot = before(seat_state())
    snapshot_before = json.dumps(snapshot.to_record(), sort_keys=True)
    CONTROLLER.propose(
        "Forget that I prefer aisle seats.",
        evidence("Forget that I prefer aisle seats."),
        snapshot,
    )
    assert json.dumps(snapshot.to_record(), sort_keys=True) == snapshot_before


def test_controller_never_writes_to_a_store():
    store = InMemoryMemoryStore()
    entry = store.add(ExperienceEntry(user_id="u", text="I don't like cilantro."))
    snapshot = build_before_state([entry])
    records = [m.to_record() for m in store.list_memories(user_id="u")]
    CONTROLLER.propose(
        "Forget that I don't like cilantro.",
        evidence("Forget that I don't like cilantro."),
        snapshot,
    )
    assert [m.to_record() for m in store.list_memories(user_id="u")] == records
    assert store.get(entry.id).status == MemoryStatus.ACTIVE


def test_controller_module_imports_no_mutation_or_provider_code():
    import ast

    import experienceos.memory.forget_intelligence as module

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
        ), f"forget controller imports {banned}"


def test_controller_calls_no_store_mutation_method():
    import ast

    import experienceos.memory.forget_intelligence as module

    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_apply_memory_actions" not in called
    assert "supersede" not in called


def test_controller_is_stateless_across_calls():
    first = propose("Forget that I prefer aisle seats.", seat_state())
    propose("Forget everything about travel.", seat_state())
    second = propose("Forget that I prefer aisle seats.", seat_state())
    assert first.proposal.to_record() == second.proposal.to_record()


def test_controller_performs_no_network_access(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("forget controller attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    result = propose("Forget that I prefer aisle seats.", seat_state())
    assert result.transition_type == "forget_existing"


def test_module_api_is_available_without_a_controller_instance():
    result = propose_forget_transition(
        "Forget that I prefer aisle seats.",
        evidence("Forget that I prefer aisle seats."),
        before(seat_state()),
    )
    assert result.transition_type == "forget_existing"
    assert result.controller_id == FORGET_CONTROLLER_ID


# --- Diagnostics --------------------------------------------------------------


def test_diagnostics_are_structured_stable_and_bounded():
    result = propose("Forget that I prefer aisle seats.", seat_state())
    codes = [d.code for d in result.diagnostics]
    assert "directive_classified" in codes
    assert "target_resolved" in codes
    assert "verifier_status" in codes
    assert len(result.diagnostics) <= 6


def test_result_serializes_deterministically():
    result = propose("Forget that I prefer aisle seats.", seat_state())
    first = json.dumps(result.to_record(), sort_keys=True)
    second = json.dumps(result.to_record(), sort_keys=True)
    assert first == second
    assert json.loads(first)["action_applied"] is False
    assert json.loads(first)["authorized"] is False


def test_diagnostics_leak_no_paths_or_secrets():
    result = propose("Forget that I prefer aisle seats.", seat_state())
    blob = json.dumps(result.to_record())
    assert "/Users/" not in blob
    assert "/home/" not in blob
    for secret in ("api_key", "password", "secret"):
        assert secret not in blob.lower()


def test_candidate_diagnostics_are_bounded_by_configuration():
    controller = DeterministicForgetController(
        config=ForgetControllerConfig(max_candidate_diagnostics=1)
    )
    result = controller.propose(
        "Forget my seat thing.",
        evidence("Forget my seat thing."),
        before(seat_state(), snap(WINDOW, WINDOW_TEXT)),
    )
    assert len(result.target.candidates) <= 1


# --- Typed-evidence defect ----------------------------------------------------


def test_grounding_validation_field_defect_is_still_present_and_not_blocking():
    # Confirmed and reported, deliberately not corrected: this controller
    # decides from `evidence_mode` and never constructs the field, so the
    # defect blocks nothing here. Frozen code stays untouched.
    import dataclasses

    names = {f.name for f in dataclasses.fields(TransitionSourceEvidence)}
    assert "grounding_validation" not in names
    with pytest.raises(TypeError):
        TransitionSourceEvidence(source_statement="x", grounding_validation=object())
    # The forget controller works regardless.
    result = propose("Forget that I prefer aisle seats.", seat_state())
    assert result.transition_type == "forget_existing"


# --- Corpus evaluation --------------------------------------------------------


def test_corpus_manifest_unchanged_by_evaluation():
    digest = tv.file_digest(tv.MANIFEST_PATH)
    evaluate_corpus()
    assert tv.file_digest(tv.MANIFEST_PATH) == digest
    assert tv.verify_manifest() is True


def test_applicability_splits_forget_sources_from_abstention_cases():
    corpus = tv.load_corpus()
    historical = [r for r in corpus["historical_scored"] if is_forget_applicable(r)]
    development = [
        r for r in corpus["development_fixtures"] if is_forget_applicable(r)
    ]
    assert len(historical) == 4
    assert len(development) == 6
    # A forget category alone does not make a forget source.
    assert all(
        not is_forget_applicable(r) or "forget" in (r["source_statement"] or "").lower()
        or "remember" in (r["source_statement"] or "").lower()
        or "care about" in (r["source_statement"] or "").lower()
        for r in corpus["historical_scored"] + corpus["development_fixtures"]
    )
    assert is_abstention_case(
        next(r for r in corpus["historical_scored"]
             if r["source_case_id"] == "forgetting_006_restatement_not_resurrection")
    )


def test_measured_classification_matches_the_reported_result():
    data = evaluate_corpus()
    assert data["historical_scored"]["classification"] == {"correct": 4, "total": 4}
    assert data["development_only"]["classification"] == {"correct": 6, "total": 6}


def test_measured_target_accuracy_is_complete():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        target = data[partition]["target"]
        assert target["correct"] == target["cases_requiring_target"]
        assert target["wrong"] == 0
        assert target["spurious"] == 0


def test_controller_abstains_on_every_non_forget_source():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        assert data[partition]["abstained"] == data[partition]["abstention_cases"]
        assert data[partition]["safety"]["non_forget_sources_claimed"] == 0


def test_every_corpus_forget_proposal_is_accepted_by_the_verifier():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        verification = data[partition]["verification"]
        assert verification["accepted"] == verification["verified"]
        assert verification["rejected"] == 0
        assert verification["action_applied"] == 0
        assert verification["canonical_effect_eligible"] == 0


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
    import inspect

    import experienceos.memory.forget_intelligence as module

    source = inspect.getsource(module)
    assert "expected_transition" not in source
    assert "benchmarks" not in source


def test_evaluation_is_deterministically_repeatable():
    assert forget_signature() == forget_signature()


def test_update_controller_handoff_is_preserved():
    # The update controller still detects and hands off forget language;
    # the forget controller is what picks it up. Neither emits the
    # other's transition.
    from experienceos.memory.update_intelligence import (
        DeterministicUpdateController,
        UpdateIntentType,
    )

    statement = "Forget that I prefer aisle seats."
    update = DeterministicUpdateController().propose(
        statement, evidence(statement), before(seat_state())
    )
    assert update.intent.intent_type == UpdateIntentType.FORGET_DIRECTIVE
    assert update.abstained is True
    assert update.proposal is None

    forget = propose(statement, seat_state())
    assert forget.transition_type == "forget_existing"


def test_reference_comparison_is_deterministic():
    from benchmarks.forget_intelligence.reference import (
        build_planner,
        reference_forget_effect,
    )

    record = next(
        r for r in tv.load_corpus()["development_fixtures"]
        if r["source_case_id"] == "forget_directive-01"
    )
    planner = build_planner()
    assert reference_forget_effect(record, planner) == reference_forget_effect(
        record, planner
    )


def test_latency_stays_within_the_contract_budget():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        latency = data[partition]["latency"]
        # Contract gate 15: <= 5 ms added per interaction.
        assert latency["p95_ms"] < 5.0, partition
