"""Phase 11 Prompt 5: selection identity and shadow diagnostics.

The core proof: for every retrieval mode, running with no gate, a
pass-through gate, a heuristic gate, an always-disagreeing gate, or a
failing gate yields an identical canonical result on the full
selection-relevant surface — only gate diagnostics differ.
"""

import pytest

from experienceos.context.builder import ContextBuilder
from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.context.semantic import SemanticCandidateGenerator
from experienceos.controllers.gate import (
    GateProposal,
    HeuristicShadowMemoryGate,
    PassThroughMemoryGate,
)
from experienceos.embeddings import DeterministicEmbeddingProvider
from experienceos.memory.schema import ExperienceEntry, MemoryStatus


def entry(text, status=MemoryStatus.ACTIVE):
    return ExperienceEntry(user_id="u1", text=text, status=status)


MEMORIES = (
    entry("prefers green tea daily"),
    entry("remember what you know about me"),  # semantic-only evidence
    entry("green tea supplies restock"),
    entry("budget spreadsheet"),
    entry("green tea remember", status=MemoryStatus.SUPERSEDED),
)
REQUEST = RetrievalRequest(
    query="green tea remember what you know",
    memories=MEMORIES, k=2, token_budget=60,
)


class AlwaysRejectGate:
    controller_id = "gate_test_reject-1"

    def evaluate(self, evidence):
        return GateProposal(
            proposal="reject", score=0.0, confidence=0.5,
            reason="test gate rejects everything",
            controller_id=self.controller_id,
        )


class AlwaysAdmitGate:
    controller_id = "gate_test_admit-1"

    def evaluate(self, evidence):
        return GateProposal(
            proposal="admit", score=1.0, confidence=0.5,
            reason="test gate admits everything",
            controller_id=self.controller_id,
        )


class ExplodingGate:
    controller_id = "gate_test_exploding-1"

    def evaluate(self, evidence):
        raise RuntimeError("boom")


def _strategy(mode, gate):
    if mode == "disabled":
        return HybridRetrievalStrategy(memory_gate=gate)
    kwargs = dict(
        semantic_generator=SemanticCandidateGenerator(
            DeterministicEmbeddingProvider()
        ),
        semantic_mode=mode,
        memory_gate=gate,
    )
    if mode == "fused":
        kwargs["fusion_profile"] = "full_fusion"
    return HybridRetrievalStrategy(**kwargs)


def _canonical_surface(result):
    return {
        "selected": [m.id for m in result.selected],
        "candidates": [
            (c.memory.id, c.rank, c.final_score, c.exclusion_reason,
             dict(c.component_scores), c.selected,
             c.semantic if c.semantic is None else dict(c.semantic),
             c.fusion if c.fusion is None else str(c.fusion))
            for c in result.candidates
        ],
        "tokens": result.context_token_estimate,
        "k_compliant": result.k_compliant,
        "budget_compliant": result.budget_compliant,
        "semantic": {
            k: v for k, v in result.semantic.items()
            if not isinstance(v, dict) or "elapsed_ms" not in v
        },
    }


GATES = [
    ("pass_through", PassThroughMemoryGate()),
    ("heuristic", HeuristicShadowMemoryGate()),
    ("always_reject", AlwaysRejectGate()),
    ("exploding", ExplodingGate()),
]


@pytest.mark.parametrize("mode", [
    "disabled", "score_only", "semantic_only", "fused",
])
@pytest.mark.parametrize("gate_name,gate", GATES)
def test_selection_identity_across_modes_and_gates(mode, gate_name, gate):
    baseline = _strategy(mode, None).retrieve(REQUEST)
    gated = _strategy(mode, gate).retrieve(REQUEST)
    assert _canonical_surface(baseline) == _canonical_surface(gated)
    assert baseline.gate == {}
    assert gated.gate["enabled"] is True
    assert gated.gate["affected_selection"] == 0


@pytest.mark.parametrize("mode", ["disabled", "fused"])
def test_rendered_context_identical_with_and_without_gate(mode):
    def build(gate):
        return ContextBuilder(
            memory_budget=2, retrieval_strategy=_strategy(mode, gate)
        ).build_context(
            user_id="u1", session_id="s1",
            message=REQUEST.query,
            memories=[m for m in MEMORIES if m.status == "active"],
        )

    assert build(None).messages == build(PassThroughMemoryGate()).messages
    assert build(None).messages == build(AlwaysRejectGate()).messages


def test_reject_proposal_leaves_memory_selected():
    result = _strategy("fused", AlwaysRejectGate()).retrieve(REQUEST)
    selected = [c for c in result.candidates if c.selected]
    assert selected  # canonical selection happened
    for candidate in selected:
        assert candidate.gate["proposal"] == "reject"
        assert candidate.gate["agreement_with_selection"] == "disagreement"
        assert candidate.selected is True  # unchanged
    assert result.gate["selected_proposed_reject"] == len(selected)
    assert result.gate["affected_selection"] == 0


def test_admit_proposal_leaves_skipped_memory_skipped():
    strategy = _strategy("fused", AlwaysAdmitGate())
    result = strategy.retrieve(REQUEST)
    skipped = [
        c for c in result.candidates
        if c.rank > 0 and not c.selected
    ]
    assert skipped  # K=2 forces skips
    for candidate in skipped:
        assert candidate.gate["proposal"] == "admit"
        assert candidate.gate["agreement_with_selection"] == "disagreement"
        assert candidate.selected is False  # unchanged
        assert candidate.exclusion_reason in ("not_top_k", "token_budget")
    assert result.gate["skipped_proposed_admit"] == len(skipped)


def test_admit_proposal_cannot_bypass_token_budget():
    long_text = "green tea " * 40
    request = RetrievalRequest(
        query="green tea",
        memories=(entry("green tea daily"), entry(long_text.strip())),
        k=2, token_budget=20,
    )
    baseline = _strategy("disabled", None).retrieve(request)
    gated = _strategy("disabled", AlwaysAdmitGate()).retrieve(request)
    over_budget = next(
        c for c in gated.candidates
        if c.exclusion_reason == "token_budget"
    )
    assert over_budget.gate["proposal"] == "admit"
    assert over_budget.selected is False
    assert gated.context_token_estimate == baseline.context_token_estimate
    assert gated.context_token_estimate <= 20


def test_gate_summary_counters_are_consistent():
    result = _strategy("fused", HeuristicShadowMemoryGate()).retrieve(
        REQUEST
    )
    summary = result.gate
    assert summary["evaluated"] == (
        summary["admit"] + summary["reject"] + summary["abstain"]
    )
    assert summary["evaluated"] == (
        summary["agreement"] + summary["disagreement"]
        + summary["neutral"]
    )
    assert summary["failures"] == 0
    assert summary["affected_selection"] == 0
    assert summary["controller_id"] == "gate_shadow_heuristic-1"
    assert summary["shadow_mode"] is True
    assert "elapsed_ms" in summary["evaluation"]
    ranked = [c for c in result.candidates if c.rank > 0]
    assert summary["evaluated"] == len(ranked)


def test_candidate_gate_fields_complete():
    result = _strategy("fused", HeuristicShadowMemoryGate()).retrieve(
        REQUEST
    )
    for candidate in result.candidates:
        if candidate.rank > 0:
            gate = candidate.gate
            assert gate["considered"] is True
            assert gate["proposal"] in ("admit", "reject", "abstain")
            assert 0.0 <= gate["score"] <= 1.0
            assert 0.0 <= gate["confidence"] <= 1.0
            assert gate["shadow_mode"] is True
            assert gate["affected_selection"] is False
            assert gate["canonical_selected"] == candidate.selected
            assert gate["agreement_with_selection"] in (
                "agreement", "disagreement", "neutral"
            )
        else:
            assert candidate.gate == {"considered": False}


def test_gate_double_run_is_deterministic():
    strategy = _strategy("fused", HeuristicShadowMemoryGate())
    def fingerprint(result):
        return [
            (c.memory.id,
             None if not c.gate or not c.gate.get("considered")
             else (c.gate["proposal"], c.gate["score"],
                   c.gate["confidence"]))
            for c in result.candidates
        ]
    first = strategy.retrieve(REQUEST)
    second = strategy.retrieve(REQUEST)
    assert fingerprint(first) == fingerprint(second)
    assert {k: v for k, v in first.gate.items() if k != "evaluation"} == {
        k: v for k, v in second.gate.items() if k != "evaluation"
    }


def test_gate_diagnostics_serialize_safely():
    import json

    result = _strategy("fused", HeuristicShadowMemoryGate()).retrieve(
        REQUEST
    )
    payload = json.dumps(
        {"summary": result.gate,
         "candidates": [c.gate for c in result.candidates]}
    )
    assert "/Users/" not in payload and "/home/" not in payload
    assert "[0." not in payload  # no vectors
    assert "Traceback" not in payload


def test_no_gate_configured_leaves_no_gate_fields():
    result = _strategy("fused", None).retrieve(REQUEST)
    assert result.gate == {}
    assert all(c.gate is None for c in result.candidates)
