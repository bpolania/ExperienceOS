"""Fixture-driven tests for grounded candidate validation.

Every committed development fixture is pushed through the validator:
positives must validate with at least one acceptable normalization,
every recorded unsupported normalization must reject, and every
negative case must reject with a code consistent with its fixture
rejection category.
"""

import pytest

from benchmarks.fixtures.grounded_extraction import (
    load_development_fixtures,
)
from experienceos.controllers.base import EvidenceSpan
from experienceos.controllers.extraction import ProposedMemoryCandidate
from experienceos.memory.grounding import (
    ApprovedSource,
    GroundedCandidateValidator,
)

VALIDATOR = GroundedCandidateValidator()
FIXTURES = load_development_fixtures()
POSITIVE = [f for f in FIXTURES if f["candidate_expected"]]
NEGATIVE = [f for f in FIXTURES if not f["candidate_expected"]]

# Fixture rejection category -> acceptable validator code families.
CODE_FAMILIES = {
    "temporary_state": {"temporary_state"},
    "one_off_request": {"one_off_request", "temporary_state"},
    "hypothetical": {"hypothetical_derived"},
    "question": {"question_derived"},
    "assistant_only": {"assistant_only_source", "non_durable",
                       "evidence_mismatch"},
    "third_party_statement": {"unsupported_ownership"},
    "ambiguous_durability": {"non_durable", "indeterminate_support"},
}


def _proposal(fixture, text):
    return ProposedMemoryCandidate(
        kind=fixture.get("expected_kind") or "preference",
        text=text,
        grounded=True,
        confidence=0.9,
        evidence_spans=(
            EvidenceSpan(
                source="user",
                start=fixture["expected_start_offset"],
                end=fixture["expected_end_offset"],
                excerpt=fixture["expected_evidence_text"],
            ),
        ),
    )


def _source(fixture):
    return ApprovedSource(
        source_id=fixture["case_id"], text=fixture["user_message"]
    )


@pytest.mark.parametrize(
    "fixture", POSITIVE, ids=lambda f: f["case_id"]
)
def test_positive_fixture_validates(fixture):
    results = [
        VALIDATOR.validate(_proposal(fixture, text), _source(fixture))
        for text in fixture["acceptable_normalized_texts"]
    ]
    assert any(result.valid for result in results), [
        (r.code, r.explanation) for r in results
    ]
    # Acceptable kind set is honored where declared, checked with a
    # normalization that already validated.
    supported_text = next(
        text
        for text, result in zip(
            fixture["acceptable_normalized_texts"], results
        )
        if result.valid
    )
    for kind in fixture.get("acceptable_kinds", []):
        proposal = ProposedMemoryCandidate(
            kind=kind,
            text=supported_text,
            grounded=True,
            confidence=0.9,
            evidence_spans=_proposal(fixture, "x").evidence_spans,
        )
        assert VALIDATOR.validate(proposal, _source(fixture)).valid


@pytest.mark.parametrize(
    "fixture",
    [f for f in POSITIVE if f.get("unsupported_normalized_texts")],
    ids=lambda f: f["case_id"],
)
def test_unsupported_normalizations_reject(fixture):
    for bad in fixture["unsupported_normalized_texts"]:
        result = VALIDATOR.validate(
            _proposal(fixture, bad), _source(fixture)
        )
        assert not result.valid, bad
        assert result.code in (
            "unsupported_normalization", "indeterminate_support",
        ), (bad, result.code)


@pytest.mark.parametrize(
    "fixture", NEGATIVE, ids=lambda f: f["case_id"]
)
def test_negative_fixture_rejects_naive_whole_message_proposal(fixture):
    message = fixture["user_message"]
    proposal = ProposedMemoryCandidate(
        kind="preference",
        text="Naive candidate from the whole message.",
        grounded=True,
        confidence=0.9,
        evidence_spans=(
            EvidenceSpan(source="user", start=0, end=len(message),
                         excerpt=message),
        ),
    )
    result = VALIDATOR.validate(proposal, _source(fixture))
    assert not result.valid
    assert result.code in CODE_FAMILIES[fixture["rejection_reason"]], (
        fixture["case_id"], result.code
    )


def test_assistant_only_fixture_rejects_assistant_cited_span():
    fixture = next(
        f for f in NEGATIVE if f["category"] == "assistant-only"
    )
    assistant_text = fixture["assistant_message"]
    proposal = ProposedMemoryCandidate(
        kind="preference",
        text="Prefers window seats.",
        grounded=True,
        confidence=0.9,
        evidence_spans=(
            EvidenceSpan(source="assistant", start=0,
                         end=len(assistant_text),
                         excerpt=assistant_text),
        ),
    )
    result = VALIDATOR.validate(
        proposal,
        ApprovedSource(source_id=fixture["case_id"],
                       text=fixture["user_message"]),
    )
    assert result.code == "assistant_only_source"


def test_mixed_message_durable_clause_controls_validation():
    fixture = next(
        f for f in POSITIVE if f["case_id"] == "one-off-request-002"
    )
    # The cited durable clause validates...
    good = VALIDATOR.validate(
        _proposal(fixture, fixture["acceptable_normalized_texts"][0]),
        _source(fixture),
    )
    assert good.valid
    # ...while a whole-message span for the same fixture rejects.
    message = fixture["user_message"]
    whole = ProposedMemoryCandidate(
        kind="preference", text="Prefers aisle seats.", grounded=True,
        confidence=0.9,
        evidence_spans=(
            EvidenceSpan(source="user", start=0, end=len(message),
                         excerpt=message),
        ),
    )
    result = VALIDATOR.validate(whole, _source(fixture))
    assert not result.valid


def test_duplicate_and_change_fixtures_validate_grounding_only():
    lifecycle_cases = [
        f for f in POSITIVE if f.get("lifecycle_expectation")
    ]
    assert lifecycle_cases
    for fixture in lifecycle_cases:
        results = [
            VALIDATOR.validate(
                _proposal(fixture, text), _source(fixture)
            )
            for text in fixture["acceptable_normalized_texts"]
        ]
        best = next(r for r in results if r.valid)
        # The validation result carries NO lifecycle instruction: the
        # fixture's lifecycle_expectation is future work for the
        # kernel, invisible to this validator.
        assert not any(
            "lifecycle" in key or "duplicate" in key
            or "supersede" in key
            for key in best.diagnostics
        )
        assert best.diagnostics["canonical_effect"] is False


def test_every_fixture_was_exercised():
    assert len(FIXTURES) == 37
    assert len(POSITIVE) == 24
    assert len(NEGATIVE) == 13
