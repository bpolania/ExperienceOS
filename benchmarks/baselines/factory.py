"""Baseline factory: SystemId -> baseline instance.

The two ExperienceOS system IDs are deliberately rejected here — their
adapters are Prompt 4 work and must not be confused with baselines.
"""

from __future__ import annotations

from benchmarks.baselines.append_only import AppendOnlyBaseline
from benchmarks.baselines.full_history import FullHistoryBaseline
from benchmarks.baselines.naive_top_k import NaiveTopKBaseline
from benchmarks.baselines.stateless import StatelessBaseline
from benchmarks.contract import KNOWN_SYSTEM_IDS, SystemId

BASELINE_CLASSES = {
    SystemId.STATELESS: StatelessBaseline,
    SystemId.FULL_HISTORY: FullHistoryBaseline,
    SystemId.APPEND_ONLY: AppendOnlyBaseline,
    SystemId.NAIVE_TOP_K: NaiveTopKBaseline,
}

BASELINE_SYSTEM_IDS = tuple(BASELINE_CLASSES)


def create_baseline(system_id: str, provider=None, seed: int = 0):
    if system_id in (SystemId.EXPERIENCEOS_RULES, SystemId.EXPERIENCEOS_LOCAL):
        raise ValueError(
            f"{system_id!r} is an ExperienceOS adapter (Prompt 4), "
            "not a comparison baseline"
        )
    if system_id not in BASELINE_CLASSES:
        raise ValueError(
            f"unknown baseline system {system_id!r}; expected one of "
            f"{sorted(BASELINE_CLASSES)} (known system IDs: "
            f"{sorted(KNOWN_SYSTEM_IDS)})"
        )
    return BASELINE_CLASSES[system_id](provider=provider, seed=seed)
