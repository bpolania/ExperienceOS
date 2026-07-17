"""Integrity checks for the canonical action-replacement contract.

The contract fixes scope, authority, gates, digests, system IDs, and
artifact boundaries for the action-replacement work. These tests bind
the document to committed evidence so it cannot drift: the reserved
system IDs must not collide, the quoted frozen digests must match the
committed manifests, the classification and blocking-gate count must be
the ones the artifact actually carries, and the reserved output
directories must stay empty until later work fills them.

If one of these fails, the contract is wrong -- not the evidence.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/action_replacement_contract.md"
REPORT_DIR = ROOT / "benchmarks/results/committed/report-transition-verification"
COMMITTED = ROOT / "benchmarks/results/committed"

# System IDs the contract reserves for the new work.
RESERVED_IDS = (
    "experienceos_action_replacement_shadow_v1",
    "experienceos_action_replacement_candidate_v1",
    "experienceos_action_replacement_verify_only_v1",
    "experienceos_action_replacement_adopted_v1",
    "experienceos_action_replacement_ablation_no_replacement_v1",
    "experienceos_action_replacement_ablation_replace_all_v1",
)

# Output directories the contract reserves but must not yet populate.
RESERVED_DIRS = (
    "action-replacement",
    "deduplicated-transition",
    "report-action-replacement",
)


def _prose() -> str:
    return re.sub(r"\s+", " ", CONTRACT.read_text().lower().replace("*", ""))


def test_contract_exists() -> None:
    assert CONTRACT.is_file()


def test_contract_states_the_required_rule_sections() -> None:
    prose = _prose()
    for phrase in (
        "planner-action conflict",
        "replacement rejection",
        "action preservation",
        "authority boundary",
        "metric definitions",
        "adoption gates",
        "stop conditions",
        "reserved system ids",
        "artifact boundaries",
    ):
        assert phrase in prose, phrase


def test_reserved_ids_do_not_collide_with_committed_systems() -> None:
    systems = json.loads((REPORT_DIR.parent
                          / "transition-verification/systems.json").read_text())
    existing = {s["system_id"] for s in systems["systems"]}
    for reserved in RESERVED_IDS:
        assert reserved not in existing, f"{reserved} collides with committed id"
        assert reserved in CONTRACT.read_text(), f"{reserved} missing from contract"


def test_contract_quotes_the_committed_frozen_digests() -> None:
    text = CONTRACT.read_text()
    for family in ("transition-verification", "transition-ablation"):
        manifest = json.loads((COMMITTED / family / "manifest.json").read_text())
        assert manifest["content_digest"] in text, family
    report_manifest = json.loads((REPORT_DIR / "manifest.json").read_text())
    assert report_manifest["content_digest"] in text


def test_contract_carries_the_committed_classification() -> None:
    gate_summary = json.loads((REPORT_DIR / "gate_summary.json").read_text())
    assert gate_summary["classification"] in CONTRACT.read_text()


def test_contract_states_the_artifact_blocking_gate_count() -> None:
    gate_summary = json.loads((REPORT_DIR / "gate_summary.json").read_text())
    blocking = [g for g in gate_summary["gates"] if g.get("blocking")]
    assert len(blocking) == 9
    numbers = sorted(g.get("gate", g.get("number")) for g in blocking)
    assert numbers == [4, 5, 8, 9, 10, 11, 12, 19, 20]
    # The contract names the same blocking gate numbers the artifact
    # carries, tolerant of comma spacing / line wrap.
    normalized = re.sub(r"\s+", "", CONTRACT.read_text())
    assert "(" + ",".join(str(n) for n in numbers) + ")" in normalized
    assert f"{len(blocking)} blocking" in _prose()


def test_reserved_output_directories_are_not_yet_populated() -> None:
    for name in RESERVED_DIRS:
        d = COMMITTED / name
        assert not d.exists(), f"{name} was populated prematurely"


def test_contract_locates_the_engine_seam() -> None:
    text = CONTRACT.read_text()
    # The seam is an append in the engine, not the coordinator.
    assert "experience_engine.py:450" in text or "experience_engine.py:451" in text
    assert "_apply_memory_actions" in text
