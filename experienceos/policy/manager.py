"""ExperienceManager: bounded orchestration between policies and the engine.

The manager selects and invokes the active MemoryPolicy, validates the
returned proposals, resolves contradictions deterministically, and
converts accepted proposals into the engine's existing MemoryAction
representation. It holds no storage access and applies no mutations —
lifecycle validation and application remain the engine's authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experienceos.memory.planner import MemoryAction
from experienceos.policy.base import (
    VALID_ACTIONS,
    VALID_DECISION_SOURCES,
    VALID_FALLBACK_REASONS,
    VALID_KINDS,
    MemoryDecisionProposal,
    MemoryPolicy,
    PolicyAction,
    PolicyContext,
)
from experienceos.policy.rule_based import RuleBasedMemoryPolicy


class InvalidMemoryProposal(ValueError):
    """Raised when a policy returns a proposal that fails validation."""


@dataclass(frozen=True)
class ExperienceManagerResult:
    """Validated planning output handed back to the engine.

    ``actions`` and ``decisions`` are parallel lists: decisions[i] is
    the accepted proposal that produced actions[i].
    """

    actions: list[MemoryAction] = field(default_factory=list)
    decisions: list[MemoryDecisionProposal] = field(default_factory=list)
    policy_mode: str = "rule_based"


class ExperienceManager:
    """Validates and normalizes memory policy proposals.

    Contradiction resolution (deterministic, documented):
    1. Proposal order is preserved for independent actions.
    2. Target-based actions (supersede/forget) are unique per target:
       the first accepted proposal for a target wins, except that a
       later forget replaces an earlier supersede of the same target
       (forget outranks supersede, in place).
    3. Exact duplicate creates (same kind and text) are dropped.
    """

    def __init__(self, policy: MemoryPolicy | None = None):
        self.policy = policy or RuleBasedMemoryPolicy()

    @property
    def policy_mode(self) -> str:
        return getattr(self.policy, "mode", "custom")

    def plan(self, context: PolicyContext) -> ExperienceManagerResult:
        proposals = self.policy.plan(context)
        validated = []
        for proposal in proposals:
            self._validate(proposal)
            if proposal.action != PolicyAction.NOOP:
                validated.append(proposal)
        accepted = self._resolve_contradictions(validated)
        return ExperienceManagerResult(
            actions=[self._to_action(p) for p in accepted],
            decisions=accepted,
            policy_mode=self.policy_mode,
        )

    @staticmethod
    def _validate(proposal: MemoryDecisionProposal) -> None:
        if not isinstance(proposal, MemoryDecisionProposal):
            raise InvalidMemoryProposal(
                f"Expected MemoryDecisionProposal, got {type(proposal).__name__}"
            )
        if proposal.action not in VALID_ACTIONS:
            raise InvalidMemoryProposal(f"Unknown action: {proposal.action!r}")
        if proposal.kind not in VALID_KINDS:
            raise InvalidMemoryProposal(f"Unknown memory kind: {proposal.kind!r}")
        if not isinstance(proposal.confidence, (int, float)) or isinstance(
            proposal.confidence, bool
        ):
            raise InvalidMemoryProposal(
                f"Confidence must be numeric, got {proposal.confidence!r}"
            )
        if not 0.0 <= proposal.confidence <= 1.0:
            raise InvalidMemoryProposal(
                f"Confidence out of bounds: {proposal.confidence!r}"
            )
        if proposal.decision_source not in VALID_DECISION_SOURCES:
            raise InvalidMemoryProposal(
                f"Unknown decision source: {proposal.decision_source!r}"
            )
        if (
            proposal.fallback_reason is not None
            and proposal.fallback_reason not in VALID_FALLBACK_REASONS
        ):
            raise InvalidMemoryProposal(
                f"Unknown fallback reason: {proposal.fallback_reason!r}"
            )
        if proposal.action == PolicyAction.CREATE:
            if not (proposal.text or "").strip():
                raise InvalidMemoryProposal("Create proposal requires text.")
        if proposal.action == PolicyAction.SUPERSEDE:
            if not proposal.target_memory_id:
                raise InvalidMemoryProposal(
                    "Supersede proposal requires target_memory_id."
                )
            if not (proposal.text or "").strip():
                raise InvalidMemoryProposal("Supersede proposal requires text.")
        if proposal.action == PolicyAction.FORGET:
            if not proposal.target_memory_id:
                raise InvalidMemoryProposal(
                    "Forget proposal requires target_memory_id."
                )

    @staticmethod
    def _resolve_contradictions(
        proposals: list[MemoryDecisionProposal],
    ) -> list[MemoryDecisionProposal]:
        result: list[MemoryDecisionProposal] = []
        target_index: dict[str, int] = {}
        seen_creates: set[tuple[str, str]] = set()
        for proposal in proposals:
            if proposal.action in (PolicyAction.SUPERSEDE, PolicyAction.FORGET):
                target = proposal.target_memory_id
                if target in target_index:
                    existing = result[target_index[target]]
                    if (
                        proposal.action == PolicyAction.FORGET
                        and existing.action == PolicyAction.SUPERSEDE
                    ):
                        result[target_index[target]] = proposal
                    continue  # first accepted proposal for a target wins
                target_index[target] = len(result)
                result.append(proposal)
            else:  # create
                create_key = (proposal.kind, proposal.text or "")
                if create_key in seen_creates:
                    continue
                seen_creates.add(create_key)
                result.append(proposal)
        return result

    @staticmethod
    def _to_action(proposal: MemoryDecisionProposal) -> MemoryAction:
        """Convert an accepted proposal to the engine's MemoryAction.

        Field-for-field inverse of RuleBasedMemoryPolicy._to_proposal,
        so rule-based planning round-trips exactly.
        """
        return MemoryAction(
            action=proposal.action,
            kind=proposal.kind,
            text=proposal.text or "",
            memory_id=proposal.target_memory_id,
            replaces=proposal.replaces,
            reason=proposal.explanation or None,
            request=proposal.metadata.get("request"),
        )
