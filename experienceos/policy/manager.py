"""ExperienceManager: bounded orchestration between policies and the engine.

The manager selects and invokes the active MemoryPolicy, validates the
returned proposals, resolves contradictions deterministically, and
converts accepted proposals into the engine's existing MemoryAction
representation. It holds no storage access and applies no mutations —
lifecycle validation and application remain the engine's authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from experienceos.memory.planner import MemoryAction
from experienceos.policy.base import (
    VALID_ACTIONS,
    VALID_DECISION_SOURCES,
    VALID_FALLBACK_REASONS,
    VALID_KINDS,
    DecisionSource,
    FallbackReason,
    MemoryDecisionProposal,
    MemoryPolicy,
    PolicyAction,
    PolicyContext,
)
from experienceos.policy.local_runner import LocalModelRunnerError
from experienceos.policy.rule_based import RuleBasedMemoryPolicy


class InvalidMemoryProposal(ValueError):
    """Raised when a policy returns a proposal that fails validation."""


@dataclass(frozen=True)
class ExperienceManagerResult:
    """Validated planning output handed back to the engine.

    ``actions`` and ``decisions`` are parallel lists: decisions[i] is
    the accepted proposal that produced actions[i]. ``decision_source``
    describes the batch as a whole; fallback provenance is present even
    when the batch is empty, so the planning event stays truthful.
    """

    actions: list[MemoryAction] = field(default_factory=list)
    decisions: list[MemoryDecisionProposal] = field(default_factory=list)
    policy_mode: str = "rule_based"
    decision_source: str = DecisionSource.RULE_BASED
    fallback_used: bool = False
    fallback_reason: str | None = None


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

    def __init__(
        self,
        policy: MemoryPolicy | None = None,
        *,
        fallback_policy: MemoryPolicy | None = None,
        minimum_confidence: float = 0.60,
    ):
        if isinstance(minimum_confidence, bool) or not isinstance(
            minimum_confidence, (int, float)
        ):
            raise ValueError(
                f"minimum_confidence must be numeric, got {minimum_confidence!r}"
            )
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError(
                f"minimum_confidence out of bounds: {minimum_confidence!r}"
            )
        self.policy = policy or RuleBasedMemoryPolicy()
        self.fallback_policy = fallback_policy
        self.minimum_confidence = minimum_confidence

    @property
    def policy_mode(self) -> str:
        return getattr(self.policy, "mode", "custom")

    def plan(self, context: PolicyContext) -> ExperienceManagerResult:
        if self.fallback_policy is None:
            # Primary-only mode: exact pre-fallback semantics — invalid
            # proposals raise instead of falling back.
            accepted = self._accept(self.policy.plan(context))
            return self._result(accepted, self.policy_mode)

        try:
            accepted = self._accept(self.policy.plan(context))
        except LocalModelRunnerError as exc:
            return self._run_fallback(context, exc.reason)
        except InvalidMemoryProposal:
            return self._run_fallback(context, FallbackReason.VALIDATION_FAILED)
        except Exception:  # noqa: BLE001 — deliberate demo-safe containment
            # Unexpected policy failures degrade to deterministic rules;
            # KeyboardInterrupt/SystemExit are BaseException and propagate.
            return self._run_fallback(context, FallbackReason.VALIDATION_FAILED)

        # Whole-batch atomicity: one low-confidence mutating proposal
        # rejects the entire local result (>= threshold is accepted).
        if any(p.confidence < self.minimum_confidence for p in accepted):
            return self._run_fallback(context, FallbackReason.LOW_CONFIDENCE)
        return self._result(accepted, self.policy_mode)

    def _accept(
        self, proposals: list[MemoryDecisionProposal]
    ) -> list[MemoryDecisionProposal]:
        validated = []
        for proposal in proposals:
            self._validate(proposal)
            if proposal.action != PolicyAction.NOOP:
                validated.append(proposal)
        return self._resolve_contradictions(validated)

    def _result(
        self,
        accepted: list[MemoryDecisionProposal],
        decision_source: str,
        *,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> ExperienceManagerResult:
        return ExperienceManagerResult(
            actions=[self._to_action(p) for p in accepted],
            decisions=accepted,
            policy_mode=self.policy_mode,
            decision_source=decision_source,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    def _run_fallback(
        self, context: PolicyContext, reason: str
    ) -> ExperienceManagerResult:
        """Whole-batch fallback: local output is discarded entirely."""
        accepted = self._accept(self.fallback_policy.plan(context))
        stamped = [
            replace(
                proposal,
                decision_source=DecisionSource.FALLBACK,
                fallback_reason=reason,
            )
            for proposal in accepted
        ]
        return self._result(
            stamped,
            DecisionSource.FALLBACK,
            fallback_used=True,
            fallback_reason=reason,
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
        # If forget won a target, its paired replacement create (from an
        # expanded supersede of the same target) must not survive.
        forgotten_targets = {
            p.target_memory_id
            for p in result
            if p.action == PolicyAction.FORGET
        }
        return [
            p
            for p in result
            if not (
                p.action == PolicyAction.CREATE
                and p.replaces in forgotten_targets
            )
        ]

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
