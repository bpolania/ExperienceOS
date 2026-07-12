"""Phase 11 Prompt 5: gate failure containment tests."""

import pytest

from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.controllers.gate import (
    GateEvaluationError,
    GateProposal,
    GateProposalError,
)
from experienceos.memory.schema import ExperienceEntry

MEMORIES = (
    ExperienceEntry(user_id="u1", text="prefers green tea daily"),
    ExperienceEntry(user_id="u1", text="green tea supplies restock"),
)
REQUEST = RetrievalRequest(query="green tea", memories=MEMORIES, k=1)


class TypedErrorGate:
    controller_id = "gate_test_typed_error-1"

    def evaluate(self, evidence):
        raise GateProposalError("typed failure")


class RuntimeErrorGate:
    controller_id = "gate_test_runtime_error-1"

    def evaluate(self, evidence):
        raise RuntimeError("unexpected failure")


class NanScoreGate:
    controller_id = "gate_test_nan-1"

    def evaluate(self, evidence):
        return GateProposal(
            proposal="admit", score=float("nan"), confidence=1.0,
            reason="bad", controller_id=self.controller_id,
        )


class InvalidConfidenceGate:
    controller_id = "gate_test_confidence-1"

    def evaluate(self, evidence):
        return GateProposal(
            proposal="admit", score=1.0, confidence=7.0,
            reason="bad", controller_id=self.controller_id,
        )


class UnknownProposalGate:
    controller_id = "gate_test_unknown-1"

    def evaluate(self, evidence):
        return GateProposal(
            proposal="enforce", score=1.0, confidence=1.0,
            reason="bad", controller_id=self.controller_id,
        )


class NonSerializableDiagnosticsGate:
    controller_id = "gate_test_diagnostics-1"

    def evaluate(self, evidence):
        return GateProposal(
            proposal="admit", score=1.0, confidence=1.0, reason="bad",
            controller_id=self.controller_id,
            diagnostics={"handle": object()},
        )


class WrongTypeGate:
    controller_id = "gate_test_wrong_type-1"

    def evaluate(self, evidence):
        return {"proposal": "admit"}  # not a GateProposal


FAILING_GATES = [
    TypedErrorGate(), RuntimeErrorGate(), NanScoreGate(),
    InvalidConfidenceGate(), UnknownProposalGate(),
    NonSerializableDiagnosticsGate(), WrongTypeGate(),
]


def _surface(result):
    return (
        [m.id for m in result.selected],
        [(c.memory.id, c.rank, c.final_score, c.exclusion_reason)
         for c in result.candidates],
        result.context_token_estimate,
    )


@pytest.mark.parametrize(
    "gate", FAILING_GATES, ids=lambda g: g.controller_id
)
def test_every_failure_is_contained_by_default(gate):
    baseline = HybridRetrievalStrategy().retrieve(REQUEST)
    result = HybridRetrievalStrategy(memory_gate=gate).retrieve(REQUEST)
    assert _surface(result) == _surface(baseline)
    assert result.gate["status"] == "failed"
    assert result.gate["failures"] == 2  # both ranked candidates
    assert result.gate["evaluated"] == 0
    assert result.gate["affected_selection"] == 0
    assert result.gate["first_failure"]  # exception type recorded
    for candidate in result.candidates:
        if candidate.rank > 0:
            assert candidate.gate["status"] == "failed"
            assert "proposal" not in candidate.gate  # never fabricated
            assert candidate.gate["affected_selection"] is False


def test_failure_diagnostics_are_sanitized():
    result = HybridRetrievalStrategy(
        memory_gate=RuntimeErrorGate()
    ).retrieve(REQUEST)
    import json

    payload = json.dumps(
        {"summary": result.gate,
         "candidates": [c.gate for c in result.candidates]}
    )
    assert "Traceback" not in payload
    assert "/Users/" not in payload and "/home/" not in payload
    assert "unexpected failure" not in payload  # message withheld
    assert "RuntimeError" in payload  # type name is the evidence


def test_failure_does_not_mutate_memories():
    snapshot = [(m.id, m.status, m.text, m.updated_at) for m in MEMORIES]
    HybridRetrievalStrategy(memory_gate=RuntimeErrorGate()).retrieve(
        REQUEST
    )
    assert [
        (m.id, m.status, m.text, m.updated_at) for m in MEMORIES
    ] == snapshot


def test_strict_mode_raises_typed_error_after_canonical_completion():
    strategy = HybridRetrievalStrategy(
        memory_gate=RuntimeErrorGate(), gate_strict=True
    )
    with pytest.raises(GateEvaluationError) as excinfo:
        strategy.retrieve(REQUEST)
    assert "RuntimeError" in str(excinfo.value)


def test_partial_failure_contains_only_failing_candidates():
    class FailOnceGate:
        controller_id = "gate_test_fail_once-1"

        def __init__(self):
            self.calls = 0

        def evaluate(self, evidence):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first call fails")
            return GateProposal(
                proposal="admit", score=1.0, confidence=1.0,
                reason="ok", controller_id=self.controller_id,
            )

    result = HybridRetrievalStrategy(memory_gate=FailOnceGate()).retrieve(
        REQUEST
    )
    assert result.gate["failures"] == 1
    assert result.gate["evaluated"] == 1
    statuses = sorted(
        c.gate["status"] for c in result.candidates if c.rank > 0
    )
    assert statuses == ["evaluated", "failed"]
