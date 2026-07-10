"""Benchmark runner (Phase 8 Prompt 5): deterministic six-system
orchestration over the committed lifecycle dataset."""

from benchmarks.runner.config import PROFILES, QUICK_PROFILE_SCENARIOS, RunConfig, profile_config
from benchmarks.runner.execute import execute_run

__all__ = ["PROFILES", "QUICK_PROFILE_SCENARIOS", "RunConfig", "execute_run", "profile_config"]
