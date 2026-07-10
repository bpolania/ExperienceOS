"""ExperienceOS + RuleBasedMemoryPolicy benchmark adapter.

Runs the real engine, store, planner, context builder, and
compression through the SDK's default rule-based path. All lifecycle
behavior is production behavior; the adapter only observes events and
state. Known honest limitations (paraphrase dedupe, unkeyed-domain
supersession, lexical-mismatch retrieval) are deliberately preserved
for measurement.
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.contract import SystemId


class ExperienceOSRulesAdapter(ExperienceOSAdapterBase):
    system_id = SystemId.EXPERIENCEOS_RULES
    memory_policy_label = "rule_based"

    def _make_policy(self, case):
        return None  # SDK default: deterministic RuleBasedMemoryPolicy
