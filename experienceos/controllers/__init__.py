"""Specialized controller seams.

Controllers propose; the deterministic ExperienceOS kernel validates
and decides. The shadow-only MemoryGate is the only
meaningfully integrated controller. Additional interface-only,
proposal-only contracts cover admission, extraction, update,
forget-intent, and transition verification, with deterministic
abstaining/no-op defaults; none participates in canonical behavior. No
controller receives a store, engine, manager, bus, or mutation handle,
and no proposal is ever automatically applied. See
``docs/controller_architecture.md``.
"""

from experienceos.controllers.admission import (
    ADMISSION_RECOMMENDATIONS,
    AbstainingAdmissionController,
    AdmissionController,
    AdmissionEvidence,
    AdmissionProposal,
)
from experienceos.controllers.base import (
    ControllerError,
    ControllerInputError,
    ControllerProposalError,
    ControllerUnavailableError,
    EvidenceSpan,
    LIFECYCLE_STATUSES,
    MEMORY_KINDS,
    MemorySnapshot,
    RUNTIME_MODES,
)
from experienceos.controllers.extraction import (
    EXTRACTION_RECOMMENDATIONS,
    ExtractionController,
    ExtractionEvidence,
    ExtractionProposal,
    NoOpExtractionController,
    ProposedMemoryCandidate,
)
from experienceos.controllers.forget import (
    FORGET_RECOMMENDATIONS,
    ForgetIntentController,
    ForgetIntentEvidence,
    ForgetIntentProposal,
    NoForgetIntentController,
)
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
from experienceos.controllers.transition import (
    TRANSITION_RECOMMENDATIONS,
    TRANSITION_TYPES,
    AbstainingTransitionVerifier,
    TransitionEvidence,
    TransitionProposal,
    TransitionVerifier,
)
from experienceos.controllers.update import (
    RELATIONSHIPS_REQUIRING_TARGET,
    UPDATE_RELATIONSHIPS,
    AbstainingUpdateController,
    UpdateController,
    UpdateEvidence,
    UpdateProposal,
)

__all__ = [
    "ADMISSION_RECOMMENDATIONS",
    "AbstainingAdmissionController",
    "AbstainingTransitionVerifier",
    "AbstainingUpdateController",
    "AdmissionController",
    "AdmissionEvidence",
    "AdmissionProposal",
    "ControllerError",
    "ControllerInputError",
    "ControllerProposalError",
    "ControllerUnavailableError",
    "EXTRACTION_RECOMMENDATIONS",
    "EvidenceSpan",
    "ExtractionController",
    "ExtractionEvidence",
    "ExtractionProposal",
    "FORGET_RECOMMENDATIONS",
    "ForgetIntentController",
    "ForgetIntentEvidence",
    "ForgetIntentProposal",
    "GATE_PROPOSALS",
    "GateCandidateEvidence",
    "GateError",
    "GateEvaluationError",
    "GateProposal",
    "GateProposalError",
    "HeuristicShadowMemoryGate",
    "LIFECYCLE_STATUSES",
    "MEMORY_KINDS",
    "MemoryGate",
    "MemorySnapshot",
    "NoForgetIntentController",
    "NoOpExtractionController",
    "PassThroughMemoryGate",
    "ProposedMemoryCandidate",
    "RELATIONSHIPS_REQUIRING_TARGET",
    "RUNTIME_MODES",
    "TRANSITION_RECOMMENDATIONS",
    "TRANSITION_TYPES",
    "TransitionEvidence",
    "TransitionProposal",
    "TransitionVerifier",
    "UPDATE_RELATIONSHIPS",
    "UpdateController",
    "UpdateEvidence",
    "UpdateProposal",
]
