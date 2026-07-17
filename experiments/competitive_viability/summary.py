"""Curated, committable execution summary for a viability run.

Derives completeness and fairness evidence from the run's comparison
records without carrying any raw answer text, provider payload, or
secret. This is execution evidence only — it computes no scores or
rankings.
"""

from __future__ import annotations

from experiments.competitive_viability import DEVELOPMENT_ONLY_MARKER


def curated_execution_summary(records, *, run_id, execution_mode,
                              viability_manifest_hash, git_commit) -> dict:
    """Build a curated summary from comparison-record payloads.

    ``records`` are the per-(case, system) record dicts. Only counts,
    statuses, and non-secret configuration are read — never answer text.
    """
    systems = {}
    response_models = set()
    cases = set()
    provider_failures = 0
    for record in records:
        sid = record["system_id"]
        cases.add(record["case_id"])
        response_models.add(record["response_model"])
        tally = systems.setdefault(
            sid,
            {"total": 0, "completed": 0, "failed": 0, "unavailable": 0,
             "not_applicable": 0, "unscorable": 0},
        )
        tally["total"] += 1
        tally[record["status"]] = tally.get(record["status"], 0) + 1
        if record["status"] == "failed" and record.get("execution_error"):
            provider_failures += 1

    completed_per_system = {s: t["completed"] for s, t in systems.items()}
    return {
        "development_only": None if execution_mode == "live"
        else DEVELOPMENT_ONLY_MARKER,
        "run_id": run_id,
        "execution_mode": execution_mode,
        "git_commit": git_commit,
        "viability_manifest_hash": viability_manifest_hash,
        "note": (
            "execution evidence only; no scores, rankings, or competitive "
            "conclusions"
        ),
        "distinct_cases": len(cases),
        "systems_run": sorted(systems),
        "per_system_status": systems,
        "completeness": {
            "completed_per_system": completed_per_system,
            "all_systems_ran_same_case_count": (
                len({t["total"] for t in systems.values()}) == 1
            ),
        },
        "fairness": {
            "distinct_response_models": sorted(response_models),
            "single_response_model": len(response_models) == 1,
            "identical_case_set_per_system": (
                len({t["total"] for t in systems.values()}) == 1
            ),
        },
        "provider_failures": provider_failures,
    }
