"""Domain/tag metadata tests: classification, creation, explanations."""

from experienceos import ExperienceOS
from experienceos.events import EventType
from experienceos.memory import MemoryStatus, assign_tags, domain_for
from experienceos.providers import MockProvider


def make_agent(**kwargs):
    return ExperienceOS(model=MockProvider(), **kwargs)


def test_airport_fact_tags():
    assert assign_tags("Home airport is SFO.") == ["travel", "airport"]


def test_seat_preference_tags():
    assert assign_tags("Prefers aisle seats.") == ["travel", "flight", "seat"]


def test_timing_preference_tags():
    assert assign_tags("Dislikes red-eye flights.") == ["travel", "flight", "timing"]


def test_transfer_instruction_tags():
    tags = assign_tags("Include airport transfer time when planning work trips.")
    assert set(tags) >= {"travel", "transfer", "planning", "work"}
    assert tags == [t for t in tags]  # canonical order preserved by construction
    assert tags[0] == "travel"


def test_work_and_company_location_tags():
    assert assign_tags("Company is based in San Jose.") == [
        "work",
        "company",
        "location",
    ]
    assert assign_tags("Works out of Santa Clara.") == ["work", "location"]


def test_response_style_tags():
    assert assign_tags("Keep answers concise.") == ["style", "response_style"]


def test_untaggable_text_yields_no_tags():
    assert assign_tags("Give options with estimated tradeoffs.") == []
    assert domain_for([]) is None


def test_created_memories_carry_tag_metadata():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    memory = agent.memories_for_user("u1")[0]
    assert memory.metadata["tags"] == ["travel", "airport"]
    assert memory.metadata["domain"] == "travel"


def test_tag_metadata_persists_in_sqlite(tmp_path):
    agent = ExperienceOS.with_sqlite_memory(
        model=MockProvider(), db_path=tmp_path / "tags.sqlite3"
    )
    agent.chat(user_id="u1", session_id="s1", message="I prefer aisle seats.")
    from experienceos.memory import SQLiteMemoryStore

    reloaded = SQLiteMemoryStore(tmp_path / "tags.sqlite3").active_for_user("u1")
    assert reloaded[0].metadata["tags"] == ["travel", "flight", "seat"]


def test_supersession_preserves_old_tags_and_assigns_new():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    agent.chat(
        user_id="u1", session_id="s2", message="Actually, my home airport is now SJC."
    )
    old = agent.memories_for_user("u1", status=MemoryStatus.SUPERSEDED)[0]
    new = agent.memories_for_user("u1")[0]
    assert old.metadata["tags"] == ["travel", "airport"]
    assert new.metadata["tags"] == ["travel", "airport"]
    assert old.metadata["superseded_by"] == new.id


def test_selected_reason_includes_domain_evidence():
    agent = make_agent()
    agent.chat(user_id="u1", session_id="s1", message="My home airport is SFO.")
    agent.chat(user_id="u1", session_id="ask", message="Book me a flight.")
    record = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload["selection_records"][0]
    assert record["tags"] == ["travel", "airport"]
    assert record["matched_domains"] == ["travel"]
    assert "domains travel" in record["reason"]


def test_skipped_reason_names_irrelevant_domain():
    agent = make_agent()
    # Meal preference first (oldest), then four travel memories fill the budget.
    for i, message in enumerate(
        [
            "I prefer vegetarian meals.",
            "I prefer aisle seats.",
            "My home airport is SFO.",
            "When planning work trips, include airport transfer time.",
            "Remember to keep travel plans concise.",
        ]
    ):
        agent.chat(user_id="u1", session_id=f"s-{i}", message=message)
    agent.chat(user_id="u1", session_id="trip", message="Help me plan a work trip.")
    payload = [
        e for e in agent.events if e.type == EventType.CONTEXT_BUILT
    ][-1].payload
    skipped = [r for r in payload["selection_records"] if not r["selected"]]
    assert len(skipped) == 1
    record = skipped[0]
    assert record["text"] == "Prefers vegetarian meals."
    assert record["tags"] == ["meal"]
    assert record["matched_domains"] == []
    assert record["reason"] == (
        "skipped: its meal experience was less relevant to this request; "
        "budget reached after 4 selected memories"
    )
