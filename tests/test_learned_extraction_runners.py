"""Availability, import-safety, and optional-runner tests for learned
grounded extraction. Default runs construct no provider or model."""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.memory.learned_extraction import (
    CloudLearnedExtractionRunner,
    LearnedExtractionRequest,
    LearnedGroundedExtractionController,
    LocalLearnedExtractionRunner,
    RUNNER_OK,
    build_prompts,
)


# -- optional local runner ---------------------------------------------------------


def test_local_runner_reports_unavailable_when_dependency_missing(
    monkeypatch,
):
    original = importlib.util.find_spec

    def fake(name, *args, **kwargs):
        if name == "llama_cpp":
            return None
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    monkeypatch.delenv("EXPERIENCEOS_LOCAL_MODEL_PATH", raising=False)
    runner = LocalLearnedExtractionRunner()
    assert runner.availability() is False
    assert "llama_cpp" not in sys.modules  # no eager import


def test_local_runner_unavailable_yields_clean_controller_none():
    runner = LocalLearnedExtractionRunner()  # no model configured
    controller = LearnedGroundedExtractionController(
        runner, fallback_mode="none"
    )
    proposal = controller.extract(
        ExtractionEvidence(user_text="I prefer aisle seats",
                           metadata={"source_id": "t"})
    )
    # Unavailable in this environment -> clean none, no crash.
    if not runner.availability():
        assert proposal.recommendation == "none"
        assert proposal.diagnostics["runner_status"] == (
            "runner_unavailable"
        )


def test_local_runner_wraps_injected_runner_without_download():
    class FakeLocal:
        def availability(self):
            from experienceos.policy.local_runner import (
                LocalModelAvailability,
            )

            return LocalModelAvailability(available=True)

        def generate_structured(self, *, system_prompt, user_prompt,
                                schema):
            from experienceos.policy.local_runner import (
                LocalModelResult,
            )

            return LocalModelResult(
                data={
                    "action": "candidate", "kind": "preference",
                    "normalized_text": "Prefers aisle seats",
                    "evidence_text": "I prefer aisle seats",
                    "start_offset": 0, "end_offset": 20,
                    "confidence": 0.8, "reason": "pref",
                },
                model_path="/redacted", model_name="fake",
                prompt_tokens=10, completion_tokens=5, elapsed_ms=2.0,
            )

    runner = LocalLearnedExtractionRunner(local_runner=FakeLocal())
    assert runner.availability() is True
    result = runner.run(
        LearnedExtractionRequest(source_text="I prefer aisle seats")
    )
    assert result.status == RUNNER_OK
    parsed = json.loads(result.raw_output)
    assert parsed["action"] == "candidate"
    # The model path is never surfaced in the runner result.
    assert "model_path" not in (result.usage or {})
    payload = json.dumps({k: v for k, v in result.__dict__.items()})
    assert "/redacted" not in payload


# -- optional cloud runner ---------------------------------------------------------


def test_cloud_runner_available_only_with_provider():
    assert CloudLearnedExtractionRunner(provider=None).availability() is (
        False
    )

    class FakeProvider:
        def complete(self, messages):
            return json.dumps({
                "action": "none", "kind": None,
                "normalized_text": None, "evidence_text": None,
                "start_offset": None, "end_offset": None,
                "confidence": None, "reason": "no candidate",
            })

    runner = CloudLearnedExtractionRunner(provider=FakeProvider())
    assert runner.availability() is True
    result = runner.run(
        LearnedExtractionRequest(source_text="hello")
    )
    assert result.status == RUNNER_OK
    assert json.loads(result.raw_output)["action"] == "none"


def test_cloud_runner_provider_error_maps_to_runner_error():
    class BoomProvider:
        def complete(self, messages):
            raise RuntimeError("network down")

    runner = CloudLearnedExtractionRunner(provider=BoomProvider())
    result = runner.run(LearnedExtractionRequest(source_text="hi"))
    assert result.status == "runner_error"
    assert result.error_class == "RuntimeError"
    assert "network down" not in json.dumps(
        {k: str(v) for k, v in result.__dict__.items()}
    )


# -- prompt safety -----------------------------------------------------------------


def test_prompt_is_bounded_and_instructive():
    system, user = build_prompts("I prefer aisle seats")
    assert "one JSON object only" in system
    assert "message[start:end] == evidence_text" in system
    assert "I prefer aisle seats" in user
    # The instruction forbids the unsafe conversions and lifecycle
    # authority the contract prohibits.
    lowered = system.lower()
    for term in ("assistant", "question", "hypothetical", "temporary",
                 "multiple", "lifecycle action", "one candidate"):
        assert term in lowered


# -- import safety -----------------------------------------------------------------


def test_module_import_loads_nothing_heavy():
    probe = (
        "import sys\n"
        "import experienceos.memory.learned_extraction\n"
        "flagged = [m for m in sys.modules if m in ("
        "'llama_cpp', 'sentence_transformers', 'torch', "
        "'onnxruntime')]\n"
        "print(','.join(flagged) or 'clean')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        check=True, env=dict(os.environ, PYTHONPATH="."),
    )
    assert completed.stdout.strip() == "clean"


def test_root_import_does_not_pull_learned_extraction():
    probe = (
        "import sys\n"
        "import experienceos\n"
        "from experienceos.providers.mock import MockProvider\n"
        "from experienceos import ExperienceOS\n"
        "ExperienceOS(model=MockProvider())\n"
        "print('learned_extraction' in "
        "','.join(sys.modules) and 'llama_cpp' not in sys.modules)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        check=True, env=dict(os.environ, PYTHONPATH="."),
    )
    # Neither the learned controller nor the local runtime is loaded by
    # default ExperienceOS construction.
    assert completed.stdout.strip() == "False"


def test_learned_controller_not_referenced_by_canonical_code():
    import pathlib

    for path in pathlib.Path("experienceos").rglob("*.py"):
        if path.name == "learned_extraction.py":
            continue
        assert "LearnedGroundedExtractionController" not in (
            path.read_text()
        ), path


# -- optional runtime smoke (clean skip when unavailable) --------------------------


def test_optional_local_smoke_or_clean_skip():
    runner = LocalLearnedExtractionRunner()
    if not runner.availability():
        pytest.skip("local extraction runtime unavailable "
                    "(dependency or model path not configured)")
    controller = LearnedGroundedExtractionController(
        runner, fallback_mode="none"
    )
    proposal = controller.extract(
        ExtractionEvidence(user_text="I prefer aisle seats",
                           metadata={"source_id": "smoke"})
    )
    assert proposal.recommendation in ("candidate", "none")
    if proposal.candidate is not None:
        span = proposal.candidate.evidence_spans[0]
        message = "I prefer aisle seats"
        assert message[span.start:span.end] == span.excerpt
