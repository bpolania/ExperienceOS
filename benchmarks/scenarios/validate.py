"""Lifecycle dataset validation: manifest, hashes, and oracle rules.

Run directly:

    PYTHONPATH=. python -m benchmarks.scenarios.validate

Exit 0 when the committed dataset is internally consistent. This
validates dataset integrity only — it never executes systems or
produces benchmark results.
"""

from __future__ import annotations

from benchmarks.contract import manifest_hash
from benchmarks.scenarios.loader import (
    DATASET_VERSION,
    GROUP_ALLOCATION,
    GROUP_CATEGORIES,
    GROUP_ORDER,
    SUITE_NAME,
    DatasetError,
    LoadedScenario,
    canonical_scenario_files,
    content_hash,
    dataset_summary,
    load_dataset,
    load_manifest,
)

FORBIDDEN_CONTENT_MARKERS = (
    "/Users/",
    "/home/",
    "\\Users\\",
    "api_key",
    "sk-",
    "Bearer ",
)


def _fail(scenario_id: str, message: str) -> None:
    raise DatasetError(f"{scenario_id}: {message}")


def validate_manifest_structure(manifest: dict) -> None:
    if manifest["suite_name"] != SUITE_NAME:
        raise DatasetError(
            f"manifest suite_name must be {SUITE_NAME!r}, "
            f"got {manifest['suite_name']!r}"
        )
    if manifest["dataset_version"] != DATASET_VERSION:
        raise DatasetError(
            f"manifest dataset_version must be {DATASET_VERSION!r}, "
            f"got {manifest['dataset_version']!r}"
        )
    entries = manifest["scenarios"]
    if manifest["scenario_count"] != len(entries):
        raise DatasetError(
            f"manifest scenario_count {manifest['scenario_count']} does not "
            f"match {len(entries)} entries"
        )
    ids = [e["scenario_id"] for e in entries]
    if len(ids) != len(set(ids)):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        raise DatasetError(f"duplicate scenario IDs in manifest: {duplicates}")
    paths = [e["path"] for e in entries]
    if len(paths) != len(set(paths)):
        raise DatasetError("duplicate scenario paths in manifest")
    # Canonical deterministic order: group order, then scenario_id.
    expected_order = sorted(
        entries,
        key=lambda e: (GROUP_ORDER.index(e["group"]), e["scenario_id"]),
    )
    if [e["scenario_id"] for e in expected_order] != ids:
        raise DatasetError(
            "manifest order must be group order then scenario_id; "
            "filesystem or insertion order is not canonical"
        )
    if manifest["group_allocation"] != GROUP_ALLOCATION:
        raise DatasetError(
            f"group allocation drifted: manifest says "
            f"{manifest['group_allocation']}, contract says "
            f"{GROUP_ALLOCATION}"
        )


def validate_files_match_manifest(manifest: dict) -> None:
    from benchmarks.scenarios.loader import REPO_ROOT

    manifest_paths = {e["path"] for e in manifest["scenarios"]}
    on_disk = {
        str(p.relative_to(REPO_ROOT)) for p in canonical_scenario_files()
    }
    unmanifested = sorted(on_disk - manifest_paths)
    if unmanifested:
        raise DatasetError(
            f"canonical scenario files missing from manifest: {unmanifested}"
        )
    missing = sorted(manifest_paths - on_disk)
    if missing:
        raise DatasetError(f"manifest entries without files: {missing}")


def validate_hashes(manifest: dict, scenarios: list[LoadedScenario]) -> None:
    payloads = []
    for scenario in scenarios:
        actual = content_hash(scenario.case)
        recorded = scenario.entry["content_hash"]
        if actual != recorded:
            _fail(
                scenario.case.scenario_id,
                f"content hash mismatch: manifest records {recorded[:12]}..., "
                f"file hashes to {actual[:12]}... — scenario changed without "
                "a manifest update",
            )
        payloads.append(scenario.case.to_payload())
    overall = manifest_hash(payloads)
    if overall != manifest["manifest_hash"]:
        raise DatasetError(
            f"overall manifest hash mismatch: recorded "
            f"{manifest['manifest_hash'][:12]}..., computed {overall[:12]}..."
        )


def validate_group_allocation(scenarios: list[LoadedScenario]) -> None:
    counts: dict = {}
    for scenario in scenarios:
        counts[scenario.group] = counts.get(scenario.group, 0) + 1
    if counts != GROUP_ALLOCATION:
        raise DatasetError(
            f"category allocation drifted: expected {GROUP_ALLOCATION}, "
            f"got {counts}"
        )
    for scenario in scenarios:
        allowed = GROUP_CATEGORIES[scenario.group]
        if scenario.case.category not in allowed:
            _fail(
                scenario.case.scenario_id,
                f"category {scenario.case.category!r} not allowed in group "
                f"{scenario.group!r} (allowed: {sorted(allowed)})",
            )


def _ref_ids(refs) -> set:
    return {r.logical_id for r in refs}


def validate_oracle(scenario: LoadedScenario) -> None:
    case = scenario.case
    sid = case.scenario_id
    expected = case.expected

    for action in expected.memory_actions:
        if action.action == "create" and action.kind is None:
            _fail(sid, "create expectation must declare a memory kind")
        # supersede/forget targets are enforced by the case schema.

    active_ids = _ref_ids(expected.active)
    superseded_ids = _ref_ids(expected.superseded)
    forgotten_ids = _ref_ids(expected.forgotten)
    overlap_af = active_ids & forgotten_ids
    if overlap_af:
        _fail(sid, f"logical memories both active and forgotten: {sorted(overlap_af)}")
    overlap_as = active_ids & superseded_ids
    if overlap_as:
        _fail(sid, f"logical memories both active and superseded: {sorted(overlap_as)}")

    if expected.retrieval_candidates and expected.selected:
        missing = _ref_ids(expected.selected) - _ref_ids(
            expected.retrieval_candidates
        )
        if missing:
            _fail(
                sid,
                f"selected memories missing from retrieval candidates: "
                f"{sorted(missing)}",
            )

    response = expected.response
    tags = set(case.tags)
    if ("stale-leakage" in tags or "forgotten-leakage" in tags) and (
        response is None or not response.must_exclude
    ):
        _fail(
            sid,
            "leakage case must carry forbidden response constraints "
            "(response.must_exclude)",
        )
    if response is not None and response.expect_abstention and (
        response.must_include_all or response.must_include_any
    ):
        _fail(
            sid,
            "abstention case must not also require answer content "
            "(contradictory constraints)",
        )
    if "local-model-behavior" in tags and not case.requires_local_model:
        _fail(sid, "local-model behavior case must set requires_local_model")
    if case.evaluation_mode == "model_scored" and not case.requires_provider:
        _fail(sid, "model-scored case must set requires_provider")
    if case.selection_k is not None and case.selection_k > case.context_budget:
        _fail(
            sid,
            f"selection_k {case.selection_k} exceeds context_budget "
            f"{case.context_budget} without explanation",
        )
    if case.category == "compression" and not expected.compression_expected:
        _fail(sid, "compression-category case must set compression_expected")
    for marker in FORBIDDEN_CONTENT_MARKERS:
        if marker in scenario.path.read_text():
            _fail(sid, f"scenario file contains forbidden content {marker!r}")


def validate_dataset() -> dict:
    """Run every dataset check; return the summary on success."""
    manifest = load_manifest()
    validate_manifest_structure(manifest)
    validate_files_match_manifest(manifest)
    scenarios = load_dataset(manifest)
    validate_hashes(manifest, scenarios)
    validate_group_allocation(scenarios)
    for scenario in scenarios:
        validate_oracle(scenario)
    return dataset_summary(manifest, scenarios)


def main() -> int:
    try:
        summary = validate_dataset()
    except DatasetError as exc:
        print(f"DATASET INVALID: {exc}")
        return 1
    print(f"dataset: {summary['suite_name']} {summary['dataset_version']}")
    print(f"total scenarios: {summary['total_scenarios']}")
    print(f"groups: {summary['group_counts']}")
    print(f"categories: {summary['category_counts']}")
    print(
        f"deterministic: {summary['deterministic']} · "
        f"model-scored: {summary['model_scored']} · "
        f"provider-required: {summary['provider_required']} · "
        f"local-model-required: {summary['local_model_required']}"
    )
    print(f"manifest hash: {summary['manifest_hash']}")
    print("RESULT: lifecycle dataset validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
