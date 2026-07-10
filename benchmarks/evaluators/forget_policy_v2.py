"""Phase 9 forget/local-policy evaluator: v2-only contributions.

Reads Prompt 7 diagnostics (``result.diagnostics["forget_policy_v2"]``)
and converts them into raw metric contributions. Systems without these
diagnostics contribute nothing, so earlier evaluation output stays
byte-identical. All metrics are neutral/observational.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution


def forget_policy_v2_contributions(case, result):
    counters = result.diagnostics.get("forget_policy_v2")
    if not isinstance(counters, dict):
        return []

    def count(key) -> float:
        value = counters.get(key, 0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    decisions = count("decisions") or count("turns")
    intents = count("forget_intents_detected")
    fallbacks = count("fallbacks_total")
    evidence = {
        "scenario_id": case.scenario_id,
        "local_model_mode": counters.get("local_policy_version") and (
            "policy"
        ) or "deterministic",
        "forget_resolver_version": counters.get("forget_resolver_version"),
    }
    return [
        contribution(
            "forget_intent_detection_v2", intents, decisions, **evidence,
        ),
        contribution(
            "forget_target_resolution_v2",
            count("forget_targets_resolved"), intents, **evidence,
        ),
        contribution(
            "forget_ambiguity_containment_v2",
            count("forget_unresolved"), intents, **evidence,
        ),
        contribution(
            "bulk_forget_containment_v2",
            count("forget_bulk_rejected"), intents, **evidence,
        ),
        contribution(
            "local_structural_validity_v2",
            count("structural_valid"), count("decisions"), **evidence,
        ),
        contribution(
            "local_fallback_rate_v2",
            fallbacks, count("decisions"), **evidence,
        ),
        contribution(
            "local_applied_action_rate_v2",
            count("local_accepted"), count("decisions"), **evidence,
        ),
        contribution(
            "local_retry_success_v2",
            count("retry_success"), count("retries"), **evidence,
        ),
    ]
