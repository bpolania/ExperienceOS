"""Optional .env loading tests: safe defaults, precedence, hygiene."""

import os
import sys
from pathlib import Path

import pytest

from demo.env import load_local_env

TEST_VAR = "EXPERIENCEOS_ENV_LOADING_TEST_VAR"


def test_env_file_is_gitignored_and_example_committed():
    gitignore = Path(".gitignore").read_text().splitlines()
    assert ".env" in gitignore
    example = Path(".env.example").read_text()
    assert "QWEN_API_KEY=" in example
    # The example must never ship a value.
    for line in example.splitlines():
        if line.startswith("QWEN_API_KEY="):
            assert line == "QWEN_API_KEY="


def test_load_local_env_is_safe_without_dotenv(monkeypatch):
    # Simulate python-dotenv being uninstalled.
    monkeypatch.setitem(sys.modules, "dotenv", None)
    assert load_local_env() is False


def test_load_local_env_reads_env_file(tmp_path, monkeypatch):
    pytest.importorskip("dotenv")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(TEST_VAR, raising=False)
    (tmp_path / ".env").write_text(f"{TEST_VAR}=from-file\n")
    try:
        assert load_local_env() is True
        assert os.environ[TEST_VAR] == "from-file"
    finally:
        os.environ.pop(TEST_VAR, None)


def test_load_local_env_never_overrides_existing_vars(tmp_path, monkeypatch):
    pytest.importorskip("dotenv")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(TEST_VAR, "from-environment")
    (tmp_path / ".env").write_text(f"{TEST_VAR}=from-file\n")
    load_local_env()
    assert os.environ[TEST_VAR] == "from-environment"


def test_load_local_env_without_file_is_clean(tmp_path, monkeypatch):
    pytest.importorskip("dotenv")
    monkeypatch.chdir(tmp_path)
    assert load_local_env() is False


def test_entry_points_load_local_env():
    for entry_point in (
        "demo/app.py",
        "examples/qwen_live_demo.py",
        "examples/basic_qwen_demo.py",
    ):
        assert "load_local_env()" in Path(entry_point).read_text(), entry_point


def test_sdk_never_loads_env_files():
    """The .env behavior belongs to entry points, never the SDK core."""
    for path in Path("experienceos").rglob("*.py"):
        text = path.read_text()
        assert "dotenv" not in text, f"SDK module loads .env: {path}"
