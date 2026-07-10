"""Comparison baselines (Prompt 3). Contract: benchmarks.contract.system.

Four reasonable simpler strategies — stateless, full-history,
append-only, naive top-K — implemented independently of ExperienceOS
lifecycle logic, emitting common evidence for fair comparison.
"""

from benchmarks.baselines.factory import (
    BASELINE_SYSTEM_IDS,
    create_baseline,
)

__all__ = ["BASELINE_SYSTEM_IDS", "create_baseline"]
