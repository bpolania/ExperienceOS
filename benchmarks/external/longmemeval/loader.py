"""Official LongMemEval data loading against the committed manifest.

Official data lives at an explicitly configured local path (normally
the gitignored ``benchmarks/data/external/longmemeval/``). Nothing
here searches the filesystem, downloads anything, or records personal
absolute paths — emitted metadata uses basenames only.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePath

from benchmarks.external.longmemeval.schema import (
    ExternalCase,
    InvalidExternalRecord,
    normalize_record,
    validate_official_record,
)
from benchmarks.external.longmemeval.selection import (
    SelectionError,
    source_fingerprint,
    subset_category,
)

MANIFEST_PATH = (
    Path(__file__).resolve().parent / "manifest.json"
)


class ExternalDataError(ValueError):
    pass


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if not path.exists():
        raise ExternalDataError(
            f"subset manifest not found: {path.name}"
        )
    return json.loads(path.read_text())


def load_official_records(data_path: str | Path) -> list[dict]:
    path = Path(data_path)
    if not path.exists():
        raise ExternalDataError(
            f"official data file not available: {path.name} "
            "(see docs/longmemeval_subset.md for how to obtain it)"
        )
    try:
        records = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ExternalDataError(
            f"{path.name}: not valid JSON: {exc}"
        )
    if not isinstance(records, list):
        raise ExternalDataError(f"{path.name}: expected a list of records")
    for index, record in enumerate(records):
        validate_official_record(record, index)
    return records


def dataset_variant_for(path: str | Path) -> str:
    name = PurePath(path).name
    if "oracle" in name:
        return "oracle"
    if "_s_" in name or name.endswith("_s.json"):
        return "s_cleaned"
    if "_m_" in name or name.endswith("_m.json"):
        return "m_cleaned"
    if "synthetic" in name:
        return "synthetic"
    raise ExternalDataError(
        f"unknown dataset variant for file {name!r}; expected an "
        "official longmemeval_{oracle,s_cleaned,m_cleaned} file"
    )


def load_selected_cases(
    data_path: str | Path, manifest: dict | None = None
) -> list[ExternalCase]:
    """The committed subset, in committed manifest order.

    Verifies the source fingerprint, rejects missing/duplicate/unknown
    IDs, and never silently substitutes an unavailable ID.
    """
    manifest = manifest or load_manifest()
    variant = dataset_variant_for(data_path)
    if variant == "synthetic":
        raise ExternalDataError(
            "synthetic fixtures cannot be loaded as official subset data"
        )
    records = load_official_records(data_path)
    fingerprint = source_fingerprint(records)
    if fingerprint != manifest["source_fingerprint"]:
        raise ExternalDataError(
            "official source fingerprint mismatch: the data file does not "
            f"match the committed manifest (got {fingerprint[:12]}..., "
            f"manifest records {manifest['source_fingerprint'][:12]}...)"
        )
    by_id: dict[str, dict] = {}
    for record in records:
        by_id[str(record["question_id"])] = record
    cases = []
    seen = set()
    for entry in manifest["selected"]:
        question_id = entry["question_id"]
        if question_id in seen:
            raise ExternalDataError(
                f"duplicate selected ID in manifest: {question_id}"
            )
        seen.add(question_id)
        record = by_id.get(question_id)
        if record is None:
            raise ExternalDataError(
                f"selected ID missing from official data: {question_id}"
            )
        expected_category = subset_category(record)
        if expected_category != entry["category"]:
            raise ExternalDataError(
                f"{question_id}: category drift "
                f"({entry['category']} vs {expected_category})"
            )
        cases.append(
            normalize_record(record, entry["category"], variant)
        )
    return cases


def load_fixture_cases(fixture_path: str | Path) -> list[ExternalCase]:
    """Synthetic official-shape fixtures for offline tests. Never a
    benchmark result."""
    records = json.loads(Path(fixture_path).read_text())
    cases = []
    for index, record in enumerate(records):
        validate_official_record(record, index)
        category = subset_category(record) or "information-extraction"
        cases.append(normalize_record(record, category, "synthetic"))
    return cases
