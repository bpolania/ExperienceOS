"""Provider abstraction tests. All offline — no network calls."""

import pytest

from experienceos.providers import (
    MockProvider,
    ModelProvider,
    QwenCloudConfigurationError,
    QwenCloudProvider,
)

QWEN_ENV_VARS = (
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "QWEN_BASE_URL",
    "DASHSCOPE_BASE_URL",
    "QWEN_MODEL",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in QWEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_mock_is_a_provider():
    assert isinstance(MockProvider(), ModelProvider)


def test_mock_completes_offline():
    response = MockProvider().complete([{"role": "user", "content": "ping"}])
    assert "ping" in response
    assert "ExperienceOS" in response


def test_mock_canned_response():
    assert MockProvider(canned_response="hi").complete([]) == "hi"


def test_qwen_constructible_without_credentials(clean_env):
    provider = QwenCloudProvider()
    assert isinstance(provider, ModelProvider)
    assert provider.is_configured is False


def test_qwen_constructible_from_explicit_config(clean_env):
    provider = QwenCloudProvider(
        api_key="test-key", base_url="https://example.test/v1", model="qwen-max"
    )
    assert provider.is_configured is True
    assert provider.api_key == "test-key"
    assert provider.base_url == "https://example.test/v1"
    assert provider.model == "qwen-max"


def test_qwen_constructible_from_qwen_env_vars(clean_env):
    clean_env.setenv("QWEN_API_KEY", "env-key")
    clean_env.setenv("QWEN_BASE_URL", "https://env.test/v1/")
    clean_env.setenv("QWEN_MODEL", "qwen-turbo")
    provider = QwenCloudProvider()
    assert provider.api_key == "env-key"
    assert provider.base_url == "https://env.test/v1"
    assert provider.model == "qwen-turbo"


def test_qwen_dashscope_env_fallback(clean_env):
    clean_env.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    provider = QwenCloudProvider()
    assert provider.api_key == "dashscope-key"


def test_qwen_explicit_config_beats_env(clean_env):
    clean_env.setenv("QWEN_API_KEY", "env-key")
    provider = QwenCloudProvider(api_key="explicit-key")
    assert provider.api_key == "explicit-key"


def test_qwen_complete_without_credentials_raises_helpful_error(clean_env):
    provider = QwenCloudProvider()
    with pytest.raises(QwenCloudConfigurationError, match="QWEN_API_KEY"):
        provider.complete([{"role": "user", "content": "ping"}])


def test_qwen_complete_sends_openai_compatible_payload(clean_env, monkeypatch):
    provider = QwenCloudProvider(api_key="k", model="qwen-plus", temperature=0.2)
    sent = {}

    def fake_post(payload):
        sent.update(payload)
        return {"choices": [{"message": {"content": "Booked it."}}]}

    monkeypatch.setattr(provider, "_post", fake_post)
    messages = [
        {"role": "system", "content": "ExperienceOS is active."},
        {"role": "user", "content": "Help me book a trip."},
    ]
    response = provider.complete(messages)
    assert response == "Booked it."
    assert sent["model"] == "qwen-plus"
    assert sent["messages"] == messages
    assert sent["temperature"] == 0.2


def test_qwen_unexpected_response_shape_raises(clean_env, monkeypatch):
    provider = QwenCloudProvider(api_key="k")
    monkeypatch.setattr(provider, "_post", lambda payload: {"choices": []})
    with pytest.raises(RuntimeError, match="Qwen Cloud request failed"):
        provider.complete([{"role": "user", "content": "ping"}])


def test_qwen_parses_content_parts_list(clean_env, monkeypatch):
    provider = QwenCloudProvider(api_key="k")
    monkeypatch.setattr(
        provider,
        "_post",
        lambda payload: {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Hello "},
                            {"type": "text", "text": "there."},
                        ]
                    }
                }
            ]
        },
    )
    assert provider.complete([{"role": "user", "content": "hi"}]) == "Hello there."


def test_qwen_empty_content_raises(clean_env, monkeypatch):
    provider = QwenCloudProvider(api_key="k")
    monkeypatch.setattr(
        provider,
        "_post",
        lambda payload: {"choices": [{"message": {"content": ""}}]},
    )
    with pytest.raises(RuntimeError, match="empty assistant content"):
        provider.complete([{"role": "user", "content": "hi"}])


def test_qwen_non_secret_defaults(clean_env):
    provider = QwenCloudProvider()
    assert provider.model == "qwen-plus"
    assert provider.base_url == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )


def test_mock_flow_unaffected_by_missing_credentials(clean_env):
    from experienceos import ExperienceOS

    agent = ExperienceOS(model=MockProvider())
    response = agent.chat(user_id="u1", session_id="s1", message="hello")
    assert "ExperienceOS" in response


def test_core_modules_have_no_qwen_coupling():
    """The SDK core never imports or configures the Qwen adapter.

    Usage examples in docstrings are fine; imports, env-var names, and
    endpoint references are not.
    """
    import re
    from pathlib import Path

    core = Path("experienceos")
    core_files = [
        core / "__init__.py",
        core / "sdk.py",
        *(core / "engine").glob("*.py"),
        *(core / "context").glob("*.py"),
        *(core / "memory").glob("*.py"),
        *(core / "events").glob("*.py"),
    ]
    forbidden = re.compile(
        r"import\s+\w*qwen|from\s+experienceos\.providers\.qwen"
        r"|QWEN_API|DASHSCOPE|dashscope|compatible-mode",
        re.IGNORECASE,
    )
    for path in core_files:
        assert not forbidden.search(path.read_text()), f"Qwen coupling in {path}"


def test_live_demo_unconfigured_exits_cleanly(clean_env, capsys):
    from examples.qwen_live_demo import configuration_lines, main

    assert main() == 1
    out = capsys.readouterr().out
    assert "API key: missing" in out
    assert "QWEN_API_KEY" in out
    assert "memory_demo.py" in out

    provider = QwenCloudProvider(api_key="secret-key", model="qwen-max")
    lines = configuration_lines(provider)
    assert "API key: set" in lines
    assert "Model: qwen-max" in lines
    assert all("secret-key" not in line for line in lines)
