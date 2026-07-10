"""ExperienceOS benchmark adapters: shared base and harness.

The adapters attach to public seams only — ``ExperienceOS(...)``
construction with injected provider/policy/context builder, ``chat``,
``memories_for_user(status=...)``, and the public event stream. No
private store access, no monkey-patching, no benchmark flags in the
production package.

Oracle firewall: adapters receive user messages, budgets, the seed,
and (for the local adapter) the scenario ID to resolve a scripted
proposal fixture — the documented narrow exception, since the fixture
stands in for external model output, not expected results. Expected
oracle fields never reach lifecycle decisions; annotation runs after
execution, on the emitted result.
"""

from __future__ import annotations

import time

from benchmarks.adapters.translation import translate_turn
from benchmarks.contract import (
    BenchmarkCase,
    CaseResult,
    CaseStatus,
    ContextAccounting,
    MemorySnapshot,
    MemorySnapshotEntry,
    SystemConfig,
    TurnEvidence,
)
from experienceos import ExperienceOS
from experienceos.context.builder import ContextBuilder
from experienceos.context.compression import ExperienceCompressor
from experienceos.memory import MemoryStatus
from experienceos.providers import MockProvider

STATUS_ORDER = (
    MemoryStatus.ACTIVE,
    MemoryStatus.SUPERSEDED,
    MemoryStatus.FORGOTTEN,
)


class ExperienceOSAdapterBase:
    """Common adapter flow behind the BenchmarkSystem protocol.

    Each ``initialize`` builds a fresh, scenario-isolated ExperienceOS
    instance with an in-memory store, the deterministic offline
    provider (or an injected one), compression enabled (the demo-path
    configuration), and the scenario's budget interpretation shared
    with the baselines: memory budget = min(context_budget,
    selection_k or context_budget).
    """

    system_id = "experienceos"
    memory_policy_label = "rule_based"

    def __init__(self, provider=None, seed: int = 0):
        self._injected_provider = provider
        self.provider = provider or MockProvider()
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
            retrieval_description=(
                "ExperienceOS deterministic ranking: keyword overlap, "
                "kind priority, recency, stable tie-break; active "
                "memories only; compression enabled"
            ),
        )
        self._clear()

    def _clear(self) -> None:
        self.agent = None
        self.user_id = ""
        self._event_offset = 0
        self.context_budget = 4
        self.last_accounting: ContextAccounting | None = None
        self.provider_request_count = 0
        self.local_model_invocation_count = 0
        self.diagnostics: dict = {}

    # -- subclass surface ------------------------------------------------------

    def _make_policy(self, case: BenchmarkCase):
        """Return the memory policy for this scenario (None = default
        rule-based)."""
        return None

    def _make_planner(self, case: BenchmarkCase):
        """Return a memory planner to inject (None = SDK default).
        Mutually exclusive with _make_policy by SDK contract."""
        return None

    def _make_retrieval_strategy(self, case: BenchmarkCase):
        """Return a retrieval strategy for the ContextBuilder (None =
        the unchanged Phase 8 deterministic ranking)."""
        return None

    # -- BenchmarkSystem -------------------------------------------------------

    def initialize(self, case: BenchmarkCase) -> None:
        self._clear()
        self.provider = self._injected_provider or MockProvider()
        budget = case.context_budget
        if case.selection_k is not None:
            budget = min(budget, case.selection_k)
        self.context_budget = case.context_budget
        builder = ContextBuilder(
            memory_budget=budget,
            compressor=ExperienceCompressor(),
            retrieval_strategy=self._make_retrieval_strategy(case),
        )
        policy = self._make_policy(case)
        planner = self._make_planner(case)
        kwargs = {}
        if policy is not None:
            kwargs["memory_policy"] = policy
        elif planner is not None:
            kwargs["memory_planner"] = planner
        self.agent = ExperienceOS(
            model=self.provider, context_builder=builder, **kwargs
        )
        self.user_id = f"bench-{case.scenario_id}"
        self._event_offset = 0
        self.config = SystemConfig(
            **{
                **self.config.to_payload(),
                "context_budget": case.context_budget,
                "selection_k": case.selection_k,
                "seed": case.seed,
            }
        )

    def process_turn(
        self, turn_index: int, session_id: str, message: str
    ) -> TurnEvidence:
        started = time.perf_counter()
        response = self.agent.chat(
            user_id=self.user_id, session_id=session_id, message=message
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        events = self.agent.events[self._event_offset:]
        self._event_offset = len(self.agent.events)
        self.provider_request_count += 1
        evidence, accounting = translate_turn(
            turn_index=turn_index,
            session_id=session_id,
            message=message,
            response=response,
            events=events,
            end_to_end_ms=elapsed_ms,
        )
        self.last_accounting = ContextAccounting(
            **{
                **accounting.to_payload(),
                "context_budget": self.context_budget,
            }
        )
        return evidence

    def final_state(self) -> MemorySnapshot:
        entries = []
        for status in STATUS_ORDER:
            for memory in self.agent.memories_for_user(
                self.user_id, status=status
            ):
                entries.append(
                    MemorySnapshotEntry(
                        memory_id=memory.id,
                        kind=memory.kind,
                        text=memory.text,
                        status=memory.status,
                    )
                )
        return MemorySnapshot(label="final", entries=tuple(entries))

    def close(self) -> None:
        self._clear()


def annotate_logical_references(case: BenchmarkCase, result: CaseResult) -> None:
    """Post-run annotation across ALL lifecycle statuses (adapters
    surface superseded and forgotten records too). Diagnostics only —
    never affects behavior."""
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
    entries = [
        *result.final_active,
        *result.final_superseded,
        *result.final_forgotten,
    ]
    resolution = {}
    for logical_id, ref in sorted(refs.items()):
        resolution[logical_id] = [
            entry.memory_id
            for entry in entries
            if all(
                term.lower() in entry.text.lower()
                for term in ref.match_terms
            )
        ]
    result.diagnostics["logical_resolution"] = resolution


def run_adapter_case(
    system,
    scenario,
    run_id: str = "adapter-smoke-local",
    allow_local: bool = False,
) -> CaseResult:
    """Execution-integrity harness for ExperienceOS adapters.

    Splits the final snapshot by lifecycle status, preserves partial
    evidence on failure, and skips requires_local_model cases unless a
    real local mode explicitly allows them.
    """
    case = scenario.case
    result = CaseResult(
        scenario_id=case.scenario_id,
        system_id=system.system_id,
        run_id=run_id,
        suite_version="experienceos-lifecycle-v1",
        status=CaseStatus.PASSED,
        evaluator_type="deterministic",
    )
    if case.requires_local_model and not allow_local:
        result.status = CaseStatus.SKIPPED
        result.skip_reason = (
            "requires_local_model: no real local model configured for "
            "this run"
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
        result.final_active = [
            e for e in snapshot.entries if e.status == "active"
        ]
        result.final_superseded = [
            e for e in snapshot.entries if e.status == "superseded"
        ]
        result.final_forgotten = [
            e for e in snapshot.entries if e.status == "forgotten"
        ]
        result.context_accounting = system.last_accounting
        result.latencies = list(result.turns[-1].latencies)
        result.provider_request_count = system.provider_request_count
        result.local_model_invocation_count = (
            system.local_model_invocation_count
        )
        result.diagnostics.update(system.diagnostics)
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
