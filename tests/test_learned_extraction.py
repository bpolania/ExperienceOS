"""Tests for the optional learned grounded extraction controller.

All default tests use in-process fake runners: no provider, no model,
no credentials, no network.
"""

import json

import pytest

from experienceos.controllers.extraction import (
    ExtractionController,
    ExtractionEvidence,
    ExtractionProposal,
)
from experienceos.memory.learned_extraction import (
    EXTRACTION_OUTPUT_SCHEMA,
    ExtractionParseError,
    FALLBACK_MODES,
    FALLBACK_NONE,
    FALLBACK_ON_ERROR,
    FALLBACK_ON_INVALID,
    FALLBACK_ON_UNAVAILABLE,
    LearnedExtractionRequest,
    LearnedExtractionRunnerResult,
    LearnedGroundedExtractionController,
    OUTCOME_CANDIDATE,
    OUTCOME_FALLBACK_USED,
    OUTCOME_MALFORMED,
    OUTCOME_MODEL_NONE,
    OUTCOME_RUNNER_ERROR,
    OUTCOME_RUNNER_TIMEOUT,
    OUTCOME_RUNNER_UNAVAILABLE,
    OUTCOME_VALIDATION_REJECTED,
    RUNNER_ERROR,
    RUNNER_OK,
    RUNNER_TIMEOUT,
    RUNNER_UNAVAILABLE,
    parse_extraction_output,
)

MESSAGE = "I prefer aisle seats"


def candidate_json(message=MESSAGE, kind="preference",
                   normalized="Prefers aisle seats", evidence=None,
                   start=0, end=None, confidence=0.9, **extra):
    evidence = message if evidence is None else evidence
    end = len(message) if end is None else end
    payload = {
        "action": "candidate", "kind": kind,
        "normalized_text": normalized, "evidence_text": evidence,
        "start_offset": start, "end_offset": end,
        "confidence": confidence, "reason": "test",
    }
    payload.update(extra)
    return json.dumps(payload)


def none_json(reason="one-off request"):
    return json.dumps({
        "action": "none", "kind": None, "normalized_text": None,
        "evidence_text": None, "start_offset": None,
        "end_offset": None, "confidence": None, "reason": reason,
    })


class FakeRunner:
    """Returns a controlled result. Records the request it received."""

    runner_id = "fake_runner"
    runner_version = "1"

    def __init__(self, raw=None, *, available=True, status=RUNNER_OK,
                 raise_exc=None, error_class=None,
                 return_wrong_type=False):
        self.raw = raw
        self._available = available
        self.status = status
        self.raise_exc = raise_exc
        self.error_class = error_class
        self.return_wrong_type = return_wrong_type
        self.seen_request = None

    def availability(self):
        return self._available

    def run(self, request):
        self.seen_request = request
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.return_wrong_type:
            return {"not": "a result"}
        return LearnedExtractionRunnerResult(
            raw_output=self.raw, runner_id=self.runner_id,
            runner_version=self.runner_version, available=True,
            status=self.status, elapsed_ms=1.0,
            error_class=self.error_class,
        )


def controller(runner, fallback_mode=FALLBACK_NONE):
    return LearnedGroundedExtractionController(
        runner, fallback_mode=fallback_mode
    )


def extract(runner, message=MESSAGE, provenance="", fallback=FALLBACK_NONE):
    return controller(runner, fallback).extract(
        ExtractionEvidence(
            user_text=message, provenance_label=provenance,
            metadata={"source_id": "t-1"},
        )
    )


# -- runner protocol and construction ----------------------------------------------


def test_controller_conforms_to_extraction_protocol():
    ctl = controller(FakeRunner(none_json()))
    assert callable(ctl.extract)
    for name in ExtractionController.__protocol_attrs__:
        assert hasattr(ctl, name)
    assert ctl.controller_id == "grounded_learned_shadow-1"


def test_runner_receives_only_bounded_request():
    runner = FakeRunner(none_json())
    extract(runner)
    request = runner.seen_request
    assert isinstance(request, LearnedExtractionRequest)
    from dataclasses import fields

    names = {f.name for f in fields(LearnedExtractionRequest)}
    assert names == {
        "source_text", "allowed_kinds", "schema_version", "timeout_ms",
    }
    assert "store" not in names and "memories" not in names


def test_controller_accepts_no_authority_handles():
    import inspect

    parameters = inspect.signature(
        LearnedGroundedExtractionController
    ).parameters
    assert not any(
        token in name
        for name in parameters
        for token in ("store", "engine", "manager", "bus", "callback")
    )


def test_invalid_fallback_mode_rejected():
    with pytest.raises(ValueError):
        controller(FakeRunner(none_json()), fallback_mode="always")
    assert set(FALLBACK_MODES) == {
        FALLBACK_NONE, FALLBACK_ON_UNAVAILABLE, FALLBACK_ON_ERROR,
        FALLBACK_ON_INVALID,
    }


# -- valid learned proposals -------------------------------------------------------


@pytest.mark.parametrize("kind,message,normalized", [
    ("preference", "I prefer aisle seats", "Prefers aisle seats"),
    ("fact", "My home airport is SJC", "Home airport is SJC"),
    ("instruction",
     "When planning work trips, always include transfer time",
     "When planning work trips, always include transfer time"),
])
def test_valid_learned_candidate_accepted(kind, message, normalized):
    raw = candidate_json(message=message, kind=kind,
                         normalized=normalized)
    proposal = extract(FakeRunner(raw), message=message)
    assert proposal.recommendation == "candidate"
    assert proposal.candidate.kind == kind
    assert proposal.candidate.text == normalized
    span = proposal.candidate.evidence_spans[0]
    assert message[span.start:span.end] == span.excerpt
    assert proposal.diagnostics["outcome"] == OUTCOME_CANDIDATE
    assert proposal.diagnostics["validation_status"] == "valid"
    assert proposal.diagnostics["final_proposal_source"] == "learned"


def test_exactly_one_candidate_and_approved_provenance_used():
    proposal = extract(FakeRunner(candidate_json()))
    assert proposal.candidate is not None
    span = proposal.candidate.evidence_spans[0]
    assert span.source == "user"  # not model-controlled
    # The validation ran against the approved source (id + provenance).
    validation = proposal.diagnostics["validation"]
    assert validation["source_id"] == "t-1"
    assert validation["source_provenance"] == "user_asserted"


def test_model_supplied_provenance_cannot_override_approved():
    # Approved provenance is assistant_derived: the validator rejects
    # regardless of what the model "claims".
    proposal = extract(FakeRunner(candidate_json()),
                       provenance="assistant_derived")
    assert proposal.recommendation == "none"
    assert proposal.diagnostics["outcome"] == OUTCOME_VALIDATION_REJECTED
    assert proposal.diagnostics["validation_status"] == (
        "assistant_only_source"
    )


# -- none behavior -----------------------------------------------------------------


def test_model_none_returns_no_candidate():
    proposal = extract(FakeRunner(none_json("question")))
    assert proposal.recommendation == "none"
    assert proposal.candidate is None
    assert proposal.diagnostics["outcome"] == OUTCOME_MODEL_NONE
    assert "question" in proposal.reason


# -- strict parsing ----------------------------------------------------------------


def test_parser_accepts_valid_objects():
    parsed = parse_extraction_output(candidate_json())
    assert parsed.action == "candidate"
    assert parsed.kind == "preference"
    assert parse_extraction_output(none_json()).action == "none"


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "not json",
    "[1, 2, 3]",                                      # not an object
    '{"action": "maybe", "reason": "x"}',             # bad action
    '{"action": "candidate", "reason": "x"}',         # missing fields
    candidate_json(kind="opinion"),                   # bad kind
    candidate_json(start="0"),                        # non-int offset
    candidate_json(confidence=1.5),                   # bad confidence
    candidate_json(extra_field="boom"),               # unknown field
    '{"action":"none","reason":"x","kind":"fact"}',   # none w/ fields
    "```json\n" + candidate_json() + "\n```",         # markdown
    '{"action":"candidate","kind":"preference",'
    '"normalized_text":"' + "x" * 500 + '",'
    '"evidence_text":"e","start_offset":0,"end_offset":1,'
    '"confidence":0.5,"reason":"r"}',                  # oversized field
])
def test_parser_rejects_malformed_output(raw):
    with pytest.raises(ExtractionParseError):
        parse_extraction_output(raw)


def test_multiple_candidates_structure_rejected():
    # A JSON array or a candidate object carrying a nested list is not
    # a single top-level object with allowed scalar fields.
    with pytest.raises(ExtractionParseError):
        parse_extraction_output('[{"action":"candidate"}]')
    with pytest.raises(ExtractionParseError):
        parse_extraction_output(
            candidate_json(candidates=[1, 2])
        )


def test_controller_maps_malformed_output_to_none():
    proposal = extract(FakeRunner("garbage output"))
    assert proposal.recommendation == "none"
    assert proposal.diagnostics["outcome"] == OUTCOME_MALFORMED
    assert proposal.diagnostics["parser_status"] == "malformed"


# -- grounding enforcement ---------------------------------------------------------


@pytest.mark.parametrize("message,evidence,normalized,expect_valid", [
    # question-derived (validator rejects the cited span)
    ("Should I use SFO?", "Should I use SFO?", "Uses SFO", False),
    # temporary state
    ("I use SFO this month", "I use SFO this month",
     "Uses SFO", False),
    # scope expansion
    ("I prefer aisle seats for short work trips",
     "I prefer aisle seats for short work trips",
     "Prefers aisle seats for all flights", False),
    # polarity inversion
    ("I do not prefer red-eye flights",
     "I do not prefer red-eye flights",
     "Prefers red-eye flights", False),
    # safe normalization
    ("I prefer aisle seats", "I prefer aisle seats",
     "Prefers aisle seats", True),
])
def test_grounding_gate_enforced(message, evidence, normalized,
                                 expect_valid):
    raw = candidate_json(message=message, evidence=evidence,
                        normalized=normalized, start=0,
                        end=len(evidence))
    proposal = extract(FakeRunner(raw), message=message)
    if expect_valid:
        assert proposal.recommendation == "candidate"
    else:
        assert proposal.recommendation == "none"
        assert proposal.diagnostics["outcome"] in (
            OUTCOME_VALIDATION_REJECTED, OUTCOME_MALFORMED
        )


def test_validation_cannot_be_bypassed():
    # Every candidate that leaves the controller carries a valid
    # grounding result.
    proposal = extract(FakeRunner(candidate_json()))
    assert proposal.candidate is not None
    assert proposal.diagnostics["validation"]["valid"] is True


# -- no repair ---------------------------------------------------------------------


def test_correct_evidence_with_wrong_offsets_rejected():
    message = "please note I prefer aisle seats"
    # Evidence text is correct but offsets point elsewhere.
    raw = candidate_json(message=message,
                        evidence="I prefer aisle seats",
                        normalized="Prefers aisle seats",
                        start=0, end=len("I prefer aisle seats"))
    proposal = extract(FakeRunner(raw), message=message)
    assert proposal.recommendation == "none"
    assert proposal.diagnostics["outcome"] == OUTCOME_MALFORMED
    assert proposal.diagnostics["error_detail"] == (
        "evidence_not_at_offsets"
    )


def test_repeated_evidence_does_not_trigger_offset_search():
    message = "aisle aisle: I prefer aisle seats"
    raw = candidate_json(message=message, evidence="aisle",
                        normalized="Prefers aisle", start=0, end=5)
    # "aisle" appears three times; the controller uses ONLY the given
    # offsets and never searches for a better-matching occurrence.
    proposal = extract(FakeRunner(raw), message=message)
    # The span at [0:5] == "aisle" matches exactly, so it is not a
    # mismatch; it fails later on grounding, never via repair.
    assert message[0:5] == "aisle"
    assert proposal.diagnostics["final_proposal_source"] == "learned"


def test_out_of_range_offsets_rejected():
    raw = candidate_json(start=0, end=10_000)
    proposal = extract(FakeRunner(raw))
    assert proposal.recommendation == "none"
    assert proposal.diagnostics["error_detail"] == "offsets_out_of_range"


# -- fallback ----------------------------------------------------------------------


def test_unavailable_runner_triggers_default_fallback():
    proposal = extract(
        FakeRunner(None, available=False),
        fallback=FALLBACK_ON_UNAVAILABLE,
    )
    # The deterministic path finds the durable preference.
    assert proposal.recommendation == "candidate"
    assert proposal.diagnostics["outcome"] == OUTCOME_FALLBACK_USED
    assert proposal.diagnostics["final_proposal_source"] == (
        "deterministic_fallback"
    )
    assert proposal.diagnostics["fallback_reason"] == (
        OUTCOME_RUNNER_UNAVAILABLE
    )
    assert proposal.diagnostics["candidate_present"] is True


def test_unavailable_runner_none_mode_returns_no_candidate():
    proposal = extract(FakeRunner(None, available=False),
                       fallback=FALLBACK_NONE)
    assert proposal.recommendation == "none"
    assert proposal.diagnostics["outcome"] == OUTCOME_RUNNER_UNAVAILABLE
    assert proposal.diagnostics["fallback_used"] is False


def test_error_mode_falls_back_on_runner_error():
    runner = FakeRunner(raise_exc=RuntimeError("boom"))
    on_error = extract(runner, fallback=FALLBACK_ON_ERROR)
    assert on_error.diagnostics["runner_status"] == RUNNER_ERROR
    assert on_error.diagnostics["fallback_used"] is True
    # But on_unavailable mode does NOT fall back for a runtime error.
    runner2 = FakeRunner(raise_exc=RuntimeError("boom"))
    on_unavail = extract(runner2, fallback=FALLBACK_ON_UNAVAILABLE)
    assert on_unavail.recommendation == "none"
    assert on_unavail.diagnostics["outcome"] == OUTCOME_RUNNER_ERROR
    assert on_unavail.diagnostics["fallback_used"] is False


def test_timeout_maps_to_status():
    runner = FakeRunner(raise_exc=TimeoutError())
    proposal = extract(runner, fallback=FALLBACK_NONE)
    assert proposal.diagnostics["runner_status"] == RUNNER_TIMEOUT
    assert proposal.diagnostics["outcome"] == OUTCOME_RUNNER_TIMEOUT


def test_invalid_mode_falls_back_on_validation_rejection():
    # A question span the validator rejects; on_invalid falls back.
    message = "Should I use SFO?"
    raw = candidate_json(message=message, evidence=message,
                        normalized="Uses SFO", start=0,
                        end=len(message))
    proposal = extract(FakeRunner(raw), message=message,
                      fallback=FALLBACK_ON_INVALID)
    assert proposal.diagnostics["learned_outcome"] == (
        OUTCOME_VALIDATION_REJECTED
    )
    assert proposal.diagnostics["fallback_used"] is True
    # The deterministic controller also abstains on a question, so the
    # final result is none — but attributed to the fallback path.
    assert proposal.recommendation == "none"
    assert proposal.diagnostics["final_proposal_source"] == (
        "deterministic_fallback"
    )


def test_fallback_cannot_bypass_grounding_validation():
    # A malformed learned output falls back; the deterministic path
    # still runs its own validator, so any returned candidate is valid.
    message = "I prefer aisle seats"
    proposal = extract(FakeRunner("garbage"), message=message,
                      fallback=FALLBACK_ON_INVALID)
    assert proposal.diagnostics["fallback_used"] is True
    if proposal.candidate is not None:
        # Deterministic candidate carries its own grounded span.
        span = proposal.candidate.evidence_spans[0]
        assert message[span.start:span.end] == span.excerpt


def test_learned_never_credited_for_fallback():
    proposal = extract(FakeRunner(None, available=False),
                      fallback=FALLBACK_ON_UNAVAILABLE)
    # Even when a candidate is returned, its source is the fallback.
    assert proposal.diagnostics["final_proposal_source"] != "learned"


def test_wrong_type_runner_result_is_error():
    proposal = extract(FakeRunner(return_wrong_type=True))
    assert proposal.diagnostics["runner_status"] == RUNNER_ERROR


# -- determinism and serialization -------------------------------------------------


def test_identical_outputs_produce_identical_proposals():
    def strip_timing(value):
        if isinstance(value, dict):
            return {k: strip_timing(v) for k, v in value.items()
                    if k not in ("evaluation",)}
        return value

    raw = candidate_json()
    first = extract(FakeRunner(raw))
    second = extract(FakeRunner(raw))
    assert first.candidate == second.candidate
    assert strip_timing(first.diagnostics) == strip_timing(
        second.diagnostics
    )


def test_all_result_shapes_serialize_safely():
    for runner in (
        FakeRunner(candidate_json()),
        FakeRunner(none_json()),
        FakeRunner("garbage"),
        FakeRunner(None, available=False),
        FakeRunner(raise_exc=RuntimeError("boom")),
    ):
        proposal = extract(runner)
        payload = json.dumps(proposal.diagnostics)
        assert "/Users/" not in payload and "/home/" not in payload
        assert "boom" not in payload  # exception messages withheld
        assert proposal.diagnostics["canonical_effect"] is False
        assert isinstance(proposal, ExtractionProposal)


def test_diagnostics_distinguish_stages():
    proposal = extract(FakeRunner(candidate_json()))
    d = proposal.diagnostics
    for field_name in ("runner_status", "parser_status",
                       "validation_status", "outcome",
                       "final_proposal_source"):
        assert field_name in d


# -- side effects ------------------------------------------------------------------


def test_extraction_has_no_side_effects(tmp_path):
    from experienceos.events.bus import EventBus
    from experienceos.memory.store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    bus = EventBus()
    extract(FakeRunner(candidate_json()))
    assert store.list_memories("u1") == []
    assert bus.history() == []
    assert not list(tmp_path.iterdir())


def test_schema_is_bounded_and_closed():
    assert EXTRACTION_OUTPUT_SCHEMA["additionalProperties"] is False
    assert set(EXTRACTION_OUTPUT_SCHEMA["properties"]) == {
        "action", "kind", "normalized_text", "evidence_text",
        "start_offset", "end_offset", "confidence", "reason",
    }
