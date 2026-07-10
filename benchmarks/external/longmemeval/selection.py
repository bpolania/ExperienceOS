"""Deterministic 50-case stratified subset selection.

Algorithm (version 1) — uses pre-result official metadata ONLY
(question IDs, question types, the ``_abs`` abstention suffix); it
never inspects questions, answers, histories, model outputs, or any
system's behavior:

1. Assign each official record a subset category:
   - ``abstention`` for every ``_abs``-suffixed question ID,
   - otherwise ``information-extraction`` (single-session-user),
     ``multi-session-reasoning`` (multi-session),
     ``temporal-reasoning``, or ``knowledge-updates``
     (knowledge-update); other official types are out of scope.
2. Within each category, sort question IDs lexicographically.
3. Take 10 evenly spaced IDs: index ``floor(i * n / 10)`` for
   i = 0..9 over the n sorted IDs.
4. Concatenate categories in the fixed order below.
5. Hash-lock the ordered (ID, category) list plus the source
   fingerprint into the committed manifest. Regeneration from the
   same source revision reproduces it byte-for-byte; a different
   source changes the manifest identity.
"""

from __future__ import annotations

import hashlib

from benchmarks.contract import canonical_json
from benchmarks.external.longmemeval.schema import (
    BENCHMARK_NAME,
    REQUIRED_DISPLAY_LABEL,
    is_abstention,
)

SELECTION_ALGORITHM_VERSION = "1"
SUBSET_VERSION = "longmemeval-50-subset-v1"
MANIFEST_SCHEMA_VERSION = "1"
PER_CATEGORY = 10

CATEGORY_ORDER = (
    "information-extraction",
    "multi-session-reasoning",
    "temporal-reasoning",
    "knowledge-updates",
    "abstention",
)

_TYPE_TO_CATEGORY = {
    "single-session-user": "information-extraction",
    "multi-session": "multi-session-reasoning",
    "temporal-reasoning": "temporal-reasoning",
    "knowledge-update": "knowledge-updates",
}


class SelectionError(ValueError):
    pass


def subset_category(record: dict) -> str | None:
    """Subset category for an official record, or None if out of scope."""
    if is_abstention(record["question_id"]):
        return "abstention"
    return _TYPE_TO_CATEGORY.get(record["question_type"])


def select_subset(records: list[dict], per_category: int = PER_CATEGORY):
    """Ordered [(question_id, category)] — deterministic, metadata-only."""
    groups: dict[str, list[str]] = {c: [] for c in CATEGORY_ORDER}
    seen: set[str] = set()
    for record in records:
        question_id = str(record["question_id"])
        if question_id in seen:
            raise SelectionError(f"duplicate official ID: {question_id}")
        seen.add(question_id)
        category = subset_category(record)
        if category is not None:
            groups[category].append(question_id)

    selected = []
    for category in CATEGORY_ORDER:
        ids = sorted(groups[category])
        if len(ids) < per_category:
            raise SelectionError(
                f"category {category!r} has only {len(ids)} official "
                f"cases; {per_category} required"
            )
        for i in range(per_category):
            selected.append((ids[i * len(ids) // per_category], category))
    return selected


def source_fingerprint(records: list[dict]) -> str:
    """Fingerprint over the official (id, type) identity set."""
    identity = sorted(
        (str(r["question_id"]), r["question_type"]) for r in records
    )
    return hashlib.sha256(
        canonical_json(identity).encode("utf-8")
    ).hexdigest()


def build_manifest(
    records: list[dict],
    *,
    dataset_variant: str,
    source_revision: str,
    source_file: str,
    verification_date: str,
) -> dict:
    selected = select_subset(records)
    counts: dict[str, int] = {}
    for _, category in selected:
        counts[category] = counts.get(category, 0) + 1
    body = {
        "benchmark": BENCHMARK_NAME,
        "display_label": REQUIRED_DISPLAY_LABEL,
        "subset_version": SUBSET_VERSION,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "selection_algorithm_version": SELECTION_ALGORITHM_VERSION,
        "official_repository": "https://github.com/xiaowu0162/LongMemEval",
        "official_dataset": (
            "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"
        ),
        "official_paper": (
            "LongMemEval: Benchmarking Chat Assistants on Long-Term "
            "Interactive Memory (ICLR 2025, arXiv:2410.10813)"
        ),
        "licenses": {"repository": "MIT", "dataset": "MIT"},
        "source_revision": source_revision,
        "source_file": source_file,
        "source_fingerprint": source_fingerprint(records),
        "source_verification_date": verification_date,
        "dataset_variant": dataset_variant,
        "target_per_category": PER_CATEGORY,
        "category_counts": counts,
        "selected": [
            {"question_id": qid, "category": category}
            for qid, category in selected
        ],
        "dataset_content_committed": False,
        "official_evaluation": False,
        "limitations": [
            "50-case stratified subset, not the full 500-question "
            "official benchmark",
            "official evaluation uses a GPT-4o judge; this integration "
            "uses deterministic structural evidence and clearly-labeled "
            "proxy answer checks unless a live judged run is recorded",
        ],
        "notes": (
            "IDs only; official data is loaded from a gitignored local "
            "path and never committed."
        ),
    }
    body["manifest_hash"] = hashlib.sha256(
        canonical_json(body).encode("utf-8")
    ).hexdigest()
    return body
