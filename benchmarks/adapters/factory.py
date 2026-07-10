"""Six-system dispatcher: baselines plus ExperienceOS adapters.

The Prompt 3 baseline factory stays unchanged (and still rejects
ExperienceOS IDs); this is the public path that resolves every
SystemId.
"""

from __future__ import annotations

from benchmarks.adapters.experienceos_local import (
    MODES,
    ExperienceOSLocalAdapter,
)
from benchmarks.adapters.experienceos_hybrid_extract_v2 import (
    ExperienceOSHybridExtractV2Adapter,
)
from benchmarks.adapters.experienceos_hybrid_retrieval_v2 import (
    ExperienceOSExtractRetrievalV2Adapter,
    ExperienceOSHybridRetrievalV2Adapter,
)
from benchmarks.adapters.experienceos_rules import ExperienceOSRulesAdapter
from benchmarks.adapters.experienceos_slots_v2 import (
    ExperienceOSSlotsV2Adapter,
)
from benchmarks.baselines.factory import BASELINE_CLASSES
from benchmarks.contract import KNOWN_SYSTEM_IDS, SystemId

ADAPTER_SYSTEM_IDS = (
    SystemId.EXPERIENCEOS_RULES,
    SystemId.EXPERIENCEOS_LOCAL,
    SystemId.EXPERIENCEOS_SLOTS_V2,
    SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2,
    SystemId.EXPERIENCEOS_HYBRID_RETRIEVAL_V2,
    SystemId.EXPERIENCEOS_EXTRACT_RETRIEVAL_V2,
)


def create_system(
    system_id: str,
    provider=None,
    seed: int = 0,
    local_mode: str = "scripted",
):
    """Resolve any of the six benchmark systems.

    ``local_mode`` applies only to experienceos_local; passing a
    non-default value for any other system is rejected to prevent
    silently ignored configuration.
    """
    if system_id == SystemId.EXPERIENCEOS_LOCAL:
        return ExperienceOSLocalAdapter(
            provider=provider, seed=seed, mode=local_mode
        )
    if local_mode != "scripted":
        raise ValueError(
            f"local_mode={local_mode!r} applies only to "
            f"{SystemId.EXPERIENCEOS_LOCAL!r}, not {system_id!r} "
            f"(valid modes: {MODES})"
        )
    if system_id == SystemId.EXPERIENCEOS_RULES:
        return ExperienceOSRulesAdapter(provider=provider, seed=seed)
    if system_id == SystemId.EXPERIENCEOS_SLOTS_V2:
        return ExperienceOSSlotsV2Adapter(provider=provider, seed=seed)
    if system_id == SystemId.EXPERIENCEOS_HYBRID_EXTRACT_V2:
        return ExperienceOSHybridExtractV2Adapter(
            provider=provider, seed=seed
        )
    if system_id == SystemId.EXPERIENCEOS_HYBRID_RETRIEVAL_V2:
        return ExperienceOSHybridRetrievalV2Adapter(
            provider=provider, seed=seed
        )
    if system_id == SystemId.EXPERIENCEOS_EXTRACT_RETRIEVAL_V2:
        return ExperienceOSExtractRetrievalV2Adapter(
            provider=provider, seed=seed
        )
    if system_id in BASELINE_CLASSES:
        return BASELINE_CLASSES[system_id](provider=provider, seed=seed)
    raise ValueError(
        f"unknown system {system_id!r}; known system IDs: "
        f"{sorted(KNOWN_SYSTEM_IDS)}"
    )
