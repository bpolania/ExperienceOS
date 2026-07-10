"""ExperienceOS slots-v2 benchmark adapter (Phase 9 ablation A).

Identical to ``experienceos_rules`` in every variable — provider mode,
deterministic settings, extraction, retrieval K, token budget, dataset,
metric semantics, lifecycle filtering — except that memory planning
uses ``SemanticMemoryPlanner``: v1 planning plus versioned semantic
identity and conservative generalized supersession. The v1
``experienceos_rules`` system keeps the plain ``MemoryPlanner`` and its
frozen Phase 8 behavior.
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.contract import SystemId
from experienceos.memory.semantic import (
    CONFLICT_STRATEGY_VERSION,
    SEMANTIC_IDENTITY_VERSION,
)
from experienceos.memory.semantic_planner import SemanticMemoryPlanner


class ExperienceOSSlotsV2Adapter(ExperienceOSAdapterBase):
    system_id = SystemId.EXPERIENCEOS_SLOTS_V2
    memory_policy_label = (
        f"rule_based+semantic_identity_v{SEMANTIC_IDENTITY_VERSION}"
    )

    def _make_planner(self, case):
        self.diagnostics.update(
            {
                "semantic_identity_enabled": True,
                "semantic_identity_version": SEMANTIC_IDENTITY_VERSION,
                "conflict_strategy": CONFLICT_STRATEGY_VERSION,
                "generalized_supersession_enabled": True,
            }
        )
        return SemanticMemoryPlanner()
