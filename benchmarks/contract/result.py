"""Per-case raw result contract.

One ``CaseResult`` preserves the full evidence chain for one scenario
run on one system, in provider-independent terms. The layers are kept
separate so a rejected policy proposal is never mistaken for final
state corruption, and a clean final state never erases the evidence
that an invalid action was proposed:

1. proposal records      — what the policy proposed
2. rejected actions      — what engine validation contained
3. applied actions       — what actually mutated lifecycle state
4. memory snapshots      — state before/after, and final by status
5. retrieval evidence    — candidates, ranking, selected, skipped
6. context evidence      — messages supplied plus token accounting
7. response + evaluation — deterministic constraints, optional judge
8. operational evidence  — latency, request counts, retries

Partial failure keeps earlier evidence: a provider failure after the
lifecycle turn still records every proposal, rejection, and snapshot,
with ``status = "partial"`` and a ``failure_reason``.

Serialization is deterministic: ``to_payload`` emits keys in fixed
dataclass field order, and hashing uses canonical (key-sorted) JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RESULT_SCHEMA_VERSION = "1"


class CaseStatus:
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL = "partial"


KNOWN_CASE_STATUSES = frozenset(
    (
        CaseStatus.PASSED,
        CaseStatus.FAILED,
        CaseStatus.SKIPPED,
        CaseStatus.PARTIAL,
    )
)


class EvaluatorType:
    DETERMINISTIC = "deterministic"
    MODEL_JUDGE = "model_judge"


@dataclass(frozen=True)
class ProposalRecord:
    """One policy proposal, before any validation."""

    action: str
    kind: str | None = None
    text: str | None = None
    target_memory_id: str | None = None
    replaces: str | None = None
    confidence: float | None = None
    explanation: str | None = None
    decision_source: str | None = None

    def to_payload(self) -> dict:
        return {
            "action": self.action,
            "kind": self.kind,
            "text": self.text,
            "target_memory_id": self.target_memory_id,
            "replaces": self.replaces,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "decision_source": self.decision_source,
        }


@dataclass(frozen=True)
class AppliedActionRecord:
    """One lifecycle action the engine actually applied."""

    action: str
    memory_id: str
    kind: str | None = None
    text: str | None = None
    replaces: str | None = None

    def to_payload(self) -> dict:
        return {
            "action": self.action,
            "memory_id": self.memory_id,
            "kind": self.kind,
            "text": self.text,
            "replaces": self.replaces,
        }


@dataclass(frozen=True)
class RejectedActionRecord:
    """One proposal contained by engine validation. Not a mutation."""

    action: str
    rejected_reason: str
    text: str | None = None
    target_memory_id: str | None = None

    def to_payload(self) -> dict:
        return {
            "action": self.action,
            "rejected_reason": self.rejected_reason,
            "text": self.text,
            "target_memory_id": self.target_memory_id,
        }


@dataclass(frozen=True)
class FallbackRecord:
    """One whole-batch typed fallback with its attributed reason."""

    reason: str
    turn_index: int

    def to_payload(self) -> dict:
        return {"reason": self.reason, "turn_index": self.turn_index}


@dataclass(frozen=True)
class MemorySnapshotEntry:
    memory_id: str
    kind: str
    text: str
    status: str

    def to_payload(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "kind": self.kind,
            "text": self.text,
            "status": self.status,
        }


@dataclass(frozen=True)
class MemorySnapshot:
    """Memory state at one labeled point (for example "after_turn_3")."""

    label: str
    entries: tuple[MemorySnapshotEntry, ...] = ()

    def to_payload(self) -> dict:
        return {
            "label": self.label,
            "entries": [e.to_payload() for e in self.entries],
        }


@dataclass(frozen=True)
class CandidateRecord:
    """One retrieval candidate with deterministic rank (1 = best)."""

    memory_id: str
    text: str
    rank: int
    score: float
    selected: bool
    reason: str = ""

    def to_payload(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "text": self.text,
            "rank": self.rank,
            "score": self.score,
            "selected": self.selected,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ContextAccounting:
    """Context usage for the answer turn, with an explicit method.

    ``method`` must be one of the contract's accounting methods
    (provider_reported, tokenizer, approximation) so mixed methods can
    never be compared silently. Character counts are always recorded
    as the method-independent floor.
    """

    method: str
    total_context_tokens: int | None
    memory_context_tokens: int | None
    total_context_chars: int
    memory_context_chars: int
    selected_memory_count: int
    candidate_memory_count: int
    context_budget: int
    compressed_summary_count: int = 0
    compression_saved_chars: int = 0

    def to_payload(self) -> dict:
        return {
            "method": self.method,
            "total_context_tokens": self.total_context_tokens,
            "memory_context_tokens": self.memory_context_tokens,
            "total_context_chars": self.total_context_chars,
            "memory_context_chars": self.memory_context_chars,
            "selected_memory_count": self.selected_memory_count,
            "candidate_memory_count": self.candidate_memory_count,
            "context_budget": self.context_budget,
            "compressed_summary_count": self.compressed_summary_count,
            "compression_saved_chars": self.compression_saved_chars,
        }


KNOWN_ACCOUNTING_METHODS = frozenset(
    ("provider_reported", "tokenizer", "approximation")
)


@dataclass(frozen=True)
class ConstraintResult:
    """One deterministic response/lifecycle constraint outcome."""

    constraint: str
    passed: bool
    detail: str = ""

    def to_payload(self) -> dict:
        return {
            "constraint": self.constraint,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class JudgeResult:
    """Optional model-scored evaluation; never mixed into deterministic
    pass counts without labeling."""

    judge_model: str
    verdict: str
    rationale: str = ""

    def to_payload(self) -> dict:
        return {
            "judge_model": self.judge_model,
            "verdict": self.verdict,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class LatencyRecord:
    """One timed stage in milliseconds (memory_decision, retrieval,
    context_assembly, response, end_to_end)."""

    stage: str
    milliseconds: float

    def to_payload(self) -> dict:
        return {"stage": self.stage, "milliseconds": self.milliseconds}


@dataclass(frozen=True)
class TurnEvidence:
    """Everything observed while processing one ordered turn."""

    turn_index: int
    session_id: str
    message: str
    proposals: tuple[ProposalRecord, ...] = ()
    applied_actions: tuple[AppliedActionRecord, ...] = ()
    rejected_actions: tuple[RejectedActionRecord, ...] = ()
    fallbacks: tuple[FallbackRecord, ...] = ()
    candidates: tuple[CandidateRecord, ...] = ()
    context_messages: tuple[str, ...] = ()
    response: str | None = None
    latencies: tuple[LatencyRecord, ...] = ()

    def to_payload(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "session_id": self.session_id,
            "message": self.message,
            "proposals": [p.to_payload() for p in self.proposals],
            "applied_actions": [a.to_payload() for a in self.applied_actions],
            "rejected_actions": [
                r.to_payload() for r in self.rejected_actions
            ],
            "fallbacks": [f.to_payload() for f in self.fallbacks],
            "candidates": [c.to_payload() for c in self.candidates],
            "context_messages": list(self.context_messages),
            "response": self.response,
            "latencies": [l.to_payload() for l in self.latencies],
        }


@dataclass
class CaseResult:
    """The complete raw evidence for one (scenario, system) execution."""

    scenario_id: str
    system_id: str
    run_id: str
    suite_version: str
    status: str
    skip_reason: str | None = None
    failure_reason: str | None = None
    turns: list[TurnEvidence] = field(default_factory=list)
    snapshots: list[MemorySnapshot] = field(default_factory=list)
    final_active: list[MemorySnapshotEntry] = field(default_factory=list)
    final_superseded: list[MemorySnapshotEntry] = field(default_factory=list)
    final_forgotten: list[MemorySnapshotEntry] = field(default_factory=list)
    context_accounting: ContextAccounting | None = None
    constraint_results: list[ConstraintResult] = field(default_factory=list)
    judge_result: JudgeResult | None = None
    latencies: list[LatencyRecord] = field(default_factory=list)
    provider_request_count: int = 0
    local_model_invocation_count: int = 0
    retry_count: int = 0
    evaluator_type: str = EvaluatorType.DETERMINISTIC
    diagnostics: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "scenario_id": self.scenario_id,
            "system_id": self.system_id,
            "run_id": self.run_id,
            "suite_version": self.suite_version,
            "status": self.status,
            "skip_reason": self.skip_reason,
            "failure_reason": self.failure_reason,
            "turns": [t.to_payload() for t in self.turns],
            "snapshots": [s.to_payload() for s in self.snapshots],
            "final_active": [e.to_payload() for e in self.final_active],
            "final_superseded": [
                e.to_payload() for e in self.final_superseded
            ],
            "final_forgotten": [e.to_payload() for e in self.final_forgotten],
            "context_accounting": (
                self.context_accounting.to_payload()
                if self.context_accounting
                else None
            ),
            "constraint_results": [
                c.to_payload() for c in self.constraint_results
            ],
            "judge_result": (
                self.judge_result.to_payload() if self.judge_result else None
            ),
            "latencies": [l.to_payload() for l in self.latencies],
            "provider_request_count": self.provider_request_count,
            "local_model_invocation_count": self.local_model_invocation_count,
            "retry_count": self.retry_count,
            "evaluator_type": self.evaluator_type,
            "diagnostics": dict(sorted(self.diagnostics.items())),
        }


def validate_case_result(result: CaseResult) -> None:
    """Contract-level checks a result must satisfy before emission."""
    if result.status not in KNOWN_CASE_STATUSES:
        raise ValueError(
            f"{result.scenario_id}: unknown status {result.status!r}; "
            f"expected one of {sorted(KNOWN_CASE_STATUSES)}"
        )
    if result.status == CaseStatus.SKIPPED and not result.skip_reason:
        raise ValueError(
            f"{result.scenario_id}: skipped result requires skip_reason"
        )
    if (
        result.status in (CaseStatus.FAILED, CaseStatus.PARTIAL)
        and not result.failure_reason
    ):
        raise ValueError(
            f"{result.scenario_id}: {result.status} result requires "
            "failure_reason"
        )
    accounting = result.context_accounting
    if accounting is not None and (
        accounting.method not in KNOWN_ACCOUNTING_METHODS
    ):
        raise ValueError(
            f"{result.scenario_id}: unknown context accounting method "
            f"{accounting.method!r}; expected one of "
            f"{sorted(KNOWN_ACCOUNTING_METHODS)}"
        )
