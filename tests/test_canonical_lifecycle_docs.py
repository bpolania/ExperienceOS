"""Consistency tests for the canonical-lifecycle-activation documentation.

Pins the current-status prose to the committed machine-readable evidence:
every headline metric in the README / docs must trace to an aggregate
record, the referenced paths must exist, and authored docs must carry no
secret or real home-directory path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "benchmarks/results/committed/canonical-lifecycle-activation-live"
OFFLINE = ROOT / "benchmarks/results/committed/canonical-lifecycle-activation"
README = ROOT / "README.md"


def _agg():
    return json.loads((LIVE / "aggregate_by_system.json").read_text())


def _pct(a, k):
    v = a[k]
    return v["numerator"], v["denominator"], v["percentage"]


# -- the committed evidence itself is internally consistent ------------------


def test_live_campaign_shape():
    raw = [json.loads(l) for l in (LIVE / "raw_case_results.jsonl").open()]
    scored = [json.loads(l) for l in (LIVE / "scoring_results.jsonl").open()]
    systems = {r["system_id"] for r in raw}
    assert len(systems) == 6
    assert len(raw) == 240
    assert len(scored) == 228
    assert sum(1 for r in raw if r["status"] == "completed") == 228
    assert sum(1 for r in raw if r["status"] == "not_applicable") == 12


def test_canonical_and_baseline_headline_numbers():
    agg = _agg()
    c = agg["canonical_experienceos_qwen"]
    assert _pct(c, "final_answer_accuracy") == (30, 38, 78.95)
    assert _pct(c, "stale_information_use_rate") == (5, 18, 27.78)
    assert _pct(c, "current_information_accuracy") == (15, 17, 88.24)
    assert _pct(c, "unsupported_claim_rate") == (5, 38, 13.16)
    assert _pct(agg["stateless"], "final_answer_accuracy") == (31, 38, 81.58)


def test_competitive_decision_is_comparable_with_notes():
    cd = json.loads((LIVE / "competitive_decision.json").read_text())
    assert cd["competitive_decision"] == "COMPETITIVE_VIABILITY_COMPARABLE_WITH_NOTES"
    assert cd["strongest_baseline"] == "stateless"
    assert cd["gap_points"] == 2.63
    assert cd["within_five_point_comparability_heuristic"] is True
    assert cd["equals_or_exceeds_strongest"] is False


def test_four_genuine_fixed_five_false_positives_remain():
    fu = json.loads((LIVE / "phase18_followup_live.json").read_text())["cases"]
    outcomes = [c["phase20_outcome_classification"] for c in fu]
    assert outcomes.count("fixed_by_lifecycle_activation") == 4
    assert outcomes.count("evaluator_false_positive_remains") == 5
    audit = json.loads((LIVE / "four_genuine_case_audit_live.json").read_text())["cases"]
    assert len(audit) == 4
    assert all(c["verdict_correct"] for c in audit)
    assert not any(c["verdict_uses_stale"] for c in audit)


# -- the README prose matches that evidence ----------------------------------


def test_readme_headline_numbers_match_evidence():
    text = README.read_text()
    for token in ("78.95%", "71.05%", "81.58%", "2.63", "50.00%", "27.78%",
                  "88.24%", "18.42%", "13.16%", "87.23%"):
        assert token in text, f"README missing {token}"
    # current status must not describe the canonical path as candidate-only
    assert "Current status (canonical activation)" in text
    assert "COMPARABLE" in text or "comparable with notes" in text.lower()


def test_referenced_docs_and_evidence_paths_exist():
    for p in ("docs/bounded_runtime_transition_authority.md",
              "docs/canonical_lifecycle_transitions.md",
              "docs/canonical_lifecycle_claims_matrix.md",
              "benchmarks/results/committed/canonical-lifecycle-activation-live",
              "benchmarks/results/committed/canonical-lifecycle-activation"):
        assert (ROOT / p).exists(), f"missing {p}"


def test_authored_docs_carry_no_secret_or_home_path():
    for name in ("README.md", "docs/bounded_runtime_transition_authority.md",
                 "docs/canonical_lifecycle_transitions.md",
                 "docs/canonical_lifecycle_claims_matrix.md"):
        text = (ROOT / name).read_text()
        assert "/Users/bpolania" not in text
        assert "sk-" not in text
        # placeholder credentials only
        assert 'api_key="..."' in text or "QWEN_API_KEY" in text or "docs/" in name
