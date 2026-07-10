"""Serializable benchmark run configuration and profiles.

The quick profile's scenario list is committed here — chosen for
coverage (including known hard cases), fixed BEFORE interpreting any
output, and never adjusted after observing results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.contract import SystemId

SUITE_VERSION = "experienceos-lifecycle-v1"

SYSTEM_ORDER = (
    SystemId.STATELESS,
    SystemId.FULL_HISTORY,
    SystemId.APPEND_ONLY,
    SystemId.NAIVE_TOP_K,
    SystemId.EXPERIENCEOS_RULES,
    SystemId.EXPERIENCEOS_LOCAL,
)

# Quick profile: ~14 representative scenarios, committed before any
# interpretation. Coverage: creation, non-durable boundary, paraphrase
# duplicate (HARD), fact correction, instead-of supersession,
# forgetting, forgotten-leakage probe, lexical mismatch (HARD),
# wrong-domain distractor (HARD), stale leakage, budget pressure,
# compression (HARD for the current engine), duplicate containment,
# malformed-proposal fallback.
QUICK_PROFILE_SCENARIOS = (
    "creation_001_explicit_scoped_preference",
    "creation_004_non_durable_statement",
    "creation_006_paraphrased_duplicate",
    "updates_002_fact_correction",
    "updates_005_instead_of_wording",
    "forgetting_001_exact_forget",
    "forgetting_005_forgotten_leakage_check",
    "retrieval_003_lexical_mismatch",
    "retrieval_004_wrong_domain_similar_wording",
    "retrieval_008_stale_would_mislead",
    "context_001_budget_exceeded",
    "context_003_redundant_compression",
    "containment_001_duplicate_create_contained",
    "containment_004_malformed_proposal_fallback",
)

PROFILES = ("quick", "full-offline", "qwen", "real-local")

# Optional profiles are configuration-only in Prompt 5: they resolve
# but are never executed by default and never required for validation.
OFFLINE_PROFILES = ("quick", "full-offline")


@dataclass(frozen=True)
class RunConfig:
    profile: str
    output_dir: str
    run_id: str = "offline-run"
    suite_version: str = SUITE_VERSION
    dataset_version: str = "experienceos-lifecycle-v1"
    systems: tuple = SYSTEM_ORDER
    scenario_ids: tuple = ()  # empty = manifest order (full profile)
    response_provider_mode: str = "deterministic-offline"
    memory_policy_mode: str = "per-system"
    local_policy_mode: str = "scripted"
    storage_mode: str = "in_memory"
    context_budget_source: str = "per-scenario"
    selection_k_source: str = "per-scenario"
    token_accounting_method: str = "approximation"
    temperature: float | None = None
    max_output_tokens: int | None = None
    seed_policy: str = "per-scenario committed seeds"
    retry_policy: str = "none"
    evaluator_mode: str = "deterministic"
    overwrite: bool = False
    fail_fast: bool = False
    timestamp_override: str | None = None
    notes: tuple = ()

    def to_payload(self) -> dict:
        return {
            "profile": self.profile,
            "output_dir": self.output_dir,
            "run_id": self.run_id,
            "suite_version": self.suite_version,
            "dataset_version": self.dataset_version,
            "systems": list(self.systems),
            "scenario_ids": list(self.scenario_ids),
            "response_provider_mode": self.response_provider_mode,
            "memory_policy_mode": self.memory_policy_mode,
            "local_policy_mode": self.local_policy_mode,
            "storage_mode": self.storage_mode,
            "context_budget_source": self.context_budget_source,
            "selection_k_source": self.selection_k_source,
            "token_accounting_method": self.token_accounting_method,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "seed_policy": self.seed_policy,
            "retry_policy": self.retry_policy,
            "evaluator_mode": self.evaluator_mode,
            "overwrite": self.overwrite,
            "fail_fast": self.fail_fast,
            "notes": list(self.notes),
        }


def profile_config(profile: str, output_dir: str, **overrides) -> RunConfig:
    if profile not in PROFILES:
        raise ValueError(
            f"unknown profile {profile!r}; expected one of {PROFILES}"
        )
    if profile not in OFFLINE_PROFILES:
        raise ValueError(
            f"profile {profile!r} is configuration-only in this phase: "
            "it requires explicit credentials/model setup and is never "
            "run by default"
        )
    scenario_ids = (
        QUICK_PROFILE_SCENARIOS if profile == "quick" else ()
    )
    return RunConfig(
        profile=profile,
        output_dir=output_dir,
        run_id=overrides.pop("run_id", f"{profile}-offline"),
        scenario_ids=scenario_ids,
        **overrides,
    )
