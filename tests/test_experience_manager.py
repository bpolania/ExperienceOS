"""ExperienceManager, SDK integration, lifecycle-boundary, and event tests."""

import pytest

from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory import ExperienceEntry, MemoryPlanner, MemoryStatus
from experienceos.policy import (
    ExperienceManager,
    MemoryDecisionProposal,
    PolicyContext,
    RuleBasedMemoryPolicy,
)
from experienceos.providers import MockProvider


class FixedPolicy:
    """Returns the same proposals for every turn (for boundary tests)."""

    mode = "fixed"

    def __init__(self, proposals):
        self.proposals = proposals
        self.calls = 0
        self.received = []

    def plan(self, context):
        self.calls += 1
        self.received.append(context)
        return list(self.proposals)


def last_planned(agent):
    return [
        e for e in agent.events if e.type == EventType.MEMORY_ACTION_PLANNED
    ][-1].payload


# --- Manager behavior ----------------------------------------------------------


def test_manager_invokes_policy_once_with_bounded_context():
    policy = FixedPolicy([])
    agent = ExperienceOS(model=MockProvider(), memory_policy=policy)
    agent.chat(user_id="u1", session_id="s1", message="hello")
    assert policy.calls == 1
    context = policy.received[0]
    assert isinstance(context, PolicyContext)
    assert context.message == "hello"
    # Bounded data only — no store, engine, or bus reachable.
    assert not hasattr(context, "memory_store")
    assert set(vars(context)) == {
        "user_id",
        "session_id",
        "message",
        "active_memories",
        "request_tags",
    }


def test_proposal_order_preserved_for_independent_actions():
    proposals = [
        MemoryDecisionProposal(action="create", text="A."),
        MemoryDecisionProposal(action="create", text="B."),
        MemoryDecisionProposal(action="create", text="C."),
    ]
    result = ExperienceManager(FixedPolicy(proposals)).plan(
        PolicyContext(user_id="u", session_id="s", message="m")
    )
    assert [a.text for a in result.actions] == ["A.", "B.", "C."]


def test_duplicate_supersedes_first_wins():
    proposals = [
        MemoryDecisionProposal(
            action="supersede", target_memory_id="m1", text="First."
        ),
        MemoryDecisionProposal(
            action="supersede", target_memory_id="m1", text="Second."
        ),
    ]
    result = ExperienceManager(FixedPolicy(proposals)).plan(
        PolicyContext(user_id="u", session_id="s", message="m")
    )
    assert len(result.actions) == 1
    assert result.actions[0].text == "First."


def test_forget_outranks_supersede_for_same_target():
    proposals = [
        MemoryDecisionProposal(
            action="supersede", target_memory_id="m1", text="Replacement."
        ),
        MemoryDecisionProposal(action="forget", target_memory_id="m1"),
    ]
    result = ExperienceManager(FixedPolicy(proposals)).plan(
        PolicyContext(user_id="u", session_id="s", message="m")
    )
    assert [a.action for a in result.actions] == ["forget"]


def test_exact_duplicate_creates_deduplicated():
    proposals = [
        MemoryDecisionProposal(action="create", text="Same."),
        MemoryDecisionProposal(action="create", text="Same."),
    ]
    result = ExperienceManager(FixedPolicy(proposals)).plan(
        PolicyContext(user_id="u", session_id="s", message="m")
    )
    assert len(result.actions) == 1


def test_conversion_preserves_lineage():
    proposals = [
        MemoryDecisionProposal(
            action="supersede",
            target_memory_id="old-id",
            text="Old text.",
            explanation="Conflicts with updated home airport fact.",
        ),
        MemoryDecisionProposal(
            action="create",
            kind="fact",
            text="New text.",
            replaces="old-id",
            explanation="User updated this fact.",
        ),
    ]
    result = ExperienceManager(FixedPolicy(proposals)).plan(
        PolicyContext(user_id="u", session_id="s", message="m")
    )
    supersede, create = result.actions
    assert supersede.memory_id == "old-id"
    assert supersede.reason == "Conflicts with updated home airport fact."
    assert create.replaces == "old-id"
    assert create.reason == "User updated this fact."


def test_policy_mode_reported():
    assert ExperienceManager(FixedPolicy([])).policy_mode == "fixed"
    assert ExperienceManager(RuleBasedMemoryPolicy()).policy_mode == "rule_based"


# --- SDK integration ------------------------------------------------------------


def test_default_agent_uses_rule_based_policy():
    agent = ExperienceOS(model=MockProvider())
    assert agent.experience_manager.policy_mode == "rule_based"
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    assert [m.text for m in agent.memories_for_user("u1")] == [
        "Prefers aisle seats."
    ]


def test_explicit_policy_and_planner_injection_work(tmp_path):
    for kwargs in (
        {"memory_policy": RuleBasedMemoryPolicy()},
        {"memory_planner": MemoryPlanner()},
        {"experience_manager": ExperienceManager(RuleBasedMemoryPolicy())},
    ):
        agent = ExperienceOS(model=MockProvider(), **kwargs)
        agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
        assert [m.text for m in agent.memories_for_user("u1")] == [
            "Prefers aisle seats."
        ]

    wrapped = ExperienceOS.wrap(
        MockProvider(), memory_policy=RuleBasedMemoryPolicy()
    )
    assert wrapped.experience_manager.policy_mode == "rule_based"

    sqlite_agent = ExperienceOS.with_sqlite_memory(
        model=MockProvider(),
        db_path=str(tmp_path / "policy.sqlite3"),
        memory_policy=RuleBasedMemoryPolicy(),
    )
    sqlite_agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    assert sqlite_agent.memories_for_user("u1")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"experience_manager": ExperienceManager(), "memory_policy": RuleBasedMemoryPolicy()},
        {"experience_manager": ExperienceManager(), "memory_planner": MemoryPlanner()},
        {"memory_policy": RuleBasedMemoryPolicy(), "memory_planner": MemoryPlanner()},
    ],
)
def test_ambiguous_injection_combinations_rejected(kwargs):
    with pytest.raises(ValueError, match="only one of"):
        ExperienceOS(model=MockProvider(), **kwargs)


# --- Engine lifecycle boundary ---------------------------------------------------


def seeded_shared_store_agent(policy):
    """Agent with a real lifecycle history, then driven by a fixed policy."""
    base = ExperienceOS(model=MockProvider())
    base.chat(user_id="u1", session_id="s1", message="I prefer morning flights.")
    base.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer evening flights."
    )
    base.chat(user_id="u1", session_id="s3", message="I prefer aisle seats.")
    base.chat(
        user_id="u1", session_id="s4", message="Forget my aisle seat preference."
    )
    base.chat(user_id="other", session_id="o1", message="I prefer quiet hotels.")
    return (
        ExperienceOS(
            model=MockProvider(),
            memory_store=base.memory_store,
            memory_policy=policy,
        ),
        base.memory_store,
    )


def statuses(store, user_id="u1"):
    return {m.text: m.status for m in store.list_memories(user_id)}


def test_superseded_target_cannot_be_superseded_again():
    store_probe = ExperienceOS(model=MockProvider())
    # Find the superseded morning-flights id through a seeded store.
    agent, store = seeded_shared_store_agent(FixedPolicy([]))
    superseded_id = next(
        m.id
        for m in store.list_memories("u1", status=MemoryStatus.SUPERSEDED)
        if "morning" in m.text
    )
    policy = FixedPolicy(
        [
            MemoryDecisionProposal(
                action="supersede",
                target_memory_id=superseded_id,
                text="Hijacked.",
            )
        ]
    )
    agent = ExperienceOS(
        model=MockProvider(), memory_store=store, memory_policy=policy
    )
    before = statuses(store)
    agent.chat(user_id="u1", session_id="attack", message="anything")
    assert statuses(store) == before
    payload = last_planned(agent)
    assert len(payload["rejected_actions"]) == 1
    assert payload["rejected_actions"][0]["rejected_reason"] == "target_not_active"
    assert not [
        e for e in agent.events if e.type == EventType.MEMORY_SUPERSEDED
    ]


def test_forgotten_target_cannot_be_forgotten_or_superseded():
    agent, store = seeded_shared_store_agent(FixedPolicy([]))
    forgotten_id = store.list_memories("u1", status=MemoryStatus.FORGOTTEN)[0].id
    for action in ("forget", "supersede"):
        policy = FixedPolicy(
            [
                MemoryDecisionProposal(
                    action=action,
                    target_memory_id=forgotten_id,
                    text="Resurrected." if action == "supersede" else None,
                )
            ]
        )
        attacker = ExperienceOS(
            model=MockProvider(), memory_store=store, memory_policy=policy
        )
        before = statuses(store)
        attacker.chat(user_id="u1", session_id="attack", message="anything")
        assert statuses(store) == before
        assert last_planned(attacker)["rejected_actions"]


def test_cross_user_target_cannot_be_modified():
    agent, store = seeded_shared_store_agent(FixedPolicy([]))
    other_id = store.list_memories("other")[0].id
    policy = FixedPolicy(
        [MemoryDecisionProposal(action="forget", target_memory_id=other_id)]
    )
    attacker = ExperienceOS(
        model=MockProvider(), memory_store=store, memory_policy=policy
    )
    attacker.chat(user_id="u1", session_id="attack", message="anything")
    assert statuses(store, "other") == {"Prefers quiet hotels.": "active"}
    assert last_planned(attacker)["rejected_actions"]


def test_unknown_target_rejected_and_valid_actions_still_apply():
    policy_holder = []

    class MixedPolicy:
        mode = "fixed"

        def plan(self, context):
            return [
                MemoryDecisionProposal(action="create", text="Prefers naps."),
                MemoryDecisionProposal(
                    action="forget", target_memory_id="no-such-id"
                ),
            ]

    agent = ExperienceOS(model=MockProvider(), memory_policy=MixedPolicy())
    agent.chat(user_id="u1", session_id="s1", message="anything")
    # Independent valid actions apply; the invalid target is skipped.
    assert [m.text for m in agent.memories_for_user("u1")] == ["Prefers naps."]
    payload = last_planned(agent)
    assert len(payload["planned_actions"]) == 2
    assert len(payload["rejected_actions"]) == 1
    assert not [
        e for e in agent.events if e.type == EventType.MEMORY_FORGOTTEN
    ]


def test_create_duplicating_active_memory_is_rejected():
    agent = ExperienceOS(
        model=MockProvider(),
        memory_policy=FixedPolicy(
            [
                MemoryDecisionProposal(
                    action="create",
                    kind="fact",
                    text="Aisle seats are preferred for short work trips.",
                )
            ]
        ),
    )
    agent.chat(user_id="u1", session_id="s1", message="first turn")
    agent.chat(user_id="u1", session_id="s1", message="second turn")
    # The first create applies; the identical re-create is rejected.
    assert [m.text for m in agent.memories_for_user("u1")] == [
        "Aisle seats are preferred for short work trips."
    ]
    payload = last_planned(agent)
    assert len(payload["rejected_actions"]) == 1
    assert payload["rejected_actions"][0]["rejected_reason"] == "duplicate_of_active"
    assert payload["policy"]["fallback_used"] is False


def test_duplicate_create_allowed_when_matching_memory_is_retired_in_batch():
    creator = FixedPolicy(
        [MemoryDecisionProposal(action="create", text="Prefers aisle seats.")]
    )
    agent = ExperienceOS(model=MockProvider(), memory_policy=creator)
    agent.chat(user_id="u1", session_id="s1", message="seed")
    old_id = agent.memories_for_user("u1")[0].id

    replacer = FixedPolicy(
        [
            MemoryDecisionProposal(
                action="supersede",
                target_memory_id=old_id,
                text="Prefers aisle seats.",
            ),
            MemoryDecisionProposal(
                action="create",
                text="Prefers aisle seats.",
                replaces=old_id,
            ),
        ]
    )
    agent2 = ExperienceOS(
        model=MockProvider(),
        memory_store=agent.memory_store,
        memory_policy=replacer,
    )
    agent2.chat(user_id="u1", session_id="s2", message="replace it")
    # The supersede pair is a replacement, not a duplicate: the old
    # memory retires and the paired create still applies.
    active = agent2.memories_for_user("u1")
    assert [m.text for m in active] == ["Prefers aisle seats."]
    assert active[0].id != old_id
    assert last_planned(agent2)["rejected_actions"] == []


def test_valid_active_supersede_and_forget_still_work():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer morning flights.")
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer evening flights."
    )
    agent.chat(
        user_id="u1", session_id="s3", message="Forget my evening flight preference."
    )
    assert agent.memories_for_user("u1") == []
    assert last_planned(agent)["rejected_actions"] == []


# --- Event provenance -------------------------------------------------------------


def test_planning_event_carries_rule_based_provenance():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    payload = last_planned(agent)
    assert payload["policy"] == {
        "mode": "rule_based",
        "decision_source": "rule_based",
        "fallback_used": False,
        "fallback_reason": None,
    }
    action = payload["planned_actions"][0]
    # Existing fields preserved:
    assert action["action"] == "create"
    assert action["kind"] == "preference"
    assert action["text"] == "Prefers aisle seats."
    # Additive provenance:
    assert action["confidence"] == 1.0
    assert action["decision_source"] == "rule_based"
    assert "explanation" in action
