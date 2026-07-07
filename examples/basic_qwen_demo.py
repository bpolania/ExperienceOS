"""Basic ExperienceOS lifecycle demo. Runs offline via MockProvider.

To use Qwen Cloud instead:

    from experienceos.providers import QwenCloud
    agent = ExperienceOS(model=QwenCloud(model="qwen-plus"))  # reads QWEN_API_KEY
"""

from experienceos import ExperienceOS
from experienceos.providers import MockProvider


def main() -> None:
    agent = ExperienceOS(model=MockProvider())

    response = agent.chat(
        user_id="demo-user",
        session_id="session-1",
        message="I prefer aisle seats and morning flights.",
    )

    print(f"Provider: {agent.model.name}")
    print(f"Assistant: {response}")
    print()
    print("Events emitted:")
    for event in agent.events:
        print(f"  - {event.type}")


if __name__ == "__main__":
    main()
