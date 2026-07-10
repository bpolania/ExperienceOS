"""ExperienceOS benchmark adapters (Prompt 4).

The experienceos_rules and experienceos_local systems behind the
common BenchmarkSystem interface, observing the real engine through
public seams. benchmarks.adapters.factory.create_system resolves all
six benchmark systems.
"""

from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system

__all__ = ["ADAPTER_SYSTEM_IDS", "create_system"]
