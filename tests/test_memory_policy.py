"""Policy contract tests: types, validation, and rule-based parity."""

import pytest

from experienceos.memory import ExperienceEntry, MemoryKind, MemoryPlanner
from experienceos.policy import (
    DecisionSource,
    ExperienceManager,
    MemoryDecisionProposal,
    PolicyAction,
    PolicyContext,
    RuleBasedMemoryPolicy,
)
from experienceos.policy.manager import InvalidMemoryProposal


class FakePolicy:
    """Minimal MemoryPolicy implementation for contract tests."""

    mode = "custom"

    def __init__(self, proposals):
        self.proposals = proposals
        self.contexts = []

    def plan(self, context):
        self.contexts.append(context)
        return list(self.proposals)


def make_context(message="hello", active=None):
    return PolicyContext(
        user_id="u1",
        session_id="s1",
        message=message,
        active_memories=active or [],
    )


def plan_with(proposals):
    return ExperienceManager(FakePolicy(proposals)).plan(make_context())


# --- Contract and validation -------------------------------------------------


def test_fake_policy_satisfies_protocol():
    manager = ExperienceManager(FakePolicy([]))
    result = manager.plan(make_context())
    assert result.actions == []
    assert result.policy_mode == "custom"


def test_policy_context_is_bounded_data_only():
    context = make_context(active=[ExperienceEntry(user_id="u1", text="A.")])
    fields = set(vars(context))
    assert fields == {
        "user_id",
        "session_id",
        "message",
        "active_memories",
        "request_tags",
    }


def test_proposal_defaults():
    proposal = MemoryDecisionProposal(action=PolicyAction.CREATE, text="X.")
    assert proposal.kind == MemoryKind.PREFERENCE
    assert proposal.confidence == 1.0
    assert proposal.decision_source == DecisionSource.RULE_BASED
    assert proposal.fallback_reason is None
    assert proposal.metadata == {}


def test_recognized_actions_accepted():
    result = plan_with(
        [
            MemoryDecisionProposal(action=PolicyAction.CREATE, text="A."),
            MemoryDecisionProposal(action=PolicyAction.NOOP),
        ]
    )
    assert [a.action for a in result.actions] == ["create"]


def test_unknown_action_rejected():
    with pytest.raises(InvalidMemoryProposal, match="Unknown action"):
        plan_with([MemoryDecisionProposal(action="update", text="A.")])


def test_unknown_kind_rejected():
    with pytest.raises(InvalidMemoryProposal, match="Unknown memory kind"):
        plan_with(
            [MemoryDecisionProposal(action="create", kind="goal", text="A.")]
        )


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_confidence_bounds_accepted(confidence):
    result = plan_with(
        [
            MemoryDecisionProposal(
                action="create", text="A.", confidence=confidence
            )
        ]
    )
    assert len(result.actions) == 1


@pytest.mark.parametrize("confidence", [-0.1, 1.1, "high", None])
def test_bad_confidence_rejected(confidence):
    with pytest.raises(InvalidMemoryProposal):
        plan_with(
            [
                MemoryDecisionProposal(
                    action="create", text="A.", confidence=confidence
                )
            ]
        )


def test_create_without_text_rejected():
    with pytest.raises(InvalidMemoryProposal, match="requires text"):
        plan_with([MemoryDecisionProposal(action="create", text="   ")])


def test_supersede_without_target_rejected():
    with pytest.raises(InvalidMemoryProposal, match="target_memory_id"):
        plan_with([MemoryDecisionProposal(action="supersede", text="A.")])


def test_supersede_without_text_rejected():
    with pytest.raises(InvalidMemoryProposal, match="requires text"):
        plan_with(
            [MemoryDecisionProposal(action="supersede", target_memory_id="m1")]
        )


def test_forget_without_target_rejected():
    with pytest.raises(InvalidMemoryProposal, match="target_memory_id"):
        plan_with([MemoryDecisionProposal(action="forget")])


def test_unknown_decision_source_rejected():
    with pytest.raises(InvalidMemoryProposal, match="decision source"):
        plan_with(
            [
                MemoryDecisionProposal(
                    action="create", text="A.", decision_source="oracle"
                )
            ]
        )


def test_invalid_fallback_reason_rejected():
    with pytest.raises(InvalidMemoryProposal, match="fallback reason"):
        plan_with(
            [
                MemoryDecisionProposal(
                    action="create", text="A.", fallback_reason="bad_luck"
                )
            ]
        )


# --- Rule-based parity --------------------------------------------------------

PARITY_SCENARIOS = [
    ("simple preference create", "I prefer aisle seats.", []),
    (
        "multiple creates from one message",
        "I prefer aisle seats and morning flights. I don't like red-eye flights.",
        [],
    ),
    ("fact creation", "My home airport is SFO.", []),
    (
        "instruction creation",
        "When planning work trips, include airport transfer time.",
        [],
    ),
    (
        "exact duplicate avoidance",
        "I prefer aisle seats.",
        [ExperienceEntry(user_id="u1", text="Prefers aisle seats.")],
    ),
    (
        "preference supersession",
        "Actually, I prefer window seats now.",
        [ExperienceEntry(user_id="u1", text="Prefers aisle seats.")],
    ),
    (
        "fact supersession",
        "Actually, my home airport is now SJC.",
        [
            ExperienceEntry(
                user_id="u1", text="Home airport is SFO.", kind=MemoryKind.FACT
            )
        ],
    ),
    (
        "instruction supersession",
        "From now on, keep travel plans even shorter.",
        [
            ExperienceEntry(
                user_id="u1",
                text="Include detailed options when planning trips.",
                kind=MemoryKind.INSTRUCTION,
            )
        ],
    ),
    (
        "explicit forgetting",
        "Forget my aisle seat preference.",
        [ExperienceEntry(user_id="u1", text="Prefers aisle seats.")],
    ),
    (
        "forget alongside create in one message",
        "Forget my aisle seat preference. I prefer quiet hotels.",
        [ExperienceEntry(user_id="u1", text="Prefers aisle seats.")],
    ),
]


@pytest.mark.parametrize(
    "message,existing",
    [(m, e) for _, m, e in PARITY_SCENARIOS],
    ids=[name for name, _, _ in PARITY_SCENARIOS],
)
def test_rule_based_policy_parity_with_planner(message, existing):
    """policy → manager → MemoryAction must equal the planner exactly."""
    planner = MemoryPlanner()
    direct = planner.plan_memory_actions("u1", "s1", message, existing=existing)

    manager = ExperienceManager(RuleBasedMemoryPolicy(planner))
    routed = manager.plan(
        PolicyContext(
            user_id="u1",
            session_id="s1",
            message=message,
            active_memories=existing,
        )
    ).actions

    assert routed == direct  # frozen dataclasses: field-for-field equality


def test_policy_modules_import_no_local_runtime():
    """Optional runtime references live only in local_runner.py
    (whose own lazy-import rules are guarded in test_local_runner)."""
    from pathlib import Path

    for path in Path("experienceos/policy").glob("*.py"):
        if path.name == "local_runner.py":
            continue
        text = path.read_text()
        for forbidden in ("llama_cpp", "transformers", "torch", "onnxruntime"):
            assert forbidden not in text, f"{forbidden} in {path}"
