"""Audit-only classification facts for the canonical activation defect.

Pure and offline: no runtime behavior change, no mutation, no network.
Pins the load-bearing facts of the defect classification so they stay
verifiable — the deterministic controllers already resolve the genuine
cases, no canonical composition configures a transition coordinator, the
demo builder refuses adopted mode, and exact authorization binds to the
runtime proposal (so a static config-time authorization cannot match).
"""

from __future__ import annotations

import pytest

from experienceos.controllers.base import MemorySnapshot
from experienceos.memory.forget_intelligence import DeterministicForgetController
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    build_before_state,
)
from experienceos.memory.update_intelligence import DeterministicUpdateController


def _before(mems):
    return build_before_state(
        [MemorySnapshot(memory_id=i, kind=k, text=t, status="active")
         for i, k, t in mems],
        snapshot_source="audit",
    )


def _evid(stmt):
    return TransitionSourceEvidence(
        source_statement=stmt, source_event_id="e", session_id="s",
        evidence_mode=EvidenceMode.GROUNDED_VALID, provenance_ref="user_asserted",
    )


# -- the capable controllers already resolve the four genuine cases ----------


def test_update_controller_supersedes_the_genuine_update_cases():
    uc = DeterministicUpdateController()
    for stmt, mem in (
        ("Actually, I prefer coffee in the morning.",
         ("food.morning_drink", "preference", "Prefers tea in the morning.")),
        ("Switch that — I prefer light mode in my editor now.",
         ("editor.color_mode", "preference", "Prefers dark mode in my code editor.")),
        ("I upgraded — my phone is a Pixel 9 now.",
         ("device.phone", "fact", "Phone is a Pixel 6.")),
    ):
        res = uc.propose(stmt, _evid(stmt), _before([mem]))
        assert res.transition_type == "supersede_existing"
        assert list(res.proposal.superseded_ids) == [mem[0]]


def test_forget_controller_forgets_the_genuine_forget_case():
    fc = DeterministicForgetController()
    stmt = "Forget the instruction about my daily status channel."
    mem = ("work.daily_status_channel", "instruction",
           "Send my daily status summary to the #eng-daily channel.")
    res = fc.propose(stmt, _evid(stmt), _before([mem]))
    assert res.transition_type == "forget_existing"
    assert list(res.proposal.forgotten_ids) == [mem[0]]


def test_controllers_are_deterministic_not_qwen():
    assert DeterministicUpdateController().controller_id == (
        "experienceos_transition_rules_v1")
    assert DeterministicForgetController().controller_id == (
        "experienceos_forget_rules_v1")


# -- no canonical composition configures a transition coordinator ------------


def test_create_agent_default_has_no_transition_coordinator():
    from experienceos.providers import MockProvider
    from demo.support import create_agent

    agent = create_agent(MockProvider())
    assert getattr(agent, "transition_coordinator", None) is None


def test_canonical_qwen_system_wires_no_transition():
    import inspect
    from experiments.competitive_viability import qwen_system

    src = inspect.getsource(qwen_system)
    # The canonical answer-run adapter passes extraction only; it never
    # constructs or passes a transition config/coordinator.
    assert "transition" not in src


def test_transition_config_defaults_to_disabled():
    from experienceos.memory.transition_integration import (
        TransitionIntegrationConfig, TransitionIntegrationMode,
    )
    cfg = TransitionIntegrationConfig()
    assert cfg.mode == TransitionIntegrationMode.DISABLED
    assert cfg.enabled is False
    assert cfg.update_controller is None and cfg.forget_controller is None
    assert cfg.authorizations == () and cfg.replacement_authorizations == ()


def test_demo_builder_refuses_adopted_mode():
    from demo.transition_diagnostics import build_transition_config

    assert build_transition_config("disabled") is None
    with pytest.raises(ValueError):
        build_transition_config("adopted")


# -- exact authorization binds to the runtime proposal -----------------------


def test_authorization_binding_is_runtime_specific():
    from experienceos.memory.transition_integration import TransitionAuthorization

    fields = TransitionAuthorization.__dataclass_fields__
    # Bound to the exact runtime request / before-state / proposal /
    # verification, so a static config-time authorization cannot match an
    # arbitrary runtime proposal.
    for runtime_field in ("request_id", "source_digest", "before_state_digest",
                          "proposal_id", "proposal_digest", "verification_digest"):
        assert runtime_field in fields
    # deliberately single-proposal, single-use
    import dataclasses
    inst = {f.name: ("x" if f.default is dataclasses.MISSING else f.default)
            for f in fields.values()}
    # scope/single_use defaults encode the "one exact proposal" contract
    assert fields["scope"].default == "single_proposal"
    assert fields["single_use"].default is True
