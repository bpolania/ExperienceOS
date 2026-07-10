"""Lifecycle dataset loading.

The committed JSON files under ``benchmarks/scenarios/lifecycle/`` are
the benchmark source of truth; the committed manifest defines the
canonical deterministic order. Filesystem enumeration order is never
used to define benchmark order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from benchmarks.contract import BenchmarkCase, canonical_json, case_from_dict

DATASET_VERSION = "experienceos-lifecycle-v1"
SUITE_NAME = "experienceos-lifecycle"

GROUP_ORDER = (
    "creation",
    "updates",
    "forgetting",
    "retrieval",
    "context",
    "containment",
)

GROUP_ALLOCATION = {
    "creation": 6,
    "updates": 8,
    "forgetting": 6,
    "retrieval": 8,
    "context": 6,
    "containment": 6,
}

# Which contract categories each dataset group may use.
GROUP_CATEGORIES = {
    "creation": {"creation"},
    "updates": {"update"},
    "forgetting": {"forgetting"},
    "retrieval": {"retrieval", "distractor", "abstention", "multi_session"},
    "context": {"context_budget", "selection", "compression"},
    "containment": {"rejection", "fallback"},
}

SCENARIOS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCENARIOS_DIR.parents[1]
LIFECYCLE_DIR = SCENARIOS_DIR / "lifecycle"
MANIFEST_PATH = SCENARIOS_DIR / "lifecycle_manifest.json"


class DatasetError(ValueError):
    """Raised when the dataset or manifest fails validation."""


@dataclass(frozen=True)
class LoadedScenario:
    case: BenchmarkCase
    group: str
    path: Path
    entry: dict


def content_hash(case: BenchmarkCase) -> str:
    """Deterministic per-case hash over the canonical payload."""
    body = canonical_json(case.to_payload())
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    try:
        manifest = json.loads(path.read_text())
    except FileNotFoundError:
        raise DatasetError(f"manifest not found: {path.name}")
    except json.JSONDecodeError as exc:
        raise DatasetError(f"manifest is not valid JSON: {exc}")
    for field in (
        "suite_name",
        "schema_version",
        "dataset_version",
        "scenario_count",
        "group_allocation",
        "scenarios",
        "manifest_hash",
    ):
        if field not in manifest:
            raise DatasetError(f"manifest missing required field {field!r}")
    return manifest


def load_scenario_file(path: Path) -> BenchmarkCase:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{path.name}: not valid JSON: {exc}")
    return case_from_dict(data)


def load_dataset(manifest: dict | None = None) -> list[LoadedScenario]:
    """Load every scenario in canonical manifest order."""
    manifest = manifest or load_manifest()
    loaded = []
    for entry in manifest["scenarios"]:
        rel_path = entry["path"]
        path = (REPO_ROOT / rel_path).resolve()
        if REPO_ROOT.resolve() not in path.parents:
            raise DatasetError(
                f"{entry['scenario_id']}: manifest path escapes the "
                f"repository: {rel_path}"
            )
        if not path.exists():
            raise DatasetError(
                f"{entry['scenario_id']}: scenario file missing: {rel_path}"
            )
        case = load_scenario_file(path)
        loaded.append(
            LoadedScenario(
                case=case, group=entry["group"], path=path, entry=entry
            )
        )
    return loaded


def canonical_scenario_files() -> list[Path]:
    """Every scenario file present under the lifecycle directory."""
    return sorted(LIFECYCLE_DIR.glob("*/*.json"))


def dataset_summary(manifest: dict, scenarios: list[LoadedScenario]) -> dict:
    category_counts: dict = {}
    group_counts: dict = {}
    deterministic = provider_required = local_required = model_scored = 0
    for scenario in scenarios:
        case = scenario.case
        category_counts[case.category] = (
            category_counts.get(case.category, 0) + 1
        )
        group_counts[scenario.group] = group_counts.get(scenario.group, 0) + 1
        if case.evaluation_mode == "deterministic":
            deterministic += 1
        else:
            model_scored += 1
        if case.requires_provider:
            provider_required += 1
        if case.requires_local_model:
            local_required += 1
    return {
        "suite_name": manifest["suite_name"],
        "dataset_version": manifest["dataset_version"],
        "total_scenarios": len(scenarios),
        "group_counts": {g: group_counts.get(g, 0) for g in GROUP_ORDER},
        "category_counts": dict(sorted(category_counts.items())),
        "deterministic": deterministic,
        "model_scored": model_scored,
        "provider_required": provider_required,
        "local_model_required": local_required,
        "manifest_hash": manifest["manifest_hash"],
    }
