"""Local model runner smoke check. Optional and offline-safe.

Verifies that the optional CPU local runtime can produce structured
JSON. Skips cleanly (exit 0) when the optional dependency or model
path is not configured. This does not perform memory extraction and
does not call Qwen Cloud.

Setup:

    pip install -e ".[local]"
    export EXPERIENCEOS_LOCAL_MODEL_PATH=/path/to/model.gguf

    PYTHONPATH=. python examples/local_runner_smoke.py
"""

import sys
from pathlib import Path

from experienceos.policy import (
    LlamaCppLocalModelRunner,
    LocalModelRunnerError,
)

SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}


def main() -> int:
    runner = LlamaCppLocalModelRunner()
    status = runner.availability()
    model_name = Path(status.model_path).name if status.model_path else "—"
    print("Local model runner status:")
    print(f"  available: {status.available}")
    print(f"  model: {model_name}")

    if not status.available:
        print(f"  reason: {status.reason}")
        print(f"  detail: {status.detail}")
        print("SKIPPED — optional dependency or model not configured.")
        return 0

    try:
        result = runner.generate_structured(
            system_prompt=(
                "You produce strict JSON only. Reply with exactly "
                '{"status": "ready"}.'
            ),
            user_prompt='Reply with {"status": "ready"}.',
            schema=SCHEMA,
        )
    except LocalModelRunnerError as exc:
        print(f"FAILED — {exc.reason}: {exc}")
        return 1

    if not isinstance(result.data, dict):
        print("FAILED — structured result is not a dictionary.")
        return 1

    print(f"  result: {result.data}")
    print(f"  model file: {result.model_name}")
    print(f"  prompt tokens: {result.prompt_tokens}")
    print(f"  completion tokens: {result.completion_tokens}")
    if result.elapsed_ms is not None:
        print(f"  elapsed: {result.elapsed_ms:.0f} ms")
    print("PASSED — local structured generation succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
