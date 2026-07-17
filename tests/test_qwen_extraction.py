"""Tests for the experimental Qwen-backed extraction controller.

Offline only: a stub provider returns canned JSON; no network, no
credentials, no live Qwen call. Verifies the controller returns the
existing proposal type, does exactly one temperature-0 inference with no
retries, treats model output as untrusted, and — with no deterministic
fallback — reports an explicit non-candidate result when the provider is
unavailable or fails, never substituting a deterministic proposal.
"""

from __future__ import annotations

import json

import pytest

from experienceos.controllers.extraction import (
    ExtractionEvidence,
    ExtractionProposal,
)
from experiments.qwen_extraction import (
    QWEN_EXTRACTION_CONTROLLER_ID,
    QWEN_EXTRACTION_RUNNER_ID,
    QwenExtractionController,
    QwenExtractionRunner,
    build_extraction_messages,
    build_qwen_extraction_controller,
)

MSG = "I prefer window seats for work trips."


class _StubProvider:
    """A provider returning canned text; counts inferences."""

    def __init__(self, output, *, configured=True):
        self._output = output
        self.is_configured = configured
        self.calls = 0
        self.last_messages = None

    def complete(self, messages):
        self.calls += 1
        self.last_messages = messages
        return self._output


def _candidate_json(text=MSG):
    return json.dumps({
        "action": "candidate", "kind": "preference",
        "normalized_text": text, "evidence_text": text,
        "start_offset": 0, "end_offset": len(text),
        "confidence": 0.9, "reason": "stable seat preference",
    })


def _none_json():
    return json.dumps({
        "action": "none", "kind": None, "normalized_text": None,
        "evidence_text": None, "start_offset": None, "end_offset": None,
        "confidence": None, "reason": "no durable memory",
    })


def _controller(output, *, configured=True):
    return QwenExtractionController(_StubProvider(output, configured=configured))


# --- proposal type and candidate --------------------------------------------


def test_returns_the_existing_proposal_type() -> None:
    proposal = _controller(_candidate_json()).extract(ExtractionEvidence(user_text=MSG))
    assert isinstance(proposal, ExtractionProposal)
    assert proposal.proposal_only is True


def test_valid_candidate_is_grounded_and_attributed_to_qwen() -> None:
    proposal = _controller(_candidate_json()).extract(ExtractionEvidence(user_text=MSG))
    assert proposal.recommendation == "candidate"
    assert proposal.candidate is not None
    assert proposal.candidate.kind == "preference"
    assert proposal.candidate.text == MSG
    assert proposal.controller_id == QWEN_EXTRACTION_CONTROLLER_ID
    assert proposal.diagnostics.get("provider") == "qwen_cloud"
    assert proposal.diagnostics.get("runner_id") == QWEN_EXTRACTION_RUNNER_ID


def test_none_result() -> None:
    proposal = _controller(_none_json()).extract(
        ExtractionEvidence(user_text="what is the weather today?")
    )
    assert proposal.recommendation == "none"
    assert proposal.candidate is None


# --- untrusted output -------------------------------------------------------


def test_malformed_output_yields_none() -> None:
    proposal = _controller("not json at all").extract(ExtractionEvidence(user_text=MSG))
    assert proposal.recommendation == "none"


def test_markdown_wrapped_output_is_rejected() -> None:
    proposal = _controller("```json\n" + _candidate_json() + "\n```").extract(
        ExtractionEvidence(user_text=MSG)
    )
    assert proposal.recommendation == "none"


def test_fabricated_evidence_is_rejected_by_the_validator() -> None:
    # evidence_text that does not appear in the message must not ground.
    bad = json.dumps({
        "action": "candidate", "kind": "preference",
        "normalized_text": "I like aisle seats", "evidence_text": "aisle seats",
        "start_offset": 0, "end_offset": 11, "confidence": 0.9, "reason": "x",
    })
    proposal = _controller(bad).extract(ExtractionEvidence(user_text=MSG))
    assert proposal.recommendation == "none"


# --- one inference, no retries ----------------------------------------------


def test_exactly_one_inference_and_no_retry() -> None:
    stub = _StubProvider(_candidate_json())
    QwenExtractionController(stub).extract(
        ExtractionEvidence(user_text=MSG)
    )
    assert stub.calls == 1


def test_prompt_is_deterministic_and_json_only() -> None:
    a = build_extraction_messages(MSG)
    b = build_extraction_messages(MSG)
    assert a == b  # deterministic
    system = a[0]["content"]
    assert "JSON" in system and "no markdown" in system.lower()
    assert a[1] == {"role": "user", "content": MSG}


# --- availability, no fallback, error containment ---------------------------


def test_unavailable_provider_is_explicit_none_never_deterministic() -> None:
    # No deterministic fallback: an unavailable provider yields an explicit
    # non-candidate Qwen result, still attributed to the Qwen path, and the
    # provider is never invoked.
    class _Unconfigured:
        is_configured = False

        def complete(self, messages):
            raise AssertionError("must not be called when unavailable")

    proposal = QwenExtractionController(_Unconfigured()).extract(
        ExtractionEvidence(user_text=MSG)
    )
    assert proposal.recommendation == "none"
    assert proposal.candidate is None
    assert proposal.controller_id == QWEN_EXTRACTION_CONTROLLER_ID
    assert proposal.diagnostics.get("fallback_used") is not True
    assert proposal.diagnostics.get("runner_status") == "runner_unavailable"


def test_failure_never_returns_a_deterministic_proposal() -> None:
    # A provider error yields a non-candidate Qwen result, not the
    # deterministic extractor's proposal for the same durable message.
    class _Boom:
        is_configured = True

        def complete(self, messages):
            raise RuntimeError("boom")

    proposal = QwenExtractionController(_Boom()).extract(
        ExtractionEvidence(user_text=MSG)
    )
    assert proposal.recommendation == "none"  # not the deterministic candidate
    assert proposal.controller_id == QWEN_EXTRACTION_CONTROLLER_ID
    assert proposal.diagnostics.get("runner_status") == "runner_error"


def test_provider_error_is_contained() -> None:
    class _Boom:
        is_configured = True

        def complete(self, messages):
            raise RuntimeError("network down")

    proposal = _controller_error = QwenExtractionController(
        _Boom()
    ).extract(ExtractionEvidence(user_text=MSG))
    assert proposal.recommendation == "none"  # no crash, contained


def test_runner_availability_reflects_provider() -> None:
    assert QwenExtractionRunner(_StubProvider("x")).availability() is True
    assert QwenExtractionRunner(_StubProvider("x", configured=False)).availability() is False
    assert QwenExtractionRunner(None).availability() is False


# --- real Qwen provider integration (offline, network monkeypatched) --------


def test_injected_qwen_provider_is_called_once_with_temperature_zero() -> None:
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    provider = QwenCloudProvider(api_key="test-key", temperature=0.0)
    posted = {}

    def _fake_post(payload):
        posted["payload"] = payload
        return {"choices": [{"message": {"content": _candidate_json()}}]}

    provider._post = _fake_post  # no network
    proposal = QwenExtractionController(provider).extract(
        ExtractionEvidence(user_text=MSG)
    )
    assert proposal.recommendation == "candidate"
    assert proposal.controller_id == QWEN_EXTRACTION_CONTROLLER_ID
    assert posted["payload"]["temperature"] == 0.0  # determinism enforced
    assert len(posted["payload"]["messages"]) == 2  # system + user, one call


def test_builder_enforces_temperature_zero_and_timeout() -> None:
    controller = build_qwen_extraction_controller(api_key="k", timeout_ms=5000)
    provider = controller._runner._provider
    assert provider.temperature == 0.0
    assert provider.timeout == 5.0


# --- purity: the controller holds no store or mutation authority ------------


def test_controller_holds_no_store_or_mutation() -> None:
    controller = _controller(_none_json())
    for forbidden in ("memory_store", "engine", "experience_manager", "add",
                      "supersede", "forget"):
        assert not hasattr(controller, forbidden)
