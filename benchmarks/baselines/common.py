"""Shared baseline machinery: provider seam, memory records, heuristics,
context accounting, evidence assembly, and the common execution flow.

Boundary rules enforced by structure:

- Baseline decision methods receive ONLY user-visible inputs (turn
  messages, their own stored state, budgets). Expected-oracle fields
  are never passed into a baseline; logical-reference annotation runs
  after execution, on the emitted result.
- The deterministic response provider derives its reply purely from
  the supplied context messages — never from oracle constraints.
- No baseline imports ExperienceOS lifecycle logic. Their strategies
  (and their limitations) are implemented here, independently.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

from benchmarks.contract import (
    AppliedActionRecord,
    BenchmarkCase,
    CandidateRecord,
    CaseResult,
    CaseStatus,
    ContextAccounting,
    LatencyRecord,
    MemorySnapshot,
    MemorySnapshotEntry,
    ProposalRecord,
    SystemConfig,
    TurnEvidence,
)

SYSTEM_INSTRUCTIONS = "You are a helpful assistant."

APPROXIMATION_METHOD = "approximation"


def approximate_tokens(chars: int) -> int:
    """The contract's documented deterministic fallback: ceil(chars/4)."""
    return math.ceil(chars / 4)


class DeterministicEchoProvider:
    """Offline, stateless answer provider for baseline execution.

    The reply is a deterministic, inspectable function of the supplied
    context only: it names the current request and summarizes how much
    context accompanied it. It never sees oracle expectations and
    keeps no state between calls, so baseline correctness (and
    baseline failure) emerges entirely from the context each baseline
    assembled.
    """

    name = "deterministic-echo"

    def complete(self, messages: list[str]) -> str:
        current = messages[-1] if messages else ""
        context = messages[:-1]
        context_chars = sum(len(m) for m in context)
        return (
            f"[deterministic] reply to: {current} "
            f"(context messages: {len(context)}, "
            f"context chars: {context_chars})"
        )


# --- Durability heuristic (append-only and naive top-K) -----------------------

# Small, documented, deterministic, oracle-blind. A message is stored
# when any pattern matches — UNLESS it reads as a forget command,
# which is an instruction to the assistant, not a durable statement.
DURABLE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bi (?:now )?prefer\b",
        r"\bi like\b",
        r"\bi don'?t like\b",
        r"\bi dislike\b",
        r"\bi avoid\b",
        r"\bi am based in\b",
        r"\bmy [\w' -]+ is\b",
        r"\bfrom now on\b",
        r"\balways\b",
        r"\bremember that\b",
        r"\bi go to the\b",
        r"\bi upgraded\b",
    )
)

FORGET_COMMAND = re.compile(
    r"\bforget\b|\bdon'?t care about\b", re.IGNORECASE
)

_INSTRUCTION_HINT = re.compile(
    r"\bfrom now on\b|\balways\b|\bnever\b", re.IGNORECASE
)
_FACT_HINT = re.compile(
    r"\bi am based in\b|\bmy [\w' -]+ is\b|\bi upgraded\b|\bi go to the\b",
    re.IGNORECASE,
)


def looks_durable(message: str) -> bool:
    if FORGET_COMMAND.search(message):
        return False
    return any(p.search(message) for p in DURABLE_PATTERNS)


def estimate_kind(message: str) -> str:
    if _INSTRUCTION_HINT.search(message):
        return "instruction"
    if _FACT_HINT.search(message):
        return "fact"
    return "preference"


_WORD = re.compile(r"[a-z0-9#'-]+")
STOPWORDS = frozenset(
    "a an and are for i in is it me my of on the to with that this those "
    "these please help was were be been do does don't what which should "
    "would could you your we our us".split()
)


def content_words(text: str) -> set:
    return {
        w for w in _WORD.findall(text.lower()) if w not in STOPWORDS
    }


@dataclass
class BaselineMemoryRecord:
    """One stored baseline memory. Always active: none of the Prompt 3
    baselines ever supersedes or forgets a record."""

    record_id: str
    text: str
    kind: str
    created_turn: int

    def snapshot_entry(self) -> MemorySnapshotEntry:
        return MemorySnapshotEntry(
            memory_id=self.record_id,
            kind=self.kind,
            text=self.text,
            status="active",
        )


@dataclass
class TurnPlan:
    """What a baseline decided for one turn, before evidence assembly."""

    writes: list[BaselineMemoryRecord] = field(default_factory=list)
    candidates: list[CandidateRecord] = field(default_factory=list)
    memory_context: list[str] = field(default_factory=list)
    history_context: list[str] = field(default_factory=list)


class BaselineSystem:
    """Common execution flow behind the BenchmarkSystem protocol.

    Subclasses implement ``_plan_turn(turn_index, session_id, message)``
    using only user-visible inputs and their own state. Everything else
    — context assembly, provider call, accounting, timing, snapshots,
    reset — is shared so evidence stays comparable across systems.
    """

    system_id = "baseline"
    memory_policy_label = "none"

    def __init__(self, provider=None, seed: int = 0):
        self.provider = provider or DeterministicEchoProvider()
        self.config = SystemConfig(
            system_id=self.system_id,
            provider_name=self.provider.name,
            response_model=self.provider.name,
            memory_policy=self.memory_policy_label,
            storage_mode="in_memory",
            context_budget=4,
            selection_k=4,
            temperature=None,
            max_output_tokens=None,
            seed=seed,
            retry_policy="none",
            retrieval_description=self.retrieval_description(),
        )
        self._reset()

    # -- subclass surface ---------------------------------------------------

    def retrieval_description(self) -> str:
        return "none"

    def _plan_turn(
        self, turn_index: int, session_id: str, message: str
    ) -> TurnPlan:
        raise NotImplementedError

    def _after_response(
        self, turn_index: int, message: str, response: str
    ) -> None:
        """Post-response hook (full-history transcript append)."""

    # -- common flow ----------------------------------------------------------

    def _reset(self) -> None:
        self.records: list[BaselineMemoryRecord] = []
        self._record_counter = 0
        self.context_budget = 4
        self.selection_k: int | None = 4
        self.last_accounting: ContextAccounting | None = None
        self.provider_request_count = 0

    def initialize(self, case: BenchmarkCase) -> None:
        self._reset()
        self.context_budget = case.context_budget
        self.selection_k = case.selection_k
        self.config = SystemConfig(
            **{
                **self.config.to_payload(),
                "context_budget": case.context_budget,
                "selection_k": case.selection_k,
                "seed": case.seed,
            }
        )

    def _new_record(
        self, text: str, kind: str, created_turn: int
    ) -> BaselineMemoryRecord:
        self._record_counter += 1
        return BaselineMemoryRecord(
            record_id=f"{self.system_id}-mem-{self._record_counter:03d}",
            text=text,
            kind=kind,
            created_turn=created_turn,
        )

    def memory_limit(self) -> int:
        """Memory slots per turn: the same budget/K pair every system
        gets — min(context_budget, selection_k) when both exist."""
        if self.selection_k is None:
            return self.context_budget
        return min(self.context_budget, self.selection_k)

    def process_turn(
        self, turn_index: int, session_id: str, message: str
    ) -> TurnEvidence:
        started = time.perf_counter()
        plan = self._plan_turn(turn_index, session_id, message)
        planned = time.perf_counter()

        context_messages = [
            SYSTEM_INSTRUCTIONS,
            *plan.history_context,
            *plan.memory_context,
            message,
        ]
        assembled = time.perf_counter()

        response = self.provider.complete(context_messages)
        self.provider_request_count += 1
        answered = time.perf_counter()
        self._after_response(turn_index, message, response)

        memory_chars = sum(len(m) for m in plan.memory_context)
        total_chars = sum(len(m) for m in context_messages)
        self.last_accounting = ContextAccounting(
            method=APPROXIMATION_METHOD,
            total_context_tokens=approximate_tokens(total_chars),
            memory_context_tokens=approximate_tokens(memory_chars),
            total_context_chars=total_chars,
            memory_context_chars=memory_chars,
            selected_memory_count=sum(
                1 for c in plan.candidates if c.selected
            ),
            candidate_memory_count=len(plan.candidates),
            context_budget=self.context_budget,
        )

        def ms(a: float, b: float) -> float:
            return (b - a) * 1000.0

        proposals = tuple(
            ProposalRecord(
                action="create",
                kind=record.kind,
                text=record.text,
                confidence=None,
                explanation="durability heuristic",
                decision_source="heuristic",
            )
            for record in plan.writes
        )
        applied = tuple(
            AppliedActionRecord(
                action="create",
                memory_id=record.record_id,
                kind=record.kind,
                text=record.text,
            )
            for record in plan.writes
        )
        return TurnEvidence(
            turn_index=turn_index,
            session_id=session_id,
            message=message,
            proposals=proposals,
            applied_actions=applied,
            rejected_actions=(),
            fallbacks=(),
            candidates=tuple(plan.candidates),
            context_messages=tuple(context_messages),
            response=response,
            latencies=(
                LatencyRecord("memory_decision", ms(started, planned)),
                LatencyRecord("retrieval", ms(started, planned)),
                LatencyRecord("context_assembly", ms(planned, assembled)),
                LatencyRecord("response", ms(assembled, answered)),
                LatencyRecord("end_to_end", ms(started, answered)),
            ),
        )

    def final_state(self) -> MemorySnapshot:
        return MemorySnapshot(
            label="final",
            entries=tuple(r.snapshot_entry() for r in self.records),
        )

    def close(self) -> None:
        self._reset()


def annotate_logical_references(case: BenchmarkCase, result: CaseResult) -> None:
    """Observational post-run annotation: map the oracle's logical IDs
    to the runtime memory IDs whose text carries every match term.

    Runs strictly AFTER execution and writes only into diagnostics —
    it cannot influence storage, retrieval, selection, or context.
    """
    refs = {}
    expected = case.expected
    for ref_list in (
        expected.active,
        expected.superseded,
        expected.forgotten,
        expected.retrieval_candidates,
        expected.selected,
        expected.skipped,
    ):
        for ref in ref_list:
            refs.setdefault(ref.logical_id, ref)
    resolution = {}
    entries = list(result.final_active)
    for logical_id, ref in sorted(refs.items()):
        matched = [
            entry.memory_id
            for entry in entries
            if all(
                term.lower() in entry.text.lower()
                for term in ref.match_terms
            )
        ]
        resolution[logical_id] = matched
    result.diagnostics["logical_resolution"] = resolution


def run_case(system, scenario, run_id: str = "smoke-local") -> CaseResult:
    """Execution-integrity harness: drive one baseline through one
    scenario and emit a contract-valid CaseResult. Pass/fail here means
    'executed and serialized cleanly', never 'answered correctly'."""
    case = scenario.case
    result = CaseResult(
        scenario_id=case.scenario_id,
        system_id=system.system_id,
        run_id=run_id,
        suite_version="experienceos-lifecycle-v1",
        status=CaseStatus.PASSED,
        evaluator_type="deterministic",
    )
    if case.requires_local_model:
        result.status = CaseStatus.SKIPPED
        result.skip_reason = (
            "requires_local_model: scripted local-proposal semantics are "
            "not applicable to this baseline"
        )
        return result
    try:
        system.initialize(case)
        turn_index = 0
        for turn in case.turns:
            result.turns.append(
                system.process_turn(turn_index, turn.session_id, turn.message)
            )
            turn_index += 1
        result.turns.append(
            system.process_turn(
                turn_index, case.current_session_id, case.current_message
            )
        )
        snapshot = system.final_state()
        result.snapshots.append(snapshot)
        result.final_active = list(snapshot.entries)
        result.context_accounting = system.last_accounting
        result.latencies = list(result.turns[-1].latencies)
        result.provider_request_count = system.provider_request_count
        if "scripted_local_proposals" in case.evaluator_requirements:
            result.diagnostics["scripted_proposals"] = (
                "not_applicable_to_baseline"
            )
        if case.requires_provider:
            result.diagnostics["provider_note"] = (
                "executed with deterministic offline provider; "
                "response-quality evaluation deferred to provider-backed runs"
            )
    except Exception as exc:  # noqa: BLE001 — evidence must survive
        result.status = CaseStatus.PARTIAL
        result.failure_reason = f"{type(exc).__name__}: {exc}"
    finally:
        system.close()
    annotate_logical_references(case, result)
    return result
