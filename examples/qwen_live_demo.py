"""Manual live smoke for the Qwen Cloud provider.

Not part of automated tests — requires Qwen/DashScope credentials and
makes real network calls. Runs in two stages: one narrow provider call
to prove the adapter works, then a short experience lifecycle on live
Qwen.

Setup (either export the variables or copy .env.example to .env —
the .env file is loaded automatically when python-dotenv is installed):

    export QWEN_API_KEY="..."          # or DASHSCOPE_API_KEY
    export QWEN_BASE_URL="..."         # only if your workspace needs a regional endpoint
    export QWEN_MODEL="qwen-plus"      # optional

    PYTHONPATH=. python examples/qwen_live_demo.py

Exits 0 on success, 1 when unconfigured.
"""

import sys

from demo.env import load_local_env
from experienceos import ExperienceOS
from experienceos.providers import QwenCloudProvider

load_local_env()

SETUP_INSTRUCTIONS = """\
Set QWEN_API_KEY (or DASHSCOPE_API_KEY), and QWEN_BASE_URL if your
Model Studio workspace requires a regional endpoint. For an offline
run of the experience flow, use:

    PYTHONPATH=. python examples/memory_demo.py"""


def configuration_lines(provider: QwenCloudProvider) -> list[str]:
    """Human-readable configuration status. Never leaks the key."""
    return [
        f"API key: {'set' if provider.is_configured else 'missing'}",
        f"Base URL: {provider.base_url}",
        f"Model: {provider.model}",
    ]


def main() -> int:
    provider = QwenCloudProvider()
    print("Qwen Cloud configuration:")
    for line in configuration_lines(provider):
        print(f"  {line}")

    if not provider.is_configured:
        print()
        print("Not configured — the live smoke cannot run.")
        print(SETUP_INSTRUCTIONS)
        return 1

    print()
    print("--- Stage 1: narrow provider call ---")
    reply = provider.complete(
        [{"role": "user", "content": "Reply with the single word: ready"}]
    )
    print(f"Model replied: {reply.strip()[:120]}")

    print()
    print("--- Stage 2: experience lifecycle on live Qwen ---")
    agent = ExperienceOS(model=provider)
    user_id = "demo-user"
    for session_id, message in [
        ("session-1", "I prefer aisle seats and morning flights."),
        ("session-2", "Help me book a work trip to NYC."),
    ]:
        print(f"User: {message}")
        response = agent.chat(
            user_id=user_id, session_id=session_id, message=message
        )
        print(f"Assistant: {response.strip()[:300]}")
        print()

    print("Active memories accumulated:")
    for m in agent.memories_for_user(user_id):
        print(f"  - ({m.kind}) {m.text}")
    print()
    print(f"Lifecycle events emitted: {len(agent.events)}")
    print("Live smoke succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
