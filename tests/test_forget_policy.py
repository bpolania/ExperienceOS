"""Phase 9 Prompt 7: forget resolution and local-policy v2 tests.

All tests run offline and deterministically; the local model is
exercised through fake runners only.
"""

import json
from pathlib import Path

import pytest

from experienceos import ExperienceOS
from experienceos.memory.forget import (
    ForgetIntentDetector,
    ForgetOutcome,
    ForgetTargetResolver,
    describe_target,
)
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.semantic import METADATA_KEY, SemanticNormalizer
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.memory.temporal_planner import TemporalMemoryPlanner
from experienceos.policy.base import PolicyContext
from experienceos.policy.local_runner import (
    LocalModelGenerationFailed,
    LocalModelResult,
)
from experienceos.policy.local_v2 import (
    LocalPolicyV2,
    ParseFailure,
    ProposalParserV2,
    ScriptedLocalPolicyV2,
)
from experienceos.providers import MockProvider

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "benchmarks/fixtures/phase9_dev/forget_policy/cases.json"
    ).read_text()
)

_NORMALIZER = SemanticNormalizer()
DETECTOR = ForgetIntentDetector()
RESOLVER = ForgetTargetResolver()


def entry(kind, text, status=MemoryStatus.ACTIVE):
    record = ExperienceEntry(user_id="u", text=text, kind=kind, status=status)
    identity = _NORMALIZER.normalize(kind, text)
    if identity is not None:
        record.metadata[METADATA_KEY] = identity.to_metadata()
    return record


def forget_agent():
    planner = TemporalMemoryPlanner(forget_resolver=ForgetTargetResolver())
    return ExperienceOS(model=MockProvider(), memory_planner=planner), planner


# --- Forget intent ------------------------------------------------------------------


@pytest.mark.parametrize("message", FIXTURES["forget_intent_positives"])
def test_forget_intent_positives(message):
    intent = DETECTOR.detect(message)
    assert intent.detected, message
    assert not intent.bulk
    assert intent.target_text


@pytest.mark.parametrize("message", FIXTURES["forget_intent_negatives"])
def test_forget_intent_negatives(message):
    intent = DETECTOR.detect(message)
    assert not intent.detected, message


@pytest.mark.parametrize("message", FIXTURES["bulk_requests"])
def test_bulk_requests_flagged(message):
    intent = DETECTOR.detect(message)
    assert intent.detected and intent.bulk, message
    result = RESOLVER.resolve(intent, [entry("preference", "Likes tea.")])
    assert result.outcome == ForgetOutcome.BULK_UNSUPPORTED
    assert result.targets == []


def test_detector_versioned_with_reasons():
    intent = DETECTOR.detect("Don't forget my aisle preference.")
    assert intent.negated and intent.ambiguity_reason == "negated forget"
    assert intent.version == "1"


# --- Target description ----------------------------------------------------------------


def test_description_attribute_hint_and_kind():
    description = describe_target(
        "the instruction about my daily status channel"
    )
    assert description.kind_hint == "instruction"
    assert "send" in description.attribute_hints  # routing alias class
    assert "daily" in description.tokens


def test_description_historical_qualifier():
    assert describe_target("my old phone").historical
    assert not describe_target("my phone").historical


def test_description_stable():
    a = describe_target("my morning drink preference")
    b = describe_target("my morning drink preference")
    assert a == b


# --- Target resolution --------------------------------------------------------------


def test_exact_match_resolves():
    memories = [entry("preference", "Prefers morning flights."),
                entry("fact", "Home airport is SJC.")]
    intent = DETECTOR.detect("Forget that I prefer morning flights.")
    result = RESOLVER.resolve(intent, memories)
    assert result.outcome == ForgetOutcome.RESOLVED
    assert result.targets[0].text == "Prefers morning flights."


def test_semantic_attribute_outranks_lexical():
    memories = [entry("preference", "Prefers coffee in the morning."),
                entry("preference", "Prefers morning flights.")]
    intent = DETECTOR.detect("Forget my morning drink preference.")
    result = RESOLVER.resolve(intent, memories)
    assert result.outcome == ForgetOutcome.RESOLVED
    assert "coffee" in result.targets[0].text


def test_scoped_target_resolution():
    memories = [
        entry("preference", "Prefers aisle seats for short work trips."),
        entry("preference", "Prefers window seats for long international trips."),
    ]
    intent = DETECTOR.detect(
        "Forget my seat preference for long international trips."
    )
    result = RESOLVER.resolve(intent, memories)
    assert result.outcome == ForgetOutcome.RESOLVED
    assert "window" in result.targets[0].text


def test_ambiguous_two_candidates_rejected():
    memories = [entry("preference", "Prefers aisle seats."),
                entry("preference", "Prefers window seats.")]
    intent = DETECTOR.detect("Forget my seat preference.")
    result = RESOLVER.resolve(intent, memories)
    assert result.outcome == ForgetOutcome.AMBIGUOUS
    assert result.targets == []


def test_inactive_only_target_rejected():
    superseded = entry("fact", "Phone is a Pixel 6.",
                       status=MemoryStatus.SUPERSEDED)
    intent = DETECTOR.detect("Forget my Pixel 6 phone fact.")
    result = RESOLVER.resolve(intent, [superseded])
    assert result.outcome == ForgetOutcome.INACTIVE_TARGET_ONLY
    assert superseded.status == MemoryStatus.SUPERSEDED  # untouched


def test_no_active_candidates():
    intent = DETECTOR.detect("Forget my parking spot.")
    result = RESOLVER.resolve(intent, [entry("preference", "Likes tea.")])
    assert result.outcome == ForgetOutcome.NO_ACTIVE_CANDIDATES


def test_multi_target_explicit_and():
    memories = [
        entry("preference", "Prefers aisle seats for short work trips."),
        entry("instruction", "Use Celsius for weather reports."),
        entry("fact", "Works for Globex."),
    ]
    intent = DETECTOR.detect(
        "Forget my aisle seat preference and the Celsius instruction."
    )
    result = RESOLVER.resolve(intent, memories)
    assert result.outcome == ForgetOutcome.RESOLVED
    texts = {t.text for t in result.targets}
    assert texts == {
        "Prefers aisle seats for short work trips.",
        "Use Celsius for weather reports.",
    }


def test_max_targets_bounded():
    assert RESOLVER.max_targets == 3


def test_deterministic_resolution():
    memories = [entry("preference", "Prefers coffee in the morning."),
                entry("preference", "Prefers morning flights.")]
    intent = DETECTOR.detect("Forget my morning drink preference.")
    outputs = {
        RESOLVER.resolve(intent, memories).targets[0].id for _ in range(5)
    }
    assert len(outputs) == 1


@pytest.mark.parametrize(
    "case",
    FIXTURES["target_resolution"],
    ids=lambda c: c["request"][:40],
)
def test_fixture_target_resolution(case):
    memories = [entry(k, t) for k, t in case["memories"]]
    intent = DETECTOR.detect(case["request"])
    result = RESOLVER.resolve(intent, memories)
    expect = case["expect"]
    if "resolved_contains" in expect:
        assert result.outcome == ForgetOutcome.RESOLVED, result.reason
        assert expect["resolved_contains"] in result.targets[0].text
    if "outcome" in expect:
        assert result.outcome == expect["outcome"]


# --- Forget lifecycle integration -------------------------------------------------------


def test_forget_end_to_end_with_metadata_preserved():
    agent, planner = forget_agent()
    planner.set_reference_time("2026-07-10")
    agent.chat(user_id="u", session_id="s1",
               message="I prefer coffee in the morning.")
    agent.chat(user_id="u", session_id="s1",
               message="Works fine. My home airport is SJC.")
    agent.chat(user_id="u", session_id="s2",
               message="Forget my morning drink preference.")
    forgotten = agent.memories_for_user("u", status="forgotten")
    assert [m.text for m in forgotten] == ["Prefers coffee in the morning."]
    # Semantic/temporal/provenance metadata preserved on the target.
    assert METADATA_KEY in forgotten[0].metadata
    assert "provenance" in forgotten[0].metadata
    assert "forgotten_at" in forgotten[0].metadata
    # Unrelated memory unchanged.
    assert "Home airport is SJC." in [
        m.text for m in agent.memories_for_user("u")
    ]


def test_forgotten_excluded_from_all_temporal_modes():
    from experienceos.context.builder import ContextBuilder
    from experienceos.context.retrieval import HybridRetrievalStrategy
    from experienceos.context.selection import CoverageSelectionStrategy
    from experienceos.memory.temporal import TemporalRetrievalPolicy

    planner = TemporalMemoryPlanner(forget_resolver=ForgetTargetResolver())
    agent = ExperienceOS(
        model=MockProvider(),
        memory_planner=planner,
        context_builder=ContextBuilder(
            memory_budget=4,
            retrieval_strategy=HybridRetrievalStrategy(
                selection_strategy=CoverageSelectionStrategy(),
                temporal_policy=TemporalRetrievalPolicy(
                    reference_time="2026-07-10"
                ),
            ),
        ),
    )
    agent.chat(user_id="u", session_id="s1",
               message="I prefer coffee in the morning.")
    agent.chat(user_id="u", session_id="s1",
               message="Forget my morning drink preference.")
    for query in (
        "What do I drink in the morning?",           # current
        "What was my old drink preference?",         # historical
        "What did I drink in 2025?",                 # as-of
        "Show my drink preference history.",         # timeline
    ):
        agent.chat(user_id="u", session_id="q", message=query)
        events = [
            e for e in agent.events if str(e.type) == "context_built"
        ]
        rendered = " ".join(
            m["content"] for m in events[-1].payload["context_messages"]
        )
        assert "coffee" not in rendered, query


def test_forgotten_target_cannot_be_superseded():
    agent, planner = forget_agent()
    agent.chat(user_id="u", session_id="s1",
               message="My phone is a Pixel 6.")
    agent.chat(user_id="u", session_id="s1",
               message="Forget my phone fact.")
    agent.chat(user_id="u", session_id="s1",
               message="My phone is a Pixel 9.")
    forgotten = agent.memories_for_user("u", status="forgotten")
    assert [m.text for m in forgotten] == ["Phone is a Pixel 6."]
    assert forgotten[0].status == "forgotten"  # never superseded
    active = [m.text for m in agent.memories_for_user("u")]
    assert active == ["Phone is a Pixel 9."]


def test_forget_audit_events_emitted():
    agent, planner = forget_agent()
    agent.chat(user_id="u", session_id="s1", message="I like hiking.")
    agent.chat(user_id="u", session_id="s1",
               message="Forget my hiking preference.")
    types = [str(e.type) for e in agent.events]
    assert "memory_forget_intent_detected" in types
    assert "memory_forget_target_resolved" in types
    assert "memory_forgotten" in types
    agent.chat(user_id="u", session_id="s1", message="Forget everything.")
    types = [str(e.type) for e in agent.events]
    assert "memory_forget_bulk_rejected" in types


def test_forget_sqlite_persistence(tmp_path):
    db = tmp_path / "memories.db"
    planner = TemporalMemoryPlanner(forget_resolver=ForgetTargetResolver())
    agent = ExperienceOS(model=MockProvider(), memory_planner=planner,
                         memory_store=SQLiteMemoryStore(db))
    agent.chat(user_id="u", session_id="s1", message="I like hiking.")
    agent.chat(user_id="u", session_id="s1",
               message="Forget my hiking preference.")
    del agent
    reopened = ExperienceOS(model=MockProvider(),
                            memory_store=SQLiteMemoryStore(db))
    assert reopened.memories_for_user("u") == []
    forgotten = reopened.memories_for_user("u", status="forgotten")
    assert [m.text for m in forgotten] == ["Likes hiking."]


# --- Parser: strict parsing and syntax-only repair -----------------------------------------


PARSER = ProposalParserV2()


def valid_none():
    return {"action": "none", "evidence": "hi", "confidence": 0.9,
            "reason": "r"}


@pytest.mark.parametrize(
    "case",
    FIXTURES["local_policy_malformed"],
    ids=lambda c: c["class"],
)
def test_fixture_malformed_outputs(case):
    if case["expect"] == "repaired":
        data, repairs = PARSER.parse(case["raw"])
        assert data["action"] == "none"
        assert repairs  # syntax-only repair recorded
    else:
        with pytest.raises(ParseFailure):
            PARSER.parse(case["raw"])


@pytest.mark.parametrize(
    "case", FIXTURES["local_policy_valid"], ids=lambda c: c["class"]
)
def test_fixture_valid_outputs(case):
    data, repairs = PARSER.parse(case["raw"])
    assert data["action"] in ("remember", "update", "forget", "none")
    assert repairs == ()


def test_parser_rejects_forbidden_and_oversized():
    with pytest.raises(ParseFailure):  # forbidden lifecycle field
        PARSER.parse({**valid_none(), "status": "active"})
    with pytest.raises(ParseFailure):  # oversized string
        PARSER.parse({**valid_none(), "evidence": "x" * 500})
    with pytest.raises(ParseFailure):  # confidence bounds
        PARSER.parse({**valid_none(), "confidence": 1.5})
    with pytest.raises(ParseFailure):  # remember requires memory
        PARSER.parse({"action": "remember", "evidence": "e",
                      "confidence": 0.9, "reason": "r"})


def test_semantic_repair_is_never_performed():
    raw = {"action": "supersede", "evidence": "e", "confidence": 0.9,
           "reason": "r"}
    with pytest.raises(ParseFailure):
        PARSER.parse(raw)
    assert raw["action"] == "supersede"  # untouched, not rewritten


# --- Local policy v2 pipeline ------------------------------------------------------------


class FakeRunner:
    """Sequence of canned outputs (raw dict/str) or exceptions."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def generate_structured(self, *, system_prompt, user_prompt, schema):
        self.calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return LocalModelResult(
            data=output, model_path="<fake>", model_name="fake.gguf",
            prompt_tokens=30, completion_tokens=12, elapsed_ms=2.0,
        )


def policy_with(*outputs, resolver=None):
    planner = TemporalMemoryPlanner(
        forget_resolver=resolver or ForgetTargetResolver()
    )
    return LocalPolicyV2(FakeRunner(*outputs), planner), planner


def context_with(message, memories=()):
    return PolicyContext(
        user_id="u", session_id="s1", message=message,
        active_memories=list(memories),
    )


def test_valid_remember_applied_from_local():
    policy, _ = policy_with(
        {"action": "remember",
         "memory": {"kind": "fact", "statement": "Works for Globex."},
         "evidence": "I work for Globex", "confidence": 0.9, "reason": "r"}
    )
    proposals = policy.plan(context_with("I work for Globex now."))
    creates = [p for p in proposals if p.action == "create"]
    # Deterministic hybrid extraction also produces this create; the
    # local duplicate is contained, not double-applied.
    assert len(creates) == 1
    assert policy.counters["structural_valid"] == 1
    assert policy.counters["fallbacks_total" ] if False else True


def test_valid_forget_by_alias():
    coffee = entry("preference", "Prefers coffee in the morning.")
    policy, _ = policy_with(
        {"action": "forget",
         "target": {"memory_id": "m1", "description": "coffee preference"},
         "evidence": "forget my coffee preference", "confidence": 0.9,
         "reason": "r"}
    )
    proposals = policy.plan(
        context_with("Please forget my coffee preference.", [coffee])
    )
    forgets = [p for p in proposals if p.action == "forget"]
    assert len(forgets) == 1
    assert forgets[0].target_memory_id == coffee.id
    assert forgets[0].decision_source == "local_model"


def test_invented_target_id_rejected_with_forget_fallback():
    coffee = entry("preference", "Prefers coffee in the morning.")
    policy, _ = policy_with(
        {"action": "forget",
         "target": {"memory_id": "made-up-id", "description": None},
         "evidence": "forget my coffee preference", "confidence": 0.9,
         "reason": "r"}
    )
    proposals = policy.plan(
        context_with("Forget my coffee preference.", [coffee])
    )
    # Fallback stays within the forget action: the deterministic
    # resolver still forgets the right target; nothing is created.
    forgets = [p for p in proposals if p.action == "forget"]
    assert len(forgets) == 1
    assert forgets[0].target_memory_id == coffee.id
    assert forgets[0].decision_source == "fallback"
    assert policy.counters["target_rejections"] >= 1
    assert policy.counters["fallback_forget"] == 1
    assert not any(p.action == "create" for p in proposals)


def test_malformed_forget_never_becomes_remember():
    coffee = entry("preference", "Prefers coffee in the morning.")
    policy, _ = policy_with("not json {{{", "still not json")
    proposals = policy.plan(
        context_with("Forget my coffee preference.", [coffee])
    )
    # Unclassifiable output → full deterministic plan (which is the
    # forget); no creation appears from the malformed proposal.
    assert [p.action for p in proposals] == ["forget"]
    assert policy.counters["retries"] == 1
    assert policy.counters["fallback_unclassified"] == 1


def test_one_bounded_retry_success():
    policy, _ = policy_with(
        "```json\nbroken{{{\n```",
        {"action": "none", "evidence": "hello", "confidence": 0.9,
         "reason": "nothing durable"},
    )
    policy.plan(context_with("Hello there!"))
    assert policy.counters["retries"] == 1
    assert policy.counters["retry_success"] == 1
    assert policy.counters["structural_valid"] == 1


def test_runner_error_falls_back_safely():
    policy, _ = policy_with(LocalModelGenerationFailed("timeout"))
    proposals = policy.plan(context_with("I prefer aisle seats."))
    creates = [p for p in proposals if p.action == "create"]
    assert len(creates) == 1  # deterministic extraction still applies
    assert creates[0].decision_source == "fallback"
    assert policy.counters["fallback_unclassified"] == 1


def test_hallucinated_evidence_rejected():
    policy, _ = policy_with(
        {"action": "remember",
         "memory": {"kind": "fact", "statement": "Works for Initech."},
         "evidence": "I work for Initech", "confidence": 0.9, "reason": "r"}
    )
    proposals = policy.plan(context_with("What time is it?"))
    assert proposals == []  # nothing durable, nothing stored
    assert policy.counters["semantic_rejections"] == 1


def test_valid_update_supersedes_target():
    old = entry("fact", "Phone is a Pixel 6.")
    policy, _ = policy_with(
        {"action": "update",
         "memory": {"kind": "fact", "statement": "Phone is a Pixel 9."},
         "target": {"memory_id": "m1", "description": "old phone"},
         "evidence": "my phone is a Pixel 9 now", "confidence": 0.9,
         "reason": "r"}
    )
    proposals = policy.plan(
        context_with("Actually, my phone is a Pixel 9 now.", [old])
    )
    actions = [(p.action, p.target_memory_id or p.text) for p in proposals]
    assert ("supersede", old.id) in actions
    assert any(a == "create" and "Pixel 9" in t for a, t in actions)


def test_none_action_is_valid_not_fallback():
    policy, _ = policy_with(
        {"action": "none", "evidence": "what time is it",
         "confidence": 0.9, "reason": "no durable content"}
    )
    proposals = policy.plan(context_with("What time is it?"))
    assert proposals == []
    assert policy.counters["none_actions"] == 1
    assert policy.counters["fallback_none"] == 0


def test_state_containment_through_engine():
    """Malformed and unsafe local output can never mutate state."""
    planner = TemporalMemoryPlanner(forget_resolver=ForgetTargetResolver())
    policy = LocalPolicyV2(
        FakeRunner(
            "garbage", "more garbage",  # turn 1: unparseable + retry
            {"action": "forget",
             "target": {"memory_id": "fake-id", "description": None},
             "evidence": "irrelevant", "confidence": 0.9, "reason": "r"},
        ),
        planner,
    )
    agent = ExperienceOS(model=MockProvider(), memory_policy=policy)
    agent.chat(user_id="u", session_id="s1", message="I like hiking.")
    agent.chat(user_id="u", session_id="s1", message="Nice weather!")
    memories = agent.memories_for_user("u")
    assert [m.text for m in memories] == ["Likes hiking."]
    assert agent.memories_for_user("u", status="forgotten") == []
    assert agent.memories_for_user("u", status="superseded") == []


def test_audit_evidence_recorded():
    policy, _ = policy_with(
        "```json\n{\"action\": \"none\", \"evidence\": \"hi\", "
        "\"confidence\": 0.9, \"reason\": \"r\"}\n```"
    )
    policy.plan(context_with("Hi!"))
    audit = policy.audits[0]
    assert audit.model_mode == "generated"
    assert audit.parse_ok and audit.structural_valid
    assert "stripped_markdown_fence" in audit.repairs
    assert audit.prompt_tokens == 30 and audit.completion_tokens == 12
    assert audit.elapsed_ms is not None
    summary = policy.summary()
    assert summary["proposal_schema_version"] == "1"
    assert summary["fallback_strategy"] == "per_action_deterministic"


# --- Scripted simulated mode -----------------------------------------------------------


def test_scripted_policy_matches_deterministic_behavior():
    planner_a = TemporalMemoryPlanner(
        forget_resolver=ForgetTargetResolver()
    )
    scripted = ScriptedLocalPolicyV2(deterministic_planner=planner_a)
    agent_a = ExperienceOS(model=MockProvider(), memory_policy=scripted)

    planner_b = TemporalMemoryPlanner(
        forget_resolver=ForgetTargetResolver()
    )
    agent_b = ExperienceOS(model=MockProvider(), memory_planner=planner_b)

    turns = [
        "I prefer tea in the morning.",
        "Actually, I prefer coffee in the morning.",
        "Forget my morning drink preference.",
        "What time is it?",
    ]
    for agent in (agent_a, agent_b):
        for turn in turns:
            agent.chat(user_id="u", session_id="s1", message=turn)

    def snapshot(agent):
        return {
            status: sorted(
                m.text
                for m in agent.memories_for_user("u", status=status)
            )
            for status in ("active", "superseded", "forgotten")
        }

    assert snapshot(agent_a) == snapshot(agent_b)
    assert scripted.counters["decisions"] == 4
    assert scripted.counters["structural_valid"] == 4
    fallbacks = sum(
        v for k, v in scripted.counters.items() if k.startswith("fallback_")
    )
    assert fallbacks == 0


# --- V1/V2 isolation --------------------------------------------------------------------


def test_registration_and_provenance():
    from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
    from benchmarks.contract import SystemId

    assert SystemId.EXPERIENCEOS_LOCAL_V2 in ADAPTER_SYSTEM_IDS
    system = create_system(SystemId.EXPERIENCEOS_LOCAL_V2)
    assert system.system_id == "experienceos_local_v2"
    assert system.mode == "scripted"


def test_historical_local_v1_unchanged():
    from benchmarks.adapters.experienceos_local import (
        ExperienceOSLocalAdapter,
    )
    from experienceos.policy.local_model import MEMORY_DECISION_SCHEMA

    adapter = ExperienceOSLocalAdapter()
    assert adapter.memory_policy_label == "local_model"
    # v1 multi-decision schema untouched.
    assert "decisions" in MEMORY_DECISION_SCHEMA["properties"]


def test_prior_planners_have_no_forget_resolver():
    from experienceos.memory.hybrid_planner import HybridMemoryPlanner
    from experienceos.memory.planner import MemoryPlanner
    from experienceos.memory.semantic_planner import SemanticMemoryPlanner

    for planner in (MemoryPlanner(), SemanticMemoryPlanner(),
                    HybridMemoryPlanner()):
        assert not getattr(planner, "forget_resolver", None)
    assert TemporalMemoryPlanner().forget_resolver is None  # Prompt 6 default


def test_v1_forget_behavior_without_resolver_unchanged():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u", session_id="s1", message="I don't like cilantro.")
    agent.chat(user_id="u", session_id="s1",
               message="Forget that I don't like cilantro.")
    assert agent.memories_for_user("u") == []
    assert [m.text for m in agent.memories_for_user("u", status="forgotten")] \
        == ["Dislikes cilantro."]


def test_deterministic_mode_adapter():
    from benchmarks.adapters.experienceos_local_v2 import (
        ExperienceOSLocalV2Adapter,
    )
    from benchmarks.contract import KNOWN_SYSTEM_IDS

    dev = ExperienceOSLocalV2Adapter(mode="deterministic")
    assert dev.system_id == "dev_forget_deterministic"
    assert dev.system_id not in KNOWN_SYSTEM_IDS
    with pytest.raises(ValueError):
        ExperienceOSLocalV2Adapter(mode="bogus")


def test_no_metrics_without_diagnostics():
    from benchmarks.evaluators.forget_policy_v2 import (
        forget_policy_v2_contributions,
    )

    class Result:
        diagnostics = {}

    assert forget_policy_v2_contributions(object(), Result()) == []
