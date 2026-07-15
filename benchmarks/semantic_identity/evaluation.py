"""Measure the identity layer against the frozen annotation corpus.

The corpus is read-only evidence. Nothing here rewrites an oracle, and
the applicability rule below is mechanical: a record is evaluated only
when it has an active memory to compare against *and* its committed
label maps onto an identity relation. Records that primarily test
forget handling, question rejection, unsupported transitions, or
lifecycle preservation are counted as not-applicable rather than being
forced into an identity metric.

Historical-scored and development-only records are always reported
separately. Unresolved and excluded records are never scored; they are
available for fail-closed diagnostics only.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from benchmarks.annotations import transition_verification as tv
from experienceos.memory.identity import (
    IdentityRelation,
    IdentityProjector,
    resolve_identity,
)

#: Committed primary types that name an identity relation.
_PRIMARY_TO_RELATION = {
    "scoped_coexistence": (IdentityRelation.SCOPED_COEXISTENCE,),
    "supersede_existing": (IdentityRelation.CURRENT_STATE_CONFLICT,),
    "semantic_duplicate_noop": (IdentityRelation.SEMANTIC_DUPLICATE,),
    "reject_temporary": (IdentityRelation.TEMPORARY_EXCEPTION,),
    "reject_hypothetical": (IdentityRelation.HYPOTHETICAL,),
    "reject_ambiguous": (IdentityRelation.AMBIGUOUS,),
}

#: A `duplicate_noop` labelled `exact_duplicate` must be exact. A
#: `duplicate_noop` without that category (the negative-forget case)
#: asserts only that the proposal duplicates existing experience, so
#: either duplicate relation satisfies the committed oracle.
_DUPLICATE_ANY = (
    IdentityRelation.EXACT_DUPLICATE,
    IdentityRelation.SEMANTIC_DUPLICATE,
)

#: Relations that must never be produced for a case whose oracle
#: preserves state — a confident duplicate or conflict here would be an
#: unsafe classification, not a scoring miss.
_CONFIDENT_MUTATING = frozenset(
    {IdentityRelation.CURRENT_STATE_CONFLICT}
)

_ANNOTATED_FIELDS = ("subject", "attribute", "value", "scope")


def expected_relations(record: dict) -> tuple:
    """Identity relations that satisfy this record's committed oracle.

    Returns an empty tuple when the record does not name an identity
    relation, which makes it not-applicable.
    """
    transition = record.get("expected_transition") or {}
    primary = transition.get("primary_type")
    categories = set(record.get("scoring_categories") or ())

    if primary in _PRIMARY_TO_RELATION:
        return _PRIMARY_TO_RELATION[primary]
    if primary == "duplicate_noop":
        if "exact_duplicate" in categories:
            return (IdentityRelation.EXACT_DUPLICATE,)
        return _DUPLICATE_ANY
    if "historical_statement" in categories:
        return (IdentityRelation.HISTORICAL,)
    if primary == "create_new" and "unrelated_preservation" in categories:
        return (IdentityRelation.UNRELATED,)
    return ()


def active_memories(record: dict) -> list:
    return [
        memory
        for memory in record.get("before_state") or ()
        if memory.get("lifecycle_state") == "active"
    ]


def is_applicable(record: dict) -> bool:
    """Deterministic applicability: an active memory plus a relation."""
    return bool(active_memories(record)) and bool(expected_relations(record))


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    source_case_id: str
    partition: str
    expected: tuple
    observed: str
    correct: bool
    fail_closed: bool
    target_index: int | None
    latency_ms: float
    rationale: tuple

    def to_record(self) -> dict:
        return {
            "case_id": self.case_id,
            "source_case_id": self.source_case_id,
            "partition": self.partition,
            "expected_relations": list(self.expected),
            "observed_relation": self.observed,
            "correct": self.correct,
            "fail_closed": self.fail_closed,
            "target_index": self.target_index,
            "rationale": [d.to_record() for d in self.rationale],
        }


def evaluate_record(record: dict, projector: IdentityProjector) -> CaseResult:
    """Project the before-state and the proposal, then resolve."""
    memories = active_memories(record)
    existing = [
        projector.project_text(m.get("canonical_text") or "", kind=m.get("kind"))
        for m in memories
    ]
    started = time.perf_counter()
    # The proposal's kind is inferred from the statement: the corpus
    # does not annotate it, and borrowing it from the before-state
    # would leak the oracle into the projection.
    proposed = projector.project_text(record.get("source_statement") or "")
    resolution = resolve_identity(proposed, existing)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    expected = expected_relations(record)
    return CaseResult(
        case_id=record["case_id"],
        source_case_id=record["source_case_id"],
        partition=record["annotation_classification"],
        expected=expected,
        observed=resolution.relation,
        correct=resolution.relation in expected,
        fail_closed=resolution.fail_closed,
        target_index=resolution.target_index,
        latency_ms=elapsed_ms,
        rationale=resolution.rationale,
    )


def _field_accuracy(records: list, projector: IdentityProjector) -> dict:
    """Projection agreement with the annotated before-state fields.

    The corpus annotates subject/attribute/value/scope on before-state
    memories. Each is compared literally against the projection, so a
    vocabulary difference counts as a miss rather than being explained
    away.
    """
    totals = {name: [0, 0] for name in _ANNOTATED_FIELDS}
    for record in records:
        for memory in active_memories(record):
            identity = projector.project_text(
                memory.get("canonical_text") or "", kind=memory.get("kind")
            )
            for name in _ANNOTATED_FIELDS:
                annotated = memory.get(name)
                if not annotated or annotated == "not_represented":
                    continue
                totals[name][1] += 1
                projected = getattr(identity, name).value
                if projected.lower() == str(annotated).lower():
                    totals[name][0] += 1
    return {
        name: {"correct": hit, "total": total}
        for name, (hit, total) in totals.items()
    }


def _projection_stats(records: list, projector: IdentityProjector) -> dict:
    projected = 0
    total = 0
    completeness = []
    for record in records:
        total += 1
        identity = projector.project_text(record.get("source_statement") or "")
        completeness.append(identity.completeness)
        if identity.projected or identity.value.known:
            projected += 1
    return {
        "projected": projected,
        "total": total,
        "mean_completeness": round(
            statistics.fmean(completeness) if completeness else 0.0, 4
        ),
    }


def _relation_breakdown(results: list) -> dict:
    breakdown = {}
    for result in results:
        # A case is keyed by the relation its oracle requires; where the
        # oracle accepts either duplicate form, key it by the first.
        key = result.expected[0]
        entry = breakdown.setdefault(key, {"correct": 0, "total": 0})
        entry["total"] += 1
        entry["correct"] += int(result.correct)
    return breakdown


def _safety_counts(results: list) -> dict:
    """Zero-tolerance safety tallies.

    A false duplicate/conflict/coexistence is a *confident* claim the
    oracle contradicts. Producing `ambiguous` where a relation was
    expected is a miss, never a safety violation: it fails closed.
    """
    false_duplicate = 0
    false_conflict = 0
    false_coexistence = 0
    unsafe_confident = 0
    for result in results:
        if result.correct:
            continue
        if result.observed in _DUPLICATE_ANY:
            false_duplicate += 1
        if result.observed == IdentityRelation.CURRENT_STATE_CONFLICT:
            false_conflict += 1
        if result.observed == IdentityRelation.SCOPED_COEXISTENCE:
            false_coexistence += 1
        # An unsafe classification is a confident mutating relation on a
        # case whose oracle preserves state.
        preserving = not set(result.expected) & _CONFIDENT_MUTATING
        if preserving and result.observed in _CONFIDENT_MUTATING:
            unsafe_confident += 1
    return {
        "false_duplicate": false_duplicate,
        "false_update_conflict": false_conflict,
        "false_scoped_coexistence": false_coexistence,
        "unsafe_confident_classifications": unsafe_confident,
    }


def evaluate_partition(records: list, projector: IdentityProjector) -> dict:
    applicable = [r for r in records if is_applicable(r)]
    results = [evaluate_record(r, projector) for r in applicable]
    correct = sum(r.correct for r in results)
    latencies = sorted(r.latency_ms for r in results)
    ambiguous = sum(
        1 for r in results if r.observed == IdentityRelation.AMBIGUOUS
    )
    return {
        "records": len(records),
        "applicable": len(applicable),
        "not_applicable": len(records) - len(applicable),
        "correct": correct,
        "relation_accuracy": {"correct": correct, "total": len(results)},
        "by_relation": _relation_breakdown(results),
        "safety": _safety_counts(results),
        "projection": _projection_stats(applicable, projector),
        "field_accuracy": _field_accuracy(applicable, projector),
        "fallback": {"ambiguous": ambiguous, "total": len(results)},
        "latency": _latency(latencies),
        "results": results,
    }


def _latency(sorted_ms: list) -> dict:
    if not sorted_ms:
        return {"count": 0}
    index = min(len(sorted_ms) - 1, int(round(0.95 * (len(sorted_ms) - 1))))
    return {
        "count": len(sorted_ms),
        "median_ms": statistics.median(sorted_ms),
        "p95_ms": sorted_ms[index],
        "max_ms": sorted_ms[-1],
    }


def unresolved_diagnostics(records: list, projector: IdentityProjector) -> dict:
    """Fail-closed diagnostics only — never scored correct/incorrect."""
    observed = {}
    for record in records:
        if record["annotation_classification"] != "historical_unresolved":
            continue
        memories = active_memories(record)
        if not memories:
            continue
        existing = [
            projector.project_text(m.get("canonical_text") or "", kind=m.get("kind"))
            for m in memories
        ]
        proposed = projector.project_text(record.get("source_statement") or "")
        resolution = resolve_identity(proposed, existing)
        observed[record["case_id"]] = {
            "relation": resolution.relation,
            "fail_closed": resolution.fail_closed,
        }
    return observed


def evaluate_corpus() -> dict:
    """Full read-only evaluation over the frozen corpus."""
    corpus = tv.load_corpus()
    projector = IdentityProjector()
    return {
        "evaluation_version": "1",
        "projection_version": projector.version,
        "historical_scored": evaluate_partition(
            corpus["historical_scored"], projector
        ),
        "development_only": evaluate_partition(
            corpus["development_fixtures"], projector
        ),
        "unresolved_diagnostics": unresolved_diagnostics(
            corpus["unresolved_candidates"], projector
        ),
        "excluded_records": sum(
            1
            for r in corpus["unresolved_candidates"]
            if r["annotation_classification"] == "excluded"
        ),
    }


def relation_signature() -> tuple:
    """Ordered (case_id, relation) pairs — a repeatability fingerprint."""
    corpus = tv.load_corpus()
    projector = IdentityProjector()
    signature = []
    for partition in ("historical_scored", "development_fixtures"):
        for record in corpus[partition]:
            if not is_applicable(record):
                continue
            result = evaluate_record(record, projector)
            signature.append((result.case_id, result.observed))
    return tuple(signature)
