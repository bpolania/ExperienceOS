"""ExperienceOS coverage-selection benchmark adapter (Phase 9 E).

Ablation E — ``experienceos_coverage_v2``: identical to
``experienceos_hybrid_retrieval_v2`` in every variable — v1 rules
extraction and lifecycle planning, provider, dataset, K, token budget,
metric semantics, Prompt 4 hybrid retrieval candidate generation and
scoring — except FINAL selection uses the Prompt 5
``CoverageSelectionStrategy``: deterministic query-facet coverage,
redundancy penalties, bounded source-session diversity, and
no-zero-value-padding stop conditions over the same scored active
candidate pool. It answers: does coverage-aware selection improve
context composition when stored memories and retrieval candidates are
unchanged?

No Prompt 2 generalized supersession, no Prompt 3 hybrid extraction,
no Prompt 6 temporal behavior, no Prompt 7 changes.
"""

from __future__ import annotations

from benchmarks.adapters.experienceos_hybrid_retrieval_v2 import (
    ExperienceOSHybridRetrievalV2Adapter,
)
from benchmarks.contract import SystemId
from experienceos.context.retrieval import (
    RETRIEVAL_STRATEGY_VERSION,
    HybridRetrievalStrategy,
)
from experienceos.context.selection import (
    COVERAGE_WEIGHTS_VERSION,
    FACET_EXTRACTOR_VERSION,
    SELECTION_STRATEGY_VERSION,
    CoverageSelectionStrategy,
)


class ExperienceOSCoverageV2Adapter(ExperienceOSHybridRetrievalV2Adapter):
    system_id = SystemId.EXPERIENCEOS_COVERAGE_V2
    memory_policy_label = (
        f"rule_based+hybrid_retrieval_v{RETRIEVAL_STRATEGY_VERSION}"
        f"+coverage_selection_v{SELECTION_STRATEGY_VERSION}"
    )

    def _clear(self) -> None:
        super()._clear()
        self._coverage_strategy: CoverageSelectionStrategy | None = None

    def _make_retrieval_strategy(self, case):
        self._coverage_strategy = CoverageSelectionStrategy()
        self._retrieval_strategy = HybridRetrievalStrategy(
            selection_strategy=self._coverage_strategy
        )
        self.diagnostics.update(
            {
                "memory_extraction_strategy": "v1_rules_unchanged",
                "semantic_identity_strategy": "none",
                "retrieval_strategy": "hybrid_retrieval",
                "retrieval_strategy_version": RETRIEVAL_STRATEGY_VERSION,
                "selection_strategy": "coverage_selection",
                "selection_strategy_version": SELECTION_STRATEGY_VERSION,
                "coverage_weights_version": COVERAGE_WEIGHTS_VERSION,
                "facet_extractor_version": FACET_EXTRACTOR_VERSION,
                "redundancy_strategy": "slot_value+jaccard+evidence",
                "source_diversity_enabled": True,
                "selection_k": case.selection_k,
                "token_budget": case.context_budget,
                "zero_value_padding": False,
                "lifecycle_filtering": "active_only_before_ranking",
                "generalized_supersession_enabled": False,
            }
        )
        return self._retrieval_strategy

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        if self._coverage_strategy is not None:
            self.diagnostics["coverage_v2"] = (
                self._coverage_strategy.summary()
            )
        return evidence
