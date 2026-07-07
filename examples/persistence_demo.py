"""Experience persistence across process restarts. Runs offline.

Three agents share one SQLite database, simulating restarts:
Agent A stores preferences, Agent B retrieves them, an update turn
supersedes one, and Agent C proves the corrected experience survived.

The database is recreated at .experienceos/persistence_demo.sqlite3 on
each run (gitignored).
"""

from pathlib import Path

from experienceos import ExperienceOS
from experienceos.providers import MockProvider

DB_PATH = Path(".experienceos/persistence_demo.sqlite3")
USER_ID = "demo-user"


def fresh_agent() -> ExperienceOS:
    """Simulates a process restart: new agent, same database."""
    return ExperienceOS.with_sqlite_memory(model=MockProvider(), db_path=DB_PATH)


def show_memories(agent: ExperienceOS) -> None:
    print("  Active memories:")
    for m in agent.memories_for_user(USER_ID):
        print(f"    - {m.text}")
    superseded = agent.memories_for_user(USER_ID, status="superseded")
    if superseded:
        print("  Superseded memories:")
        for m in superseded:
            print(f"    - {m.text}")


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    print("=== Run 1: agent A stores preferences ===")
    agent_a = fresh_agent()
    agent_a.chat(
        user_id=USER_ID,
        session_id="session-1",
        message="I prefer aisle seats and morning flights.",
    )
    show_memories(agent_a)

    print()
    print("=== Run 2 (restart): agent B retrieves persisted experience ===")
    agent_b = fresh_agent()
    response = agent_b.chat(
        user_id=USER_ID,
        session_id="session-2",
        message="Help me book a work trip to NYC.",
    )
    print(f"  Assistant: {response}")
    retrieved = [e for e in agent_b.events if e.type == "memory_retrieved"]
    print(f"  memory_retrieved: {retrieved[0].payload['count']} from SQLite")

    print()
    print("=== Run 2 continued: preference change persists ===")
    agent_b.chat(
        user_id=USER_ID,
        session_id="session-3",
        message="Actually, I prefer window seats now.",
    )
    show_memories(agent_b)

    print()
    print("=== Run 3 (restart): agent C sees the corrected experience ===")
    agent_c = fresh_agent()
    agent_c.chat(
        user_id=USER_ID, session_id="session-4", message="Help me book a trip."
    )
    show_memories(agent_c)
    final_context = [
        e for e in agent_c.events if e.type == "context_built"
    ][-1].payload["context_messages"]
    print("  Final context evidence:")
    for message in final_context:
        if "retrieved these active user experiences" in message["content"]:
            for line in message["content"].splitlines():
                print(f"    {line}")


if __name__ == "__main__":
    main()
