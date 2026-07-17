"""Tests for canonical extraction controller selection.

Qwen extraction is canonical whenever Qwen Cloud is configured; the
deterministic controller stays the alternate implementation for offline
runs, tests, and comparison benchmarks. Offline only: credentials are
injected as a literal string and no network call is made.

Selection happens in composition (``demo.support``), so these tests also
pin the properties that make that safe: the proposal structure is
unchanged, grounded validation stays downstream and authoritative, the
selected controller runs through the existing integration coordinator,
and no mutation capability is introduced.
"""

from __future__ import annotations

import json

import pytest

from demo.support import (
    PROVIDER_MOCK,
    PROVIDER_QWEN,
    build_canonical_extraction_config,
    make_provider,
    qwen_extraction_configured,
)
from experienceos.controllers.extraction import (
    ExtractionEvidence,
    ExtractionProposal,
)
from experienceos.memory.extraction_integration import (
    CONTROLLER_DETERMINISTIC,
    CONTROLLER_LEARNED,
    MODE_CANDIDATE,
    MODE_SHADOW,
    ExtractionIntegrationCoordinator,
)
from experienceos.providers import MockProvider, QwenCloudProvider
from experiments.qwen_extraction import QwenExtractionController

MSG = "I prefer window seats for work trips."


def _configured_qwen() -> QwenCloudProvider:
    """A Qwen provider that is configured but never called."""
    return QwenCloudProvider(api_key="test-key")


def _candidate_json(text=MSG):
    return json.dumps({
        "action": "candidate", "kind": "preference",
        "normalized_text": text, "evidence_text": text,
        "start_offset": 0, "end_offset": len(text),
        "confidence": 0.9, "reason": "stable seat preference",
    })


def _canonical_config(handler, mode=MODE_SHADOW):
    """Canonical config with the extraction transport stubbed.

    Replaces only the HTTP POST, so the real provider, controller,
    parser, and validator all still run — offline, with no network.
    """
    config = build_canonical_extraction_config(mode, _configured_qwen())
    config.learned_controller._runner._provider._post = handler
    return config


def _responds(content):
    return lambda payload: {"choices": [{"message": {"content": content}}]}


def _evidence():
    return ExtractionEvidence(user_text=MSG, metadata={"source_id": "s1"})


# -- 1. Qwen-configured initialization selects the Qwen controller ---------


def test_configured_qwen_selects_the_qwen_controller():
    config = build_canonical_extraction_config(MODE_SHADOW, _configured_qwen())
    assert config.controller_type == CONTROLLER_LEARNED
    assert isinstance(config.learned_controller, QwenExtractionController)
    assert config.effect_mode == MODE_SHADOW


def test_canonical_selection_holds_for_every_selectable_mode():
    for mode in (MODE_SHADOW, MODE_CANDIDATE):
        config = build_canonical_extraction_config(mode, _configured_qwen())
        assert isinstance(config.learned_controller, QwenExtractionController)
        assert config.effect_mode == mode


def test_extraction_carries_chat_settings_but_forces_temperature_zero():
    # Same credentials, endpoint, and model as the configured chat
    # provider, but extraction never inherits chat sampling settings:
    # the validated path is temperature 0 with a bounded timeout.
    chat = QwenCloudProvider(
        api_key="test-key", base_url="https://regional.example/v1",
        model="qwen-max", temperature=0.9,
    )
    extraction = build_canonical_extraction_config(
        MODE_SHADOW, chat
    ).learned_controller._runner._provider
    assert extraction.api_key == "test-key"
    assert extraction.base_url == "https://regional.example/v1"
    assert extraction.model == "qwen-max"
    assert extraction.temperature == 0.0  # not the chat provider's 0.9
    assert extraction.timeout == 8.0
    assert extraction is not chat


# -- 2. Offline / unconfigured selects the deterministic controller --------


def test_unconfigured_qwen_stays_deterministic():
    unconfigured = QwenCloudProvider(api_key=None)
    assert unconfigured.is_configured is False
    config = build_canonical_extraction_config(MODE_SHADOW, unconfigured)
    assert config.controller_type == CONTROLLER_DETERMINISTIC
    assert config.learned_controller is None


def test_offline_mock_provider_stays_deterministic():
    config = build_canonical_extraction_config(MODE_SHADOW, MockProvider())
    assert config.controller_type == CONTROLLER_DETERMINISTIC
    assert config.learned_controller is None


def test_demo_provider_choices_map_to_the_expected_controllers(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    offline = build_canonical_extraction_config(
        MODE_SHADOW, make_provider(PROVIDER_MOCK)
    )
    assert offline.controller_type == CONTROLLER_DETERMINISTIC
    # Qwen selected in the UI but unconfigured must not claim canonical.
    unconfigured = build_canonical_extraction_config(
        MODE_SHADOW, make_provider(PROVIDER_QWEN)
    )
    assert unconfigured.controller_type == CONTROLLER_DETERMINISTIC


def test_qwen_extraction_configured_predicate():
    assert qwen_extraction_configured(_configured_qwen()) is True
    assert qwen_extraction_configured(QwenCloudProvider(api_key=None)) is False
    assert qwen_extraction_configured(MockProvider()) is False


# -- disabled mode and the adopted guard are unchanged ---------------------


def test_disabled_mode_builds_no_config_and_no_controller():
    assert build_canonical_extraction_config("disabled", _configured_qwen()) is None


def test_adopted_mode_remains_unreachable_from_composition():
    # Canonical selection must not become a way to reach adopted mode.
    assert build_canonical_extraction_config("adopted", _configured_qwen()) is None


# -- 3. The selected controller runs through the existing coordinator ------


def test_canonical_qwen_runs_through_the_existing_coordinator():
    config = _canonical_config(_responds(_candidate_json()))
    coordinator = ExtractionIntegrationCoordinator(config)
    outcome = coordinator.evaluate(
        _evidence(), source_id="s1", provenance="user_asserted",
    )
    assert coordinator.enabled is True
    assert outcome.controller_type == CONTROLLER_LEARNED
    assert outcome.proposal.controller_id == QwenExtractionController.controller_id


# -- 4. Proposal structures are unchanged ---------------------------------


def test_proposal_structure_is_unchanged():
    config = _canonical_config(_responds(_candidate_json()))
    proposal = config.learned_controller.extract(_evidence())
    assert isinstance(proposal, ExtractionProposal)
    assert proposal.proposal_only is True
    assert proposal.recommendation == "candidate"
    span = proposal.candidate.evidence_spans[0]
    assert MSG[span.start:span.end] == span.excerpt


# -- 5. Grounded validation remains downstream and authoritative ----------


def test_grounded_validation_still_rejects_fabricated_evidence():
    # Canonical status does not let Qwen bypass the validator.
    fabricated = json.dumps({
        "action": "candidate", "kind": "preference",
        "normalized_text": "I like aisle seats",
        "evidence_text": "aisle seats",
        "start_offset": 0, "end_offset": 11, "confidence": 0.9, "reason": "x",
    })
    config = _canonical_config(_responds(fabricated))
    outcome = ExtractionIntegrationCoordinator(config).evaluate(
        _evidence(), source_id="s1", provenance="user_asserted",
    )
    assert outcome.proposal.recommendation == "none"
    assert outcome.translated_action is None


def test_coordinator_keeps_its_own_validator_for_the_canonical_path():
    config = build_canonical_extraction_config(MODE_SHADOW, _configured_qwen())
    coordinator = ExtractionIntegrationCoordinator(config)
    from experienceos.memory.grounding import GroundedCandidateValidator

    assert isinstance(coordinator.validator, GroundedCandidateValidator)


# -- 6. No mutation capability is introduced ------------------------------


def test_canonical_controller_has_no_mutation_capability():
    controller = build_canonical_extraction_config(
        MODE_SHADOW, _configured_qwen()
    ).learned_controller
    for forbidden in ("memory_store", "engine", "experience_manager", "add",
                      "supersede", "forget", "_apply_memory_actions"):
        assert not hasattr(controller, forbidden)


def test_shadow_mode_config_carries_no_adoption_authorization():
    config = build_canonical_extraction_config(MODE_SHADOW, _configured_qwen())
    assert config.authorizations == ()


# -- 7. No fallback was added: failure stays an explicit Qwen result ------


def test_failure_is_explicit_and_never_falls_back_to_deterministic():
    def _boom(payload):
        raise RuntimeError("provider down")

    config = _canonical_config(_boom)
    proposal = config.learned_controller.extract(_evidence())
    assert proposal.recommendation == "none"  # not a deterministic candidate
    assert proposal.diagnostics.get("runner_status") == "runner_error"
    assert proposal.diagnostics.get("fallback_used") is not True


def test_canonical_path_makes_exactly_one_temperature_zero_inference():
    calls = []

    def _post(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": _candidate_json()}}]}

    config = _canonical_config(_post)
    ExtractionIntegrationCoordinator(config).evaluate(
        _evidence(), source_id="s1", provenance="user_asserted",
    )
    assert len(calls) == 1  # one call, no retries
    assert calls[0]["temperature"] == 0.0  # the validated path
    assert len(calls[0]["messages"]) == 2  # system + user


# -- the core stays provider-neutral --------------------------------------


def test_core_does_not_select_a_provider_controller():
    """Selection lives in composition; the core default is unchanged."""
    from experienceos.memory.extraction_integration import (
        ExtractionIntegrationConfig,
    )

    assert ExtractionIntegrationConfig().controller_type == (
        CONTROLLER_DETERMINISTIC
    )
    # The controller vocabulary never names a provider.
    from experienceos.memory import extraction_integration

    assert "qwen" not in str(extraction_integration.CONTROLLER_TYPES).lower()
    with pytest.raises(Exception):
        ExtractionIntegrationConfig(controller_type="qwen")
