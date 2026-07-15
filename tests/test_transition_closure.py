"""Cross-document consistency for the transition closure documentation.

Every number quoted in the README, the runbook, and the closure report
must come from the committed artifact. These tests load the artifact and
assert the documents agree with it, so prose cannot drift away from
evidence.

The artifact is the source of truth. If one of these tests fails, the
document is wrong -- not the artifact.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "benchmarks/results/committed/report-transition-verification"

README = ROOT / "README.md"
CLOSURE = ROOT / "docs/transition_verification_closure.md"
RUNBOOK = ROOT / "docs/transition_demo_runbook.md"
REPORT_DOC = ROOT / "docs/transition_verification_report.md"
DASHBOARD_DOC = ROOT / "docs/transition_dashboard.md"

CLOSURE_DOCS = (README, CLOSURE, RUNBOOK)


def _load(name: str) -> dict:
    return json.loads((REPORT_DIR / name).read_text())


def _prose(doc: pathlib.Path) -> str:
    """Lowercased text with whitespace and emphasis collapsed.

    These documents are hard-wrapped Markdown, so a phrase like "9
    blocking gates" routinely straddles a line break or carries bold
    markers. Substring assertions have to read the prose, not the
    layout.
    """
    text = doc.read_text().lower().replace("*", "")
    return re.sub(r"\s+", " ", text)


@pytest.fixture(scope="module")
def gate_summary() -> dict:
    return _load("gate_summary.json")


@pytest.fixture(scope="module")
def headline() -> dict:
    return _load("headline_metrics.json")


@pytest.fixture(scope="module")
def blocking_gates(gate_summary: dict) -> list:
    return [g for g in gate_summary["gates"] if g.get("blocking")]


# --- the documents exist and are reachable -------------------------------


def test_closure_documents_exist() -> None:
    for doc in CLOSURE_DOCS:
        assert doc.is_file(), f"{doc.name} is missing"


def test_readme_links_the_closure_documents() -> None:
    text = README.read_text()
    assert "docs/transition_verification_closure.md" in text
    assert "docs/transition_demo_runbook.md" in text
    assert "docs/transition_verification_report.md" in text


def test_aggregate_validation_target_exists() -> None:
    script = (ROOT / "scripts/run_benchmarks.sh").read_text()
    assert "validate-transition-verification)" in script
    for doc in (README, CLOSURE, RUNBOOK):
        assert "validate-transition-verification" in doc.read_text(), doc.name


# --- blocking gates: 9, derived from the artifact ------------------------


def test_artifact_declares_nine_blocking_gates(blocking_gates: list) -> None:
    assert len(blocking_gates) == 9
    numbers = sorted(g.get("gate", g.get("number")) for g in blocking_gates)
    assert numbers == [4, 5, 8, 9, 10, 11, 12, 19, 20]


def test_all_blocking_gates_pass(blocking_gates: list) -> None:
    assert {g["decision"] for g in blocking_gates} == {"pass"}


def test_documents_state_the_artifact_blocking_count(blocking_gates: list) -> None:
    count = len(blocking_gates)
    for doc in CLOSURE_DOCS:
        assert f"{count} blocking" in _prose(doc), (
            f"{doc.name} omits the blocking-gate count"
        )


def test_no_document_claims_eight_blocking_gates() -> None:
    """The count was misstated as 8 in narrative once; it is 9 in evidence."""
    docs = list(ROOT.glob("docs/*.md")) + [README]
    for doc in docs:
        prose = _prose(doc)
        assert "8 blocking" not in prose, f"{doc.name} claims 8 blocking gates"
        assert "eight blocking" not in prose, f"{doc.name} claims eight blocking gates"


# --- gate tallies and classification -------------------------------------


def test_documents_match_gate_tallies(gate_summary: dict) -> None:
    passed = gate_summary["passed"]
    failed = gate_summary["failed"]
    inconclusive = gate_summary["inconclusive"]
    assert (passed, failed, inconclusive) == (18, 1, 1)
    for doc in CLOSURE_DOCS:
        prose = _prose(doc)
        assert f"{passed} passed" in prose or f"{passed} of 20" in prose, doc.name


def test_documents_carry_the_committed_classification(gate_summary: dict) -> None:
    classification = gate_summary["classification"]
    assert classification == "TRANSITION_PATH_CANDIDATE_ONLY"
    for doc in (README, CLOSURE):
        assert classification in doc.read_text(), doc.name


def test_documents_state_that_no_transition_controller_is_adopted() -> None:
    """Stated positively: a negative substring sweep over prose is noise.

    The README legitimately says "no controller is adopted" about
    grounded extraction, so scanning for the absence of an
    adoption-shaped phrase flags correct sentences. Assert the refusal
    is present instead.
    """
    readme = _prose(README)
    assert "no transition controller is canonical" in readme
    closure = _prose(CLOSURE)
    assert "no transition controller is canonical" in closure


# --- headline metrics ----------------------------------------------------


def test_documents_match_headline_metrics(headline: dict) -> None:
    assert headline["classification_correct"] == 28
    assert headline["classification_total"] == 28
    assert headline["target_correct"] == 11
    assert headline["target_total"] == 11
    assert headline["reference_stale_pairs"] == 6
    assert headline["adopted_stale_pairs"] == 1
    assert headline["reference_duplicate_pairs"] == 0
    assert headline["adopted_duplicate_pairs"] == 10

    for doc in (README, CLOSURE):
        prose = _prose(doc)
        assert "28/28" in prose, doc.name
        assert "11/11" in prose, doc.name

    # The stale-leakage reduction, in each document's own phrasing.
    assert "6 → 1" in _prose(README)
    assert "6 pairs to 1" in _prose(CLOSURE)


def test_duplicate_regression_is_disclosed(headline: dict) -> None:
    """The failed gate must be visible, not buried."""
    before = headline["reference_duplicate_pairs"]
    after = headline["adopted_duplicate_pairs"]
    assert after > before
    for doc in (README, CLOSURE):
        text = doc.read_text()
        assert "Gate 1" in text, doc.name
        assert str(after) in text, doc.name


def test_gate_six_reported_inconclusive_not_passed() -> None:
    for doc in (README, CLOSURE):
        lowered = doc.read_text().lower()
        assert "inconclusive" in lowered, doc.name


# --- partitions stay separate --------------------------------------------


def test_documents_separate_historical_from_fixture_evidence() -> None:
    data = _load("report_data.json")
    assert data["partitions"] == {"historical_scored": 28, "development_fixtures": 27}
    for doc in (README, CLOSURE):
        text = doc.read_text()
        assert "28 historical" in text or "28 historical scored" in text, doc.name
        assert "27 development" in text, doc.name


# --- default posture -----------------------------------------------------


def test_documents_state_the_default_is_disabled() -> None:
    for doc in CLOSURE_DOCS:
        lowered = doc.read_text().lower()
        assert "disabled" in lowered, doc.name


def test_runbook_states_adopted_is_not_offered() -> None:
    lowered = RUNBOOK.read_text().lower()
    assert "adopted mode is not offered" in lowered


def test_runbook_requires_no_credentials() -> None:
    lowered = RUNBOOK.read_text().lower()
    assert "no qwen credentials" in lowered or "no credentials" in lowered


# --- limitations are carried forward -------------------------------------


def test_closure_reports_the_known_unfixed_defect() -> None:
    limitations = _load("limitations.json")["limitations"]
    assert any("grounding_validation" in x for x in limitations)
    assert "grounding_validation" in CLOSURE.read_text()


def test_closure_carries_every_committed_limitation_theme() -> None:
    closure = CLOSURE.read_text().lower()
    for theme in ("28 scored cases", "recall@k", "no learned controller", "in-memory"):
        assert theme in closure, theme


def test_closure_does_not_claim_unsupported_items() -> None:
    unsupported = {x["claim"] for x in _load("claims.json")["unsupported"]}
    assert "canonical adoption" in unsupported
    closure = CLOSURE.read_text().lower()
    assert "not claimed" in closure or "does **not** support" in closure


# --- the dashboard doc already agrees ------------------------------------


def test_dashboard_doc_agrees_with_the_artifact(blocking_gates: list) -> None:
    text = DASHBOARD_DOC.read_text()
    assert f"**{len(blocking_gates)}** blocking gates" in text
    assert "18 passed, 1 failed, 1 inconclusive" in text


def test_report_doc_and_closure_agree_on_classification() -> None:
    assert "TRANSITION_PATH_CANDIDATE_ONLY" in REPORT_DOC.read_text()
    assert "TRANSITION_PATH_CANDIDATE_ONLY" in CLOSURE.read_text()
