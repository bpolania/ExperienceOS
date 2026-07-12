"""Fixture-driven test matrix for deterministic grounded extraction.

All 37 committed development fixtures run through the controller.
These results are development fixture coverage, not benchmark
precision or recall.
"""

import pytest

from benchmarks.fixtures.grounded_extraction import (
    load_development_fixtures,
)
from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.memory.grounded_extraction import (
    DeterministicGroundedExtractionController,
)

CONTROLLER = DeterministicGroundedExtractionController()
FIXTURES = load_development_fixtures()
POSITIVE = [f for f in FIXTURES if f["candidate_expected"]]
NEGATIVE = [f for f in FIXTURES if not f["candidate_expected"]]


def _evidence(fixture):
    return ExtractionEvidence(
        user_text=fixture["user_message"],
        assistant_text=fixture.get("assistant_message") or "",
        metadata={"source_id": fixture["case_id"]},
    )


@pytest.mark.parametrize(
    "fixture", POSITIVE, ids=lambda f: f["case_id"]
)
def test_positive_fixture_produces_valid_candidate(fixture):
    proposal = CONTROLLER.extract(_evidence(fixture))
    assert proposal.recommendation == "candidate", (
        proposal.diagnostics
    )
    candidate = proposal.candidate
    span = candidate.evidence_spans[0]
    assert (span.start, span.end) == (
        fixture["expected_start_offset"],
        fixture["expected_end_offset"],
    ), fixture["user_message"][span.start:span.end]
    assert span.excerpt == fixture["expected_evidence_text"]
    assert candidate.text in fixture["acceptable_normalized_texts"], (
        candidate.text
    )
    accepted_kinds = {
        fixture.get("expected_kind"),
        *fixture.get("acceptable_kinds", []),
    }
    assert candidate.kind in accepted_kinds
    assert proposal.diagnostics["validation"]["valid"] is True
    assert proposal.diagnostics["canonical_effect"] is False


@pytest.mark.parametrize(
    "fixture", NEGATIVE, ids=lambda f: f["case_id"]
)
def test_negative_fixture_abstains(fixture):
    proposal = CONTROLLER.extract(_evidence(fixture))
    assert proposal.recommendation == "none", (
        proposal.candidate and proposal.candidate.text
    )
    assert proposal.candidate is None
    assert proposal.diagnostics.get("abstention_reason") or (
        proposal.diagnostics.get("rejected_candidates")
    )


@pytest.mark.parametrize(
    "fixture",
    [f for f in POSITIVE if f.get("unsupported_normalized_texts")],
    ids=lambda f: f["case_id"],
)
def test_unsupported_normalizations_never_emitted(fixture):
    proposal = CONTROLLER.extract(_evidence(fixture))
    assert proposal.candidate.text not in (
        fixture["unsupported_normalized_texts"]
    )


def test_lifecycle_metadata_does_not_alter_proposals():
    lifecycle_cases = [
        f for f in POSITIVE if f.get("lifecycle_expectation")
    ]
    assert lifecycle_cases
    for fixture in lifecycle_cases:
        proposal = CONTROLLER.extract(_evidence(fixture))
        assert proposal.recommendation == "candidate"
        # The controller neither sees nor acts on the fixture's later
        # lifecycle expectation: no lifecycle vocabulary in output.
        assert not any(
            "lifecycle" in key or "supersede" in key
            for key in proposal.diagnostics
        )


def test_unscorable_ambiguity_abstains():
    fixture = next(
        f for f in NEGATIVE
        if f["category"] == "ambiguous-durability"
    )
    proposal = CONTROLLER.extract(_evidence(fixture))
    assert proposal.recommendation == "none"


def test_fixture_matrix_is_deterministic():
    def run_all():
        return [
            (
                f["case_id"],
                CONTROLLER.extract(_evidence(f)).recommendation,
                (CONTROLLER.extract(_evidence(f)).candidate or None)
                and CONTROLLER.extract(_evidence(f)).candidate.text,
            )
            for f in FIXTURES
        ]

    assert run_all() == run_all()


def test_full_coverage_counts():
    positives = sum(
        CONTROLLER.extract(_evidence(f)).recommendation == "candidate"
        for f in POSITIVE
    )
    negatives = sum(
        CONTROLLER.extract(_evidence(f)).recommendation == "none"
        for f in NEGATIVE
    )
    assert len(FIXTURES) == 37
    assert positives == len(POSITIVE) == 24
    assert negatives == len(NEGATIVE) == 13
