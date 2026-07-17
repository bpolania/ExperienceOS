"""System registry and adapters for the comparison harness.

Maps the evaluation's seven logical system ids to existing benchmark
implementations, adds the canonical Qwen system adapter, and registers
the lightweight Mem0-style baseline as an explicit unavailable seam. Each
system is driven through the existing execution drivers
(`run_adapter_case` for ExperienceOS systems, `run_case` for baselines),
so no second execution path is introduced. Availability is checked
before execution; an unavailable system is recorded as unavailable and
never silently replaced by another system.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.adapters.common import run_adapter_case
from benchmarks.adapters.experienceos_rules import ExperienceOSRulesAdapter
from benchmarks.baselines.factory import create_baseline
from benchmarks.baselines.common import run_case as run_baseline_case
from benchmarks.contract import SystemId

# -- logical system ids (the evaluation's names) -----------------------------

CANONICAL_EXPERIENCEOS_QWEN = "canonical_experienceos_qwen"
DETERMINISTIC_EXPERIENCEOS = "deterministic_experienceos"
STATELESS = "stateless"
FULL_HISTORY = "full_history"
NAIVE_TOP_K = "naive_top_k"
APPEND_ONLY = "append_only"
MEM0_STYLE_LIGHTWEIGHT = "mem0_style_lightweight"

# Execution families decide which existing driver runs a system.
FAMILY_EXPERIENCEOS = "experienceos"
FAMILY_BASELINE = "baseline"
FAMILY_UNIMPLEMENTED = "unimplemented"

# Availability statuses.
AVAILABLE = "available"
NOT_IMPLEMENTED = "not_implemented"


@dataclass(frozen=True)
class SystemSpec:
    """Static description of one registered system.

    ``builder`` constructs a BenchmarkSystem from an injected provider and
    seed; it is None for a system that is registered but not implemented,
    which the harness records as unavailable rather than dropping.
    """

    logical_id: str
    family: str
    availability: str
    capabilities: tuple = ()
    builder: object = None
    note: str = ""


def _baseline_builder(underlying_id):
    def build(provider, seed):
        return create_baseline(underlying_id, provider=provider, seed=seed)

    return build


def _deterministic_builder(provider, seed):
    return ExperienceOSRulesAdapter(provider=provider, seed=seed)


def _canonical_builder(provider, seed):
    # Imported lazily so this registry stays importable without the demo /
    # provider-coupled dependencies loaded.
    from experiments.competitive_viability.qwen_system import (
        CanonicalQwenSystem,
    )

    return CanonicalQwenSystem(provider=provider, seed=seed)


#: Capability vocabulary — honest per-system feature presence, so a
#: baseline is never forced to emulate lifecycle features it lacks.
CAP_CREATE = "create"
CAP_UPDATE = "update"
CAP_FORGET = "forget"
CAP_SUPERSEDE = "supersede"
CAP_RETRIEVAL = "retrieval"
CAP_GOVERNED_MUTATION = "governed_mutation"
CAP_QWEN_EXTRACTION = "qwen_extraction"
CAP_FULL_HISTORY = "full_history_context"


SYSTEM_REGISTRY = {
    CANONICAL_EXPERIENCEOS_QWEN: SystemSpec(
        logical_id=CANONICAL_EXPERIENCEOS_QWEN,
        family=FAMILY_EXPERIENCEOS,
        availability=AVAILABLE,
        capabilities=(
            CAP_CREATE, CAP_UPDATE, CAP_FORGET, CAP_SUPERSEDE, CAP_RETRIEVAL,
            CAP_GOVERNED_MUTATION, CAP_QWEN_EXTRACTION,
        ),
        builder=_canonical_builder,
        note="demo composition: create_agent + build_canonical_extraction_config",
    ),
    DETERMINISTIC_EXPERIENCEOS: SystemSpec(
        logical_id=DETERMINISTIC_EXPERIENCEOS,
        family=FAMILY_EXPERIENCEOS,
        availability=AVAILABLE,
        capabilities=(
            CAP_CREATE, CAP_UPDATE, CAP_FORGET, CAP_SUPERSEDE, CAP_RETRIEVAL,
            CAP_GOVERNED_MUTATION,
        ),
        builder=_deterministic_builder,
        note="internal reference; ExperienceOSRulesAdapter",
    ),
    STATELESS: SystemSpec(
        logical_id=STATELESS,
        family=FAMILY_BASELINE,
        availability=AVAILABLE,
        capabilities=(),
        builder=_baseline_builder(SystemId.STATELESS),
        note="no persistent memory",
    ),
    FULL_HISTORY: SystemSpec(
        logical_id=FULL_HISTORY,
        family=FAMILY_BASELINE,
        availability=AVAILABLE,
        capabilities=(CAP_FULL_HISTORY,),
        builder=_baseline_builder(SystemId.FULL_HISTORY),
        note="complete history to the response model",
    ),
    NAIVE_TOP_K: SystemSpec(
        logical_id=NAIVE_TOP_K,
        family=FAMILY_BASELINE,
        availability=AVAILABLE,
        capabilities=(CAP_CREATE, CAP_RETRIEVAL),
        builder=_baseline_builder(SystemId.NAIVE_TOP_K),
        note="raw top-K retrieval, no lifecycle",
    ),
    APPEND_ONLY: SystemSpec(
        logical_id=APPEND_ONLY,
        family=FAMILY_BASELINE,
        availability=AVAILABLE,
        capabilities=(CAP_CREATE, CAP_RETRIEVAL),
        builder=_baseline_builder(SystemId.APPEND_ONLY),
        note="stored memories, no update/forget/supersede",
    ),
    MEM0_STYLE_LIGHTWEIGHT: SystemSpec(
        logical_id=MEM0_STYLE_LIGHTWEIGHT,
        family=FAMILY_UNIMPLEMENTED,
        availability=NOT_IMPLEMENTED,
        capabilities=(CAP_CREATE, CAP_UPDATE, CAP_FORGET, CAP_RETRIEVAL),
        builder=None,
        note=(
            "lightweight add/update/delete/no-op over the same provider; "
            "deferred — registered but not implemented. Never labelled "
            "as official Mem0."
        ),
    ),
}

#: Stable declaration order for manifests and reports.
REGISTERED_SYSTEM_IDS = tuple(SYSTEM_REGISTRY)


def system_spec(logical_id: str) -> SystemSpec:
    if logical_id not in SYSTEM_REGISTRY:
        raise KeyError(
            f"unknown system {logical_id!r}; registered: "
            f"{sorted(SYSTEM_REGISTRY)}"
        )
    return SYSTEM_REGISTRY[logical_id]


def is_available(logical_id: str) -> bool:
    return system_spec(logical_id).availability == AVAILABLE


def build_system(logical_id: str, provider, seed: int = 0):
    """Construct the BenchmarkSystem for a registered id, or None if the
    system is registered but not implemented/available."""
    spec = system_spec(logical_id)
    if spec.builder is None:
        return None
    return spec.builder(provider, seed)


def run_system_case(logical_id: str, scenario, provider, run_id: str):
    """Drive one system over one scenario through the existing driver.

    Returns a contract-valid CaseResult. For an unavailable system,
    returns None — the harness records it as unavailable and never
    substitutes another system's result.
    """
    spec = system_spec(logical_id)
    if spec.family == FAMILY_EXPERIENCEOS:
        # The SDK path speaks the dict-message contract natively and needs
        # the raw provider so the canonical extraction selection can detect
        # a configured Qwen provider by type.
        system = build_system(logical_id, provider, seed=scenario.case.seed)
        if system is None:
            return None
        result = run_adapter_case(system, scenario, run_id=run_id)
    else:
        # Baselines speak the string-message contract; the shim adapts the
        # same underlying model to that contract (shape only, not content).
        from experiments.competitive_viability.response_provider import (
            UnifiedResponseProvider,
        )

        system = build_system(
            logical_id, UnifiedResponseProvider(provider),
            seed=scenario.case.seed,
        )
        if system is None:
            return None
        result = run_baseline_case(system, scenario, run_id=run_id)
    # Stamp the logical system id so failures and evidence are always
    # attributed to the requested system, not an underlying adapter id.
    result.system_id = logical_id
    return result
