"""Deterministic validation of the transition-verification annotation corpus."""

import json
from pathlib import Path

import pytest

from benchmarks.annotations import transition_verification as tv

CORPUS = tv.load_corpus()
ALL = (CORPUS["historical_scored"] + CORPUS["development_fixtures"]
       + CORPUS["unresolved_candidates"])
SCORED = CORPUS["historical_scored"]
FIXTURES = CORPUS["development_fixtures"]
UNRESOLVED = CORPUS["unresolved_candidates"]


def test_corpus_validates():
    summary = tv.validate_corpus()
    assert summary["total"] == 68
    assert summary["historical_scored"] == 28
    assert summary["development_fixtures"] == 27
    assert summary["unresolved_candidates"] == 13


def test_case_ids_unique_and_well_formed():
    ids = [r["case_id"] for r in ALL]
    assert len(ids) == len(set(ids))
    for cid in ids:
        assert tv._ID_RE.match(cid), cid


def test_partitions_mechanically_separate():
    assert all(r["annotation_classification"] == "historical_scored" for r in SCORED)
    assert all(r["annotation_classification"] == "development_only" for r in FIXTURES)
    assert all(r["annotation_classification"] in ("historical_unresolved", "excluded")
               for r in UNRESOLVED)


def test_development_fixtures_never_scored():
    for r in FIXTURES:
        assert r["benchmark_scored"] is False
        assert r["development_only"] is True


def test_scored_records_have_provenance():
    for r in SCORED:
        assert r["source_paths"], r["case_id"]
        assert r["oracle_origin"] not in (None, "", "not_available")
        for p in r["source_paths"]:
            assert (tv.REPO_ROOT / p).exists(), p


def test_primary_types_in_taxonomy():
    for r in SCORED + FIXTURES:
        assert r["expected_transition"]["primary_type"] in tv.PRIMARY_TYPES


def test_supersede_targets_active_in_before_state():
    for r in SCORED + FIXTURES:
        et = r["expected_transition"]
        if et["primary_type"] == "supersede_existing":
            active = {m["memory_ref"]["logical_id"] for m in r["before_state"]
                      if m["lifecycle_state"] == "active"}
            for t in et["superseded_refs"]:
                assert t["logical_id"] in active, r["case_id"]


def test_forget_directives_expect_no_positive_creation():
    for r in SCORED + FIXTURES:
        et = r["expected_transition"]
        if et["primary_type"] == "forget_existing":
            assert et["created"] == [], r["case_id"]


def test_rejection_and_noop_expect_no_mutation():
    for r in SCORED + FIXTURES:
        et = r["expected_transition"]
        if et["primary_type"] in tv.NON_MUTATING_TYPES:
            assert not et["created"]
            assert not et["superseded_refs"]
            assert not et["forgotten_refs"]
            assert et["canonical_effect"] is False, r["case_id"]


def test_duplicate_noop_creates_nothing():
    for r in SCORED + FIXTURES:
        if r["expected_transition"]["primary_type"] in (
                "duplicate_noop", "semantic_duplicate_noop"):
            assert r["after_state"]["created_count"] == 0, r["case_id"]


def test_scoped_coexistence_preserves_existing():
    for r in SCORED + FIXTURES:
        et = r["expected_transition"]
        if et["primary_type"] == "scoped_coexistence":
            assert et["preserved_refs"], r["case_id"]
            assert not et["superseded_refs"], r["case_id"]


def test_unresolved_and_excluded_have_no_oracle_and_a_reason():
    for r in UNRESOLVED:
        assert r["expected_transition"] is None
        assert r["resolution"]["reason"].strip()
        assert r["source_paths"]


def test_forget_as_creation_case_present_with_crossref():
    # The Phase 12 forget-directive false positive is preserved as a scored
    # forget_existing case that blocks positive creation.
    rec = next(r for r in SCORED
               if r["source_case_id"] == "forgetting_003_forget_one_of_several")
    assert rec["expected_transition"]["primary_type"] == "forget_existing"
    assert rec["expected_transition"]["created"] == []
    assert "forget_as_creation_prevention" in rec["scoring_categories"]
    assert any("grounded-extraction" in p for p in rec["source_paths"])


def test_all_required_fixture_categories_covered():
    covered = {r["source_case_id"].rsplit("-", 1)[0] for r in FIXTURES}
    required = {
        "exact_duplicate", "semantic_duplicate", "current_state_replacement",
        "direct_replacement", "instead_of_replacement", "used_to_now_replacement",
        "correction", "repeated_correction", "scoped_coexistence",
        "similar_wording_different_scope", "forget_directive", "negative_forget",
        "forget_question", "memory_inspection", "broad_forget", "ambiguous_forget",
        "instruction_replacement", "temporary_exception", "historical_statement",
        "unrelated_preservation", "ambiguous_transition", "unsupported_transition",
        "hypothetical", "historical_current_state_conflict",
    }
    missing = required - covered
    assert not missing, f"missing fixture categories: {missing}"


def test_no_personal_paths_or_secrets():
    for r in ALL:
        blob = json.dumps(r, ensure_ascii=False)
        assert not tv._PERSONAL_PATH_RE.search(blob), r["case_id"]
        assert not tv._SECRET_RE.search(blob), r["case_id"]


def test_manifest_is_reproducible():
    assert tv.verify_manifest() is True


def test_manifest_records_contract_commit():
    manifest = json.loads(tv.MANIFEST_PATH.read_text())
    assert manifest["transition_contract_path"] == (
        "docs/transition_verification_contract.md")
    assert manifest["total_records"] == 68


def test_no_new_orchestration_vocabulary_in_committed_corpus():
    # New work must not introduce current-phase orchestration vocabulary.
    # References to frozen committed directory names (e.g. report-phase11)
    # are permitted cross-references and are not banned here.
    banned = ("phase 13", "phase13", "prompt 1", "prompt1", "prompt 2",
              "prompt2", "milestone")
    for name in tv.CORPUS_FILES + ("schema.json", "README.md", "audit.md"):
        text = (tv.CORPUS_ROOT / name).read_text().lower()
        for term in banned:
            assert term not in text, f"{name} contains {term!r}"
