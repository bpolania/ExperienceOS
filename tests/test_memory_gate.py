"""Phase 11 Prompt 5: MemoryGate contract, proposal, and gate tests."""

import json
import subprocess
import sys

import pytest

from experienceos.controllers.gate import (
    GATE_PROPOSALS,
    GateCandidateEvidence,
    GateProposal,
    GateProposalError,
    HeuristicShadowMemoryGate,
    PassThroughMemoryGate,
)


def evidence(**overrides):
    base = dict(
        query="green tea preference",
        memory_id="m1",
        memory_kind="preference",
        memory_text="prefers green tea daily",
        lifecycle_status="active",
        canonical_selected=True,
        canonical_rank=1,
        exclusion_reason=None,
        token_estimate=6,
        component_scores={"lexical_score": 3.2, "phrase_score": 0.0,
                          "entity_score": 0.0},
        semantic=None,
        fusion=None,
        retrieval_mode="disabled",
        fusion_profile_id=None,
    )
    base.update(overrides)
    return GateCandidateEvidence(**base)


# -- proposal validation ----------------------------------------------------------


def test_proposal_values_are_fixed():
    assert GATE_PROPOSALS == ("admit", "reject", "abstain")


def test_valid_proposal_constructs_and_serializes():
    proposal = GateProposal(
        proposal="admit", score=0.8, confidence=0.9, reason="ok",
        controller_id="gate_test-1", diagnostics={"rule": "x"},
    )
    assert proposal.shadow_mode is True
    assert proposal.affected_selection is False
    json.dumps(proposal.diagnostics)


@pytest.mark.parametrize("bad", [
    dict(proposal="approve"),
    dict(score=float("nan")),
    dict(score=1.5),
    dict(score=-0.1),
    dict(confidence=float("inf")),
    dict(confidence=2.0),
    dict(shadow_mode=False),
    dict(affected_selection=True),
    dict(controller_id=""),
    dict(reason="x" * 301),
    dict(diagnostics={"obj": object()}),
])
def test_invalid_proposals_rejected(bad):
    base = dict(
        proposal="admit", score=0.5, confidence=0.5, reason="r",
        controller_id="gate_test-1",
    )
    base.update(bad)
    with pytest.raises(GateProposalError):
        GateProposal(**base)


def test_proposal_is_immutable():
    proposal = GateProposal(
        proposal="abstain", score=0.1, confidence=0.3, reason="r",
        controller_id="gate_test-1",
    )
    with pytest.raises(Exception):
        proposal.proposal = "admit"


def test_gate_interfaces_expose_no_mutation_methods():
    for cls in (PassThroughMemoryGate, HeuristicShadowMemoryGate):
        surface = {name for name in dir(cls) if not name.startswith("_")}
        assert surface == {"controller_id", "evaluate"} or surface <= {
            "controller_id", "evaluate",
        }, surface


# -- evidence ---------------------------------------------------------------------


def test_evidence_is_immutable_and_bounds_text():
    long_text = "x" * 1000
    snapshot = evidence(memory_text=long_text)
    assert len(snapshot.memory_text) == 300
    with pytest.raises(Exception):
        snapshot.memory_id = "other"


def test_evidence_holds_primitives_not_memory_objects():
    from dataclasses import fields

    names = {f.name for f in fields(GateCandidateEvidence)}
    assert "memory" not in names
    assert "store" not in names
    assert names == {
        "query", "memory_id", "memory_kind", "memory_text",
        "lifecycle_status", "canonical_selected", "canonical_rank",
        "exclusion_reason", "token_estimate", "component_scores",
        "semantic", "fusion", "retrieval_mode", "fusion_profile_id",
    }


# -- pass-through gate ------------------------------------------------------------


def test_pass_through_admits_everything_deterministically():
    gate = PassThroughMemoryGate()
    assert gate.controller_id == "gate_pass_through-1"
    first = gate.evaluate(evidence())
    second = PassThroughMemoryGate().evaluate(evidence())
    assert first == second
    assert first.proposal == "admit"
    assert first.score == 1.0
    assert first.confidence == 1.0
    assert first.shadow_mode is True
    assert first.affected_selection is False


def test_pass_through_stable_across_processes():
    script = (
        "from experienceos.controllers.gate import ("
        "PassThroughMemoryGate, GateCandidateEvidence)\n"
        "e = GateCandidateEvidence(query='q', memory_id='m',"
        "memory_kind='fact', memory_text='t', lifecycle_status='active',"
        "canonical_selected=True, canonical_rank=1,"
        "exclusion_reason=None, token_estimate=1)\n"
        "p = PassThroughMemoryGate().evaluate(e)\n"
        "print(p.proposal, p.score, p.confidence)\n"
    )
    import os

    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True,
        check=True, env=dict(os.environ, PYTHONPATH="."),
    )
    assert completed.stdout.strip() == "admit 1.0 1.0"


# -- heuristic gate ---------------------------------------------------------------


def test_heuristic_admits_high_precision_evidence():
    proposal = HeuristicShadowMemoryGate().evaluate(
        evidence(component_scores={"lexical_score": 2.0,
                                   "phrase_score": 1.0,
                                   "entity_score": 0.0})
    )
    assert proposal.proposal == "admit"
    assert proposal.confidence == 0.9
    assert proposal.diagnostics["rule"] == "strong_evidence"


def test_heuristic_admits_dual_evidence_source():
    proposal = HeuristicShadowMemoryGate().evaluate(
        evidence(
            retrieval_mode="fused",
            fusion={"fused_score": 0.2,
                    "evidence_source": "lexical_and_semantic"},
        )
    )
    assert proposal.proposal == "admit"


def test_heuristic_rejects_near_floor_semantic_only():
    proposal = HeuristicShadowMemoryGate().evaluate(
        evidence(
            canonical_selected=False,
            retrieval_mode="fused",
            component_scores={},
            semantic={"considered": True, "score": 0.34,
                      "relevance_floor": 0.30},
            fusion={"fused_score": 0.102,
                    "evidence_source": "semantic_only"},
        )
    )
    assert proposal.proposal == "reject"
    assert proposal.confidence == 0.6
    assert proposal.diagnostics["rule"] == "near_floor_semantic"


def test_heuristic_abstains_on_ambiguous_evidence():
    proposal = HeuristicShadowMemoryGate().evaluate(
        evidence(component_scores={"lexical_score": 0.9})
    )
    assert proposal.proposal == "abstain"
    assert proposal.confidence == 0.3
    assert proposal.diagnostics["rule"] == "ambiguous"


def test_heuristic_is_deterministic_and_reconstructable():
    snapshot = evidence(
        retrieval_mode="fused",
        fusion={"fused_score": 0.41, "evidence_source": "lexical_only"},
    )
    gate = HeuristicShadowMemoryGate()
    first = gate.evaluate(snapshot)
    second = HeuristicShadowMemoryGate().evaluate(snapshot)
    assert first == second
    assert first.diagnostics["strength"] == 0.41
    assert first.diagnostics["rule_version"] == "gate_shadow_heuristic-1"
