"""Pure, deterministic canonical action replacement.

This package answers, without ever mutating anything, which planner
action a verified transition replacement would replace. It performs no
action-list rewriting, no suppression, no authorization, and no durable
mutation — those remain the engine's authority. Later work consumes
:class:`ReplacementDecision` to build and apply an explicit plan.
"""

from experienceos.memory.action_replacement.identity import (
    ACTION_IDENTITY_VERSION,
    CANDIDATE_EXTRACTION,
    CANDIDATE_OTHER,
    CANDIDATE_PLANNER,
    CANDIDATE_TRANSITION,
    OccurrenceIdentity,
    PlannerActionIdentity,
    action_content_digest,
    action_list_digest,
    occurrence_identity,
    planner_action_identity,
)
from experienceos.memory.action_replacement.planner import (
    NO_REPLACEMENT_NEEDED,
    REJECTED_BEFORE_STATE,
    REJECTED_INTERNAL,
    REJECTED_MULTIPLE_MATCHES,
    REJECTED_NO_MATCH,
    REJECTED_SCOPE_CONFLICT,
    REJECTED_UNRELATED_ACTION,
    REJECTED_UNSUPPORTED,
    REJECTED_VERIFICATION,
    REPLACEMENT_DECISIONS,
    REPLACEMENT_READY,
    ActionReplacementPlanner,
    ReplacementCandidate,
    ReplacementDecision,
    ReplacementDiagnostic,
    ReplacementMatch,
    VerifiedTransition,
)

__all__ = [
    "ACTION_IDENTITY_VERSION",
    "CANDIDATE_PLANNER",
    "CANDIDATE_EXTRACTION",
    "CANDIDATE_TRANSITION",
    "CANDIDATE_OTHER",
    "OccurrenceIdentity",
    "PlannerActionIdentity",
    "action_content_digest",
    "action_list_digest",
    "occurrence_identity",
    "planner_action_identity",
    "ActionReplacementPlanner",
    "ReplacementCandidate",
    "ReplacementDecision",
    "ReplacementDiagnostic",
    "ReplacementMatch",
    "VerifiedTransition",
    "NO_REPLACEMENT_NEEDED",
    "REPLACEMENT_READY",
    "REJECTED_NO_MATCH",
    "REJECTED_MULTIPLE_MATCHES",
    "REJECTED_SCOPE_CONFLICT",
    "REJECTED_UNRELATED_ACTION",
    "REJECTED_BEFORE_STATE",
    "REJECTED_VERIFICATION",
    "REJECTED_UNSUPPORTED",
    "REJECTED_INTERNAL",
    "REPLACEMENT_DECISIONS",
]
