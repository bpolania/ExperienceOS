"""Report source loading: validate both canonical artifacts, verify
required digests, and build the report view (report_data) — every
displayed number originates here, from committed raw artifacts. No
benchmark system is ever rerun."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmarks.artifacts.validation import validate_artifact_dir
from benchmarks.contract import canonical_json, metric as lifecycle_metric
from benchmarks.external.longmemeval.evaluate import external_metric
from benchmarks.external.longmemeval.validation import (
    validate_external_artifact,
)

SPEC_PATH = Path(__file__).resolve().parent / "report_spec.json"
REPO_ROOT = Path(__file__).resolve().parents[2]


class ReportSourceError(ValueError):
    pass


def load_spec() -> dict:
    return json.loads(SPEC_PATH.read_text())


def spec_hash() -> str:
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()


def _jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text().split("\n")
        if line.strip()
    ]


def load_sources(spec: dict) -> dict:
    """Validate both artifacts and load everything the report reads."""
    lifecycle_dir = REPO_ROOT / spec["sources"]["lifecycle"]["path"]
    external_dir = REPO_ROOT / spec["sources"]["external"]["path"]

    lifecycle_summary = validate_artifact_dir(lifecycle_dir)
    if lifecycle_summary["normalized_result_digest"] != (
        spec["sources"]["lifecycle"]["required_digest"]
    ):
        raise ReportSourceError(
            "lifecycle artifact digest does not match the report spec"
        )
    external_summary = validate_external_artifact(external_dir)
    if external_summary["normalized_result_digest"] != (
        spec["sources"]["external"]["required_digest"]
    ):
        raise ReportSourceError(
            "external artifact digest does not match the report spec"
        )

    lifecycle = {
        "aggregate": json.loads(
            (lifecycle_dir / "aggregate.json").read_text()
        ),
        "provenance": json.loads(
            (lifecycle_dir / "provenance.json").read_text()
        ),
        "failures": json.loads(
            (lifecycle_dir / "failures.json").read_text()
        ),
        "cases": _jsonl(lifecycle_dir / "cases.jsonl"),
        "digest": lifecycle_summary["normalized_result_digest"],
        "path": spec["sources"]["lifecycle"]["path"],
    }
    if lifecycle["provenance"]["manifest_hash"] != (
        spec["sources"]["lifecycle"]["required_manifest_hash"]
    ):
        raise ReportSourceError("lifecycle manifest hash mismatch")

    external = {
        "aggregate": json.loads(
            (external_dir / "aggregate.json").read_text()
        ),
        "provenance": json.loads(
            (external_dir / "external_provenance.json").read_text()
        ),
        "manifest": json.loads(
            (external_dir / "external_manifest.json").read_text()
        ),
        "failures": json.loads(
            (external_dir / "failures.json").read_text()
        ),
        "cases": _jsonl(external_dir / "cases.jsonl"),
        "metadata": _jsonl(external_dir / "selected_case_metadata.jsonl"),
        "digest": external_summary["normalized_result_digest"],
        "path": spec["sources"]["external"]["path"],
    }
    if external["manifest"]["manifest_hash"] != (
        spec["sources"]["external"]["required_subset_hash"]
    ):
        raise ReportSourceError("external subset manifest hash mismatch")
    if external["manifest"]["display_label"] != (
        spec["sources"]["external"]["required_label"]
    ):
        raise ReportSourceError("external display label mismatch")
    if external["provenance"]["official_evaluation"] is not False:
        raise ReportSourceError("external official-evaluation flag conflict")
    if lifecycle["provenance"]["used_real_local_model"] is not False:
        raise ReportSourceError("lifecycle local-policy mode mislabeled")
    return {"lifecycle": lifecycle, "external": external}


def lifecycle_cell(sources, system: str, name: str) -> dict:
    lifecycle_metric(name)  # unknown metric names are rejected
    cell = sources["lifecycle"]["aggregate"]["metrics"].get(system, {}).get(
        name
    )
    if cell is None:
        return {
            "numerator": 0.0,
            "denominator": 0.0,
            "value": None,
            "undefined_count": 0,
            "absent": True,
        }
    return {**cell, "absent": False}


def external_cell(sources, system: str, name: str) -> dict:
    external_metric(name)
    cell = sources["external"]["aggregate"]["metrics"].get(system, {}).get(
        name
    )
    if cell is None:
        return {
            "numerator": 0.0,
            "denominator": 0.0,
            "value": None,
            "undefined_count": 0,
            "absent": True,
        }
    return {**cell, "absent": False}


def lifecycle_group_cell(sources, system, group, name) -> dict | None:
    lifecycle_metric(name)
    return (
        sources["lifecycle"]["aggregate"]["by_scenario_group"]
        .get(system, {})
        .get(group, {})
        .get(name)
    )


def lifecycle_context_stats(sources) -> dict:
    """Average context accounting per system, from raw case records."""
    stats: dict = {}
    for record in sources["lifecycle"]["cases"]:
        case = record["case"]
        accounting = case.get("context_accounting")
        if not accounting or case["status"] == "skipped":
            continue
        bucket = stats.setdefault(
            case["system_id"],
            {"n": 0, "total": 0, "memory": 0, "selected": 0, "candidates": 0},
        )
        bucket["n"] += 1
        bucket["total"] += accounting["total_context_tokens"]
        bucket["memory"] += accounting["memory_context_tokens"]
        bucket["selected"] += accounting["selected_memory_count"]
        bucket["candidates"] += accounting["candidate_memory_count"]
    return {
        system: {
            "cases": b["n"],
            "avg_total_context_tokens": round(b["total"] / b["n"], 1),
            "avg_memory_context_tokens": round(b["memory"] / b["n"], 1),
            "avg_selected_memories": round(b["selected"] / b["n"], 2),
            "avg_candidate_memories": round(b["candidates"] / b["n"], 2),
        }
        for system, b in sorted(stats.items())
    }


def external_context_stats(sources) -> dict:
    stats: dict = {}
    for record in sources["external"]["cases"]:
        bucket = stats.setdefault(
            record["system_id"],
            {"n": 0, "total": 0, "history": 0, "selected": 0},
        )
        bucket["n"] += 1
        bucket["total"] += record["context_tokens"]
        bucket["history"] += record["history_or_memory_tokens"]
        bucket["selected"] += record.get("selected_count", 0)
    return {
        system: {
            "cases": b["n"],
            "avg_total_context_tokens": round(b["total"] / b["n"], 1),
            "avg_history_or_memory_tokens": round(b["history"] / b["n"], 1),
            "avg_selected_items": round(b["selected"] / b["n"], 2),
        }
        for system, b in sorted(stats.items())
    }


def external_category_cells(sources, categories, metrics) -> dict:
    """Per-category external sums recomputed from raw contributions."""
    category_of = {
        m["question_id"]: m["category"]
        for m in sources["external"]["metadata"]
    }
    out: dict = {}
    for record in sources["external"]["cases"]:
        category = category_of.get(record["question_id"])
        if category not in categories:
            continue
        for payload in record["contributions"]:
            if payload["metric"] not in metrics:
                continue
            cell = (
                out.setdefault(category, {})
                .setdefault(record["system_id"], {})
                .setdefault(
                    payload["metric"],
                    {
                        "numerator": 0.0,
                        "denominator": 0.0,
                        "undefined_count": 0,
                    },
                )
            )
            if not payload["applicable"]:
                cell["undefined_count"] += 1
                continue
            cell["numerator"] += payload["numerator"]
            cell["denominator"] += payload["denominator"]
    for category, systems in out.items():
        for system, cells in systems.items():
            for name, cell in cells.items():
                cell["value"] = (
                    cell["numerator"] / cell["denominator"]
                    if cell["denominator"]
                    else None
                )
    return out


def report_data_digest(report_data: dict) -> str:
    body = {
        k: v
        for k, v in report_data.items()
        if k not in ("generated_at_utc", "report_data_digest")
    }
    return hashlib.sha256(
        canonical_json(body).encode("utf-8")
    ).hexdigest()
