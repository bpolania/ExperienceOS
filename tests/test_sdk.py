"""SDK shape and interaction lifecycle tests."""

from experienceos import ExperienceOS
from experienceos.providers import MockProvider


def test_constructor_shape():
    agent = ExperienceOS(model=MockProvider())
    assert agent.model.name == "mock"


def test_wrap_returns_usable_agent():
    agent = ExperienceOS.wrap(MockProvider())
    assert isinstance(agent, ExperienceOS)
    response = agent.chat(user_id="u1", session_id="s1", message="hello")
    assert isinstance(response, str)


def test_chat_returns_string():
    agent = ExperienceOS(model=MockProvider(canned_response="hi"))
    assert agent.chat(user_id="u1", session_id="s1", message="hello") == "hi"


def test_memory_flow_works_with_qwen_provider_mocked(monkeypatch):
    """The same experience lifecycle runs behind QwenCloudProvider (no network)."""
    from experienceos.providers import QwenCloudProvider

    provider = QwenCloudProvider(api_key="test-key")
    monkeypatch.setattr(
        provider,
        "_post",
        lambda payload: {"choices": [{"message": {"content": "Noted!"}}]},
    )
    agent = ExperienceOS(model=provider)
    response = agent.chat(
        user_id="u1", session_id="s1", message="I prefer aisle seats."
    )
    assert response == "Noted!"
    assert [m.text for m in agent.memories_for_user("u1")] == ["Prefers aisle seats."]


def test_context_builder_is_called_during_chat():
    class SpyBuilder:
        def __init__(self):
            self.calls = []

        def build_context(self, user_id, session_id, message, memories=None):
            self.calls.append((user_id, session_id, message))
            return [{"role": "system", "content": "spy context"}]

    spy = SpyBuilder()
    agent = ExperienceOS(model=MockProvider(), context_builder=spy)
    agent.chat(user_id="u1", session_id="s1", message="hello")
    assert spy.calls == [("u1", "s1", "hello")]
