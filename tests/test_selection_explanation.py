"""Selection explanation tests: per-candidate records, reasons, summaries."""

from demo.support import selection_records, summarize_selection_record
from experienceos import ExperienceOS
from experienceos.events import EventType
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

RECORD_FIELDS = {
    "memory_id",
    "text",
    "kind",
    "status",
    "selected",
    "rank",
    "score",
    "matched_keywords",
    "kind_priority",
    "reason",
}


def seeded_agent(provider=None):
    agent = ExperienceOS(model=provider or MockProvider())
    for i, message in enumerate(SEED_MESSAGES):
        agent.chat(user_id="u1", session_id=f"seed-{i}", message=message)
    return agent


def trip_payload(agent):
    agent.chat(user_id="u1", session_id="trip", message=TRIP_REQUEST)
    return [e for e in agent.events if e.type == EventType.CONTEXT_BUILT][-1].payload


def test_payload_includes_one_record_per_candidate():
    payload = trip_payload(seeded_agent())
    records = payload["selection_records"]
    assert len(records) == 6
    assert {r["memory_id"] for r in records} == set(payload["candidate_memory_ids"])
    assert all(RECORD_FIELDS <= set(r) for r in records)


def test_records_align_with_selected_and_skipped_ids():
    payload = trip_payload(seeded_agent())
    records = payload["selection_records"]
    assert {r["memory_id"] for r in records if r["selected"]} == set(
        payload["selected_memory_ids"]
    )
    assert {r["memory_id"] for r in records if not r["selected"]} == set(
        payload["skipped_memory_ids"]
    )


def test_ranks_are_one_based_and_ordered():
    payload = trip_payload(seeded_agent())
    records = payload["selection_records"]
    assert [r["rank"] for r in records] == list(range(1, 7))
    # Selected records occupy the top ranks.
    assert all(r["selected"] == (r["rank"] <= 4) for r in records)


def test_matched_keywords_reflect_message_tokens():
    payload = trip_payload(seeded_agent())
    transfer = next(
        r
        for r in payload["selection_records"]
        if r["text"] == "Include airport transfer time when planning work trips."
    )
    assert transfer["rank"] == 1
    assert transfer["score"] == 2
    assert set(transfer["matched_keywords"]) == {"work", "trip"}


def test_selected_reason_mentions_matches_and_budget():
    payload = trip_payload(seeded_agent())
    transfer = next(
        r
        for r in payload["selection_records"]
        if r["text"] == "Include airport transfer time when planning work trips."
    )
    assert transfer["reason"] == (
        "selected: matched trip, work; domains travel + work + planning; "
        "instruction priority; within budget"
    )
    no_match = next(
        r
        for r in payload["selection_records"]
        if r["selected"] and r["score"] == 0
    )
    assert no_match["reason"].startswith("selected: no keyword match;")


def test_skipped_reason_mentions_budget_reached():
    payload = trip_payload(seeded_agent())
    skipped = [r for r in payload["selection_records"] if not r["selected"]]
    assert len(skipped) == 2
    for record in skipped:
        assert record["reason"].startswith("skipped: ")
        assert "budget reached after 4 selected memories" in record["reason"]


def test_records_are_deterministic_across_runs():
    def record_texts():
        payload = trip_payload(seeded_agent())
        return [(r["text"], r["selected"], r["reason"])
                for r in payload["selection_records"]]

    assert record_texts() == record_texts()


def test_skipped_texts_absent_from_provider_messages():
    class SpyProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = []

        def complete(self, messages):
            self.calls.append(messages)
            return super().complete(messages)

    spy = SpyProvider()
    agent = seeded_agent(provider=spy)
    payload = trip_payload(agent)
    provider_text = " ".join(m["content"] for m in spy.calls[-1])
    for record in payload["selection_records"]:
        if not record["selected"]:
            assert record["text"] not in provider_text


def test_under_budget_all_selected_within_budget():
    agent = ExperienceOS(model=MockProvider())
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    agent.chat(user_id="u1", session_id="s2", message="Book a trip.")
    payload = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload
    records = payload["selection_records"]
    assert len(records) == 1
    assert records[0]["selected"] is True
    assert records[0]["reason"].endswith("within budget")


def test_demo_support_selection_helpers():
    agent = seeded_agent()
    trip_payload(agent)
    records = selection_records(agent.events)
    assert len(records) == 6
    lines = [summarize_selection_record(r) for r in records]
    assert lines[0] == (
        "Selected: Include airport transfer time when planning work trips. "
        "— matched trip, work; domains travel + work + planning; "
        "instruction priority; within budget"
    )
    assert any(
        line.startswith("Skipped: Prefers")
        and "budget reached" in line
        for line in lines
    )


def test_context_built_summary_shows_counts():
    from demo.support import summarize_event

    agent = seeded_agent()
    trip_payload(agent)
    built = [e for e in agent.events if e.type == EventType.CONTEXT_BUILT][-1]
    assert summarize_event(built) == "Context built: 4 selected, 2 skipped."
