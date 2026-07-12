"""Integrity and separation tests for the grounded-extraction
development fixtures."""

import json
from pathlib import Path

import pytest

from benchmarks.fixtures.grounded_extraction import (
    ALLOWED_SOURCE_TYPES,
    CANONICAL_KINDS,
    CATEGORIES,
    FIXTURE_PATH,
    FixtureError,
    REJECTION_REASONS,
    load_development_fixtures,
)

FIXTURES = load_development_fixtures()


# -- loading ---------------------------------------------------------------------


def test_fixtures_load_and_are_deterministic():
    again = load_development_fixtures()
    assert FIXTURES == again
    assert [c["case_id"] for c in FIXTURES] == [
        c["case_id"] for c in again
    ]
    assert len(FIXTURES) >= 24


def test_ids_unique_stable_and_feature_named():
    ids = [c["case_id"] for c in FIXTURES]
    assert len(ids) == len(set(ids))
    for case_id in ids:
        assert case_id.rsplit("-", 1)[-1].isdigit(), case_id
        lowered = case_id.lower()
        assert "phase" not in lowered and "prompt" not in lowered
        assert " " not in case_id


def test_required_fields_kinds_and_categories():
    for case in FIXTURES:
        assert case["development_only"] is True
        assert case["category"] in CATEGORIES
        assert case["source_type"] in ALLOWED_SOURCE_TYPES
        if case["candidate_expected"]:
            for kind in (case["expected_kind"],
                         *case.get("acceptable_kinds", [])):
                assert kind in CANONICAL_KINDS


# -- positive integrity ----------------------------------------------------------


def _positives():
    return [c for c in FIXTURES if c["candidate_expected"]]


def _negatives():
    return [c for c in FIXTURES if not c["candidate_expected"]]


def test_positive_cases_have_exact_valid_spans():
    for case in _positives():
        message = case["user_message"]
        start = case["expected_start_offset"]
        end = case["expected_end_offset"]
        assert 0 <= start < end <= len(message), case["case_id"]
        assert message[start:end] == case["expected_evidence_text"], (
            case["case_id"]
        )
        assert case["expected_evidence_text"].strip()


def test_positive_cases_have_normalizations_and_no_rejection():
    for case in _positives():
        assert case["acceptable_normalized_texts"], case["case_id"]
        assert all(
            text.strip() for text in case["acceptable_normalized_texts"]
        )
        assert not case.get("rejection_reason"), case["case_id"]


def test_positive_cases_expect_at_most_one_candidate():
    for case in _positives():
        # One span, one expected kind (plus optional acceptable set):
        # the schema cannot express a second expected candidate.
        assert isinstance(case["expected_evidence_text"], str)
        assert isinstance(case["expected_kind"], str)


def test_unsupported_normalizations_differ_from_acceptable():
    for case in _positives():
        for bad in case.get("unsupported_normalized_texts", []):
            assert bad not in case["acceptable_normalized_texts"], (
                case["case_id"]
            )


# -- negative integrity ----------------------------------------------------------


def test_negative_cases_have_rejection_reasons_and_no_spans():
    for case in _negatives():
        assert case["rejection_reason"] in REJECTION_REASONS, (
            case["case_id"]
        )
        assert case.get("expected_evidence_text") is None
        assert case.get("expected_start_offset") is None


def test_assistant_only_case_has_assistant_message():
    cases = [c for c in FIXTURES if c["category"] == "assistant-only"]
    assert cases
    for case in cases:
        assert case.get("assistant_message")
        assert case["rejection_reason"] == "assistant_only"


# -- coverage --------------------------------------------------------------------


def test_all_required_categories_covered():
    covered = {c["category"] for c in FIXTURES}
    assert covered == set(CATEGORIES)


def test_temporal_forms_are_varied():
    messages = " ".join(
        c["user_message"].lower()
        for c in FIXTURES if c["category"] == "temporary-state"
    )
    assert "this month" in messages
    assert "this week" in messages
    assert "this trip" in messages
    assert "until friday" in messages


def test_lifecycle_expectations_are_separate_from_proposals():
    lifecycle_cases = [
        c for c in FIXTURES if c.get("lifecycle_expectation")
    ]
    assert lifecycle_cases
    for case in lifecycle_cases:
        # A lifecycle expectation never suppresses the proposal-layer
        # expectation: these cases still expect a valid proposal.
        assert case["candidate_expected"] is True
        assert case["existing_memories"], case["case_id"]


def test_failure_derived_cases_cite_bounded_sources():
    derived = [
        c for c in FIXTURES
        if c["source_reference"] != "synthetic-development-scenario"
    ]
    assert derived  # at least some cases trace to committed evidence
    for case in derived:
        reference = case["source_reference"]
        assert ":" in reference  # <evidence>:<stable id> shape
        assert "/Users/" not in reference and "/home/" not in reference


# -- validator behavior ----------------------------------------------------------


def test_loader_rejects_corrupted_cases(tmp_path):
    def _write(mutate):
        case = json.loads(json.dumps(FIXTURES[0]))
        mutate(case)
        path = tmp_path / "bad.jsonl"
        path.write_text(json.dumps(case) + "\n")
        return path

    bad_offsets = _write(
        lambda c: c.update(expected_start_offset=999,
                           expected_end_offset=1005)
    )
    with pytest.raises(FixtureError):
        load_development_fixtures(bad_offsets)
    bad_kind = _write(lambda c: c.update(expected_kind="opinion"))
    with pytest.raises(FixtureError):
        load_development_fixtures(bad_kind)
    not_dev = _write(lambda c: c.update(development_only=False))
    with pytest.raises(FixtureError):
        load_development_fixtures(not_dev)
    duplicate = tmp_path / "dup.jsonl"
    duplicate.write_text(
        json.dumps(FIXTURES[0]) + "\n" + json.dumps(FIXTURES[0]) + "\n"
    )
    with pytest.raises(FixtureError):
        load_development_fixtures(duplicate)


# -- separation from frozen evidence ---------------------------------------------


def test_fixtures_live_outside_committed_results():
    assert "results/committed" not in str(FIXTURE_PATH)
    assert FIXTURE_PATH.exists()
    for manifest in Path("benchmarks/results/committed").rglob(
        "artifact_manifest.json"
    ):
        assert "grounded-extraction" not in manifest.read_text(), (
            manifest
        )


def test_development_fixture_loader_used_only_by_labeled_smoke():
    # The development-fixture LOADER must not feed primary benchmark
    # aggregates: its only benchmark consumer is the grounded-extraction
    # runner's labeled fixture_smoke, and it must not be imported by the
    # scoring/aggregation/evaluation code.
    marker = "benchmarks.fixtures.grounded_extraction"
    consumers = []
    for path in Path("benchmarks").rglob("*.py"):
        if "fixtures" in path.parts:
            continue
        if marker in path.read_text():
            consumers.append(path)
    assert consumers == [
        Path("benchmarks/grounded_extraction/runner.py")
    ], consumers
    runner = Path("benchmarks/grounded_extraction/runner.py").read_text()
    smoke = runner.split("def fixture_smoke", 1)[1].split("\ndef ", 1)[0]
    assert marker in smoke
    for module in ("scoring.py", "evaluation.py", "gates.py"):
        assert marker not in Path(
            f"benchmarks/grounded_extraction/{module}").read_text()


def test_no_secrets_or_personal_paths_in_fixture_data():
    text = FIXTURE_PATH.read_text()
    for token in ("/Users/", "/home/", "API_KEY", "SECRET", "TOKEN"):
        assert token not in text


# -- side effects ----------------------------------------------------------------


def test_loading_has_no_side_effects(tmp_path):
    import sys

    from experienceos.events.bus import EventBus
    from experienceos.memory.store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    bus = EventBus()
    before_modules = set(sys.modules)
    before_bytes = FIXTURE_PATH.read_bytes()
    load_development_fixtures()
    assert FIXTURE_PATH.read_bytes() == before_bytes  # no writes
    assert store.list_memories("u1") == []  # no store mutation
    assert bus.history() == []
    heavy = {"sentence_transformers", "torch", "onnxruntime",
             "llama_cpp", "streamlit"}
    assert not (set(sys.modules) - before_modules) & heavy
    assert not list(tmp_path.iterdir())  # nothing written anywhere new
