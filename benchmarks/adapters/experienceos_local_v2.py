"""ExperienceOS local-policy v2 benchmark adapter (Phase 9 G).

``experienceos_local_v2``: the pre-full-v2 architecture (Prompt 2
semantic supersession + Prompt 3 hybrid extraction + Prompt 4 hybrid
retrieval + Prompt 5 coverage selection + Prompt 6 temporal/provenance)
plus Prompt 7 forget resolution and the one-action local-policy v2
pipeline. Unchanged K, token budget, answer provider, and datasets.

Modes:

- ``scripted`` (canonical offline): a SIMULATED well-behaved proposer
  serializes the deterministic plan into one v2 proposal per turn and
  runs it through the REAL parser/validator/fallback pipeline —
  reproducible containment evidence, never real-model accuracy.
- ``deterministic``: the same architecture without any local policy
  (isolates Prompt 7 forget-resolution value).
- ``real``: the optional local GGUF model through the same pipeline —
  separately labeled development evidence only.

Historical ``experienceos_local`` is untouched.
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.contract import SystemId, safe_model_name
from experienceos.context.retrieval import (
    RETRIEVAL_STRATEGY_VERSION,
    HybridRetrievalStrategy,
)
from experienceos.context.selection import (
    SELECTION_STRATEGY_VERSION,
    CoverageSelectionStrategy,
)
from experienceos.memory.forget import (
    FORGET_RESOLVER_VERSION,
    ForgetTargetResolver,
)
from experienceos.memory.temporal import (
    PROVENANCE_VERSION,
    TEMPORAL_VERSION,
    TemporalRetrievalPolicy,
)
from experienceos.policy.local_v2 import (
    LOCAL_POLICY_V2_VERSION,
    MAX_RETRIES,
    PARSER_V2_VERSION,
    PROPOSAL_SCHEMA_V2_VERSION,
    LocalPolicyV2,
    ScriptedLocalPolicyV2,
)

MODES_V2 = ("scripted", "deterministic", "real")


def _make_planner_stack():
    from benchmarks.adapters.experienceos_temporal_v2 import (
        _DevFullTemporalPlanner,
    )

    planner = _DevFullTemporalPlanner(assistant_ingestion=False)
    planner.forget_resolver = ForgetTargetResolver()
    return planner


class ExperienceOSLocalV2Adapter(ExperienceOSAdapterBase):
    system_id = SystemId.EXPERIENCEOS_LOCAL_V2
    memory_policy_label = (
        f"local_policy_v{LOCAL_POLICY_V2_VERSION}"
        f"+forget_resolver_v{FORGET_RESOLVER_VERSION}+pre_full_v2"
    )

    def __init__(self, provider=None, seed: int = 0,
                 mode: str = "scripted"):
        if mode not in MODES_V2:
            raise ValueError(
                f"unknown local_v2 mode {mode!r}; valid modes: {MODES_V2}"
            )
        self.mode = mode
        super().__init__(provider=provider, seed=seed)
        if mode == "deterministic":
            self.system_id = "dev_forget_deterministic"
            self.config = type(self.config)(
                **{**self.config.to_payload(),
                   "system_id": self.system_id}
            )

    def _clear(self) -> None:
        super()._clear()
        self._planner = None
        self._policy = None
        self._temporal_policy = None
        self._coverage_strategy = None
        self._retrieval = None

    def _make_policy(self, case):
        if self.mode == "deterministic":
            return None
        self._planner = _make_planner_stack()
        if self.mode == "scripted":
            self._policy = ScriptedLocalPolicyV2(
                deterministic_planner=self._planner
            )
            model_identity = "scripted-simulated-proposals"
        else:  # real
            from experienceos.policy.local_runner import (
                LlamaCppLocalModelRunner,
            )

            runner = LlamaCppLocalModelRunner()
            self._policy = LocalPolicyV2(
                runner=runner, deterministic_planner=self._planner
            )
            availability = runner.availability()
            model_identity = (
                safe_model_name(availability.model_path)
                if availability.available
                else "unavailable"
            )
        self.diagnostics.update(
            {
                "local_policy_version": LOCAL_POLICY_V2_VERSION,
                "proposal_schema_version": PROPOSAL_SCHEMA_V2_VERSION,
                "parser_version": PARSER_V2_VERSION,
                "forget_resolver_version": FORGET_RESOLVER_VERSION,
                "max_retries": MAX_RETRIES,
                "fallback_strategy": "per_action_deterministic",
                "constrained_output_requested": self.mode == "real",
                "local_model_mode": self.mode,
                "model_identity": model_identity,
            }
        )
        return self._policy

    def _make_planner(self, case):
        if self.mode != "deterministic":
            return None  # policy path owns planning
        self._planner = _make_planner_stack()
        self.diagnostics.update(
            {
                "local_model_mode": "deterministic",
                "forget_resolver_version": FORGET_RESOLVER_VERSION,
            }
        )
        return self._planner

    def _make_retrieval_strategy(self, case):
        self._temporal_policy = TemporalRetrievalPolicy()
        self._coverage_strategy = CoverageSelectionStrategy()
        self._retrieval = HybridRetrievalStrategy(
            selection_strategy=self._coverage_strategy,
            temporal_policy=self._temporal_policy,
        )
        self.diagnostics.update(
            {
                "memory_extraction_strategy": (
                    "rules_first_hybrid+semantic+temporal"
                ),
                "semantic_identity_strategy": "conservative-1",
                "temporal_metadata_version": TEMPORAL_VERSION,
                "provenance_version": PROVENANCE_VERSION,
                "retrieval_strategy": "hybrid_retrieval",
                "retrieval_strategy_version": RETRIEVAL_STRATEGY_VERSION,
                "selection_strategy": "coverage_selection",
                "selection_strategy_version": SELECTION_STRATEGY_VERSION,
                "selection_k": case.selection_k,
                "token_budget": case.context_budget,
                "lifecycle_filtering": "active_only_before_ranking"
                                       "+historical_modes_admit_superseded",
                "generalized_supersession_enabled": True,
            }
        )
        return self._retrieval

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        summary: dict = {}
        if self._planner is not None:
            summary.update(
                {k: v for k, v in self._planner.counters.items()}
            )
        if self._policy is not None:
            summary.update(self._policy.summary())
            self.local_model_invocation_count = (
                self._policy.counters["decisions"]
            )
        if summary:
            self.diagnostics["forget_policy_v2"] = summary
        if self._retrieval is not None:
            self.diagnostics["retrieval_v2"] = self._retrieval.summary()
        if self._coverage_strategy is not None:
            self.diagnostics["coverage_v2"] = (
                self._coverage_strategy.summary()
            )
        return evidence
