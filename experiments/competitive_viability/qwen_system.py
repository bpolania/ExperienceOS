"""Canonical ExperienceOS + Qwen extraction benchmark adapter.

Drives the actual demo composition: the same `ExperienceOS` agent the
demo builds, with `build_canonical_extraction_config` selecting the Qwen
extraction controller when Qwen Cloud is configured — Qwen extraction →
grounded validation → deterministic governance → memory lifecycle →
lifecycle-aware retrieval → canonical context builder → Qwen response via
`agent.chat`. It is not the proposal-only Qwen extraction shadow harness.

It subclasses the existing ExperienceOS adapter base and reuses its
turn-processing, event observation, final-state, and reset logic
unchanged; it overrides only construction, to add the canonical
extraction config. One bounded, documented deviation from
`demo.support.create_agent`: the agent honors the benchmark's per-case
memory budget instead of the demo's fixed budget, because the comparison
requires every system to run under the same budget. Every other
component — provider, store, compression, extraction selection — matches
the demo composition.
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.contract import BenchmarkCase, SystemConfig
from experienceos import ExperienceOS
from experienceos.context import ContextBuilder, ExperienceCompressor
from experienceos.memory import InMemoryMemoryStore
from experienceos.providers import MockProvider

# Candidate mode: Qwen extraction runs as a lifecycle-evaluated,
# non-mutating candidate overlay — the demo's non-adopted composition.
# The durable lifecycle is driven by the unchanged deterministic policy;
# Qwen supplies grounded extraction candidates. Adopted mode is never
# reachable here, exactly as in the demo.
from demo.extraction_diagnostics import MODE_CANDIDATE
from demo.support import build_canonical_extraction_config

CANONICAL_SYSTEM_ID = "canonical_experienceos_qwen"


class CanonicalQwenSystem(ExperienceOSAdapterBase):
    """The canonical demo path behind the benchmark system contract."""

    system_id = CANONICAL_SYSTEM_ID
    memory_policy_label = "rule_based"
    extraction_mode = MODE_CANDIDATE

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
        )
        # The canonical extraction selection: Qwen when configured, the
        # deterministic controller otherwise. Same function the demo uses.
        extraction = build_canonical_extraction_config(
            self.extraction_mode, self.provider
        )
        kwargs = {}
        if extraction is not None:
            kwargs["extraction"] = extraction
        self.agent = ExperienceOS(
            model=self.provider,
            memory_store=InMemoryMemoryStore(),
            context_builder=builder,
            **kwargs,
        )
        self.user_id = f"bench-{case.scenario_id}"
        self._event_offset = 0
        extraction_backed = (
            extraction is not None
            and getattr(extraction, "controller_type", None) == "learned"
        )
        self.diagnostics["extraction_mode"] = self.extraction_mode
        self.diagnostics["qwen_extraction_selected"] = extraction_backed
        self.config = SystemConfig(
            **{
                **self.config.to_payload(),
                "system_id": self.system_id,
                "provider_name": self.provider.name,
                "response_model": self.provider.name,
                "context_budget": case.context_budget,
                "selection_k": case.selection_k,
                "seed": case.seed,
            }
        )
