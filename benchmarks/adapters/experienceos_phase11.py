"""Phase 11 retrieval benchmark systems (Prompt 7).

Four systems over ONE shared pipeline — the accepted Phase 9 final
composition (`experienceos_hybrid_full_v2`, scripted-simulated
canonical mode) — differing ONLY in retrieval-strategy configuration:

- ``experienceos_hybrid_full_v2_reference``: byte-identical Phase 9
  behavior under a new ID (the comparison anchor). No embeddings, no
  cache, no fusion, no gate.
- ``experienceos_embedding_only_v1``: Prompt 3 ``semantic_only``
  retrieval (deterministic provider, floor 0.30). No lexical fusion.
- ``experienceos_fused_retrieval_v1``: Prompt 4 ``fused`` retrieval
  with the frozen ``full_fusion`` profile.
- ``experienceos_gate_shadow_v1``: identical to fused, plus the
  shadow-only ``HeuristicShadowMemoryGate`` — proposals are counted,
  never applied; ``affected_selection`` stays 0.

Committed evidence uses the DETERMINISTIC test embedding provider
(``deterministic`` / ``stable-feature-hash-v1``, 512 dims): it
validates plumbing, reproducibility, and lifecycle safety — it is NOT
evidence of neural semantic quality. Everything else (datasets, K,
budgets, answer provider, policy pipeline, temporal policy) is held
constant across the four systems.
"""

from __future__ import annotations

from benchmarks.adapters.experienceos_hybrid_full_v2 import (
    ExperienceOSHybridFullV2Adapter,
)
from benchmarks.contract import SystemId

PHASE11_SCHEMA_VERSION = "phase11-retrieval-1"
PHASE11_PROVIDER = {
    "embedding_provider_id": "deterministic",
    "embedding_model_id": "stable-feature-hash-v1",
    "embedding_dimensions": 512,
    "embedding_provider_class": "deterministic_test_embeddings",
}


class CountingShadowGate:
    """Shadow gate wrapper that tallies proposals for benchmarking.

    Counts are derived from the gate's own proposals plus the
    canonical-selected flag already present in the evidence; the
    wrapper applies nothing and ``affected_selection`` is structurally
    zero.
    """

    def __init__(self):
        from experienceos.controllers.gate import HeuristicShadowMemoryGate

        self._inner = HeuristicShadowMemoryGate()
        self.controller_id = self._inner.controller_id
        self.counters = {
            "gate_evaluated": 0,
            "gate_admit": 0,
            "gate_reject": 0,
            "gate_abstain": 0,
            "gate_agreement": 0,
            "gate_disagreement": 0,
            "gate_neutral": 0,
            "gate_selected_proposed_reject": 0,
            "gate_skipped_proposed_admit": 0,
            "gate_failures": 0,
            "gate_affected_selection": 0,  # invariant: stays 0
        }

    def evaluate(self, evidence):
        proposal = self._inner.evaluate(evidence)
        counters = self.counters
        counters["gate_evaluated"] += 1
        counters[f"gate_{proposal.proposal}"] += 1
        if proposal.proposal == "abstain":
            counters["gate_neutral"] += 1
        elif evidence.canonical_selected == (proposal.proposal == "admit"):
            counters["gate_agreement"] += 1
        else:
            counters["gate_disagreement"] += 1
        if evidence.canonical_selected and proposal.proposal == "reject":
            counters["gate_selected_proposed_reject"] += 1
        if not evidence.canonical_selected and proposal.proposal == "admit":
            counters["gate_skipped_proposed_admit"] += 1
        return proposal


def make_semantic_generator():
    from experienceos.context.semantic import SemanticCandidateGenerator
    from experienceos.embeddings import DeterministicEmbeddingProvider

    return SemanticCandidateGenerator(DeterministicEmbeddingProvider())


class _Phase11AdapterBase(ExperienceOSHybridFullV2Adapter):
    """Shared Phase 11 diagnostics; pipeline inherited unchanged."""

    phase11_role = "reference"

    def _make_policy(self, case):
        policy = super()._make_policy(case)
        self.diagnostics.update(
            {
                "phase11_schema_version": PHASE11_SCHEMA_VERSION,
                "phase11_role": self.phase11_role,
                "reference_of": SystemId.EXPERIENCEOS_HYBRID_FULL_V2,
            }
        )
        return policy


class ExperienceOSHybridFullV2ReferenceAdapter(_Phase11AdapterBase):
    system_id = SystemId.EXPERIENCEOS_HYBRID_FULL_V2_REFERENCE
    phase11_role = "reference"
    # Inherits _retrieval_kwargs() -> {}: the exact Phase 9 strategy.
    # No provider, no cache, no fusion, no gate.


class ExperienceOSEmbeddingOnlyV1Adapter(_Phase11AdapterBase):
    system_id = SystemId.EXPERIENCEOS_EMBEDDING_ONLY_V1
    phase11_role = "embedding_only"

    def _retrieval_kwargs(self, case) -> dict:
        return {
            "semantic_generator": make_semantic_generator(),
            "semantic_mode": "semantic_only",
        }

    def _make_policy(self, case):
        policy = super()._make_policy(case)
        self.diagnostics.update(
            {**PHASE11_PROVIDER, "retrieval_mode": "semantic_only"}
        )
        return policy


class ExperienceOSFusedRetrievalV1Adapter(_Phase11AdapterBase):
    system_id = SystemId.EXPERIENCEOS_FUSED_RETRIEVAL_V1
    phase11_role = "fused"
    fusion_profile_id = "full_fusion"

    def _retrieval_kwargs(self, case) -> dict:
        return {
            "semantic_generator": make_semantic_generator(),
            "semantic_mode": "fused",
            "fusion_profile": self.fusion_profile_id,
        }

    def _make_policy(self, case):
        policy = super()._make_policy(case)
        self.diagnostics.update(
            {
                **PHASE11_PROVIDER,
                "retrieval_mode": "fused",
                "fusion_profile": self.fusion_profile_id,
            }
        )
        return policy


class ExperienceOSGateShadowV1Adapter(ExperienceOSFusedRetrievalV1Adapter):
    system_id = SystemId.EXPERIENCEOS_GATE_SHADOW_V1
    phase11_role = "gate_shadow"

    def _clear(self) -> None:
        super()._clear()
        self._gate = None

    def _retrieval_kwargs(self, case) -> dict:
        self._gate = CountingShadowGate()
        return {**super()._retrieval_kwargs(case),
                "memory_gate": self._gate}

    def _make_policy(self, case):
        policy = super()._make_policy(case)
        self.diagnostics.update(
            {
                "gate_controller_id": "gate_shadow_heuristic-1",
                "gate_shadow_only": True,
            }
        )
        return policy

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        if self._gate is not None:
            self.diagnostics["gate_shadow_v1"] = dict(self._gate.counters)
        return evidence
