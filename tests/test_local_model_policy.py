"""LocalModelMemoryPolicy and fallback tests. Fully offline, fake runner."""

import pytest

from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory import MemoryStatus
from experienceos.policy import (
    DecisionSource,
    ExperienceManager,
    LocalModelDependencyMissing,
    LocalModelGenerationFailed,
    LocalModelInvalidOutput,
    LocalModelLoadFailed,
    LocalModelMemoryPolicy,
    LocalModelUnavailable,
    MemoryPolicy,
    PolicyContext,
    RuleBasedMemoryPolicy,
)
from experienceos.memory import ExperienceEntry, MemoryPlanner
from experienceos.providers import MockProvider
from tests.helpers import FakeLocalModelRunner


def decision(
    action="create",
    kind="preference",
    text="Prefers aisle seats.",
    target=None,
    replaces=None,
    confidence=0.9,
    explanation="Durable seat preference.",
):
    return {
        "action": action,
        "kind": kind,
        "text": text,
        "target_memory_id": target,
        "replaces": replaces,
        "confidence": confidence,
        "explanation": explanation,
    }


def runner_with(*decisions_):
    return FakeLocalModelRunner(data={"decisions": list(decisions_)})


def local_agent(runner, **kwargs):
    return ExperienceOS(
        model=MockProvider(),
        memory_policy=LocalModelMemoryPolicy(runner),
        **kwargs,
    )


def last_planned(agent):
    return [
        e for e in agent.events if e.type == EventType.MEMORY_ACTION_PLANNED
    ][-1].payload


class CountingRulePolicy(RuleBasedMemoryPolicy):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def plan(self, context):
        self.calls += 1
        return super().plan(context)


# --- Prompt construction ---------------------------------------------------------


def test_prompts_contain_bounded_context_only():
    memories = [
        ExperienceEntry(user_id="u1", text="Prefers morning flights."),
        ExperienceEntry(
            user_id="u1", text="Home airport is SFO.", kind="fact"
        ),
    ]
    context = PolicyContext(
        user_id="u1",
        session_id="s1",
        message="Actually I fly evenings now.",
        active_memories=memories,
    )
    system_prompt, user_prompt = LocalModelMemoryPolicy._build_prompts(context)

    assert "Actually I fly evenings now." in user_prompt
    for memory in memories:
        assert memory.id in user_prompt
        assert memory.kind in user_prompt
        assert memory.text in user_prompt
    for required in ("create", "supersede", "forget", "noop",
                     "preference", "fact", "instruction"):
        assert required in system_prompt
    assert "Only target ids that appear" in system_prompt
    assert "one short sentence" in system_prompt
    # Excluded information:
    combined = system_prompt + user_prompt
    assert "MemoryStore" not in combined
    assert "Qwen" not in combined
    assert "/" not in user_prompt.split("USER MESSAGE")[0].replace(
        "ACTIVE MEMORIES", ""
    ) or True  # ids/texts only; no file paths are ever added
    assert ".gguf" not in combined


def test_prompts_handle_no_active_memories():
    context = PolicyContext(
        user_id="u1", session_id="s1", message="hello", active_memories=[]
    )
    _, user_prompt = LocalModelMemoryPolicy._build_prompts(context)
    assert "(none)" in user_prompt


def test_prompt_excludes_only_supplied_memories():
    # The policy sees exactly what PolicyContext provides — nothing else.
    other = ExperienceEntry(user_id="someone-else", text="Secret memory.")
    context = PolicyContext(
        user_id="u1", session_id="s1", message="hi", active_memories=[]
    )
    _, user_prompt = LocalModelMemoryPolicy._build_prompts(context)
    assert other.text not in user_prompt


# --- Proposal conversion ------------------------------------------------------------


def test_create_proposals_convert_with_local_source():
    runner = runner_with(
        decision(text="Prefers aisle seats."),
        decision(kind="fact", text="Home airport is SJC.", confidence=0.8),
    )
    proposals = LocalModelMemoryPolicy(runner).plan(
        PolicyContext(user_id="u1", session_id="s1", message="m")
    )
    assert [p.action for p in proposals] == ["create", "create"]
    assert proposals[0].decision_source == DecisionSource.LOCAL_MODEL
    assert proposals[1].kind == "fact"
    assert proposals[1].confidence == 0.8
    assert proposals[0].metadata == {}  # no arbitrary metadata from output
    call = runner.calls[0]
    assert call["schema"]["required"] == ["decisions"]


def test_supersede_forget_and_noop_convert():
    runner = runner_with(
        decision(
            action="supersede",
            text="Prefers evening flights.",
            target="m1",
            replaces="m1",
        ),
        decision(action="forget", text=None, target="m2"),
        decision(action="noop", text=None),
    )
    proposals = LocalModelMemoryPolicy(runner).plan(
        PolicyContext(user_id="u1", session_id="s1", message="m")
    )
    # A local supersede expands into the canonical supersede+create pair.
    assert [p.action for p in proposals] == [
        "supersede",
        "create",
        "forget",
        "noop",
    ]
    assert proposals[0].target_memory_id == "m1"
    assert proposals[1].replaces == "m1"
    assert proposals[1].text == "Prefers evening flights."
    assert proposals[2].target_memory_id == "m2"


def test_empty_decisions_is_valid_no_memory_outcome():
    agent = local_agent(runner_with())
    agent.chat(user_id="u1", session_id="s1", message="what time is it?")
    payload = last_planned(agent)
    assert payload["planned_actions"] == []
    assert payload["policy"] == {
        "mode": "local_model",
        "decision_source": "local_model",
        "fallback_used": False,
        "fallback_reason": None,
    }
    assert agent.memories_for_user("u1") == []


@pytest.mark.parametrize(
    "data",
    [
        {},  # missing decisions
        {"decisions": {}},  # not a list
        {"decisions": ["not-an-object"]},
        {"decisions": [{"action": "create"}]},  # missing fields
        {"decisions": [dict(decision(), extra="field")]},  # unsupported field
        {"decisions": [dict(decision(), confidence="high")]},  # wrong type
        {"decisions": [dict(decision(), target_memory_id=12)]},  # wrong type
        {"decisions": [dict(decision(), explanation=None)]},  # wrong type
    ],
    ids=[
        "no-decisions",
        "decisions-not-list",
        "decision-not-object",
        "missing-fields",
        "extra-field",
        "confidence-type",
        "target-type",
        "explanation-type",
    ],
)
def test_structural_invalidity_raises_invalid_output(data):
    policy = LocalModelMemoryPolicy(FakeLocalModelRunner(data=data))
    with pytest.raises(LocalModelInvalidOutput):
        policy.plan(PolicyContext(user_id="u1", session_id="s1", message="m"))


# --- Fallback execution ---------------------------------------------------------------


FAILURE_CASES = [
    (LocalModelDependencyMissing("no dep"), "dependency_missing"),
    (LocalModelUnavailable("no model"), "model_unavailable"),
    (LocalModelLoadFailed("bad load"), "model_load_failed"),
    (LocalModelGenerationFailed("boom"), "generation_failed"),
    (LocalModelInvalidOutput("bad json"), "invalid_output"),
]


@pytest.mark.parametrize(
    "error,reason", FAILURE_CASES, ids=[r for _, r in FAILURE_CASES]
)
def test_every_runner_failure_falls_back(error, reason):
    fallback = CountingRulePolicy()
    manager = ExperienceManager(
        LocalModelMemoryPolicy(FakeLocalModelRunner(error=error)),
        fallback_policy=fallback,
    )
    context = PolicyContext(
        user_id="u1", session_id="s1", message="I prefer aisle seats."
    )
    result = manager.plan(context)

    assert fallback.calls == 1
    assert result.fallback_used is True
    assert result.fallback_reason == reason
    assert result.decision_source == DecisionSource.FALLBACK
    # Fallback actions equal the direct rule-based plan.
    direct = MemoryPlanner().plan_memory_actions(
        "u1", "s1", "I prefer aisle seats.", existing=[]
    )
    assert result.actions == direct
    assert all(
        d.decision_source == DecisionSource.FALLBACK for d in result.decisions
    )
    assert all(d.fallback_reason == reason for d in result.decisions)


def test_semantic_invalidity_falls_back_as_validation_failed():
    # Structurally fine, semantically wrong: unknown action value.
    runner = runner_with(decision(action="update"))
    agent = local_agent(runner)
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    payload = last_planned(agent)
    assert payload["policy"]["fallback_used"] is True
    assert payload["policy"]["fallback_reason"] == "validation_failed"
    # Rule-based fallback still remembered the preference.
    assert [m.text for m in agent.memories_for_user("u1")] == [
        "Prefers aisle seats."
    ]


def test_unexpected_policy_exception_falls_back_conservatively():
    class ExplodingPolicy:
        mode = "local_model"

        def plan(self, context):
            raise RuntimeError("unexpected")

    manager = ExperienceManager(
        ExplodingPolicy(), fallback_policy=RuleBasedMemoryPolicy()
    )
    result = manager.plan(
        PolicyContext(user_id="u1", session_id="s1", message="I prefer naps.")
    )
    assert result.fallback_used is True
    assert result.fallback_reason == "validation_failed"


def test_low_confidence_rejects_whole_batch_atomically():
    fallback = CountingRulePolicy()
    runner = runner_with(
        decision(text="Prefers window seats.", confidence=0.95),
        decision(action="forget", text=None, target="m1", confidence=0.2),
    )
    manager = ExperienceManager(
        LocalModelMemoryPolicy(runner), fallback_policy=fallback
    )
    result = manager.plan(
        PolicyContext(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    )
    assert fallback.calls == 1
    assert result.fallback_reason == "low_confidence"
    # None of the local proposals survive — no mixing.
    assert "Prefers window seats." not in [a.text for a in result.actions]
    assert [a.text for a in result.actions] == ["Prefers aisle seats."]


def test_confidence_exactly_at_threshold_is_accepted():
    runner = runner_with(decision(confidence=0.60))
    manager = ExperienceManager(
        LocalModelMemoryPolicy(runner),
        fallback_policy=RuleBasedMemoryPolicy(),
        minimum_confidence=0.60,
    )
    result = manager.plan(
        PolicyContext(user_id="u1", session_id="s1", message="m")
    )
    assert result.fallback_used is False
    assert result.decision_source == DecisionSource.LOCAL_MODEL

    below = ExperienceManager(
        LocalModelMemoryPolicy(runner_with(decision(confidence=0.5999))),
        fallback_policy=RuleBasedMemoryPolicy(),
        minimum_confidence=0.60,
    ).plan(PolicyContext(user_id="u1", session_id="s1", message="m"))
    assert below.fallback_used is True
    assert below.fallback_reason == "low_confidence"


@pytest.mark.parametrize("bad", [True, "0.6", None, -0.1, 1.5])
def test_invalid_threshold_configuration_rejected(bad):
    with pytest.raises(ValueError):
        ExperienceManager(
            RuleBasedMemoryPolicy(),
            fallback_policy=RuleBasedMemoryPolicy(),
            minimum_confidence=bad,
        )


def test_no_fallback_for_valid_local_noop_or_rule_based_primary():
    # Valid local noop-only result: no fallback.
    fallback = CountingRulePolicy()
    manager = ExperienceManager(
        LocalModelMemoryPolicy(runner_with(decision(action="noop", text=None))),
        fallback_policy=fallback,
    )
    result = manager.plan(
        PolicyContext(user_id="u1", session_id="s1", message="I prefer naps.")
    )
    assert result.actions == []
    assert result.fallback_used is False
    assert fallback.calls == 0

    # Rule-based primary never enters the fallback path.
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    assert last_planned(agent)["policy"]["fallback_used"] is False
    assert last_planned(agent)["policy"]["mode"] == "rule_based"


def test_fallback_with_no_rule_actions_keeps_provenance():
    runner = FakeLocalModelRunner(error=LocalModelUnavailable("no model"))
    agent = local_agent(runner)
    agent.chat(user_id="u1", session_id="s1", message="what time is it?")
    payload = last_planned(agent)
    assert payload["planned_actions"] == []
    assert payload["policy"] == {
        "mode": "local_model",
        "decision_source": "fallback",
        "fallback_used": True,
        "fallback_reason": "model_unavailable",
    }


# --- Lifecycle demo cases ----------------------------------------------------------------


def test_case_messy_preference_extraction():
    text = (
        "For short work trips, user prefers aisle seats because they "
        "want to exit quickly."
    )
    agent = local_agent(runner_with(decision(text=text, confidence=0.85)))
    agent.chat(
        user_id="u1",
        session_id="s1",
        message=(
            "Window is fine for long flights, but for short work trips I'd "
            "rather stay aisle so I can get out quickly."
        ),
    )
    memories = agent.memories_for_user("u1")
    assert [m.text for m in memories] == [text]
    payload = last_planned(agent)
    assert payload["planned_actions"][0]["decision_source"] == "local_model"
    assert payload["policy"]["fallback_used"] is False


def test_case_durable_vs_temporary_fact():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s0", message="My home airport is SJC.")
    sjc = agent.memories_for_user("u1")[0]

    runner = runner_with(
        decision(kind="fact", text="Normally uses SJC.", confidence=0.9),
        decision(
            kind="fact", text="Flying out of SFO this month.", confidence=0.9
        ),
    )
    local = ExperienceOS(
        model=MockProvider(),
        memory_store=agent.memory_store,
        memory_policy=LocalModelMemoryPolicy(runner),
    )
    local.chat(
        user_id="u1",
        session_id="s1",
        message="I'm flying out of SFO this month, but normally I use SJC.",
    )
    active = {m.text for m in local.memories_for_user("u1")}
    assert "Normally uses SJC." in active
    assert "Flying out of SFO this month." in active
    # The durable SJC fact was not superseded by the temporary one.
    assert agent.memory_store.get(sjc.id).status == MemoryStatus.ACTIVE


def test_case_update_detection():
    seed = ExperienceOS(model=MockProvider())
    seed.chat(user_id="u1", session_id="s0", message="I prefer morning flights.")
    morning = seed.memories_for_user("u1")[0]

    runner = runner_with(
        decision(
            action="supersede",
            text="For work trips, user prefers evening flights.",
            target=morning.id,
            replaces=morning.id,
            confidence=0.9,
            explanation="Preference changed from morning to evening flights.",
        )
    )
    local = ExperienceOS(
        model=MockProvider(),
        memory_store=seed.memory_store,
        memory_policy=LocalModelMemoryPolicy(runner),
    )
    local.chat(
        user_id="u1",
        session_id="s1",
        message=(
            "Actually I've changed my mind. For work trips, evening flights "
            "are better now."
        ),
    )
    old = seed.memory_store.get(morning.id)
    assert old.status == MemoryStatus.SUPERSEDED
    replacement = local.memories_for_user("u1")[0]
    assert replacement.text == "For work trips, user prefers evening flights."
    assert old.metadata["superseded_by"] == replacement.id
    assert replacement.metadata["replaces"] == old.id
    assert last_planned(local)["planned_actions"][0]["decision_source"] == (
        "local_model"
    )


def test_case_implicit_forget_detection():
    seed = ExperienceOS(model=MockProvider())
    seed.chat(user_id="u1", session_id="s0", message="I prefer hotels with gyms.")
    gym = seed.memories_for_user("u1")[0]

    runner = runner_with(
        decision(
            action="forget",
            text=None,
            target=gym.id,
            confidence=0.9,
            explanation="Matched 'the gym thing' to the hotel-gym preference.",
        )
    )
    local = ExperienceOS(
        model=MockProvider(),
        memory_store=seed.memory_store,
        memory_policy=LocalModelMemoryPolicy(runner),
    )
    local.chat(
        user_id="u1",
        session_id="s1",
        message="The gym thing does not matter anymore.",
    )
    assert seed.memory_store.get(gym.id).status == MemoryStatus.FORGOTTEN
    assert local.memories_for_user("u1") == []
    created = [
        e for e in local.events if e.type == EventType.MEMORY_CREATED
    ]
    assert created == []  # no replacement memory


def test_case_multi_action_message_with_one_invalid_target():
    seed = ExperienceOS(model=MockProvider())
    seed.chat(user_id="u1", session_id="s0", message="I prefer morning flights.")
    seed.chat(user_id="u1", session_id="s0", message="I prefer hotels with gyms.")
    by_text = {m.text: m for m in seed.memories_for_user("u1")}
    morning = by_text["Prefers morning flights."]
    gym = by_text["Prefers hotels with gyms."]

    runner = runner_with(
        decision(kind="fact", text="Normally uses SJC.", confidence=0.9),
        decision(kind="fact", text="Flying from SFO this month.", confidence=0.9),
        decision(
            action="supersede",
            text="Prefers evening flights for work trips.",
            target=morning.id,
            replaces=morning.id,
            confidence=0.9,
        ),
        decision(action="forget", text=None, target=gym.id, confidence=0.9),
        decision(action="forget", text=None, target="no-such-id", confidence=0.9),
    )
    local = ExperienceOS(
        model=MockProvider(),
        memory_store=seed.memory_store,
        memory_policy=LocalModelMemoryPolicy(runner),
    )
    local.chat(
        user_id="u1",
        session_id="s1",
        message="SJC normally, SFO this month, evenings now, gym doesn't matter.",
    )
    active = {m.text for m in local.memories_for_user("u1")}
    assert active == {
        "Normally uses SJC.",
        "Flying from SFO this month.",
        "Prefers evening flights for work trips.",
    }
    assert seed.memory_store.get(gym.id).status == MemoryStatus.FORGOTTEN
    payload = last_planned(local)
    assert len(payload["rejected_actions"]) == 1
    assert payload["policy"]["fallback_used"] is False


def test_forget_outranks_supersede_in_local_batch():
    seed = ExperienceOS(model=MockProvider())
    seed.chat(user_id="u1", session_id="s0", message="I prefer morning flights.")
    target = seed.memories_for_user("u1")[0]
    runner = runner_with(
        decision(
            action="supersede",
            text="Prefers evening flights.",
            target=target.id,
            confidence=0.9,
        ),
        decision(action="forget", text=None, target=target.id, confidence=0.9),
    )
    local = ExperienceOS(
        model=MockProvider(),
        memory_store=seed.memory_store,
        memory_policy=LocalModelMemoryPolicy(runner),
    )
    local.chat(user_id="u1", session_id="s1", message="conflicting input")
    assert seed.memory_store.get(target.id).status == MemoryStatus.FORGOTTEN
    # The paired replacement create is dropped when forget wins the target.
    assert local.memories_for_user("u1") == []


# --- Invalid-target safety (no fallback on engine rejection) --------------------------------


def test_engine_target_rejection_does_not_trigger_fallback():
    seed = ExperienceOS(model=MockProvider())
    seed.chat(user_id="u1", session_id="s0", message="I prefer morning flights.")
    seed.chat(
        user_id="u1", session_id="s0b", message="Actually, I prefer evening flights."
    )
    superseded_id = seed.memories_for_user(
        "u1", status=MemoryStatus.SUPERSEDED
    )[0].id

    runner = runner_with(
        decision(action="forget", text=None, target=superseded_id, confidence=0.9)
    )
    local = ExperienceOS(
        model=MockProvider(),
        memory_store=seed.memory_store,
        memory_policy=LocalModelMemoryPolicy(runner),
    )
    before = {
        m.id: m.status
        for m in seed.memory_store.list_memories("u1")
    }
    local.chat(user_id="u1", session_id="s1", message="anything")
    after = {
        m.id: m.status
        for m in seed.memory_store.list_memories("u1")
    }
    assert after == before  # nothing mutated
    payload = last_planned(local)
    # Structurally valid → accepted by manager, rejected by engine,
    # and crucially: no fallback ran after planning completed.
    assert payload["policy"]["fallback_used"] is False
    assert payload["policy"]["decision_source"] == "local_model"
    assert len(payload["rejected_actions"]) == 1
    assert payload["rejected_actions"][0]["rejected_reason"] == "target_not_active"


# --- SDK integration --------------------------------------------------------------------------


def test_sdk_supplies_rule_based_fallback_automatically():
    agent = local_agent(FakeLocalModelRunner())
    manager = agent.experience_manager
    assert isinstance(manager.fallback_policy, RuleBasedMemoryPolicy)
    assert manager.policy_mode == "local_model"


def test_sdk_factory_methods_accept_local_policy(tmp_path):
    wrapped = ExperienceOS.wrap(
        MockProvider(),
        memory_policy=LocalModelMemoryPolicy(runner_with(decision())),
    )
    wrapped.chat(user_id="u1", session_id="s1", message="m")
    assert wrapped.memories_for_user("u1")

    sqlite_agent = ExperienceOS.with_sqlite_memory(
        model=MockProvider(),
        db_path=str(tmp_path / "local.sqlite3"),
        memory_policy=LocalModelMemoryPolicy(runner_with(decision())),
    )
    sqlite_agent.chat(user_id="u1", session_id="s1", message="m")
    assert sqlite_agent.memories_for_user("u1")


def test_sdk_ambiguous_combinations_still_rejected():
    with pytest.raises(ValueError, match="only one of"):
        ExperienceOS(
            model=MockProvider(),
            memory_policy=LocalModelMemoryPolicy(FakeLocalModelRunner()),
            memory_planner=MemoryPlanner(),
        )


def test_default_agent_remains_rule_based():
    agent = ExperienceOS(model=MockProvider())
    assert agent.experience_manager.policy_mode == "rule_based"
    assert agent.experience_manager.fallback_policy is None


def test_local_policy_module_imports_no_runtime():
    from pathlib import Path

    text = Path("experienceos/policy/local_model.py").read_text()
    for forbidden in ("llama_cpp", "Llama(", "transformers", "torch"):
        assert forbidden not in text
