"""Loader for the grounded-extraction development fixtures.

Development-only design and test inputs (see
``benchmarks/fixtures/grounded-extraction/README.md``): deterministic,
offline, self-contained. Loading validates structural integrity —
required fields, unique stable IDs, canonical memory kinds, allowed
source types, positive/negative field consistency, and exact
evidence-span equality — and mutates nothing: no providers, no models,
no network, no memory store, no writes. These fixtures are never
consumed by canonical benchmark execution; callers must opt in
explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path("benchmarks/fixtures/grounded-extraction")
FIXTURE_PATH = FIXTURE_DIR / "cases.jsonl"

CANONICAL_KINDS = ("preference", "fact", "instruction")
ALLOWED_SOURCE_TYPES = ("user_asserted",)
CATEGORIES = (
    "explicit-preference",
    "semi-natural-preference",
    "durable-fact",
    "natural-durable-fact",
    "durable-instruction",
    "workflow-preference",
    "temporary-state",
    "one-off-request",
    "hypothetical",
    "question",
    "assistant-only",
    "unsupported-normalization",
    "duplicate-restatement",
    "ambiguous-durability",
    "third-party",
    "negation-polarity",
    "preference-change",
)
REJECTION_REASONS = (
    "temporary_state",
    "one_off_request",
    "hypothetical",
    "question",
    "assistant_only",
    "third_party_statement",
    "ambiguous_durability",
)

_REQUIRED_FIELDS = (
    "case_id", "category", "description", "user_message",
    "source_type", "candidate_expected", "durability_class",
    "development_only", "source_reference",
)
_POSITIVE_FIELDS = (
    "expected_kind", "acceptable_normalized_texts",
    "expected_evidence_text", "expected_start_offset",
    "expected_end_offset",
)


class FixtureError(ValueError):
    """A development fixture violated its structural contract."""


def _validate(case: dict) -> None:
    case_id = case.get("case_id", "<missing id>")
    for name in _REQUIRED_FIELDS:
        if name not in case:
            raise FixtureError(f"{case_id}: missing field {name!r}")
    if case["development_only"] is not True:
        raise FixtureError(f"{case_id}: development_only must be true")
    if case["category"] not in CATEGORIES:
        raise FixtureError(
            f"{case_id}: unknown category {case['category']!r}"
        )
    if case["source_type"] not in ALLOWED_SOURCE_TYPES:
        raise FixtureError(
            f"{case_id}: unknown source type {case['source_type']!r}"
        )
    if case["candidate_expected"]:
        for name in _POSITIVE_FIELDS:
            if case.get(name) is None:
                raise FixtureError(
                    f"{case_id}: positive case missing {name!r}"
                )
        kinds = [case["expected_kind"], *case.get("acceptable_kinds", [])]
        for kind in kinds:
            if kind not in CANONICAL_KINDS:
                raise FixtureError(
                    f"{case_id}: non-canonical kind {kind!r}"
                )
        message = case["user_message"]
        start = case["expected_start_offset"]
        end = case["expected_end_offset"]
        if not (
            isinstance(start, int) and isinstance(end, int)
            and 0 <= start < end <= len(message)
        ):
            raise FixtureError(f"{case_id}: offsets out of range")
        if message[start:end] != case["expected_evidence_text"]:
            raise FixtureError(
                f"{case_id}: evidence text does not equal the "
                "message slice"
            )
        if not case["acceptable_normalized_texts"] or not all(
            isinstance(t, str) and t.strip()
            for t in case["acceptable_normalized_texts"]
        ):
            raise FixtureError(
                f"{case_id}: acceptable normalizations must be "
                "non-empty strings"
            )
        if case.get("rejection_reason"):
            raise FixtureError(
                f"{case_id}: positive case carries a rejection reason"
            )
    else:
        if case.get("rejection_reason") not in REJECTION_REASONS:
            raise FixtureError(
                f"{case_id}: negative case needs a known rejection "
                "reason"
            )
        for name in _POSITIVE_FIELDS:
            if case.get(name) is not None:
                raise FixtureError(
                    f"{case_id}: negative case must not carry {name!r}"
                )


def load_development_fixtures(path: Path | str = FIXTURE_PATH) -> list:
    """Deterministically load and validate every development case."""
    raw = Path(path).read_text()
    cases = []
    seen: set = set()
    for line in raw.split("\n"):
        if not line.strip():
            continue
        case = json.loads(line)
        _validate(case)
        if case["case_id"] in seen:
            raise FixtureError(f"duplicate case_id {case['case_id']!r}")
        seen.add(case["case_id"])
        cases.append(case)
    return cases
