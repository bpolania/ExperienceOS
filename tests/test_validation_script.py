"""Static checks for the offline validation script.

The script runs the full suite itself, so these tests verify its shape
statically; the end-to-end run happens in validation workflows.
"""

import os
from pathlib import Path

SCRIPT = Path("scripts/validate_demo.sh")


def test_validation_script_exists_and_is_executable():
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)


def test_validation_script_runs_required_offline_commands():
    text = SCRIPT.read_text()
    assert "set -euo pipefail" in text  # stops on first failure, exits nonzero
    for required in (
        "compileall",
        "pytest",
        "examples/basic_qwen_demo.py",
        "examples/memory_demo.py",
        "examples/update_demo.py",
        "examples/persistence_demo.py",
        "examples/full_lifecycle_demo.py",
    ):
        assert required in text, f"validation script missing: {required}"


def test_validation_script_is_credential_free():
    text = SCRIPT.read_text()
    assert "qwen_live_demo" not in text
    assert "QWEN_API_KEY" not in text
    assert "DASHSCOPE_API_KEY" not in text
