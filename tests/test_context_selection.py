"""Context selection and budget tests: ranking, budget, payload, exclusions."""

from experienceos import ExperienceOS
from experienceos.context import ContextBuilder
from experienceos.events import EventType
from experienceos.memory import ExperienceEntry, MemoryKind
from experienceos.providers import MockProvider

SEED_MESSAGES = [
    "I prefer aisle seats.",
    "I prefer morning flights.",
    "My home airport is SFO.",
    "My company is based in San Jose.",
    "When planning work trips, include airport transfer time.",
    "Remember to keep travel plans concise.",
]
TRIP_REQUEST = "Help me plan a work trip to New York."


class SpyProvider(MockProvider):
    def __init__(self):
        super().__init__()
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return super().complete(messages)


def seeded_agent(provider=None):
    agent = ExperienceOS(model=provider or MockProvider())
    for i, message in enumerate(SEED_MESSAGES):
        agent.chat(user_id="u1", session_id=f"seed-{i}", message=message)
    return agent


def last_context_built(agent):
    return [e for e in agent.events if e.type == EventType.CONTEXT_BUILT][-1].payload


def test_selection_respects_budget():
    agent = seeded_agent()
    agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
    payload = last_context_built(agent)
    assert payload["memory_budget"] == 4
    assert payload["selected_memory_count"] == 4
    assert payload["skipped_memory_count"] == 2
    assert payload["memory_count"] == 6  # all active candidates considered


def test_payload_ids_partition_candidates():
    agent = seeded_agent()
    agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
    payload = last_context_built(agent)
    selected = set(payload["selected_memory_ids"])
    skipped = set(payload["skipped_memory_ids"])
    candidates = set(payload["candidate_memory_ids"])
    assert len(selected) == 4 and len(skipped) == 2
    assert selected | skipped == candidates
    assert selected & skipped == set()


def test_skipped_memories_absent_from_provider_context():
    spy = SpyProvider()
    agent = seeded_agent(provider=spy)
    agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
    provider_text = " ".join(m["content"] for m in spy.calls[-1])
    # Overlapping instructions and zero-overlap facts win the budget;
    # the two zero-overlap preferences are skipped.
    assert "Include airport transfer time when planning work trips." in provider_text
    assert "Keep travel plans concise." in provider_text
    assert "Home airport is SFO." in provider_text
    assert "Company is based in San Jose." in provider_text
    assert "Prefers aisle seats." not in provider_text
    assert "Prefers morning flights." not in provider_text


def test_selection_is_deterministic():
    def selected_texts():
        agent = seeded_agent()
        agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
        payload = last_context_built(agent)
        by_id = {m.id: m.text for m in agent.memories_for_user("u1")}
        return [by_id[i] for i in payload["selected_memory_ids"]]

    assert selected_texts() == selected_texts()


def test_instructions_favored_when_nothing_overlaps():
    agent = ExperienceOS(model=MockProvider())
    for i, message in enumerate(
        [
            "I prefer aisle seats.",
            "I prefer morning flights.",
            "I prefer quiet hotels.",
            "I prefer evening flights to Boston.",  # different domain wording
            "Remember to keep travel plans concise.",
        ]
    ):
        agent.chat(user_id="u1", session_id=f"s-{i}", message=message)
    agent.chat(user_id="u1", session_id="ask", message="What should I do next?")
    payload = last_context_built(agent)
    by_id = {m.id: m for m in agent.memories_for_user("u1")}
    selected_kinds = [by_id[i].kind for i in payload["selected_memory_ids"]]
    assert MemoryKind.INSTRUCTION == selected_kinds[0]


def test_forgotten_memories_never_selected():
    agent = seeded_agent()
    agent.chat(
        user_id="u1", session_id="forget", message="Forget my aisle seat preference."
    )
    agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
    payload = last_context_built(agent)
    all_texts = {
        m.id: m.text for m in agent.memories_for_user("u1", status=None)
    }
    considered = [all_texts[i] for i in payload["candidate_memory_ids"]]
    assert "Prefers aisle seats." not in considered


def test_superseded_memories_never_selected_over_replacement():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer morning flights.")
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, I prefer evening flights."
    )
    agent.chat(user_id="u1", session_id="s3", message="Book me a flight.")
    payload = last_context_built(agent)
    all_texts = {
        m.id: m.text for m in agent.memories_for_user("u1", status=None)
    }
    selected = [all_texts[i] for i in payload["selected_memory_ids"]]
    assert "Prefers evening flights." in selected
    assert "Prefers morning flights." not in selected
    considered = [all_texts[i] for i in payload["candidate_memory_ids"]]
    assert "Prefers morning flights." not in considered


def test_kind_grouping_preserved_for_selected():
    spy = SpyProvider()
    agent = seeded_agent(provider=spy)
    agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
    memory_block = next(
        m["content"] for m in spy.calls[-1] if "Facts:" in m.get("content", "")
    )
    assert "Instructions:\n" in memory_block
    assert memory_block.index("Facts:") < memory_block.index("Instructions:")


def test_mock_provider_counts_selected_only():
    agent = seeded_agent()
    response = agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
    assert "with 4 retrieved experience entries" in response


def test_builder_direct_budget_and_result_shape():
    builder = ContextBuilder(memory_budget=2)
    memories = [
        ExperienceEntry(user_id="u1", text=f"Prefers option {i}.") for i in range(5)
    ]
    result = builder.build_context("u1", "s1", "anything", memories=memories)
    assert result.memory_budget == 2
    assert len(result.selected_memories) == 2
    assert len(result.skipped_memories) == 3
    assert len(result.candidate_memories) == 5
    rendered = " ".join(m["content"] for m in result.messages)
    for m in result.skipped_memories:
        assert m.text not in rendered
    for m in result.selected_memories:
        assert m.text in rendered


def test_under_budget_selects_everything():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    payload = last_context_built(agent)
    assert payload["selected_memory_count"] == 1
    assert payload["skipped_memory_count"] == 0
