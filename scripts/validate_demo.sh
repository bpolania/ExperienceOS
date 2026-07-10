#!/usr/bin/env bash
# Offline validation for the ExperienceOS demo path.
#
# Runs the compile check, the full test suite, and every offline
# example, ending with the full lifecycle proof. No network access and
# no Qwen credentials are required; the live Qwen example is
# intentionally excluded.
#
# Usage (from anywhere; the script changes to the repository root):
#   ./scripts/validate_demo.sh
#
# Override the interpreter if your environment needs it, e.g.:
#   PYTHON=.venv/bin/python ./scripts/validate_demo.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
export PYTHONPATH=.

run() {
    echo
    echo ">>> $*"
    "$@"
}

run "$PYTHON" -m compileall -q experienceos demo
run "$PYTHON" -m pytest
run "$PYTHON" examples/basic_qwen_demo.py
run "$PYTHON" examples/memory_demo.py
run "$PYTHON" examples/update_demo.py
run "$PYTHON" examples/persistence_demo.py
run "$PYTHON" examples/full_lifecycle_demo.py
run "$PYTHON" examples/local_runner_smoke.py

echo
echo "Offline demo validation passed."
