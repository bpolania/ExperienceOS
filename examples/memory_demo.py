"""Cross-session experience accumulation with ExperienceOS. Runs offline.

Session 1: the user states preferences — ExperienceOS stores them.
Session 2: ExperienceOS retrieves them and injects them into context.
"""

from experienceos import ExperienceOS
from experienceos.providers import MockProvider


def main() -> None:
    agent = ExperienceOS(model=MockProvider())
    user_id = "demo-user"

    print("--- Session 1 ---")
    response = agent.chat(
        user_id=user_id,
        session_id="session-1",
        message="I prefer aisle seats and morning flights.",
    )
    print(f"Assistant: {response}")
    print("Memories created:")
    for m in agent.memories_for_user(user_id):
        print(f"  - {m.text}")

    print()
    print("--- Session 2 ---")
    response = agent.chat(
        user_id=user_id,
        session_id="session-2",
        message="Help me book a work trip to NYC.",
    )
    print(f"Assistant: {response}")
    print("Active memories:")
    for m in agent.memories_for_user(user_id):
        print(f"  - ({m.status}) {m.text}")

    print()
    print("Event types emitted:")
    for event in agent.events:
        print(f"  - {event.type}")


if __name__ == "__main__":
    main()
