"""Local model runner tests: fully offline, fake runtime, no downloads."""

import dataclasses
import importlib.machinery
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from experienceos.policy.local_runner import (
    CONTEXT_SIZE_ENV,
    MAX_TOKENS_ENV,
    MODEL_PATH_ENV,
    THREADS_ENV,
    LlamaCppLocalModelRunner,
    LocalModelAvailability,
    LocalModelDependencyMissing,
    LocalModelGenerationFailed,
    LocalModelInvalidOutput,
    LocalModelLoadFailed,
    LocalModelResult,
    LocalModelRunnerError,
    LocalModelUnavailable,
)
from tests.helpers import FakeLocalModelRunner

ALL_LOCAL_ENV = (MODEL_PATH_ENV, CONTEXT_SIZE_ENV, MAX_TOKENS_ENV, THREADS_ENV)


@pytest.fixture
def no_local_env(monkeypatch):
    for var in ALL_LOCAL_ENV:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


class FakeLlamaHandle:
    """Controls the injected fake llama_cpp module."""

    def __init__(self):
        self.instances = []
        self.init_error = None
        self.call_error = None
        self.response = {
            "choices": [{"message": {"content": '{"status": "ready"}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        }


@pytest.fixture
def fake_llama(monkeypatch, no_local_env):
    """Inject a fake llama_cpp module; returns the control handle."""
    handle = FakeLlamaHandle()

    class FakeLlama:
        def __init__(self, **kwargs):
            if handle.init_error is not None:
                raise handle.init_error
            self.kwargs = kwargs
            self.calls = []
            handle.instances.append(self)

        def create_chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            if handle.call_error is not None:
                raise handle.call_error
            return handle.response

    module = types.ModuleType("llama_cpp")
    module.Llama = FakeLlama
    module.__spec__ = importlib.machinery.ModuleSpec("llama_cpp", loader=None)
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    return handle


@pytest.fixture
def model_file(tmp_path):
    path = tmp_path / "tiny-model.gguf"
    path.write_bytes(b"gguf-fake")
    return path


# --- Contract types --------------------------------------------------------------


def test_fake_runner_satisfies_protocol():
    runner = FakeLocalModelRunner()
    assert runner.availability().available is True
    result = runner.generate_structured(
        system_prompt="s", user_prompt="u", schema={"type": "object"}
    )
    assert result.data == {"status": "ready"}
    assert runner.calls[0]["schema"] == {"type": "object"}


def test_result_and_availability_are_immutable():
    availability = LocalModelAvailability(available=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        availability.available = False
    result = LocalModelResult(data={}, model_path="x.gguf")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.data = {}


def test_typed_errors_expose_fallback_reasons():
    assert LocalModelDependencyMissing("x").reason == "dependency_missing"
    assert LocalModelUnavailable("x").reason == "model_unavailable"
    assert LocalModelLoadFailed("x").reason == "model_load_failed"
    assert LocalModelGenerationFailed("x").reason == "generation_failed"
    assert LocalModelInvalidOutput("x").reason == "invalid_output"
    assert isinstance(LocalModelInvalidOutput("x"), LocalModelRunnerError)


# --- Configuration and availability ------------------------------------------------


def test_missing_dependency_reported(no_local_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)  # blocks discovery
    status = LlamaCppLocalModelRunner().availability()
    assert status.available is False
    assert status.reason == "dependency_missing"
    assert 'pip install -e ".[local]"' in status.detail


def test_missing_model_path_reported(fake_llama):
    status = LlamaCppLocalModelRunner().availability()
    assert status.available is False
    assert status.reason == "model_unavailable"
    assert MODEL_PATH_ENV in status.detail


def test_nonexistent_path_reported(fake_llama, tmp_path):
    runner = LlamaCppLocalModelRunner(model_path=tmp_path / "missing.gguf")
    status = runner.availability()
    assert status.available is False
    assert status.reason == "model_unavailable"
    assert "does not exist" in status.detail


def test_directory_path_reported(fake_llama, tmp_path):
    status = LlamaCppLocalModelRunner(model_path=tmp_path).availability()
    assert status.available is False
    assert "not a regular file" in status.detail


@pytest.mark.skipif(os.name != "posix", reason="permission bits are POSIX-only")
def test_unreadable_path_reported(fake_llama, model_file):
    model_file.chmod(0o000)
    try:
        status = LlamaCppLocalModelRunner(model_path=model_file).availability()
        assert status.available is False
        assert "not readable" in status.detail
    finally:
        model_file.chmod(0o644)


def test_valid_file_passes_shallow_check(fake_llama, model_file):
    status = LlamaCppLocalModelRunner(model_path=model_file).availability()
    assert status.available is True
    assert status.reason is None
    assert status.model_path == str(model_file)
    # Shallow means shallow: no model was constructed.
    assert fake_llama.instances == []


def test_env_path_used_when_constructor_omits(fake_llama, model_file, monkeypatch):
    monkeypatch.setenv(MODEL_PATH_ENV, str(model_file))
    status = LlamaCppLocalModelRunner().availability()
    assert status.available is True


def test_explicit_path_overrides_environment(fake_llama, model_file, monkeypatch):
    monkeypatch.setenv(MODEL_PATH_ENV, "/nonexistent/env-model.gguf")
    status = LlamaCppLocalModelRunner(model_path=model_file).availability()
    assert status.available is True
    assert status.model_path == str(model_file)


def test_tilde_expansion(fake_llama, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "home-model.gguf").write_bytes(b"gguf")
    status = LlamaCppLocalModelRunner(model_path="~/home-model.gguf").availability()
    assert status.available is True
    assert status.model_path == str(tmp_path / "home-model.gguf")


# --- Lazy import, lazy load, cache ---------------------------------------------------


def test_construction_does_not_import_or_load(no_local_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    runner = LlamaCppLocalModelRunner(model_path="/tmp/whatever.gguf")
    assert runner._model is None  # nothing imported, nothing loaded


def test_generation_triggers_lazy_load_once_and_caches(fake_llama, model_file):
    runner = LlamaCppLocalModelRunner(model_path=model_file)
    assert fake_llama.instances == []
    runner.generate_structured(system_prompt="s", user_prompt="u", schema={})
    runner.generate_structured(system_prompt="s", user_prompt="u", schema={})
    assert len(fake_llama.instances) == 1  # loaded once, cached

    other = LlamaCppLocalModelRunner(model_path=model_file)
    other.generate_structured(system_prompt="s", user_prompt="u", schema={})
    assert len(fake_llama.instances) == 2  # per-instance ownership


def test_cpu_safe_constructor_settings(fake_llama, model_file):
    runner = LlamaCppLocalModelRunner(
        model_path=model_file, context_size=1024, threads=3
    )
    runner.generate_structured(system_prompt="s", user_prompt="u", schema={})
    kwargs = fake_llama.instances[0].kwargs
    assert kwargs["n_gpu_layers"] == 0
    assert kwargs["n_ctx"] == 1024
    assert kwargs["n_threads"] == 3
    assert kwargs["model_path"] == str(model_file)  # local file, no remote id
    assert kwargs["verbose"] is False


def test_default_threads_are_bounded(no_local_env):
    threads = LlamaCppLocalModelRunner().threads
    assert 1 <= threads <= 4


def test_env_numeric_overrides(no_local_env, monkeypatch):
    monkeypatch.setenv(CONTEXT_SIZE_ENV, "4096")
    monkeypatch.setenv(MAX_TOKENS_ENV, "256")
    monkeypatch.setenv(THREADS_ENV, "2")
    runner = LlamaCppLocalModelRunner()
    assert (runner.context_size, runner.max_tokens, runner.threads) == (4096, 256, 2)
    # Constructor wins; malformed env values fall back to defaults.
    explicit = LlamaCppLocalModelRunner(context_size=512)
    assert explicit.context_size == 512
    monkeypatch.setenv(CONTEXT_SIZE_ENV, "not-a-number")
    assert LlamaCppLocalModelRunner().context_size == 2048


# --- Structured generation ----------------------------------------------------------


def test_structured_invocation_parameters(fake_llama, model_file):
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    runner = LlamaCppLocalModelRunner(
        model_path=model_file, max_tokens=99, temperature=0.0
    )
    runner.generate_structured(
        system_prompt="SYSTEM", user_prompt="USER", schema=schema
    )
    call = fake_llama.instances[0].calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "USER"},
    ]
    assert call["response_format"] == {"type": "json_object", "schema": schema}
    assert call["max_tokens"] == 99
    assert call["temperature"] == 0.0
    assert call["stream"] is False


def test_valid_generation_returns_result(fake_llama, model_file):
    result = LlamaCppLocalModelRunner(model_path=model_file).generate_structured(
        system_prompt="s", user_prompt="u", schema={}
    )
    assert result.data == {"status": "ready"}
    assert result.model_name == "tiny-model.gguf"
    assert result.model_path == str(model_file)
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 7
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0


def test_missing_usage_is_safely_optional(fake_llama, model_file):
    fake_llama.response = {
        "choices": [{"message": {"content": '{"ok": true}'}}]
    }
    result = LlamaCppLocalModelRunner(model_path=model_file).generate_structured(
        system_prompt="s", user_prompt="u", schema={}
    )
    assert result.prompt_tokens is None
    assert result.completion_tokens is None


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[1, 2]", '"just a string"', "42", "null"],
    ids=["empty", "malformed", "array", "string", "number", "null"],
)
def test_invalid_content_rejected(fake_llama, model_file, content):
    fake_llama.response = {"choices": [{"message": {"content": content}}]}
    with pytest.raises(LocalModelInvalidOutput):
        LlamaCppLocalModelRunner(model_path=model_file).generate_structured(
            system_prompt="s", user_prompt="u", schema={}
        )


@pytest.mark.parametrize(
    "response",
    [{}, {"choices": []}, {"choices": [{}]}, {"choices": [{"message": {}}]}, "junk"],
    ids=["empty", "no-choices", "no-message", "no-content", "non-dict"],
)
def test_unsupported_response_shapes_rejected(fake_llama, model_file, response):
    fake_llama.response = response
    with pytest.raises(LocalModelInvalidOutput):
        LlamaCppLocalModelRunner(model_path=model_file).generate_structured(
            system_prompt="s", user_prompt="u", schema={}
        )


# --- Failure mapping -------------------------------------------------------------------


def test_generate_without_dependency_raises_typed_error(no_local_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    with pytest.raises(LocalModelDependencyMissing):
        LlamaCppLocalModelRunner(model_path="/x.gguf").generate_structured(
            system_prompt="s", user_prompt="u", schema={}
        )


def test_generate_without_path_raises_typed_error(fake_llama):
    with pytest.raises(LocalModelUnavailable):
        LlamaCppLocalModelRunner().generate_structured(
            system_prompt="s", user_prompt="u", schema={}
        )


def test_load_failure_maps_and_updates_availability_then_retries(
    fake_llama, model_file
):
    fake_llama.init_error = RuntimeError("bad magic bytes")
    runner = LlamaCppLocalModelRunner(model_path=model_file)
    with pytest.raises(LocalModelLoadFailed):
        runner.generate_structured(system_prompt="s", user_prompt="u", schema={})
    status = runner.availability()
    assert status.available is False
    assert status.reason == "model_load_failed"
    assert "bad magic bytes" in status.detail

    # A later call may retry after correction; success clears the state.
    fake_llama.init_error = None
    result = runner.generate_structured(
        system_prompt="s", user_prompt="u", schema={}
    )
    assert result.data == {"status": "ready"}
    assert runner.availability().available is True


def test_inference_failure_maps_to_generation_failed(fake_llama, model_file):
    fake_llama.call_error = RuntimeError("decode error")
    with pytest.raises(LocalModelGenerationFailed):
        LlamaCppLocalModelRunner(model_path=model_file).generate_structured(
            system_prompt="s", user_prompt="u", schema={}
        )


# --- Isolation guards ----------------------------------------------------------------


def test_llama_cpp_references_isolated_to_runner_module():
    for path in Path("experienceos").rglob("*.py"):
        if path.name == "local_runner.py":
            continue
        assert "llama_cpp" not in path.read_text(), f"llama_cpp leaked into {path}"


def test_runner_module_has_no_module_level_llama_import():
    for line in Path("experienceos/policy/local_runner.py").read_text().splitlines():
        assert not line.startswith(("import llama_cpp", "from llama_cpp")), line


def test_local_runner_module_makes_no_network_imports():
    text = Path("experienceos/policy/local_runner.py").read_text()
    for forbidden in ("requests", "httpx", "urllib.request", "huggingface_hub"):
        assert forbidden not in text


def test_root_import_and_rule_based_flow_without_llama(no_local_env):
    """Full isolation proof in a clean interpreter with llama_cpp blocked."""
    code = (
        "import sys; sys.modules['llama_cpp'] = None\n"
        "import experienceos\n"
        "from experienceos import ExperienceOS\n"
        "from experienceos.providers import MockProvider\n"
        "agent = ExperienceOS(model=MockProvider())\n"
        "agent.chat(user_id='u1', session_id='s1', "
        "message='I prefer aisle seats.')\n"
        "assert [m.text for m in agent.memories_for_user('u1')] == "
        "['Prefers aisle seats.']\n"
        "print('ISOLATED_OK')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
        env={**os.environ, "PYTHONPATH": "."},
    )
    assert completed.returncode == 0, completed.stderr
    assert "ISOLATED_OK" in completed.stdout


def test_smoke_example_skips_cleanly_when_unconfigured(
    no_local_env, monkeypatch, capsys
):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    from examples.local_runner_smoke import main

    assert main() == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert "dependency_missing" in out
