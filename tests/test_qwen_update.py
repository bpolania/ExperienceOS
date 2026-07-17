"""Tests for the experimental Qwen update-intelligence controller.

Offline only: a stub provider returns canned JSON; no network, no
credentials, no live call. Verifies the five-class contract, strict
structured-output validation (fabricated / missing / extra targets,
malformed JSON, prose), bounded provider-failure handling with no
deterministic fallback, exactly one temperature-0 inference, and that
the controller and comparison harness hold no store or mutation
authority. Comparison-harness tests confirm both implementations run
over the same frozen cases and that rejected proposals never reach
mutation.
"""

from __future__ import annotations

import json

from experienceos.memory.store import MemoryStore
from experiments.qwen_update import (
    QWEN_UPDATE_CONTROLLER_ID,
    QWEN_UPDATE_PROMPT_VERSION,
    ActiveMemoryView,
    QwenUpdateController,
    STATUS_INVALID_OUTPUT,
    STATUS_OK,
    STATUS_PROVIDER_ERROR,
    STATUS_PROVIDER_UNAVAILABLE,
    build_qwen_update_controller,
    build_update_messages,
    parse_update_output,
)

TARGET_ID = "food.morning_drink"
ACTIVE = (
    ActiveMemoryView(TARGET_ID, "preference", "I prefer tea in the morning."),
    ActiveMemoryView("travel.home_airport", "fact", "My home airport is SJC."),
)
ALLOWED = frozenset(v.memory_id for v in ACTIVE)


class _StubProvider:
    """Provider returning canned text; counts inferences."""

    def __init__(self, output, *, configured=True):
        self._output = output
        self.is_configured = configured
        self.calls = 0
        self.last_messages = None

    def complete(self, messages):
        self.calls += 1
        self.last_messages = messages
        return self._output


def _json(classification, target=None):
    return json.dumps(
        {"classification": classification, "target_memory_id": target}
    )


def _controller(output, *, configured=True):
    return QwenUpdateController(_StubProvider(output, configured=configured))


def _classify(controller, message="Actually, I prefer coffee now."):
    return controller.classify(
        message=message,
        candidate_text=message,
        candidate_kind="preference",
        active_memories=ACTIVE,
    )


# -- 1. all five classifications parse ----------------------------------------


def test_all_five_classifications_parse():
    assert parse_update_output(_json("NEW"), ALLOWED) == ("NEW", None, None)
    assert parse_update_output(_json("COEXIST"), ALLOWED) == ("COEXIST", None, None)
    assert parse_update_output(_json("DUPLICATE"), ALLOWED) == ("DUPLICATE", None, None)
    assert parse_update_output(_json("IGNORE"), ALLOWED) == ("IGNORE", None, None)
    assert parse_update_output(_json("UPDATE", TARGET_ID), ALLOWED) == (
        "UPDATE", TARGET_ID, None,
    )


def test_valid_update_flows_through_controller():
    result = _controller(_json("UPDATE", TARGET_ID)).classify(
        message="Actually, I prefer coffee now.",
        candidate_text="Actually, I prefer coffee now.",
        candidate_kind="preference",
        active_memories=ACTIVE,
    )
    assert result.classification == "UPDATE"
    assert result.target_memory_id == TARGET_ID
    assert result.status == STATUS_OK
    assert result.failed is False
    assert result.controller_id == QWEN_UPDATE_CONTROLLER_ID
    assert result.proposal_only is True


# -- 2. UPDATE requires a supplied target -------------------------------------


def test_update_requires_a_target():
    cls, target, error = parse_update_output(_json("UPDATE", None), ALLOWED)
    assert cls is None and target is None
    assert error == "missing_target"


# -- 3. fabricated targets are rejected ---------------------------------------


def test_fabricated_target_is_rejected():
    cls, target, error = parse_update_output(
        _json("UPDATE", "totally.invented"), ALLOWED
    )
    assert cls is None and error == "fabricated_target"


def test_fabricated_target_becomes_invalid_output_result():
    result = _controller(_json("UPDATE", "nope.invented")).classify(
        message="x", candidate_text="x", candidate_kind=None,
        active_memories=ACTIVE,
    )
    assert result.status == STATUS_INVALID_OUTPUT
    assert result.classification is None
    assert result.target_memory_id is None
    assert result.failed is False  # invalid output is not a provider failure
    assert result.diagnostics.get("reason") == "fabricated_target"


# -- 4. missing UPDATE target rejected (covered) / 5. non-UPDATE target -------


def test_non_update_target_is_rejected():
    cls, target, error = parse_update_output(_json("NEW", TARGET_ID), ALLOWED)
    assert cls is None and error == "unexpected_target"
    cls, _, error = parse_update_output(_json("DUPLICATE", TARGET_ID), ALLOWED)
    assert cls is None and error == "unexpected_target"


# -- 6. malformed JSON rejected -----------------------------------------------


def test_malformed_json_is_rejected():
    cls, _, error = parse_update_output("not json at all", ALLOWED)
    assert cls is None and error == "malformed_json"


# -- 7. extra prose / markdown / extra keys rejected --------------------------


def test_markdown_wrapped_output_is_rejected():
    result = _controller("```json\n" + _json("NEW") + "\n```")
    r = _classify(result)
    assert r.status == STATUS_INVALID_OUTPUT
    assert r.diagnostics.get("reason") == "malformed_json"


def test_extra_keys_are_rejected():
    raw = json.dumps(
        {"classification": "NEW", "target_memory_id": None, "reason": "because"}
    )
    cls, _, error = parse_update_output(raw, ALLOWED)
    assert cls is None and error == "unexpected_keys"


def test_unknown_classification_is_rejected():
    cls, _, error = parse_update_output(_json("MERGE", None), ALLOWED)
    assert cls is None and error == "unknown_classification"


# -- 8. provider exception -> bounded explicit failure ------------------------


def test_provider_exception_is_bounded_failure_no_leak():
    class _Boom:
        is_configured = True

        def complete(self, messages):
            raise RuntimeError("secret-endpoint-419 down: I prefer coffee")

    result = QwenUpdateController(_Boom()).classify(
        message="I prefer coffee", candidate_text="I prefer coffee",
        candidate_kind="preference", active_memories=ACTIVE,
    )
    assert result.status == STATUS_PROVIDER_ERROR
    assert result.failed is True
    assert result.classification is None
    # Only the exception class name is recorded, never its message text.
    assert result.diagnostics.get("reason") == "RuntimeError"
    serialised = json.dumps(result.diagnostics)
    assert "secret-endpoint" not in serialised
    assert "coffee" not in serialised


def test_unavailable_provider_is_explicit_failure():
    class _Unconfigured:
        is_configured = False

        def complete(self, messages):
            raise AssertionError("must not be called")

    result = QwenUpdateController(_Unconfigured()).classify(
        message="x", candidate_text="x", candidate_kind=None,
        active_memories=ACTIVE,
    )
    assert result.status == STATUS_PROVIDER_UNAVAILABLE
    assert result.failed is True
    assert result.classification is None


# -- 9. no deterministic fallback ---------------------------------------------


def test_failure_never_produces_a_classification():
    class _Boom:
        is_configured = True

        def complete(self, messages):
            raise RuntimeError("down")

    result = QwenUpdateController(_Boom()).classify(
        message="Actually, I prefer coffee now.",
        candidate_text="Actually, I prefer coffee now.",
        candidate_kind="preference", active_memories=ACTIVE,
    )
    # A durable-looking correction still yields no classification, no
    # target, and no deterministic substitution.
    assert result.classification is None
    assert result.target_memory_id is None
    assert result.failed is True


# -- 10. exactly one inference / 11. temperature fixed at 0 -------------------


def test_exactly_one_inference():
    stub = _StubProvider(_json("NEW"))
    QwenUpdateController(stub).classify(
        message="x", candidate_text="x", candidate_kind=None,
        active_memories=ACTIVE,
    )
    assert stub.calls == 1


def test_builder_enforces_temperature_zero_and_timeout():
    controller = build_qwen_update_controller(api_key="k", timeout_ms=5000)
    provider = controller._provider
    assert provider.temperature == 0.0
    assert provider.timeout == 5.0


def test_injected_provider_call_is_temperature_zero_and_one_call():
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    provider = QwenCloudProvider(api_key="test-key", temperature=0.0)
    posted = {}

    def _fake_post(payload):
        posted["payload"] = payload
        return {"choices": [{"message": {"content": _json("UPDATE", TARGET_ID)}}]}

    provider._post = _fake_post
    result = QwenUpdateController(provider).classify(
        message="Actually, I prefer coffee now.",
        candidate_text="Actually, I prefer coffee now.",
        candidate_kind="preference", active_memories=ACTIVE,
    )
    assert result.classification == "UPDATE"
    assert posted["payload"]["temperature"] == 0.0
    assert len(posted["payload"]["messages"]) == 2  # system + user, one call


# -- 12. no persistence or mutation capability --------------------------------


def test_controller_holds_no_store_or_mutation():
    controller = _controller(_json("NEW"))
    for forbidden in ("memory_store", "engine", "experience_manager", "add",
                      "supersede", "forget", "_apply_memory_actions", "store"):
        assert not hasattr(controller, forbidden)


def test_prompt_is_deterministic_and_hides_internals():
    a = build_update_messages("m", "c", "preference", ACTIVE)
    b = build_update_messages("m", "c", "preference", ACTIVE)
    assert a == b  # deterministic
    system = a[0]["content"]
    for token in ("NEW", "UPDATE", "COEXIST", "DUPLICATE", "IGNORE"):
        assert token in system
    # No lifecycle/persistence/authorization internals are exposed.
    joined = (a[0]["content"] + a[1]["content"]).lower()
    for leak in ("lifecycle", "persistence", "authorization", "sqlite"):
        assert leak not in joined


# -- 13/14. strict validation boundary prevents downstream mutation ----------


def test_rejected_output_yields_no_target_for_downstream():
    # A rejected (invalid) classification carries no classification and no
    # target, so nothing downstream can act on it.
    result = _controller(_json("UPDATE", "fabricated.id")).classify(
        message="x", candidate_text="x", candidate_kind=None,
        active_memories=ACTIVE,
    )
    assert result.classification is None
    assert result.target_memory_id is None


def test_comparison_harness_mutates_no_memory():
    from experiments.qwen_update_benchmark import load_cases, run_comparison

    store = MemoryStore()
    before = len(store.list_memories("u"))
    provider = _StubProvider(_json("NEW"))
    cases = load_cases()[:4]
    data = run_comparison(provider, cases=cases)
    # A separate store is untouched: the harness holds no store and applies
    # nothing; both controllers are proposal-only.
    assert len(store.list_memories("u")) == before == 0
    assert data["qwen_safety"]["rejected_reaching_mutation_authority"] == 0
    assert data["qwen_safety"]["unsafe_proposals"] == 0


# -- 15. deterministic and Qwen run over the same frozen cases ----------------


def test_both_implementations_run_over_the_same_cases():
    from experiments.qwen_update_benchmark import load_cases, run_comparison

    provider = _StubProvider(_json("NEW"))
    cases = load_cases()
    data = run_comparison(provider, cases=cases)
    assert data["case_count"] == len(cases) == 48
    assert data["deterministic"]["cases"] == data["qwen"]["cases"] == 48
    # Deterministic side scores at ceiling on its own frozen corpus.
    assert data["deterministic"]["overall_accuracy"]["value"] == 1.0
    # Support totals are the frozen five-class distribution.
    assert data["class_support"] == {
        "NEW": 6, "UPDATE": 17, "COEXIST": 3, "DUPLICATE": 5, "IGNORE": 17,
    }


def test_results_json_strips_free_text():
    from experiments.qwen_update_benchmark import (
        load_cases, run_comparison, to_results_json,
    )

    provider = _StubProvider(_json("NEW"))
    data = run_comparison(provider, cases=load_cases()[:3])
    out = to_results_json(data)
    serialised = json.dumps(out)
    # Ids are retained; the raw source statements are not.
    assert "rows" in out
    assert "Actually, I prefer coffee" not in serialised


# -- config / identity --------------------------------------------------------


def test_controller_identity_and_prompt_version():
    assert QWEN_UPDATE_CONTROLLER_ID == "qwen_update-1"
    assert QWEN_UPDATE_PROMPT_VERSION == "1"
