"""Normalized case selection for the comparison harness.

Reuses the existing lifecycle scenarios (`benchmarks/scenarios`) by
stable id — no dataset is copied into a new format. A thin
``ViabilityCase`` envelope adds only the evaluation-level metadata
(evidence classification, scoring method, provenance) around the existing
``LoadedScenario``. The oracle (`case.expected`) stays on the scenario for
later scoring and is never handed to execution adapters separately; the
existing drivers pass only user-visible turn inputs to each system.

This module defines the small development-only smoke fixture used to
validate harness mechanics. It does not finalize the viability subset.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchmarks.scenarios.loader import load_dataset, load_manifest

# Evidence classification vocabulary (kept separate in every record).
EVIDENCE_DEVELOPMENT_ONLY = "development_only"
EVIDENCE_FROZEN_HISTORICAL = "frozen_historical"
EVIDENCE_REUSED_EXTERNAL = "reused_external"

# Scoring method a later prompt will apply (recorded, not applied here).
SCORING_DETERMINISTIC = "deterministic"
SCORING_MODEL_JUDGE = "model_judge"

DATASET_LIFECYCLE = "experienceos-lifecycle-v1"

#: Development-only smoke fixture: a minimal spread across durable-fact
#: creation, update/correction, forgetting, and insufficient-evidence
#: abstention. Enough to validate mechanics; not an evaluation subset.
SMOKE_CASE_IDS = (
    "creation_002_durable_user_fact",       # durable fact
    "updates_002_fact_correction",          # update / correction
    "forgetting_001_exact_forget",          # forgetting
    "retrieval_007_correct_abstention",     # insufficient evidence -> abstain
)


@dataclass(frozen=True)
class ViabilityCase:
    """One normalized case: an existing scenario plus evaluation metadata.

    ``scenario`` is the existing ``LoadedScenario`` used for execution.
    ``oracle`` is the same scenario's expected outcome, retained for later
    scoring only — the harness never passes it to an execution adapter as
    a separate input.
    """

    case_id: str
    dataset_source: str
    evidence_classification: str
    lifecycle_category: str
    retrieval_category: str
    scoring_method: str
    scorable: bool
    provenance: str
    scenario: object  # LoadedScenario
    oracle: object     # ExpectedOutcome (hidden from execution)

    def to_metadata(self) -> dict:
        """Case metadata safe to record — no oracle content."""
        return {
            "case_id": self.case_id,
            "dataset_source": self.dataset_source,
            "evidence_classification": self.evidence_classification,
            "lifecycle_category": self.lifecycle_category,
            "retrieval_category": self.retrieval_category,
            "scoring_method": self.scoring_method,
            "scorable": self.scorable,
            "provenance": self.provenance,
        }


def _retrieval_category(case) -> str:
    tags = set(case.tags)
    if "selection" in case.category or "selection" in tags:
        return "selection"
    if "no-memory-needed" in tags:
        return "no_memory_needed"
    if case.category == "abstention" or (
        case.expected.response and case.expected.response.expect_abstention
    ):
        return "abstention"
    return "lifecycle"


def _scoring_method(case) -> str:
    response = case.expected.response
    if response and response.expect_abstention:
        return SCORING_MODEL_JUDGE
    if response and (
        response.must_include_all or response.must_include_any
        or response.must_exclude
    ):
        return SCORING_DETERMINISTIC
    return SCORING_DETERMINISTIC


def _to_viability_case(loaded, evidence_classification: str) -> ViabilityCase:
    case = loaded.case
    return ViabilityCase(
        case_id=case.scenario_id,
        dataset_source=DATASET_LIFECYCLE,
        evidence_classification=evidence_classification,
        lifecycle_category=case.category,
        retrieval_category=_retrieval_category(case),
        scoring_method=_scoring_method(case),
        scorable=True,
        provenance=f"{DATASET_LIFECYCLE}:{case.scenario_id}",
        scenario=loaded,
        oracle=case.expected,
    )


def load_cases(
    case_ids, evidence_classification: str = EVIDENCE_DEVELOPMENT_ONLY
) -> list:
    """Load specific scenarios by id as normalized viability cases,
    preserving the requested order. Unknown ids raise, so a run never
    silently drops a requested case."""
    scenarios = {s.case.scenario_id: s for s in load_dataset(load_manifest())}
    missing = [cid for cid in case_ids if cid not in scenarios]
    if missing:
        raise ValueError(f"unknown case ids: {missing}")
    return [
        _to_viability_case(scenarios[cid], evidence_classification)
        for cid in case_ids
    ]


def smoke_cases() -> list:
    """The development-only smoke fixture."""
    return load_cases(SMOKE_CASE_IDS, EVIDENCE_DEVELOPMENT_ONLY)
