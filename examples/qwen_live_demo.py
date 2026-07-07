"""Live Qwen Cloud demo of ExperienceOS memory accumulation.

Requires Qwen/DashScope credentials — exits with instructions otherwise.
Not part of automated tests.

Setup:

    export QWEN_API_KEY="..."          # or DASHSCOPE_API_KEY
    export QWEN_BASE_URL="..."         # only if your workspace needs a regional endpoint
    export QWEN_MODEL="qwen-plus"      # optional

    PYTHONPATH=. python examples/qwen_live_demo.py
"""

import sys

from experienceos import ExperienceOS
from experienceos.providers import QwenCloudProvider


def main() -> int:
    provider = QwenCloudProvider()
    if not provider.is_configured:
        print("Qwen Cloud is not configured, so this live demo cannot run.")
        print()
        print("Set QWEN_API_KEY (or DASHSCOPE_API_KEY), and QWEN_BASE_URL if your")
        print("Model Studio workspace requires a regional endpoint. For an offline")
        print("run of the same flow, use: PYTHONPATH=. python examples/memory_demo.py")
        return 1

    agent = ExperienceOS(model=provider)
    user_id = "demo-user"
    print(f"Provider: {agent.model.name} (model: {provider.model})")

    print()
    print("--- Session 1 ---")
    response = agent.chat(
        user_id=user_id,
        session_id="session-1",
        message="I prefer aisle seats and morning flights.",
    )
    print(f"Assistant: {response}")

    print()
    print("--- Session 2 ---")
    response = agent.chat(
        user_id=user_id,
        session_id="session-2",
        message="Help me book a work trip to NYC.",
    )
    print(f"Assistant: {response}")

    print()
    print("Active memories:")
    for m in agent.memories_for_user(user_id):
        print(f"  - ({m.status}) {m.text}")

    print()
    print("Event types emitted:")
    for event in agent.events:
        print(f"  - {event.type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
