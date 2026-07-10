"""Common system adapter contract.

Every compared system — the baselines and both ExperienceOS
configurations — is driven through the same interface so comparison
stays fair: same messages, same order, same result shape. Baselines
that have no lifecycle (stateless, full-history) still return
``TurnEvidence``; their proposal/applied/rejected tuples are simply
empty, which is itself evidence, never an excuse to change the shape.

Adapters are observers around existing public interfaces (the
ExperienceOS SDK, providers, event history). They never reach into
engine internals and the production engine carries no benchmark
branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from benchmarks.contract.case import BenchmarkCase
from benchmarks.contract.result import MemorySnapshot, TurnEvidence


class SystemId:
    """The six systems later prompts implement against this contract."""

    STATELESS = "stateless"
    FULL_HISTORY = "full_history"
    APPEND_ONLY = "append_only"
    NAIVE_TOP_K = "naive_top_k"
    EXPERIENCEOS_RULES = "experienceos_rules"
    EXPERIENCEOS_LOCAL = "experienceos_local"


KNOWN_SYSTEM_IDS = frozenset(
    value
    for name, value in vars(SystemId).items()
    if not name.startswith("_") and isinstance(value, str)
)


@dataclass(frozen=True)
class SystemConfig:
    """Configuration every system run must declare up front.

    These are the fair-comparison knobs: within one compared run they
    must be identical across systems (see docs/benchmark_contract.md,
    Fair-Comparison Rules) unless the report explicitly separates them.
    """

    system_id: str
    provider_name: str
    response_model: str
    memory_policy: str
    storage_mode: str
    context_budget: int
    selection_k: int | None
    temperature: float | None
    max_output_tokens: int | None
    seed: int
    retry_policy: str = "none"
    retrieval_description: str = ""

    def to_payload(self) -> dict:
        return {
            "system_id": self.system_id,
            "provider_name": self.provider_name,
            "response_model": self.response_model,
            "memory_policy": self.memory_policy,
            "storage_mode": self.storage_mode,
            "context_budget": self.context_budget,
            "selection_k": self.selection_k,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "seed": self.seed,
            "retry_policy": self.retry_policy,
            "retrieval_description": self.retrieval_description,
        }


class BenchmarkSystem(Protocol):
    """Execution contract every compared system implements.

    Flow per scenario: ``initialize`` → ``process_turn`` for each
    ordered setup turn and finally the current message → ``final_state``
    → ``close``. Each ``process_turn`` returns complete TurnEvidence;
    evidence is recorded as it happens so a later failure cannot erase
    it.
    """

    config: SystemConfig

    def initialize(self, case: BenchmarkCase) -> None:
        """Start a clean scenario state; no cross-case leakage."""

    def process_turn(
        self, turn_index: int, session_id: str, message: str
    ) -> TurnEvidence:
        """Process one ordered turn and return the observed evidence."""

    def final_state(self) -> MemorySnapshot:
        """Final memory state across all lifecycle statuses."""

    def close(self) -> None:
        """Release scenario resources (stores, temp files)."""
