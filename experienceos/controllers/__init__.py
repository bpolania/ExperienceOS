"""Specialized controller seams (Phase 11).

Controllers propose; the deterministic ExperienceOS kernel decides.
Prompt 5 introduces the shadow-only MemoryGate; the remaining
controller contracts (admission, extraction, update, forget-intent,
transition verification) arrive in Prompt 6. No controller receives a
store, engine, manager, bus, or mutation handle.
"""

from experienceos.controllers.gate import (
    GATE_PROPOSALS,
    GateCandidateEvidence,
    GateError,
    GateEvaluationError,
    GateProposal,
    GateProposalError,
    HeuristicShadowMemoryGate,
    MemoryGate,
    PassThroughMemoryGate,
)

__all__ = [
    "GATE_PROPOSALS",
    "GateCandidateEvidence",
    "GateError",
    "GateEvaluationError",
    "GateProposal",
    "GateProposalError",
    "HeuristicShadowMemoryGate",
    "MemoryGate",
    "PassThroughMemoryGate",
]
