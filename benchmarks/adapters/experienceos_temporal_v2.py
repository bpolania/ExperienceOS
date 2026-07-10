"""ExperienceOS temporal/provenance benchmark adapter (Phase 9 F).

Ablation F — ``experienceos_temporal_v2``: rules extraction + Prompt 2
semantic identity and conservative supersession (required so
corrections produce derivable validity transitions) + Prompt 4 hybrid
retrieval + Prompt 5 coverage selection + Prompt 6 temporal and
provenance behavior: temporal metadata on creates, provenance
classification, historical-statement coexistence, current/historical/
as-of/timeline query modes, temporal scoring refinement, and labeled
context rendering. Assistant-derived ingestion is feature-flagged ON
for this system only, under the explicit eligibility policy (user
confirmation, tool verification, deterministic derivation — never
unconfirmed assistant content).

Unchanged: K, token budget, answer provider, dataset, metric
semantics. No Prompt 7 behavior.

``dev_composition=True`` additionally composes Prompt 3 hybrid
extraction — a DEVELOPMENT-ONLY pre-full-v2 configuration (not a
registered system, never ``experienceos_hybrid_full_v2``).
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.contract import SystemId
from experienceos.context.retrieval import (
    RETRIEVAL_STRATEGY_VERSION,
    HybridRetrievalStrategy,
)
from experienceos.context.selection import (
    SELECTION_STRATEGY_VERSION,
    CoverageSelectionStrategy,
)
from experienceos.memory.hybrid_planner import HybridMemoryPlanner
from experienceos.memory.temporal import (
    PROVENANCE_VERSION,
    QUERY_MODE_VERSION,
    TEMPORAL_VERSION,
    VALIDITY_STRATEGY,
    TemporalRetrievalPolicy,
)
from experienceos.memory.temporal_planner import (
    ASSISTANT_INGESTION_POLICY,
    TemporalMemoryPlanner,
)


class _DevFullTemporalPlanner(TemporalMemoryPlanner, HybridMemoryPlanner):
    """Development-only: hybrid extraction under semantic+temporal
    planning (MRO: temporal → semantic → hybrid → v1 rules)."""

    def __init__(self, assistant_ingestion: bool = True):
        HybridMemoryPlanner.__init__(self)
        hybrid_counters = self.counters
        TemporalMemoryPlanner.__init__(
            self,
            normalizer=self.normalizer,
            assistant_ingestion=assistant_ingestion,
        )
        # Both mixins keep counters on ``self.counters``; merge so the
        # hybrid extraction counters survive the temporal init.
        self.counters = {**hybrid_counters, **self.counters}


class ExperienceOSTemporalV2Adapter(ExperienceOSAdapterBase):
    system_id = SystemId.EXPERIENCEOS_TEMPORAL_V2
    memory_policy_label = (
        "rule_based+semantic_identity_v1"
        f"+temporal_v{TEMPORAL_VERSION}"
        f"+hybrid_retrieval_v{RETRIEVAL_STRATEGY_VERSION}"
        f"+coverage_selection_v{SELECTION_STRATEGY_VERSION}"
    )

    def __init__(self, provider=None, seed: int = 0,
                 dev_composition: bool = False):
        self._dev_composition = dev_composition
        super().__init__(provider=provider, seed=seed)
        if dev_composition:
            self.system_id = "dev_full_temporal"
            self.memory_policy_label = (
                self.memory_policy_label.replace(
                    "rule_based+", "rule_based+hybrid_extraction_v1+"
                )
                + "(dev)"
            )
            self.config = type(self.config)(
                **{**self.config.to_payload(),
                   "system_id": self.system_id,
                   "memory_policy": self.memory_policy_label}
            )

    def _clear(self) -> None:
        super()._clear()
        self._temporal_planner = None
        self._temporal_policy = None
        self._coverage_strategy = None
        self._retrieval_strategy = None

    def _make_planner(self, case):
        if getattr(self, "_dev_composition", False):
            self._temporal_planner = _DevFullTemporalPlanner()
            extraction_strategy = "rules_first_hybrid+semantic+temporal"
        else:
            self._temporal_planner = TemporalMemoryPlanner(
                assistant_ingestion=True
            )
            extraction_strategy = "v1_rules+semantic+temporal"
        self.diagnostics.update(
            {
                "memory_extraction_strategy": extraction_strategy,
                "semantic_identity_strategy": "conservative-1",
                "temporal_metadata_version": TEMPORAL_VERSION,
                "provenance_version": PROVENANCE_VERSION,
                "assistant_ingestion_enabled": True,
                "assistant_ingestion_policy": ASSISTANT_INGESTION_POLICY,
                "temporal_query_mode_version": QUERY_MODE_VERSION,
                "validity_strategy": VALIDITY_STRATEGY,
                "retrieval_strategy": "hybrid_retrieval",
                "selection_strategy": "coverage_selection",
                "selection_k": case.selection_k,
                "token_budget": case.context_budget,
                "lifecycle_filtering": "active_only_before_ranking"
                                       "+historical_modes_admit_superseded",
                "forgotten_history_policy": "always_excluded_user_facing",
                "generalized_supersession_enabled": True,
            }
        )
        return self._temporal_planner

    def _make_retrieval_strategy(self, case):
        self._temporal_policy = TemporalRetrievalPolicy()
        self._coverage_strategy = CoverageSelectionStrategy()
        self._retrieval_strategy = HybridRetrievalStrategy(
            selection_strategy=self._coverage_strategy,
            temporal_policy=self._temporal_policy,
        )
        return self._retrieval_strategy

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        if self._temporal_planner is not None:
            self.diagnostics["temporal_v2"] = {
                **self._temporal_planner.summary(),
                **(
                    self._temporal_policy.summary()
                    if self._temporal_policy is not None
                    else {}
                ),
            }
        if self._coverage_strategy is not None:
            self.diagnostics["coverage_v2"] = (
                self._coverage_strategy.summary()
            )
        if self._retrieval_strategy is not None:
            self.diagnostics["retrieval_v2"] = (
                self._retrieval_strategy.summary()
            )
        return evidence
