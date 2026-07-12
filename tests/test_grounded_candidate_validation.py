"""Unit tests for grounded candidate validation."""

import json

import pytest

from experienceos.controllers.base import EvidenceSpan
from experienceos.controllers.extraction import ProposedMemoryCandidate
from experienceos.memory.grounding import (
    ApprovedSource,
    GroundedCandidateValidator,
    GroundingValidation,
    REJECTION_CODES,
    VALID,
)

VALIDATOR = GroundedCandidateValidator()


def candidate(text, message, evidence=None, kind="preference",
              start=None, end=None, span_source="user",
              confidence=0.9):
    evidence = evidence if evidence is not None else message
    start = message.index(evidence) if start is None else start
    end = start + len(evidence) if end is None else end
    return ProposedMemoryCandidate(
        kind=kind, text=text, grounded=True, confidence=confidence,
        evidence_spans=(
            EvidenceSpan(source=span_source, start=start, end=end,
                         excerpt=evidence),
        ),
    )


def source(message, provenance="user_asserted", source_id="msg-1"):
    return ApprovedSource(
        source_id=source_id, text=message, provenance=provenance
    )


def check(text, message, evidence=None, **kwargs):
    return VALIDATOR.validate(
        candidate(text, message, evidence, **{
            k: v for k, v in kwargs.items()
            if k in ("kind", "start", "end", "span_source", "confidence")
        }),
        source(message, **{
            k: v for k, v in kwargs.items()
            if k in ("provenance", "source_id")
        }),
    )


# -- span structure ---------------------------------------------------------------


def test_valid_span_accepted():
    result = check("Prefers aisle seats.", "I prefer aisle seats.")
    assert result.valid and result.code == VALID
    assert result.candidate is not None


@pytest.mark.parametrize("start,end", [
    (0, 0),    # zero-length
    (-1, 5),   # negative start
    (5, 3),    # start after end
])
def test_impossible_offsets_rejected_at_construction(start, end):
    # EvidenceSpan itself is the structural guard for these shapes:
    # such spans cannot be constructed at all.
    from experienceos.controllers.base import ControllerInputError

    with pytest.raises(ControllerInputError):
        EvidenceSpan(source="user", start=start, end=end, excerpt="x")


def test_end_beyond_source_rejected_by_validator():
    # The span cannot know the source length; the validator does.
    message = "I prefer aisle seats."
    result = check("Prefers aisle seats.", message,
                   evidence=message, start=0, end=10_000)
    assert not result.valid
    assert result.code == "invalid_offsets"


def test_missing_evidence_and_source_rejected():
    message = "I prefer aisle seats."
    proposal = ProposedMemoryCandidate(
        kind="preference", text="Prefers aisle seats.", grounded=True,
        confidence=0.9, evidence_spans=(),
    )
    result = VALIDATOR.validate(proposal, source(message))
    assert result.code == "malformed_proposal"
    result = VALIDATOR.validate(
        candidate("Prefers aisle seats.", message),
        ApprovedSource(source_id="", text=message),
    )
    assert result.code == "missing_source"


def test_non_candidate_input_is_malformed():
    result = VALIDATOR.validate(
        {"kind": "preference"}, source("I prefer aisle seats.")
    )
    assert result.code == "malformed_proposal"


# -- exact matching ----------------------------------------------------------------


def test_exact_text_accepted_and_mismatches_rejected():
    message = "I prefer aisle seats."
    assert check("Prefers aisle seats.", message).valid
    for wrong in (
        "I prefer aisle seats",    # trimmed period
        "i prefer aisle seats.",   # casing
        "I prefer aisle  seats.",  # whitespace
        "I prefer aisle séats.",   # unicode
    ):
        proposal = ProposedMemoryCandidate(
            kind="preference", text="Prefers aisle seats.",
            grounded=True, confidence=0.9,
            evidence_spans=(
                EvidenceSpan(source="user", start=0, end=len(message),
                             excerpt=wrong),
            ),
        )
        result = VALIDATOR.validate(proposal, source(message))
        assert result.code == "evidence_mismatch", wrong


def test_mismatched_evidence_is_never_repaired():
    result = check("Prefers aisle seats.", "I prefer aisle seats.",
                   evidence="I prefer aisle", end=len("I prefer aisle") + 1)
    assert not result.valid
    assert result.candidate is None


# -- provenance --------------------------------------------------------------------


def test_user_asserted_accepted_and_others_rejected():
    message = "I prefer aisle seats."
    assert check("Prefers aisle seats.", message).valid
    assert check("Prefers aisle seats.", message,
                 provenance="assistant_derived").code == (
        "assistant_only_source"
    )
    assert check("Prefers aisle seats.", message,
                 provenance="made_up").code == "invalid_source_type"
    # Confirmed provenance requires an explicit grant.
    assert check("Prefers aisle seats.", message,
                 provenance="jointly_confirmed").code == (
        "invalid_source_type"
    )
    granted = GroundedCandidateValidator(
        accepted_confirmed_provenance={"jointly_confirmed"}
    )
    result = granted.validate(
        candidate("Prefers aisle seats.", message),
        source(message, provenance="jointly_confirmed"),
    )
    assert result.valid


def test_ungrantable_provenance_rejected_at_construction():
    with pytest.raises(ValueError):
        GroundedCandidateValidator(
            accepted_confirmed_provenance={"assistant_derived"}
        )


def test_assistant_span_rejected_regardless_of_source_metadata():
    message = "I prefer aisle seats."
    result = check("Prefers aisle seats.", message,
                   span_source="assistant")
    assert result.code == "assistant_only_source"


# -- memory kind -------------------------------------------------------------------


def test_canonical_kinds_accepted():
    assert check("Prefers aisle seats.", "I prefer aisle seats.",
                 kind="preference").valid
    assert check("Home airport is SJC.", "My home airport is SJC.",
                 kind="fact").valid
    message = "When planning work trips, always include airport transfer time."
    assert check(message, message, kind="instruction").valid


def test_bad_kinds_rejected_at_construction_boundary():
    # ProposedMemoryCandidate already rejects non-canonical kinds; the
    # validator keeps a guard for deserialized/duck-typed inputs.
    from experienceos.controllers.base import ControllerInputError

    with pytest.raises(ControllerInputError):
        candidate("x", "I prefer aisle seats.", kind="opinion")
    with pytest.raises(ControllerInputError):
        candidate("x", "I prefer aisle seats.", kind="forget")


# -- question handling -------------------------------------------------------------


def test_questions_rejected_but_assertion_clause_validates():
    message = "I usually fly from SJC. Should I use SFO this time?"
    whole = check("Flies from SJC.", message, evidence=message)
    assert whole.code == "question_derived"
    question_only = check(
        "Uses SFO.", message, evidence="Should I use SFO this time?"
    )
    assert question_only.code == "question_derived"
    assertion_only = check(
        "Usually flies from SJC.", message,
        evidence="I usually fly from SJC.",
    )
    assert assertion_only.valid


def test_subordinate_clause_is_not_a_question():
    message = (
        "When planning work trips, always include airport transfer time."
    )
    assert check(message, message, kind="instruction").valid


# -- hypothetical handling ---------------------------------------------------------


def test_hypotheticals_rejected():
    for message in (
        "If I ever move to Seattle, I might use SEA.",
        "If I took that night-shift job, I would always fly red-eyes.",
        "Suppose we lived in Denver, then DEN would be closest.",
    ):
        result = check("Uses SEA.", message, evidence=message)
        assert result.code == "hypothetical_derived", message


def test_durable_assertion_beside_hypothetical_clause_validates():
    message = (
        "I always fly from SJC. If I ever move to Seattle, I might "
        "use SEA."
    )
    result = check("Always flies from SJC.", message,
                   evidence="I always fly from SJC.")
    assert result.valid


# -- temporary and one-off ----------------------------------------------------------


@pytest.mark.parametrize("message", [
    "I am flying out of SFO this month.",
    "I'm working from the Austin office this week.",
    "For this trip only, put me in a window seat.",
    "Until Friday I'm reachable only on my personal phone.",
    "Right now I'm using the loaner laptop.",
])
def test_temporary_states_rejected(message):
    result = check("Durable claim.", message, evidence=message,
                   kind="fact")
    assert result.code == "temporary_state", message


def test_one_off_request_rejected_but_durable_clause_validates():
    booking = "Book me an aisle seat for tomorrow."
    assert check("Prefers aisle seats.", booking,
                 evidence=booking).code == "one_off_request"
    mixed = "I normally prefer aisle seats, so book one for tomorrow."
    result = check("Normally prefers aisle seats.", mixed,
                   evidence="I normally prefer aisle seats")
    assert result.valid


# -- durability --------------------------------------------------------------------


def test_durable_assertions_accepted():
    for message, text, kind in (
        ("I prefer aisle seats.", "Prefers aisle seats.", "preference"),
        ("My home airport is SJC.", "Home airport is SJC.", "fact"),
        ("From now on, use SJC as my default airport.",
         "Use SJC as my default airport from now on.", "instruction"),
        ("SJC has become my default airport.",
         "Default airport is SJC.", "fact"),
        ("I'm lactose intolerant.", "Is lactose intolerant.", "fact"),
    ):
        result = check(text, message, evidence=message, kind=kind)
        assert result.valid, (message, result.code)


def test_vague_mood_rejected_as_non_durable():
    message = "Lately I guess I lean toward quieter hotels, sort of."
    result = check("Prefers quieter hotels.", message, evidence=message)
    assert result.code in ("non_durable", "indeterminate_support")
    assert not result.valid


def test_keywords_do_not_create_durability():
    quoted = "My partner keeps saying 'always pick the exit row'."
    assert check("Picks the exit row.", quoted,
                 evidence=quoted).code == "unsupported_ownership"
    hypothetical = (
        "If I took that night-shift job, I would always fly red-eyes."
    )
    assert check("Always flies red-eyes.", hypothetical,
                 evidence=hypothetical).code == "hypothetical_derived"


def test_third_party_preference_rejected():
    message = "My manager always prefers early flights."
    whole = check("Prefers early flights.", message, evidence=message)
    assert whole.code == "unsupported_ownership"


# -- normalization support -----------------------------------------------------------


def test_safe_normalizations_accepted():
    for message, text in (
        ("I prefer aisle seats.", "Prefers aisle seats."),
        ("My home airport is SJC.", "Home airport is SJC."),
        ("When planning work trips, always include airport transfer "
         "time.",
         "Include airport transfer time when planning work trips."),
    ):
        result = check(text, message, evidence=message,
                       kind="instruction" if "Include" in text
                       else "preference" if "aisle" in text else "fact")
        assert result.valid, (text, result.code)


@pytest.mark.parametrize("message,bad_text,expected", [
    ("I prefer aisle seats for short work trips.",
     "Prefers aisle seats for all flights.",
     "unsupported_normalization"),  # scope expansion
    ("I usually prefer aisle seats.",
     "Always requires aisle seats.",
     "unsupported_normalization"),  # certainty increase
    ("I tend to prefer cheaper options.",
     "Always chooses the cheapest option.",
     "unsupported_normalization"),  # hedge removal
    ("I do not prefer red-eye flights.",
     "Prefers red-eye flights.",
     "unsupported_normalization"),  # polarity inversion
    ("My home airport is SJC.",
     "Lives in San Jose and always departs from SJC.",
     "unsupported_normalization"),  # invented entity + universal
])
def test_unsupported_normalizations_rejected(message, bad_text, expected):
    result = check(bad_text, message, evidence=message)
    assert not result.valid
    assert result.code == expected, (bad_text, result.code)


def test_negation_added_by_candidate_is_rejected():
    result = check("Does not prefer aisle seats.",
                   "I prefer aisle seats.")
    assert result.code == "unsupported_normalization"


def test_unknown_common_words_are_indeterminate_and_fail_closed():
    result = check("Cherishes aisle seats.", "I prefer aisle seats.")
    assert not result.valid
    assert result.code == "indeterminate_support"


# -- result vocabulary and diagnostics -----------------------------------------------


def test_rejection_vocabulary_is_bounded():
    assert len(REJECTION_CODES) == 17
    assert VALID not in REJECTION_CODES


def test_validation_order_reports_most_fundamental_failure():
    # A proposal that is simultaneously mismatched AND a question must
    # report the earlier structural failure deterministically.
    message = "Should I use SFO or SJC?"
    proposal = ProposedMemoryCandidate(
        kind="preference", text="Uses SFO.", grounded=True,
        confidence=0.9,
        evidence_spans=(
            EvidenceSpan(source="user", start=0, end=len(message),
                         excerpt="Should I use SFO or SJC!"),
        ),
    )
    result = VALIDATOR.validate(proposal, source(message))
    assert result.code == "evidence_mismatch"


def test_diagnostics_serialize_safely():
    result = check("Prefers aisle seats.", "I prefer aisle seats.")
    payload = json.dumps(result.diagnostics)
    assert "validator_id" in result.diagnostics
    assert result.diagnostics["validator_version"] == "1"
    assert result.diagnostics["canonical_effect"] is False
    assert "elapsed_ms" in result.diagnostics["evaluation"]
    assert "/Users/" not in payload and "/home/" not in payload
    rejected = check("Prefers red-eye flights.",
                     "I do not prefer red-eye flights.")
    json.dumps(rejected.diagnostics)  # invalid results serialize too
    assert rejected.diagnostics["code"] == "unsupported_normalization"
    assert isinstance(result, GroundingValidation)


def test_stage_statuses_recorded():
    result = check("Prefers aisle seats.", "I prefer aisle seats.")
    assert result.stages["schema"] == "passed"
    assert result.stages["exact_match"] == "passed"
    assert result.stages["normalized_support"] == "passed"
    failed = check("x", "Book me an aisle seat for tomorrow.",
                   evidence="Book me an aisle seat for tomorrow.")
    assert failed.stages["source_form"] == "failed"
    assert failed.stages["durability"] == "skipped"


# -- side effects and authority -------------------------------------------------------


def test_validation_has_no_side_effects(tmp_path):
    import sys

    from experienceos.events.bus import EventBus
    from experienceos.memory.store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    bus = EventBus()
    check("Prefers aisle seats.", "I prefer aisle seats.")
    assert store.list_memories("u1") == []
    assert bus.history() == []
    heavy = {"sentence_transformers", "torch", "onnxruntime",
             "llama_cpp"}
    assert not heavy & set(sys.modules)
    assert not list(tmp_path.iterdir())


def test_validator_accepts_no_authority_handles():
    import inspect

    parameters = inspect.signature(GroundedCandidateValidator).parameters
    assert not any(
        token in name
        for name in parameters
        for token in ("store", "engine", "manager", "bus", "callback")
    )
    result_fields = GroundingValidation.__dataclass_fields__
    assert not any(
        "store" in name or "action" in name for name in result_fields
    )
