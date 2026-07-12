"""Validation of the additive grounded-extraction annotations."""

import json

import pytest

from benchmarks.grounded_extraction import annotations as ann_mod
from benchmarks.grounded_extraction.annotations import (
    AnnotationError,
    CANONICAL_KINDS,
    _frozen_external_ids,
    _frozen_lifecycle_ids,
    load_external_annotations,
    load_lifecycle_annotations,
)

LIFECYCLE = load_lifecycle_annotations()
EXTERNAL = load_external_annotations()
FROZEN_LIFECYCLE = _frozen_lifecycle_ids()
FROZEN_EXTERNAL = _frozen_external_ids()


def test_lifecycle_ids_are_unique_and_frozen():
    ids = [a.case_id for a in LIFECYCLE]
    assert len(ids) == len(set(ids))
    for a in LIFECYCLE:
        assert a.case_id in FROZEN_LIFECYCLE


def test_external_ids_are_unique_and_frozen():
    ids = [a.case_id for a in EXTERNAL]
    assert len(ids) == len(set(ids))
    for a in EXTERNAL:
        assert a.case_id in FROZEN_EXTERNAL


def test_lifecycle_class_counts():
    assert len(LIFECYCLE) == 40
    assert sum(a.is_positive for a in LIFECYCLE) == 13
    assert sum(a.is_duplicate for a in LIFECYCLE) == 2
    assert sum(a.is_negative for a in LIFECYCLE) == 24
    assert sum(not a.scorable for a in LIFECYCLE) == 1


def test_positive_cases_have_canonical_kind_and_tokens():
    for a in LIFECYCLE:
        if a.is_positive:
            assert a.expected_kind in CANONICAL_KINDS
            assert a.acceptable_kinds
            assert a.normalized_must_include


def test_negative_cases_have_valid_rejection_category():
    for a in LIFECYCLE:
        if a.is_negative:
            assert a.rejection_category in ann_mod.REJECTION_CATEGORIES


def test_evidence_spans_in_range_where_present():
    for a in LIFECYCLE:
        for start, end in a.acceptable_evidence_spans:
            assert 0 <= start < end <= len(a.source_text)


def test_unscorable_cases_carry_a_reason():
    for a in LIFECYCLE:
        if not a.scorable:
            assert a.annotation_notes.strip()


def test_deterministic_ordering():
    ids = [a.case_id for a in LIFECYCLE]
    assert ids == sorted(ids)
    ext_ids = [a.case_id for a in EXTERNAL]
    assert ext_ids == sorted(ext_ids)


def test_external_is_classification_only():
    for a in EXTERNAL:
        assert a.scorable is False
        assert a.span_scoring_available is False
        assert a.annotation_notes.strip()


def test_frozen_records_not_modified_by_loading():
    # Loading must not write to the frozen datasets.
    before = {}
    for cid in list(FROZEN_LIFECYCLE)[:3]:
        pass
    life_a = load_lifecycle_annotations()
    life_b = load_lifecycle_annotations()
    assert [a.case_id for a in life_a] == [a.case_id for a in life_b]


def test_duplicate_id_rejected(tmp_path, monkeypatch):
    path = tmp_path / "lifecycle.jsonl"
    rec = json.loads(next(open(ann_mod.LIFECYCLE_PATH)))
    with open(path, "w") as f:
        f.write(json.dumps(rec) + "\n")
        f.write(json.dumps(rec) + "\n")
    monkeypatch.setattr(ann_mod, "LIFECYCLE_PATH", path)
    with pytest.raises(AnnotationError, match="duplicate"):
        load_lifecycle_annotations()


def test_unknown_case_id_rejected(tmp_path, monkeypatch):
    path = tmp_path / "lifecycle.jsonl"
    rec = json.loads(next(open(ann_mod.LIFECYCLE_PATH)))
    rec["case_id"] = "not_a_real_scenario_999"
    with open(path, "w") as f:
        f.write(json.dumps(rec) + "\n")
    monkeypatch.setattr(ann_mod, "LIFECYCLE_PATH", path)
    with pytest.raises(AnnotationError, match="not a frozen"):
        load_lifecycle_annotations()


def test_non_canonical_kind_rejected(tmp_path, monkeypatch):
    path = tmp_path / "lifecycle.jsonl"
    rec = json.loads(next(
        line for line in open(ann_mod.LIFECYCLE_PATH)
        if json.loads(line)["candidate_expected"]))
    rec["acceptable_kinds"] = ["not_a_kind"]
    with open(path, "w") as f:
        f.write(json.dumps(rec) + "\n")
    monkeypatch.setattr(ann_mod, "LIFECYCLE_PATH", path)
    with pytest.raises(AnnotationError, match="non-canonical kind"):
        load_lifecycle_annotations()


def test_out_of_range_span_rejected(tmp_path, monkeypatch):
    path = tmp_path / "lifecycle.jsonl"
    rec = json.loads(next(
        line for line in open(ann_mod.LIFECYCLE_PATH)
        if json.loads(line)["candidate_expected"]))
    rec["acceptable_evidence_spans"] = [[0, 99999]]
    with open(path, "w") as f:
        f.write(json.dumps(rec) + "\n")
    monkeypatch.setattr(ann_mod, "LIFECYCLE_PATH", path)
    with pytest.raises(AnnotationError, match="out of range"):
        load_lifecycle_annotations()


def test_no_development_fixture_ids_leak_into_annotations():
    # Development fixture case IDs (e.g. explicit-preference-001) must not
    # appear as frozen benchmark case IDs.
    from benchmarks.fixtures.grounded_extraction import (
        load_development_fixtures,
    )

    fixture_ids = {f["case_id"] for f in load_development_fixtures()}
    annotation_ids = {a.case_id for a in LIFECYCLE} | {
        a.case_id for a in EXTERNAL}
    assert not (fixture_ids & annotation_ids)
