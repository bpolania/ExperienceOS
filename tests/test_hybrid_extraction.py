"""Phase 9 Prompt 3: hybrid conversational memory extraction tests.

All tests run offline and deterministically: no network, no real local
model. The optional local extractor is exercised through a fake runner
implementing the LocalModelRunner seam.
"""

import json
from pathlib import Path

import pytest

from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory.extraction import (
    CandidateValidator,
    DeterministicConversationalExtractor,
    DurabilityGate,
    ExtractionRequest,
    MemoryCandidate,
)
from experienceos.memory.hybrid_planner import HybridMemoryPlanner
from experienceos.memory.schema import MemoryKind
from experienceos.memory.semantic import METADATA_KEY
from experienceos.memory.semantic_planner import SemanticMemoryPlanner
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.policy.local_extractor import LocalModelCandidateExtractor
from experienceos.policy.local_runner import (
    LocalModelGenerationFailed,
    LocalModelResult,
)
from experienceos.providers import MockProvider

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "benchmarks/fixtures/phase9_dev/hybrid_extraction/cases.json"
    ).read_text()
)


def agent_with_planner(planner=None, **kwargs):
    return ExperienceOS(
        model=MockProvider(),
        memory_planner=planner or HybridMemoryPlanner(),
        **kwargs,
    )


def chat(agent, *messages, user_id="u", session_id="s1"):
    for message in messages:
        agent.chat(user_id=user_id, session_id=session_id, message=message)


def active_texts(agent, user_id="u"):
    return [m.text for m in agent.memories_for_user(user_id)]


def extract(text, **request_overrides):
    request = ExtractionRequest(
        source_text=text, source_ref="s1:1", **request_overrides
    )
    return DeterministicConversationalExtractor().extract(request), request


def validate(candidate, source, gate=None, **request_overrides):
    request = ExtractionRequest(
        source_text=source, source_ref="s1:1", **request_overrides
    )
    gate = gate or DurabilityGate().assess(source)
    return CandidateValidator().validate(candidate, request, gate)


# --- Durability gate ---------------------------------------------------------


def test_gate_passes_durable_fact():
    decision = DurabilityGate().assess(
        "My daughter's soccer practice is on Thursdays."
    )
    assert decision.passed
    assert decision.matched_cues


def test_gate_passes_durable_preference():
    assert DurabilityGate().assess(
        "For international trips, I usually prefer window seats."
    ).passed


def test_gate_passes_recurring_instruction():
    assert DurabilityGate().assess(
        "Use Celsius whenever you give me weather."
    ).passed


@pytest.mark.parametrize(
    "message,reason",
    [
        ("Hi there!", "greeting"),
        ("Thanks.", "greeting"),
        ("Book the cheapest flight today.", "transient_request"),
        ("What time is it?", "question"),
        ("Maybe I'll move to Seattle someday.", "hypothetical"),
        ("Suppose I owned a Pixel 9.", "hypothetical"),
        ("My friend said, 'I work for Globex.'", "quoted_third_party"),
        ("For this answer only, use a table.", "current_turn_only"),
        ("For this role-play, pretend I speak Klingon.", "hypothetical"),
    ],
)
def test_gate_rejects_non_durable(message, reason):
    decision = DurabilityGate().assess(message)
    assert not decision.passed
    assert decision.reason == reason


def test_gate_rejects_ambiguous_statement_safely():
    decision = DurabilityGate().assess("The weather was nice yesterday.")
    assert not decision.passed
    assert decision.reason == "no_durable_cues"


def test_gate_remember_overrides_transient_shape():
    # "Tell me..." rejects, but explicit remember language passes.
    assert not DurabilityGate().assess("Tell me a joke.").passed
    assert DurabilityGate().assess(
        "Tell me the weather in Celsius from now on, remember that."
    ).passed


def test_gate_records_reason_and_version():
    decision = DurabilityGate().assess("What time is it?")
    assert decision.version == "1"
    assert decision.reason == "question"
    passed = DurabilityGate().assess("I work for Globex.")
    assert passed.version == "1"
    assert 0.0 < passed.confidence <= 1.0


# --- Deterministic offline extractor ------------------------------------------


def statements(result):
    return [c.statement for c in result.candidates]


def test_extracts_possessive_subject():
    result, _ = extract("My daughter's soccer practice moved to Thursday.")
    assert statements(result) == [
        "Daughter's soccer practice is on Thursday."
    ]
    candidate = result.candidates[0]
    assert candidate.subject == "daughter"
    assert candidate.kind == MemoryKind.FACT


def test_extracts_goes_to_affiliation():
    result, _ = extract("My son goes to Lincoln Middle School.")
    assert statements(result) == ["Son goes to Lincoln Middle School."]
    assert result.candidates[0].attribute == "attends"


def test_extracts_works_for_employer():
    result, _ = extract("I work for Globex now.")
    assert statements(result) == ["Works for Globex."]


def test_extracts_speaks_multi_value_split():
    result, _ = extract("I speak Spanish and Portuguese.")
    assert statements(result) == ["Speaks Spanish.", "Speaks Portuguese."]


def test_extracts_leading_clause_scope():
    result, _ = extract(
        "For long international trips, I usually go with a window seat."
    )
    assert statements(result) == [
        "Prefers window seat for long international trips."
    ]
    assert result.candidates[0].scope == "long_international_trips"


def test_extracts_recurring_schedule():
    result, _ = extract("Soccer practice moved to Thursdays.")
    assert statements(result) == ["Soccer practice is on Thursdays."]


def test_extracts_conversational_preference():
    result, _ = extract("Coffee is usually what I drink in the morning.")
    assert statements(result) == ["Prefers coffee in the morning."]


def test_extracts_current_state_correction():
    result, _ = extract("I changed jobs and now work for Globex.")
    assert statements(result) == ["Works for Globex."]


def test_extracts_multiple_candidates_in_one_turn():
    result, _ = extract(
        "I work for Globex now, and I speak Spanish and Portuguese."
    )
    assert statements(result) == [
        "Works for Globex.",
        "Speaks Spanish.",
        "Speaks Portuguese.",
    ]


def test_candidate_count_is_bounded():
    result, request = extract(
        "I speak Spanish, Portuguese, French and Italian.",
        max_candidates=2,
    )
    assert len(result.candidates) == 2
    assert request.max_candidates == 2


def test_extraction_order_is_deterministic():
    text = "I work for Globex now, and I speak Spanish and Portuguese."
    first, _ = extract(text)
    second, _ = extract(text)
    assert statements(first) == statements(second)


def test_pronoun_resolves_only_with_unambiguous_antecedent():
    result, _ = extract(
        "She goes to Lincoln Middle School.",
        recent_context=("My daughter's soccer practice is on Thursdays.",),
    )
    assert statements(result) == ["Daughter goes to Lincoln Middle School."]
    assert result.candidates[0].qualifiers["coreference"] == {
        "pronoun": "she",
        "antecedent": "daughter",
    }
    # No antecedent → no candidate.
    bare, _ = extract("She goes to Lincoln Middle School.")
    assert bare.candidates == ()
    # Two relations → ambiguous → no candidate.
    ambiguous, _ = extract(
        "She goes to Lincoln Middle School.",
        recent_context=("My daughter and my son share a school run.",),
    )
    assert ambiguous.candidates == ()


def test_extractor_does_not_invent_unstated_values():
    result, _ = extract("I upgraded my phone.")
    assert result.candidates == ()
    result, _ = extract("She changed schools.")
    assert result.candidates == ()


# --- Grounding validator --------------------------------------------------------


def test_grounded_value_accepted():
    result, _ = extract("I work for Globex now.")
    outcome = validate(result.candidates[0], "I work for Globex now.")
    assert outcome.accepted
    assert outcome.stage == "accepted"


def test_absent_value_rejected():
    candidate = MemoryCandidate(
        kind=MemoryKind.FACT,
        statement="Works for Initech.",
        evidence="I work for Globex now.",
        attribute="employer",
        value="Initech",
    )
    outcome = validate(candidate, "I work for Globex now.")
    assert not outcome.accepted
    assert outcome.stage == "grounding"
    assert "not grounded" in outcome.reason


def test_wrong_subject_rejected():
    candidate = MemoryCandidate(
        kind=MemoryKind.FACT,
        statement="Manager goes to Lincoln Middle School.",
        evidence="My son goes to Lincoln Middle School.",
        subject="manager",
        attribute="attends",
        value="Lincoln Middle School",
    )
    outcome = validate(candidate, "My son goes to Lincoln Middle School.")
    assert not outcome.accepted
    assert "subject" in outcome.reason


def test_invented_scope_qualifier_rejected():
    candidate = MemoryCandidate(
        kind=MemoryKind.PREFERENCE,
        statement="Prefers window seats for red-eye flights.",
        evidence="I usually go with a window seat.",
        attribute="preference",
        value="window seat",
        scope="red_eye_flights",
    )
    outcome = validate(candidate, "I usually go with a window seat.")
    assert not outcome.accepted
    assert "scope" in outcome.reason


def test_negated_assertion_rejected():
    candidate = MemoryCandidate(
        kind=MemoryKind.PREFERENCE,
        statement="Prefers window seats.",
        evidence="I never choose window seats.",
        attribute="preference",
        value="window seats",
    )
    gate = DurabilityGate().assess("I never choose window seats.")
    outcome = validate(
        candidate, "I never choose window seats.", gate=gate
    )
    assert not outcome.accepted


def test_quoted_evidence_rejected():
    source = 'My friend said, "I work for Globex, you know."'
    candidate = MemoryCandidate(
        kind=MemoryKind.FACT,
        statement="Works for Globex.",
        evidence="I work for Globex",
        attribute="employer",
        value="Globex",
    )
    passing_gate = DurabilityGate().assess("I work for Globex.")
    outcome = validate(candidate, source, gate=passing_gate)
    assert not outcome.accepted
    assert "quoted" in outcome.reason


def test_malformed_candidate_rejected():
    candidate = MemoryCandidate(
        kind=MemoryKind.FACT, statement="", evidence="I work for Globex."
    )
    outcome = validate(candidate, "I work for Globex.")
    assert not outcome.accepted
    assert outcome.stage == "schema"


def test_unsupported_kind_rejected():
    candidate = MemoryCandidate(
        kind="credential",
        statement="API key is X.",
        evidence="API key is X.",
    )
    outcome = validate(candidate, "API key is X.")
    assert not outcome.accepted
    assert "unsupported kind" in outcome.reason


def test_gate_rejection_blocks_durability():
    result, _ = extract("I work for Globex now.")
    rejected_gate = DurabilityGate().assess("What time is it?")
    outcome = validate(
        result.candidates[0], "I work for Globex now.", gate=rejected_gate
    )
    assert not outcome.accepted
    assert outcome.stage == "durability"


def test_evidence_must_be_source_span():
    candidate = MemoryCandidate(
        kind=MemoryKind.FACT,
        statement="Works for Globex.",
        evidence="I work for Globex now.",
        attribute="employer",
        value="Globex",
    )
    outcome = validate(candidate, "Something entirely different.")
    assert not outcome.accepted
    assert "span" in outcome.reason


# --- Lifecycle integration ----------------------------------------------------


def test_accepted_candidate_becomes_active_memory_with_metadata():
    agent = agent_with_planner()
    chat(agent, "I work for Globex now.")
    memories = agent.memories_for_user("u")
    assert [m.text for m in memories] == ["Works for Globex."]
    entry = memories[0]
    assert entry.metadata[METADATA_KEY]["attribute"] == "employer"
    assert entry.metadata["extraction"]["extractor"] == (
        "deterministic_conversational"
    )
    assert entry.metadata["extraction"]["gate_version"] == "1"


def test_rejected_gate_creates_no_memory():
    agent = agent_with_planner()
    chat(agent, "Maybe I'll move to Seattle someday.", "What time is it?")
    assert active_texts(agent) == []


def test_duplicate_auxiliary_candidate_creates_no_duplicate():
    agent = agent_with_planner()
    chat(agent, "I work for Globex now.", "I joined Globex recently.")
    assert active_texts(agent) == ["Works for Globex."]


def test_deterministic_and_auxiliary_duplicate_collapse():
    # v1 handles "My employer is Globex." → "Employer is Globex.";
    # the auxiliary "Works for Globex." is a semantic duplicate.
    agent = agent_with_planner()
    chat(agent, "My employer is Globex.", "I work for Globex now.")
    texts = active_texts(agent)
    assert texts == ["Employer is Globex."]


def test_candidate_flows_through_manager_and_engine():
    agent = agent_with_planner()
    chat(agent, "I speak Spanish and Portuguese.")
    planned = [
        e for e in agent.events
        if e.type == EventType.MEMORY_ACTION_PLANNED
    ]
    assert planned, "candidate creates must pass through planning events"
    created = [
        e for e in agent.events if e.type == EventType.MEMORY_CREATED
    ]
    assert len(created) == 2


def test_extraction_audit_events_emitted():
    agent = agent_with_planner()
    chat(agent, "I work for Globex now.", "What time is it?")
    types = [str(e.type) for e in agent.events]
    assert EventType.MEMORY_EXTRACTION_GATE_PASSED in types
    assert EventType.MEMORY_EXTRACTION_GATE_REJECTED in types
    assert EventType.MEMORY_EXTRACTION_INVOKED in types
    assert EventType.MEMORY_CANDIDATE_PROPOSED in types
    assert EventType.MEMORY_CANDIDATE_ACCEPTED in types
    accepted = next(
        e for e in agent.events
        if e.type == EventType.MEMORY_CANDIDATE_ACCEPTED
    )
    assert accepted.payload["attribute"] == "employer"
    assert "source_ref" in accepted.payload


def test_sqlite_restart_preserves_candidate_and_provenance(tmp_path):
    db = tmp_path / "memories.db"
    agent = agent_with_planner(memory_store=SQLiteMemoryStore(db))
    chat(agent, "My daughter's soccer practice moved to Thursday.")
    del agent

    reopened = ExperienceOS(
        model=MockProvider(), memory_store=SQLiteMemoryStore(db)
    )
    memories = reopened.memories_for_user("u")
    assert [m.text for m in memories] == [
        "Daughter's soccer practice is on Thursday."
    ]
    assert memories[0].metadata["extraction"]["source_ref"] == "s1:1"
    assert METADATA_KEY in memories[0].metadata


def test_forgotten_and_superseded_stay_excluded():
    agent = agent_with_planner()
    chat(
        agent,
        "I work for Globex now.",
        "I prefer morning flights.",
        "Forget that I prefer morning flights.",
    )
    assert active_texts(agent) == ["Works for Globex."]
    forgotten = agent.memories_for_user("u", status="forgotten")
    assert [m.text for m in forgotten] == ["Prefers morning flights."]


def test_extractor_cannot_supersede_or_forget():
    planner = HybridMemoryPlanner()
    agent = agent_with_planner(planner)
    chat(agent, "I work for Globex now.", "I work for Initech now.")
    # Extraction-only strategy: conflicting employer facts COEXIST —
    # no supersede/forget action can originate from extraction.
    texts = active_texts(agent)
    assert sorted(texts) == ["Works for Globex.", "Works for Initech."]
    assert agent.memories_for_user("u", status="superseded") == []
    supersede_events = [
        e for e in agent.events if e.type == EventType.MEMORY_SUPERSEDED
    ]
    assert supersede_events == []


def test_failing_extractor_is_contained():
    class ExplodingExtractor:
        extractor_id = "exploding"
        extractor_version = "1"

        def extract(self, request):
            raise RuntimeError("boom")

    planner = HybridMemoryPlanner(extractor=ExplodingExtractor())
    agent = agent_with_planner(planner)
    chat(agent, "I work for Globex now.")
    assert active_texts(agent) == []  # no fabricated fallback memory
    assert planner.counters["extractor_failed_safe"] == 1
    failed = [
        e for e in agent.events
        if e.type == EventType.MEMORY_EXTRACTION_FAILED_SAFE
    ]
    assert failed and "boom" in failed[0].payload["reason"]


def test_per_candidate_validation_preserves_valid_siblings():
    class MixedExtractor:
        extractor_id = "mixed"
        extractor_version = "1"

        def extract(self, request):
            from experienceos.memory.extraction import ExtractionResult

            return ExtractionResult(
                candidates=(
                    MemoryCandidate(
                        kind="credential",  # invalid kind → schema reject
                        statement="API key is X.",
                        evidence=request.source_text,
                    ),
                    MemoryCandidate(
                        kind=MemoryKind.FACT,
                        statement="Works for Globex.",
                        evidence="I work for Globex now",
                        attribute="employer",
                        value="Globex",
                    ),
                ),
                extractor_id="mixed",
                extractor_version="1",
            )

    planner = HybridMemoryPlanner(extractor=MixedExtractor())
    agent = agent_with_planner(planner)
    chat(agent, "I work for Globex now, everyone.")
    assert active_texts(agent) == ["Works for Globex."]
    assert planner.counters["candidates_schema_rejected"] == 1
    assert planner.counters["candidates_accepted"] == 1


# --- V1/V2 isolation ------------------------------------------------------------


def test_v1_rules_do_not_invoke_hybrid_extraction():
    agent = ExperienceOS(model=MockProvider())
    chat(agent, "I work for Globex now.")
    assert active_texts(agent) == []  # v1 gap preserved exactly
    extraction_events = [
        e for e in agent.events
        if str(e.type).startswith("memory_extraction")
        or str(e.type).startswith("memory_candidate")
    ]
    assert extraction_events == []


def test_slots_v2_planner_unchanged_by_prompt3():
    agent = ExperienceOS(
        model=MockProvider(), memory_planner=SemanticMemoryPlanner()
    )
    chat(agent, "I work for Globex now.")
    assert active_texts(agent) == []  # extraction is NOT part of slots_v2


def test_hybrid_adapter_registration_and_provenance():
    from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
    from benchmarks.contract import SystemId

    assert (
        SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2
        == "experienceos_hybrid_extract_v2"
    )
    assert SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2 in ADAPTER_SYSTEM_IDS
    system = create_system(SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2)
    assert system.system_id == "experienceos_hybrid_extract_v2"
    assert "hybrid_extraction" in system.memory_policy_label


def test_hybrid_adapter_records_extraction_diagnostics_and_same_budget():
    from benchmarks.adapters.experienceos_hybrid_extract_v2 import (
        ExperienceOSHybridExtractV2Adapter,
    )
    from benchmarks.adapters.experienceos_rules import (
        ExperienceOSRulesAdapter,
    )
    from benchmarks.contract import case_from_dict

    case = case_from_dict(
        {
            "scenario_id": "synthetic-hybrid-001",
            "schema_version": "1",
            "title": "Synthetic",
            "category": "creation",
            "description": "Synthetic hybrid adapter test case.",
            "tags": ["domain:test"],
            "seed": 7,
            "context_budget": 4,
            "selection_k": 4,
            "turns": [],
            "current_message": "I work for Globex now.",
            "current_session_id": "s1",
            "expected": {"memory_actions": []},
            "evaluation_mode": "deterministic",
        }
    )
    hybrid = ExperienceOSHybridExtractV2Adapter()
    rules = ExperienceOSRulesAdapter()
    for system in (hybrid, rules):
        system.initialize(case)
        system.process_turn(0, "s1", "I work for Globex now.")
    # Same retrieval knobs — extraction is the only difference.
    assert hybrid.config.context_budget == rules.config.context_budget
    assert hybrid.config.selection_k == rules.config.selection_k
    assert hybrid.config.retrieval_description == (
        rules.config.retrieval_description
    )
    diagnostics = hybrid.diagnostics
    assert diagnostics["retrieval_strategy"] == "phase8_v1_unchanged"
    assert diagnostics["selection_strategy"] == "phase8_v1_unchanged"
    assert diagnostics["local_extractor_enabled"] is False
    counters = diagnostics["extraction_v2"]
    assert counters["extractor_invocations"] == 1
    assert counters["candidates_accepted"] == 1
    assert counters["durability_gate_version"] == "1"
    assert rules.diagnostics == {}  # v1 provenance unchanged
    assert hybrid.final_state().entries and not rules.final_state().entries


def test_hybrid_extractor_feeds_semantic_planner_safely():
    """Composition readiness: hybrid extraction + Prompt 2 planning.

    Private test configuration only — no combined benchmark system is
    registered in this prompt. The MRO makes SemanticMemoryPlanner's
    conflict pass run over HybridMemoryPlanner's rules+extraction
    output, so a conversational employer change supersedes cleanly.
    """

    class ComposedPlanner(SemanticMemoryPlanner, HybridMemoryPlanner):
        def __init__(self):
            HybridMemoryPlanner.__init__(self)
            SemanticMemoryPlanner.__init__(self, normalizer=self.normalizer)

    agent = ExperienceOS(
        model=MockProvider(), memory_planner=ComposedPlanner()
    )
    chat(agent, "I work for Globex now.", "I joined Initech recently.")
    assert active_texts(agent) == ["Works for Initech."]
    superseded = agent.memories_for_user("u", status="superseded")
    assert [m.text for m in superseded] == ["Works for Globex."]


def test_no_extraction_metrics_for_v1_results():
    from benchmarks.evaluators.extraction import extraction_contributions

    class Result:
        diagnostics = {}

    assert extraction_contributions(object(), Result()) == []


# --- Optional local extractor (fake runner; no real model) ------------------------


class FakeRunner:
    def __init__(self, data=None, error=None):
        self._data = data
        self._error = error

    def availability(self):
        raise AssertionError("extractor must not require availability probes")

    def generate_structured(self, *, system_prompt, user_prompt, schema):
        if self._error is not None:
            raise self._error
        return LocalModelResult(
            data=self._data,
            model_path="<fake>",
            model_name="fake.gguf",
            prompt_tokens=42,
            completion_tokens=17,
            elapsed_ms=1.5,
        )


def valid_payload():
    return {
        "candidates": [
            {
                "kind": "fact",
                "statement": "Works for Globex.",
                "evidence": "I now work for Globex.",
                "subject": "user",
                "attribute": "employer",
                "value": "Globex",
                "scope": "global",
                "confidence": 0.94,
            }
        ]
    }


def local_request():
    return ExtractionRequest(
        source_text="I now work for Globex.", source_ref="s1:1"
    )


def test_local_extractor_valid_structured_response():
    extractor = LocalModelCandidateExtractor(FakeRunner(valid_payload()))
    result = extractor.extract(local_request())
    assert result.status == "proposed"
    assert result.candidates[0].statement == "Works for Globex."
    assert result.candidates[0].extraction_method == "local_model"
    assert result.prompt_tokens == 42
    assert result.completion_tokens == 17
    assert result.elapsed_ms is not None


def test_local_extractor_empty_response():
    extractor = LocalModelCandidateExtractor(FakeRunner({"candidates": []}))
    result = extractor.extract(local_request())
    assert result.status == "no_candidates"
    assert result.candidates == ()


def test_local_extractor_malformed_output_rejected_safely():
    extractor = LocalModelCandidateExtractor(
        FakeRunner({"candidates": [{"kind": "fact"}]})
    )
    result = extractor.extract(local_request())
    assert result.status == "invalid_output"
    assert result.candidates == ()
    assert result.fallback


def test_local_extractor_unsupported_action_fields_rejected():
    payload = valid_payload()
    payload["candidates"][0]["action"] = "supersede"
    extractor = LocalModelCandidateExtractor(FakeRunner(payload))
    result = extractor.extract(local_request())
    assert result.status == "invalid_output"
    assert result.candidates == ()


def test_local_extractor_too_many_candidates_rejected():
    payload = {"candidates": [valid_payload()["candidates"][0]] * 12}
    extractor = LocalModelCandidateExtractor(FakeRunner(payload))
    result = extractor.extract(local_request())
    assert result.status == "invalid_output"


def test_local_extractor_hallucinated_value_rejected_by_validator():
    payload = valid_payload()
    payload["candidates"][0]["statement"] = "Works for Initech."
    payload["candidates"][0]["value"] = "Initech"
    extractor = LocalModelCandidateExtractor(FakeRunner(payload))
    result = extractor.extract(local_request())
    assert result.status == "proposed"  # structurally fine
    outcome = validate(
        result.candidates[0],
        "I now work for Globex.",
        gate=DurabilityGate().assess("I now work for Globex."),
    )
    assert not outcome.accepted
    assert outcome.stage == "grounding"


def test_local_extractor_provider_failure_falls_back_safely():
    extractor = LocalModelCandidateExtractor(
        FakeRunner(error=LocalModelGenerationFailed("timeout"))
    )
    result = extractor.extract(local_request())
    assert result.status == "failed_safe"
    assert result.candidates == ()
    assert result.fallback
    planner = HybridMemoryPlanner(extractor=extractor)
    agent = agent_with_planner(planner)
    chat(agent, "I now work for Globex.")
    assert active_texts(agent) == []  # safe no-candidate fallback
    assert planner.counters["extractor_failed_safe"] == 1


def test_local_extractor_through_full_pipeline():
    extractor = LocalModelCandidateExtractor(FakeRunner(valid_payload()))
    planner = HybridMemoryPlanner(extractor=extractor)
    agent = agent_with_planner(planner)
    chat(agent, "I now work for Globex.")
    memories = agent.memories_for_user("u")
    assert [m.text for m in memories] == ["Works for Globex."]
    assert memories[0].metadata["extraction"]["extractor"] == (
        "local_model_candidates"
    )


# --- Development fixtures drive the pipeline ------------------------------------


@pytest.mark.parametrize(
    "case", FIXTURES["durable_positives"], ids=lambda c: c["class"]
)
def test_fixture_durable_positives(case):
    agent = agent_with_planner()
    chat(agent, case["message"])
    texts = active_texts(agent)
    expect = case["expect"]
    for term in expect.get("created_contains", []):
        assert any(term in t for t in texts), (case["class"], texts)
    if "created_count" in expect:
        assert len(texts) == expect["created_count"]
    if "created_count_min" in expect:
        assert len(texts) >= expect["created_count_min"]


@pytest.mark.parametrize(
    "case", FIXTURES["non_durable_negatives"], ids=lambda c: c["class"]
)
def test_fixture_non_durable_negatives(case):
    agent = agent_with_planner()
    chat(agent, case["message"])
    assert active_texts(agent) == [], case["class"]
