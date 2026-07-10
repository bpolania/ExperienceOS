"""Memory policy contract: bounded inputs, validated proposals.

A memory policy proposes lifecycle changes; it never mutates storage.
The ExperienceManager validates and normalizes proposals, the
ExperienceEngine validates lifecycle targets and applies mutations, and
the MemoryStore persists them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from experienceos.memory.schema import ExperienceEntry, MemoryKind


class PolicyAction:
    """Proposal actions, matching the engine's lifecycle vocabulary."""

    CREATE = "create"
    SUPERSEDE = "supersede"
    FORGET = "forget"
    NOOP = "noop"


class DecisionSource:
    """Where a memory decision came from."""

    RULE_BASED = "rule_based"
    LOCAL_MODEL = "local_model"
    FALLBACK = "fallback"


class FallbackReason:
    """Why a decision fell back to deterministic rules.

    Vocabulary reserved by the policy contract; fallback execution is
    not part of the rule-based path.
    """

    DEPENDENCY_MISSING = "dependency_missing"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_LOAD_FAILED = "model_load_failed"
    GENERATION_FAILED = "generation_failed"
    INVALID_OUTPUT = "invalid_output"
    LOW_CONFIDENCE = "low_confidence"
    VALIDATION_FAILED = "validation_failed"


VALID_ACTIONS = frozenset(
    {PolicyAction.CREATE, PolicyAction.SUPERSEDE, PolicyAction.FORGET,
     PolicyAction.NOOP}
)
VALID_KINDS = frozenset(
    {MemoryKind.PREFERENCE, MemoryKind.FACT, MemoryKind.INSTRUCTION}
)
VALID_DECISION_SOURCES = frozenset(
    {DecisionSource.RULE_BASED, DecisionSource.LOCAL_MODEL,
     DecisionSource.FALLBACK}
)
VALID_FALLBACK_REASONS = frozenset(
    {
        FallbackReason.DEPENDENCY_MISSING,
        FallbackReason.MODEL_UNAVAILABLE,
        FallbackReason.MODEL_LOAD_FAILED,
        FallbackReason.GENERATION_FAILED,
        FallbackReason.INVALID_OUTPUT,
        FallbackReason.LOW_CONFIDENCE,
        FallbackReason.VALIDATION_FAILED,
    }
)


@dataclass(frozen=True)
class PolicyContext:
    """Everything a policy may see — and nothing more.

    Policies receive bounded data only: no store, no engine, no bus,
    and no mutation callbacks.
    """

    user_id: str
    session_id: str
    message: str
    active_memories: list[ExperienceEntry] = field(default_factory=list)
    request_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryDecisionProposal:
    """One proposed memory lifecycle change.

    ``metadata`` is policy-internal; only explicitly whitelisted keys
    (currently ``request``) survive conversion, and it is never copied
    into events or persistence.
    """

    action: str
    kind: str = MemoryKind.PREFERENCE
    text: str | None = None
    target_memory_id: str | None = None
    replaces: str | None = None
    confidence: float = 1.0
    explanation: str = ""
    decision_source: str = DecisionSource.RULE_BASED
    fallback_reason: str | None = None
    metadata: dict = field(default_factory=dict)


class MemoryPolicy(Protocol):
    """Plans memory lifecycle proposals from a bounded context."""

    def plan(self, context: PolicyContext) -> list[MemoryDecisionProposal]:
        ...
