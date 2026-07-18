"""Canonical activation and composition-safety facts for deterministic
lifecycle transitions.

Pure and offline: no network, no provider call. These pin the activated
contract — the canonical chat compositions run adopted deterministic
transitions, the capable controllers resolve the genuine cases, the
bounded runtime authority supplies each per-request authorization, and
the SDK default is unchanged so only the demo and the benchmark adapter
opt in.
"""

from __future__ import annotations

from experienceos.controllers.base import MemorySnapshot
from experienceos.memory.forget_intelligence import DeterministicForgetController
from experienceos.memory.transition_authority import (
    BoundedRuntimeTransitionAuthority,
)
from experienceos.memory.transition_integration import (
    TransitionIntegrationMode,
)
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


# -- the capable controllers resolve the four genuine cases ------------------


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


# -- the canonical compositions activate adopted transitions -----------------


def test_create_agent_default_activates_adopted_transition():
    from experienceos.providers import MockProvider
    from demo.support import create_agent

    agent = create_agent(MockProvider())
    coordinator = getattr(agent, "transition_coordinator", None)
    assert coordinator is not None
    assert coordinator.mode == TransitionIntegrationMode.ADOPTED


def test_canonical_qwen_system_wires_adopted_transition():
    import inspect
    from experiments.competitive_viability import qwen_system

    src = inspect.getsource(qwen_system)
    # The canonical answer-run adapter builds the same adopted transition
    # config the demo uses.
    assert "build_canonical_transition_config" in src
    assert 'kwargs["transition"]' in src


def test_demo_builder_builds_adopted_mode():
    from demo.transition_diagnostics import build_transition_config

    assert build_transition_config("disabled") is None
    adopted = build_transition_config("adopted")
    assert adopted.mode == TransitionIntegrationMode.ADOPTED
    assert isinstance(adopted.runtime_authority, BoundedRuntimeTransitionAuthority)


# -- composition safety ------------------------------------------------------


def test_canonical_config_has_all_four_components_and_no_static_auth():
    from demo.support import build_canonical_transition_config

    cfg = build_canonical_transition_config()
    assert cfg.mode == TransitionIntegrationMode.ADOPTED
    assert isinstance(cfg.update_controller, DeterministicUpdateController)
    assert isinstance(cfg.forget_controller, DeterministicForgetController)
    assert cfg.verifier is not None
    assert isinstance(cfg.runtime_authority, BoundedRuntimeTransitionAuthority)
    # No config-time (static) authorization: every canonical effect is
    # authorized per-request by the bounded runtime authority.
    assert cfg.authorizations == ()
    assert cfg.replacement_authorizations == ()
    # The canonical composition defers to the planner for transitions it
    # already performs, so keyed cases keep their normalized text and do
    # not duplicate a supersede/forget.
    assert cfg.planner_precedence is True


def test_canonical_config_does_not_select_the_qwen_update_controller():
    from demo.support import build_canonical_transition_config

    cfg = build_canonical_transition_config()
    # The experimental Qwen update controller is never adopted as canonical.
    assert cfg.update_controller.controller_id == "experienceos_transition_rules_v1"
    assert "qwen" not in cfg.update_controller.controller_id.lower()


def test_sdk_default_is_unchanged_no_transition_coordinator():
    from experienceos import ExperienceOS
    from experienceos.providers import MockProvider

    # Constructing the SDK without a transition config activates nothing;
    # only the demo and the benchmark adapter opt in.
    agent = ExperienceOS(model=MockProvider())
    assert getattr(agent, "transition_coordinator", None) is None


def test_transition_config_defaults_to_disabled():
    from experienceos.memory.transition_integration import (
        TransitionIntegrationConfig,
    )
    cfg = TransitionIntegrationConfig()
    assert cfg.mode == TransitionIntegrationMode.DISABLED
    assert cfg.enabled is False
    assert cfg.update_controller is None and cfg.forget_controller is None
    assert cfg.authorizations == () and cfg.replacement_authorizations == ()
    assert cfg.runtime_authority is None


def test_observational_modes_carry_no_runtime_authority():
    from demo.transition_diagnostics import build_transition_config

    for mode in ("shadow", "candidate", "verify_only"):
        cfg = build_transition_config(mode)
        assert cfg.mode == mode
        assert cfg.runtime_authority is None


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
    assert fields["scope"].default == "single_proposal"
    assert fields["single_use"].default is True
