"""Additive grounded-extraction annotation loading and validation.

Reads the annotation JSONL keyed to frozen case IDs and validates each
record against the frozen datasets. No network access, no state
mutation. The loader deliberately re-derives the set of valid frozen
case IDs from the committed datasets so an annotation can never point at
a non-existent case.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path

from experienceos.memory.schema import MemoryKind

REPO_ROOT = Path(__file__).resolve().parents[2]
ANNOTATION_ROOT = REPO_ROOT / "benchmarks/annotations/grounded-extraction"
LIFECYCLE_PATH = ANNOTATION_ROOT / "lifecycle.jsonl"
EXTERNAL_PATH = ANNOTATION_ROOT / "external.jsonl"

LIFECYCLE_SCENARIO_GLOB = str(
    REPO_ROOT / "benchmarks/scenarios/lifecycle/*/*.json"
)
EXTERNAL_FROZEN_CASES = (
    REPO_ROOT
    / "benchmarks/results/committed/longmemeval-50-subset-v1/cases.jsonl"
)

CANONICAL_KINDS = frozenset(
    {MemoryKind.PREFERENCE, MemoryKind.FACT, MemoryKind.INSTRUCTION}
)
REJECTION_CATEGORIES = frozenset(
    {
        "non-durable",
        "question",
        "hypothetical",
        "temporary-state",
        "assistant-only",
        "one-off-request",
        "unsupported-claim",
        "not-durable-assertion",
    }
)


class AnnotationError(ValueError):
    """An annotation record is malformed or references a bad case."""


@dataclass(frozen=True)
class LifecycleAnnotation:
    """One frozen lifecycle scenario's extraction oracle."""

    case_id: str
    source_text: str
    scorable: bool
    candidate_expected: bool
    expected_kind: str | None
    acceptable_kinds: tuple
    acceptable_normalized_texts: tuple
    normalized_must_include: tuple
    normalized_must_exclude: tuple
    acceptable_evidence_spans: tuple
    rejection_category: str | None
    answer_bearing_candidate_expected: bool
    duplicate_identity: str | None
    current_state: str | None
    obsolete_state: str | None
    annotation_confidence: str
    annotation_notes: str

    @property
    def is_positive(self) -> bool:
        return (
            self.scorable
            and self.candidate_expected
            and self.duplicate_identity is None
        )

    @property
    def is_duplicate(self) -> bool:
        return self.scorable and self.duplicate_identity is not None

    @property
    def is_negative(self) -> bool:
        return self.scorable and not self.candidate_expected


@dataclass(frozen=True)
class ExternalAnnotation:
    """One frozen external question's extraction classification."""

    case_id: str
    category: str
    classification: str
    scorable: bool
    candidate_expected: bool
    answer_bearing_candidate_expected: bool
    span_scoring_available: bool
    rejection_category: str | None
    annotation_confidence: str
    annotation_notes: str


def _frozen_lifecycle_ids() -> frozenset:
    ids = set()
    for path in sorted(glob.glob(LIFECYCLE_SCENARIO_GLOB)):
        with open(path) as handle:
            ids.add(json.load(handle)["scenario_id"])
    return frozenset(ids)


def _frozen_external_ids() -> frozenset:
    ids = set()
    with open(EXTERNAL_FROZEN_CASES) as handle:
        for line in handle:
            ids.add(json.loads(line)["question_id"])
    return frozenset(ids)


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        raise AnnotationError(f"annotation file missing: {path}")
    records = []
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_lifecycle_annotations() -> list:
    """Load, validate, and return lifecycle annotations in case-ID order."""
    frozen = _frozen_lifecycle_ids()
    raw = _read_jsonl(LIFECYCLE_PATH)
    seen = set()
    out = []
    for rec in raw:
        cid = rec["case_id"]
        if cid in seen:
            raise AnnotationError(f"duplicate annotation id: {cid}")
        seen.add(cid)
        if cid not in frozen:
            raise AnnotationError(
                f"annotation {cid} is not a frozen lifecycle scenario"
            )
        _validate_lifecycle(rec)
        out.append(LifecycleAnnotation(
            case_id=cid,
            source_text=rec["source_text"],
            scorable=rec["scorable"],
            candidate_expected=rec["candidate_expected"],
            expected_kind=rec["expected_kind"],
            acceptable_kinds=tuple(rec["acceptable_kinds"]),
            acceptable_normalized_texts=tuple(
                rec["acceptable_normalized_texts"]),
            normalized_must_include=tuple(rec["normalized_must_include"]),
            normalized_must_exclude=tuple(rec["normalized_must_exclude"]),
            acceptable_evidence_spans=tuple(
                tuple(s) for s in rec["acceptable_evidence_spans"]),
            rejection_category=rec["rejection_category"],
            answer_bearing_candidate_expected=rec[
                "answer_bearing_candidate_expected"],
            duplicate_identity=rec["duplicate_identity"],
            current_state=rec["current_state"],
            obsolete_state=rec["obsolete_state"],
            annotation_confidence=rec["annotation_confidence"],
            annotation_notes=rec["annotation_notes"],
        ))
    return sorted(out, key=lambda a: a.case_id)


def _validate_lifecycle(rec: dict) -> None:
    cid = rec["case_id"]
    if not rec["scorable"]:
        if not rec["annotation_notes"].strip():
            raise AnnotationError(f"{cid}: unscorable needs a bounded reason")
        return
    if rec["candidate_expected"]:
        for kind in rec["acceptable_kinds"]:
            if kind not in CANONICAL_KINDS:
                raise AnnotationError(
                    f"{cid}: non-canonical kind {kind!r}")
        if rec["expected_kind"] not in CANONICAL_KINDS:
            raise AnnotationError(
                f"{cid}: positive needs a canonical expected_kind")
        if rec["duplicate_identity"] is None:
            if not rec["normalized_must_include"]:
                raise AnnotationError(
                    f"{cid}: positive needs normalization oracle tokens")
        source = rec["source_text"]
        for span in rec["acceptable_evidence_spans"]:
            start, end = span
            if not (0 <= start < end <= len(source)):
                raise AnnotationError(
                    f"{cid}: evidence span {span} out of range")
    else:
        if rec["rejection_category"] not in REJECTION_CATEGORIES:
            raise AnnotationError(
                f"{cid}: negative needs a valid rejection_category, got "
                f"{rec['rejection_category']!r}")


def load_external_annotations() -> list:
    """Load, validate, and return external annotations in case-ID order."""
    frozen = _frozen_external_ids()
    raw = _read_jsonl(EXTERNAL_PATH)
    seen = set()
    out = []
    for rec in raw:
        cid = rec["case_id"]
        if cid in seen:
            raise AnnotationError(f"duplicate external annotation id: {cid}")
        seen.add(cid)
        if cid not in frozen:
            raise AnnotationError(
                f"external annotation {cid} is not a frozen question")
        if rec["scorable"]:
            raise AnnotationError(
                f"{cid}: external cases are classification-only (scorable "
                "must be false)")
        if not rec["annotation_notes"].strip():
            raise AnnotationError(f"{cid}: external needs a bounded reason")
        out.append(ExternalAnnotation(
            case_id=cid,
            category=rec["category"],
            classification=rec["classification"],
            scorable=rec["scorable"],
            candidate_expected=rec["candidate_expected"],
            answer_bearing_candidate_expected=rec[
                "answer_bearing_candidate_expected"],
            span_scoring_available=rec["span_scoring_available"],
            rejection_category=rec["rejection_category"],
            annotation_confidence=rec["annotation_confidence"],
            annotation_notes=rec["annotation_notes"],
        ))
    return sorted(out, key=lambda a: a.case_id)
