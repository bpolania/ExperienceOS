"""The frozen viability subset and its manifest.

The scored subset is the complete set of frozen lifecycle scenarios, in
manifest order — a deterministic, repeatable, no-cherry-pick selection
("all frozen lifecycle scenarios"). These cases are small (1–7 turns) and
cover every required behavior, so a fair live all-system run is bounded.

The LongMemEval 50-case subset is locally available but each case carries
419–608 conversation turns (24,558 total), which makes a live all-system
run structurally infeasible within a bounded evaluation; multi-session
retrieval is covered at bounded scale by the lifecycle cross-session
cases, and the existing committed offline-structural LongMemEval evidence
stands as prior reused-external evidence. This is recorded as a coverage
limitation, not a set of failures.

The manifest carries references only — never expected-answer content — so
it exposes no oracle to execution adapters.
"""

from __future__ import annotations

import hashlib
import json

from benchmarks.scenarios.loader import load_dataset, load_manifest
from experiments.competitive_viability.cases import (
    EVIDENCE_FROZEN_HISTORICAL,
    _retrieval_category,
    _scoring_method,
    SCORING_MODEL_JUDGE,
)
from experiments.competitive_viability.systems import (
    APPEND_ONLY,
    CANONICAL_EXPERIENCEOS_QWEN,
    DETERMINISTIC_EXPERIENCEOS,
    FULL_HISTORY,
    NAIVE_TOP_K,
    STATELESS,
)

VIABILITY_MANIFEST_VERSION = "1"
DATASET_LIFECYCLE = "experienceos-lifecycle-v1"

#: Systems the scored subset is run through (mem0_style_lightweight is
#: registered but unavailable and excluded from required systems).
REQUIRED_SYSTEMS = (
    CANONICAL_EXPERIENCEOS_QWEN,
    DETERMINISTIC_EXPERIENCEOS,
    STATELESS,
    FULL_HISTORY,
    NAIVE_TOP_K,
    APPEND_ONLY,
)

# Documented reused-external coverage that is not run live here.
LONGMEMEVAL_LIMITATION = (
    "LongMemEval 50-case subset is locally available but each case has "
    "419-608 turns (24,558 total); a live all-system run is infeasible "
    "within a bounded evaluation. Covered offline-structurally by the "
    "existing committed longmemeval-50-subset evidence; multi-session "
    "retrieval is covered at bounded scale by lifecycle cross-session "
    "cases."
)


def _final_answer_category(case) -> str:
    response = case.expected.response
    if response and response.expect_abstention:
        return "abstention"
    if case.category in ("update",) or any(
        t in case.tags for t in ("stale-leakage", "recency-vs-relevance")
    ):
        return "current_vs_stale"
    if case.category in ("retrieval", "selection", "distractor"):
        return "personalized_retrieval"
    return "personalized_response"


def _known_limitations(case) -> list:
    limits = []
    if case.requires_local_model:
        limits.append("requires_local_model: not_applicable to Qwen systems")
    if case.requires_provider:
        limits.append("requires_provider: needs a configured response model")
    return limits


def _case_entry(loaded) -> dict:
    case = loaded.case
    scoring = _scoring_method(case)
    return {
        "viability_case_id": f"cv-{case.scenario_id}",
        "source_case_id": case.scenario_id,
        "source_dataset": DATASET_LIFECYCLE,
        "evidence_classification": EVIDENCE_FROZEN_HISTORICAL,
        "provenance": f"{DATASET_LIFECYCLE}:{case.scenario_id}",
        "lifecycle_category": case.category,
        "retrieval_category": _retrieval_category(case),
        "final_answer_category": _final_answer_category(case),
        "scoring_method": scoring,
        "scorable": not case.requires_local_model,
        "expected_answer_ref": f"scenario:{case.scenario_id}:expected",
        "required_systems": list(REQUIRED_SYSTEMS),
        "context_budget": case.context_budget,
        "selection_k": case.selection_k,
        "known_limitations": _known_limitations(case),
        "dedup_lineage": (
            "lifecycle scenario is the canonical representation; the "
            "transition-verification and grounded-extraction annotations "
            "derive from the same underlying cases and are not counted "
            "separately"
        ),
    }


def _counts(entries, key) -> dict:
    out = {}
    for entry in entries:
        value = entry[key]
        out[value] = out.get(value, 0) + 1
    return out


def build_viability_manifest() -> dict:
    """Build the frozen viability manifest from all lifecycle scenarios."""
    lifecycle_manifest = load_manifest()
    scenarios = load_dataset(lifecycle_manifest)
    entries = [_case_entry(s) for s in scenarios]
    scorable = [e for e in entries if e["scorable"]]
    summary = {
        "total_cases": len(entries),
        "scorable_cases": len(scorable),
        "by_dataset": _counts(entries, "source_dataset"),
        "by_evidence_classification": _counts(
            entries, "evidence_classification"
        ),
        "by_lifecycle_category": _counts(entries, "lifecycle_category"),
        "by_final_answer_category": _counts(entries, "final_answer_category"),
        "by_scoring_method": _counts(entries, "scoring_method"),
        "by_scorable": {
            "scorable": len(scorable),
            "not_scorable": len(entries) - len(scorable),
        },
        "model_judge_cases": sum(
            1 for e in entries if e["scoring_method"] == SCORING_MODEL_JUDGE
        ),
    }
    return {
        "manifest_version": VIABILITY_MANIFEST_VERSION,
        "selection_method": (
            "all frozen lifecycle scenarios in manifest order; "
            "deterministic and complete; no post-run replacement"
        ),
        "source_manifest_hash": lifecycle_manifest.get("manifest_hash"),
        "required_systems": list(REQUIRED_SYSTEMS),
        "coverage_limitations": [LONGMEMEVAL_LIMITATION],
        "cases": entries,
        "summary": summary,
    }


def manifest_hash(manifest: dict) -> str:
    """Stable hash of the manifest cases (order-sensitive)."""
    payload = json.dumps(manifest["cases"], sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def viability_case_ids() -> list:
    return [e["source_case_id"] for e in build_viability_manifest()["cases"]]
