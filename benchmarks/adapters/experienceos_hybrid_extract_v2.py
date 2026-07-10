"""ExperienceOS hybrid-extraction benchmark adapter (Phase 9 ablation B).

Identical to ``experienceos_rules`` in every variable — provider mode,
deterministic settings, retrieval algorithm, selection K, context
budget, dataset, metric semantics, lifecycle filtering — except memory
planning uses ``HybridMemoryPlanner``: unchanged v1 rule planning plus
a deterministic durability gate and validated structured candidate
extraction for unmatched durable conversational content.

Extraction-only isolation (recorded in provenance): the deterministic
offline extractor is enabled, the local-model extractor is disabled,
semantic identity metadata is attached to accepted candidates, and the
lifecycle planning strategy stays v1 — no Prompt 2 generalized
supersession, no Prompt 4 retrieval changes, no Prompt 5 selection
changes, no hidden K increase.
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.contract import SystemId
from experienceos.memory.hybrid_planner import (
    EXTRACTION_STRATEGY,
    EXTRACTION_STRATEGY_VERSION,
    HybridMemoryPlanner,
)


class ExperienceOSHybridExtractV2Adapter(ExperienceOSAdapterBase):
    system_id = SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2
    memory_policy_label = (
        f"rule_based+hybrid_extraction_v{EXTRACTION_STRATEGY_VERSION}"
    )

    def _clear(self) -> None:
        super()._clear()
        self._hybrid_planner: HybridMemoryPlanner | None = None

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
                "generalized_supersession_enabled": False,
                "planner_strategy": "v1_rule_planning+hybrid_extraction",
                "retrieval_strategy": "phase8_v1_unchanged",
                "selection_strategy": "phase8_v1_unchanged",
            }
        )
        return self._hybrid_planner

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        if self._hybrid_planner is not None:
            self.diagnostics["extraction_v2"] = self._hybrid_planner.summary()
        return evidence
