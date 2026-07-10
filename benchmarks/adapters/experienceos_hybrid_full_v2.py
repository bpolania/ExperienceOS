"""ExperienceOS final Phase 9 system: ``experienceos_hybrid_full_v2``.

The contract-declared final composition, assembled ONLY from measured
components that cleared every Prompt 1 adoption blocker:

- Prompt 2 semantic identity + conservative generalized supersession
- Prompt 3 hybrid deterministic conversational extraction
- Prompt 4 lifecycle-aware hybrid retrieval
- Prompt 5 coverage-aware selection
- Prompt 6 temporal/provenance behavior (assistant ingestion OFF —
  the frozen datasets contain no eligible assistant/tool turns)
- Prompt 7 deterministic forget resolver
- Prompt 7 local-policy v2 validation/containment pipeline in the
  SCRIPTED-SIMULATED canonical mode (deterministic plan serialized
  through the real parse/validate/audit pipeline — direct model
  inference is FALSE and the provenance says so)

Unchanged: K, context-budget semantics, answer provider, frozen
datasets. No optional embeddings. No direct reliance on the 0.5B
model for canonical lifecycle correctness; the real-local variant
(``mode="real"``) is development-only evidence, never canonical.
"""

from __future__ import annotations

from benchmarks.adapters.experienceos_local_v2 import (
    ExperienceOSLocalV2Adapter,
)
from benchmarks.contract import SystemId

FULL_V2_VERSION = "1"


class ExperienceOSHybridFullV2Adapter(ExperienceOSLocalV2Adapter):
    system_id = SystemId.EXPERIENCEOS_HYBRID_FULL_V2
    memory_policy_label = (
        "hybrid_full_v2(semantic+extraction+retrieval+coverage"
        "+temporal+forget+local_policy_v2)"
    )

    def _make_policy(self, case):
        policy = super()._make_policy(case)
        self.diagnostics.update(
            {
                "final_system_version": FULL_V2_VERSION,
                "composition": (
                    "semantic_identity_v1+hybrid_extraction_v1"
                    "+hybrid_retrieval_v1+coverage_selection_v1"
                    "+temporal_v1+forget_resolver_v1+local_policy_v2"
                ),
                "proposal_source": (
                    "deterministic_plan_serialized_through_local_v2_pipeline"
                ),
                "direct_model_inference": False,
                "simulated_proposal": self.mode == "scripted",
                "assistant_ingestion_enabled": False,
                "zero_value_padding": False,
                "forgotten_history_policy": "always_excluded_user_facing",
            }
        )
        return policy
