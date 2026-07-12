"""Development-fixture evidence for learned grounded extraction.

Runs the learned controller with fake runners that echo each fixture's
own expected candidate (or none). This proves schema compliance,
exact-span verification, validation enforcement, and abstention safety
through the learned path — it is DEVELOPMENT EVIDENCE ONLY, not
benchmark precision/recall and not adoption evidence. Matching the
deterministic baseline's fixture coverage does not prove superiority.
"""

import json

from benchmarks.fixtures.grounded_extraction import (
    load_development_fixtures,
)
from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.memory.learned_extraction import (
    LearnedExtractionRunnerResult,
    LearnedGroundedExtractionController,
    RUNNER_OK,
)

FIXTURES = load_development_fixtures()
POSITIVE = [f for f in FIXTURES if f["candidate_expected"]]
NEGATIVE = [f for f in FIXTURES if not f["candidate_expected"]]


class EchoRunner:
    """Emits schema-valid output built from a fixture's oracle."""

    runner_id = "echo_runner"
    runner_version = "1"

    def __init__(self, raw):
        self._raw = raw

    def availability(self):
        return True

    def run(self, request):
        return LearnedExtractionRunnerResult(
            raw_output=self._raw, runner_id=self.runner_id,
            runner_version=self.runner_version, available=True,
            status=RUNNER_OK, elapsed_ms=0.5,
        )


def _positive_output(fixture, normalized):
    return json.dumps({
        "action": "candidate",
        "kind": fixture["expected_kind"],
        "normalized_text": normalized,
        "evidence_text": fixture["expected_evidence_text"],
        "start_offset": fixture["expected_start_offset"],
        "end_offset": fixture["expected_end_offset"],
        "confidence": 0.85,
        "reason": "durable candidate",
    })


def _none_output(reason):
    return json.dumps({
        "action": "none", "kind": None, "normalized_text": None,
        "evidence_text": None, "start_offset": None,
        "end_offset": None, "confidence": None, "reason": reason,
    })


def _controller(raw):
    return LearnedGroundedExtractionController(
        EchoRunner(raw), fallback_mode="none"
    )


def test_positive_fixtures_flow_through_learned_path_and_validate():
    accepted = 0
    for fixture in POSITIVE:
        # For each fixture, at least one oracle-acceptable
        # normalization must flow through the learned gate and
        # validate at the expected span.
        for normalized in fixture["acceptable_normalized_texts"]:
            proposal = _controller(
                _positive_output(fixture, normalized)
            ).extract(
                ExtractionEvidence(
                    user_text=fixture["user_message"],
                    metadata={"source_id": fixture["case_id"]},
                )
            )
            if proposal.recommendation == "candidate":
                accepted += 1
                span = proposal.candidate.evidence_spans[0]
                assert (span.start, span.end) == (
                    fixture["expected_start_offset"],
                    fixture["expected_end_offset"],
                )
                assert proposal.diagnostics["validation"]["valid"] is (
                    True
                )
                break
        else:
            raise AssertionError(
                f"no acceptable normalization validated for "
                f"{fixture['case_id']}"
            )
    assert accepted == len(POSITIVE) == 24


def test_negative_fixture_none_output_abstains():
    for fixture in NEGATIVE:
        proposal = _controller(_none_output("negative")).extract(
            ExtractionEvidence(user_text=fixture["user_message"],
                               metadata={"source_id": fixture["case_id"]})
        )
        assert proposal.recommendation == "none"
        assert proposal.diagnostics["outcome"] == "model_none"


def test_negative_fixture_hallucinated_candidate_is_gated_out():
    # If the model hallucinates a candidate for a negative case (whole
    # message span), the grounding validator rejects it.
    for fixture in NEGATIVE:
        message = fixture["user_message"]
        raw = json.dumps({
            "action": "candidate", "kind": "preference",
            "normalized_text": "Hallucinated durable claim.",
            "evidence_text": message,
            "start_offset": 0, "end_offset": len(message),
            "confidence": 0.9, "reason": "hallucination",
        })
        proposal = _controller(raw).extract(
            ExtractionEvidence(user_text=message,
                               metadata={"source_id": fixture["case_id"]})
        )
        # Either the validator rejects the content, or the whole-message
        # span fails support — never a fabricated durable memory.
        assert proposal.recommendation == "none", fixture["case_id"]
        assert proposal.diagnostics["outcome"] in (
            "validation_rejected", "malformed_output"
        )


def test_unsupported_normalization_from_model_is_rejected():
    for fixture in POSITIVE:
        for bad in fixture.get("unsupported_normalized_texts", []):
            raw = json.dumps({
                "action": "candidate",
                "kind": fixture["expected_kind"],
                "normalized_text": bad,
                "evidence_text": fixture["expected_evidence_text"],
                "start_offset": fixture["expected_start_offset"],
                "end_offset": fixture["expected_end_offset"],
                "confidence": 0.9, "reason": "over-broad",
            })
            proposal = _controller(raw).extract(
                ExtractionEvidence(
                    user_text=fixture["user_message"],
                    metadata={"source_id": fixture["case_id"]},
                )
            )
            assert proposal.recommendation == "none", (
                fixture["case_id"], bad
            )


def test_learned_path_is_development_evidence_not_adoption():
    # Sanity anchor for the report: the learned path merely matches the
    # deterministic baseline's fixture behavior with oracle-fed output;
    # this is not a superiority claim.
    assert len(FIXTURES) == 37
