"""Memory update and superseding with ExperienceOS. Runs offline.

Turn 1: the user states preferences — ExperienceOS stores them.
Turn 2: the user changes a preference — the old memory is superseded.
Turn 3: a trip request retrieves only the current experience.
"""

from experienceos import ExperienceOS
from experienceos.providers import MockProvider

TURNS = [
    ("session-preferences", "I prefer aisle seats and morning flights."),
    ("session-update", "Actually, I prefer window seats now."),
    ("session-trip", "Help me book a work trip to NYC."),
]


def main() -> None:
    agent = ExperienceOS(model=MockProvider())
    user_id = "demo-user"

    for session_id, message in TURNS:
        print(f"--- {session_id} ---")
        print(f"User: {message}")
        response = agent.chat(
            user_id=user_id, session_id=session_id, message=message
        )
        print(f"Assistant: {response}")
        print()

    print("Active memories:")
    for m in agent.memories_for_user(user_id):
        print(f"  - {m.text}")

    print("Superseded memories:")
    for m in agent.memories_for_user(user_id, status="superseded"):
        print(f"  - {m.text} (reason: {m.metadata.get('superseded_reason')})")

    print()
    print("Event types emitted:")
    for event in agent.events:
        print(f"  - {event.type}")

    print()
    final_context = [
        e for e in agent.events if e.type == "context_built"
    ][-1].payload["context_messages"]
    print("Final turn context evidence:")
    for message in final_context:
        if "retrieved these active user experiences" in message["content"]:
            print(message["content"])


if __name__ == "__main__":
    main()
