"""ExperienceOS hybrid-retrieval benchmark adapters (Phase 9 C and D).

Ablation C — ``experienceos_hybrid_retrieval_v2``: identical to
``experienceos_rules`` in every variable — planner (v1 rules
extraction and lifecycle), provider mode, dataset, K, token budget,
metric semantics, lifecycle filtering — except context selection uses
``HybridRetrievalStrategy`` (broad lexical + structured-semantic
candidate generation, lifecycle filtering before ranking, query-aware
scoring, deterministic tie-breaking, zero-relevance exclusion). It
answers: can retrieval improve when the stored memory set is
unchanged?

Ablation D — ``experienceos_extract_retrieval_v2``: composes Prompt 3
``HybridMemoryPlanner`` extraction with Prompt 4 hybrid retrieval.
It does NOT enable Prompt 2 generalized supersession, Prompt 5
coverage selection, Prompt 6 temporal logic, or Prompt 7 policy
changes — the exact composition is recorded in provenance. It
answers: do better extraction and better retrieval reinforce each
other, and at what contamination/context cost?
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.contract import SystemId
from experienceos.context.retrieval import (
    CANDIDATE_GENERATION_STRATEGY,
    LEXICAL_SCORING_VERSION,
    RETRIEVAL_STRATEGY_VERSION,
    HybridRetrievalStrategy,
)
from experienceos.memory.hybrid_planner import (
    EXTRACTION_STRATEGY,
    EXTRACTION_STRATEGY_VERSION,
    HybridMemoryPlanner,
)

_RETRIEVAL_PROVENANCE = {
    "retrieval_strategy": "hybrid_retrieval",
    "retrieval_strategy_version": RETRIEVAL_STRATEGY_VERSION,
    "candidate_generation_strategy": CANDIDATE_GENERATION_STRATEGY,
    "candidate_limit": None,  # bounded populations: all actives scored
    "lexical_scoring_version": LEXICAL_SCORING_VERSION,
    "semantic_scoring_enabled": True,
    "embedding_scoring_enabled": False,
    "selection_strategy": "deterministic_top_k",  # Prompt 5 owns coverage
    "lifecycle_filtering": "active_only_before_ranking",
    "historical_mode_support": False,
}


class ExperienceOSHybridRetrievalV2Adapter(ExperienceOSAdapterBase):
    """Ablation C: rules extraction + hybrid retrieval."""

    system_id = SystemId.EXPERIENCEOS_HYBRID_RETRIEVAL_V2
    memory_policy_label = (
        f"rule_based+hybrid_retrieval_v{RETRIEVAL_STRATEGY_VERSION}"
    )

    def _clear(self) -> None:
        super()._clear()
        self._retrieval_strategy: HybridRetrievalStrategy | None = None

    def _make_retrieval_strategy(self, case):
        self._retrieval_strategy = HybridRetrievalStrategy()
        self.diagnostics.update(
            {
                "memory_extraction_strategy": "v1_rules_unchanged",
                "semantic_identity_strategy": "none",
                **_RETRIEVAL_PROVENANCE,
                "selection_k": case.selection_k,
                "token_budget": case.context_budget,
            }
        )
        return self._retrieval_strategy

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        if self._retrieval_strategy is not None:
            self.diagnostics["retrieval_v2"] = (
                self._retrieval_strategy.summary()
            )
        return evidence


class ExperienceOSExtractRetrievalV2Adapter(
    ExperienceOSHybridRetrievalV2Adapter
):
    """Ablation D: Prompt 3 hybrid extraction + Prompt 4 retrieval.

    ``coverage_selection=True`` composes Prompt 5 coverage selection on
    top — a DEVELOPMENT-ONLY configuration (not a registered system,
    not ``experienceos_hybrid_full_v2``) declared in provenance and
    used by dev ablation scripts via direct construction.
    """

    system_id = SystemId.EXPERIENCEOS_EXTRACT_RETRIEVAL_V2
    memory_policy_label = (
        f"rule_based+hybrid_extraction_v{EXTRACTION_STRATEGY_VERSION}"
        f"+hybrid_retrieval_v{RETRIEVAL_STRATEGY_VERSION}"
    )

    def __init__(self, provider=None, seed: int = 0,
                 coverage_selection: bool = False):
        self._coverage_selection = coverage_selection
        super().__init__(provider=provider, seed=seed)
        if coverage_selection:
            self.system_id = "dev_extract_retrieval_coverage"
            self.memory_policy_label += "+coverage_selection_v1(dev)"
            self.config = type(self.config)(
                **{**self.config.to_payload(), "system_id": self.system_id,
                   "memory_policy": self.memory_policy_label}
            )

    def _clear(self) -> None:
        super()._clear()
        self._hybrid_planner: HybridMemoryPlanner | None = None
        self._coverage_strategy = None

    def _make_retrieval_strategy(self, case):
        if not getattr(self, "_coverage_selection", False):
            return super()._make_retrieval_strategy(case)
        from experienceos.context.selection import (
            SELECTION_STRATEGY_VERSION,
            CoverageSelectionStrategy,
        )

        self._coverage_strategy = CoverageSelectionStrategy()
        self._retrieval_strategy = HybridRetrievalStrategy(
            selection_strategy=self._coverage_strategy
        )
        self.diagnostics.update(
            {
                "memory_extraction_strategy": "v1_rules_unchanged",
                "semantic_identity_strategy": "none",
                **_RETRIEVAL_PROVENANCE,
                "selection_strategy": "coverage_selection",
                "selection_strategy_version": SELECTION_STRATEGY_VERSION,
                "development_composition": (
                    "hybrid_extraction+hybrid_retrieval+coverage_selection"
                ),
                "selection_k": case.selection_k,
                "token_budget": case.context_budget,
            }
        )
        return self._retrieval_strategy

    def _make_planner(self, case):
        self._hybrid_planner = HybridMemoryPlanner()
        self.diagnostics.update(
            {
                "memory_extraction_strategy": EXTRACTION_STRATEGY,
                "memory_extraction_strategy_version": (
                    EXTRACTION_STRATEGY_VERSION
                ),
                "local_extractor_enabled": False,
                "semantic_identity_attachment": True,
                # Prompt 3 extraction-only lifecycle retained: no
                # Prompt 2 generalized supersession in this ablation.
                "generalized_supersession_enabled": False,
                "planner_strategy": "v1_rule_planning+hybrid_extraction",
            }
        )
        return self._hybrid_planner

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        if self._hybrid_planner is not None:
            self.diagnostics["extraction_v2"] = (
                self._hybrid_planner.summary()
            )
        if self._coverage_strategy is not None:
            self.diagnostics["coverage_v2"] = (
                self._coverage_strategy.summary()
            )
        return evidence
