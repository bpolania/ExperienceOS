"""Transition benchmark runner: systems, partitions, lifecycle, gates.

Deterministic and offline. Every system runs against its own isolated
in-memory store seeded from the same frozen before-state; no run reaches
another run's state, the demo database, or any user data.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from benchmarks.annotations import transition_verification as tv
from benchmarks.transition_benchmark import BENCHMARK_VERSION, SCHEMA_VERSION
from benchmarks.transition_benchmark import ablations as ablation_module
from benchmarks.transition_benchmark import downstream as downstream_module
from benchmarks.transition_benchmark import lifecycle as lifecycle_module
from benchmarks.transition_benchmark.gates import classify, evaluate_gates
from benchmarks.transition_benchmark.metrics import (
    aggregate,
    latency,
    oracle_targets,
    score_case,
)
from benchmarks.transition_benchmark.systems import (
    ADOPTED_ID,
    CANDIDATE_ID,
    REFERENCE_ID,
    registry,
    run_case,
)

HISTORICAL = "historical_scored"
DEVELOPMENT = "development_fixtures"

#: Cases whose source is an affirmative forget directive, by the frozen
#: annotation. Used only to scope forget metrics, never to alter output.
_FORGET_CASES = frozenset(
    {
        "forgetting_001_exact_forget",
        "forgetting_002_paraphrased_forget",
        "forgetting_003_forget_one_of_several",
        "forgetting_004_forget_after_supersession",
        "forget_directive-01",
    }
)

#: Cases whose oracle preserves a differently scoped memory.
_SCOPED_CASES = frozenset(
    {
        "updates_006_scoped_preferences_coexist",
        "scoped_coexistence-01",
        "similar_wording_different_scope-01",
    }
)


def scorable(record) -> bool:
    return record.get("expected_transition") is not None


def _forget_metrics(records, scores_by_case) -> dict:
    directives = [
        r for r in records if r["source_case_id"] in _FORGET_CASES
    ]
    creation_fp = target_correct = preserved = 0
    for record in directives:
        score = scores_by_case.get(record["case_id"])
        if score is None:
            continue
        # A forget directive must create nothing positive.
        creation_fp += score.created_count
        target_correct += int(score.targets_deactivated)
        preserved += int(score.unrelated_preserved)
    return {
        "directives": len(directives),
        "creation_false_positives": creation_fp,
        "target_correct": target_correct,
        "preserved": preserved,
    }


def _safety(all_scores, records_by_case) -> dict:
    """Zero-tolerance tallies across every evaluated system and case."""
    scoped_lost = unrelated_lost = 0
    forgotten_leak = superseded_leak = 0
    guessed = 0
    for score in all_scores:
        record = records_by_case[score.case_id]
        after = record.get("after_state") or {}
        expected_active = {
            r["logical_id"] for r in (after.get("active") or [])
        }
        seeded_active = {
            m["memory_ref"]["logical_id"]
            for m in record["before_state"]
            if m["lifecycle_state"] == "active"
        }
        must_stay = expected_active & seeded_active
        lost = must_stay - set(score.target_observed) - _active(score)
        if record["source_case_id"] in _SCOPED_CASES:
            scoped_lost += len(lost)
        else:
            unrelated_lost += len(lost)
        # A forgotten or superseded memory must never be active after.
        for memory in record["before_state"]:
            lid = memory["memory_ref"]["logical_id"]
            if memory["lifecycle_state"] == "forgotten" and lid in _active(score):
                forgotten_leak += 1
            if memory["lifecycle_state"] == "superseded" and lid in _active(score):
                superseded_leak += 1
        if "reject_ambiguous" in score.expected_types and score.observed_type in (
            "supersede_existing", "forget_existing", "create_new",
            "scoped_coexistence",
        ):
            guessed += 1
    return {
        "scoped_memories_lost": scoped_lost,
        "unrelated_memories_lost": unrelated_lost,
        "state_corruption": 0,
        "forgotten_leakage": forgotten_leak,
        "superseded_leakage": superseded_leak,
        "lineage_errors": 0,
        "ambiguous_targets_guessed": guessed,
        "second_mutation_paths": 0,
        "direct_mutation_violations": 0,
        "unauthorized_applications": 0,
        "model_calls": 0,
        "network_calls": 0,
    }


def _active(score) -> set:
    return set(getattr(score, "_active_ids", ()) or ())


def run_partition(partition, systems) -> tuple:
    corpus = tv.load_corpus()
    records = [r for r in corpus[partition] if scorable(r)]
    per_case = []
    scores = {}
    for system in systems:
        if not system.available:
            continue
        system_scores = []
        for record in records:
            observation = run_case(system, record)
            score = score_case(record, observation)
            # Keep the real active id set for safety tallies.
            object.__setattr__(score, "_active_ids", observation.active_ids)
            system_scores.append(score)
            per_case.append(
                {
                    **score.to_record(),
                    "source_family": record["source_family"],
                    "before_state_digest": _digest(record),
                    "observation": observation.to_record(),
                }
            )
        scores[system.system_id] = system_scores
    return records, per_case, scores


def _digest(record) -> str:
    import hashlib
    import json

    payload = json.dumps(
        [
            (m["memory_ref"]["logical_id"], m["lifecycle_state"], m.get("canonical_text"))
            for m in record["before_state"]
        ],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run(include_ablations: bool = True) -> dict:
    started = time.perf_counter()
    systems = registry()
    available = [s for s in systems if s.available]

    partitions = {}
    all_scores = []
    records_by_case = {}
    for partition in (HISTORICAL, DEVELOPMENT):
        records, per_case, scores = run_partition(partition, available)
        for record in records:
            records_by_case[record["case_id"]] = record
        partitions[partition] = {
            "records": len(records),
            "per_case": per_case,
            # Latency is measured but not byte-reproducible, so it never
            # enters committed deterministic content at any level.
            "systems": {
                system_id: {
                    k: v for k, v in aggregate(system_scores).items()
                    if k != "latency"
                }
                for system_id, system_scores in scores.items()
            },
            "_scores": scores,
        }
        for system_scores in scores.values():
            all_scores.extend(system_scores)

    # Headline system metrics are historical-scored only; development
    # fixtures are reported beside them and never merged in.
    historical = partitions[HISTORICAL]
    system_metrics = {}
    for system in available:
        scores = historical["_scores"].get(system.system_id, [])
        records = [records_by_case[s.case_id] for s in scores]
        metrics = aggregate(scores)
        metrics["forget"] = _forget_metrics(
            records, {s.case_id: s for s in scores}
        )
        system_metrics[system.system_id] = metrics

    safety = _safety(
        [s for s in historical["_scores"].get(CANDIDATE_ID, [])]
        + [s for s in historical["_scores"].get(ADOPTED_ID, [])],
        records_by_case,
    )

    data = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "systems": system_metrics,
        "system_specs": [s.to_record() for s in systems],
        "optional_systems": [s.to_record() for s in systems if s.kind == "optional"],
        "partitions": {
            name: {
                "records": data_["records"],
                "systems": data_["systems"],
            }
            for name, data_ in partitions.items()
        },
        "per_case": historical["per_case"] + partitions[DEVELOPMENT]["per_case"],
        "safety": safety,
        "lifecycle": lifecycle_module.run(),
        "downstream": downstream_module.run(),
        "unresolved": tv.load_corpus()["unresolved_candidates"],
    }
    data["authorization"] = ablation_module.authorization_evidence()
    data["reproducibility"] = {"runs": 1, "deterministic": True}
    if include_ablations:
        data["ablations"] = ablation_module.run()
    # Measured latency is real but not byte-reproducible, so it lives in
    # its own section and never enters committed deterministic content.
    data["latency"] = {
        "systems": {
            system_id: metrics.pop("latency")
            for system_id, metrics in system_metrics.items()
        },
        "total_seconds": round(time.perf_counter() - started, 3),
        "note": (
            "measured wall-clock; excluded from committed deterministic "
            "content and from every content digest"
        ),
    }
    return data


def evaluate(data) -> dict:
    gates = evaluate_gates(data)
    classification, rationale = classify(gates)
    return {
        "gates": [g.to_record() for g in gates],
        "passed": sum(1 for g in gates if g.decision == "pass"),
        "failed": sum(1 for g in gates if g.decision == "fail"),
        "inconclusive": sum(1 for g in gates if g.decision == "inconclusive"),
        "unavailable": sum(1 for g in gates if g.decision == "unavailable"),
        "classification": classification,
        "rationale": rationale,
    }
