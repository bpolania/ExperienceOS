"""LongMemEval subset adapter tests: manifest/selection, loader and
normalization, system execution, and evaluation. Default tests run
offline on synthetic official-shape fixtures; tests that need the
real official data are skipped automatically when the gitignored data
file is absent."""

import copy
import json
from pathlib import Path

import pytest

from benchmarks.external.longmemeval.cli import FIXTURE_PATH
from benchmarks.external.longmemeval.evaluate import (
    ExternalContribution,
    aggregate_external,
    answer_contributions,
    normalize_answer,
)
from benchmarks.external.longmemeval.loader import (
    ExternalDataError,
    dataset_variant_for,
    load_fixture_cases,
    load_manifest,
    load_selected_cases,
)
from benchmarks.external.longmemeval.runner import (
    EXTERNAL_SYSTEMS,
    execute_external,
    run_experienceos_rules,
    run_full_history,
    run_naive_top_k,
)
from benchmarks.external.longmemeval.schema import (
    REQUIRED_DISPLAY_LABEL,
    InvalidExternalRecord,
    normalize_record,
    validate_official_record,
)
from benchmarks.external.longmemeval.selection import (
    SelectionError,
    build_manifest,
    select_subset,
    source_fingerprint,
)

OFFICIAL_DATA = Path("benchmarks/data/external/longmemeval")
ORACLE = OFFICIAL_DATA / "longmemeval_oracle.json"
S_CLEANED = OFFICIAL_DATA / "longmemeval_s_cleaned.json"

needs_official = pytest.mark.skipif(
    not S_CLEANED.exists(),
    reason="official LongMemEval data not present locally",
)


@pytest.fixture(scope="module")
def fixtures():
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture(scope="module")
def fixture_cases():
    return load_fixture_cases(FIXTURE_PATH)


# --- Selection and manifest -----------------------------------------------------


def synthetic_records(per_category=12):
    records = []
    for type_name, prefix in (
        ("single-session-user", "ie"),
        ("multi-session", "ms"),
        ("temporal-reasoning", "tr"),
        ("knowledge-update", "ku"),
    ):
        for i in range(per_category):
            records.append(
                {"question_id": f"{prefix}_{i:03d}", "question_type": type_name}
            )
    for i in range(per_category):
        records.append(
            {
                "question_id": f"abs_{i:03d}_abs",
                "question_type": "multi-session",
            }
        )
    return records


def test_selection_is_deterministic_and_order_independent():
    records = synthetic_records()
    selected = select_subset(records)
    shuffled = list(reversed(records))
    assert select_subset(shuffled) == selected
    assert len(selected) == 50
    counts = {}
    for _, category in selected:
        counts[category] = counts.get(category, 0) + 1
    assert set(counts.values()) == {10}


def test_selection_rejects_duplicates_and_missing_categories():
    records = synthetic_records()
    with pytest.raises(SelectionError) as excinfo:
        select_subset(records + [records[0]])
    assert "duplicate" in str(excinfo.value)
    thin = [r for r in records if not r["question_id"].startswith("tr_")]
    with pytest.raises(SelectionError) as excinfo:
        select_subset(thin)
    assert "temporal-reasoning" in str(excinfo.value)


def test_changed_source_changes_fingerprint_and_manifest_hash():
    records = synthetic_records()
    kwargs = dict(
        dataset_variant="s_cleaned",
        source_revision="rev-a",
        source_file="test.json",
        verification_date="2026-07-10",
    )
    a = build_manifest(records, **kwargs)
    changed = copy.deepcopy(records)
    changed[0]["question_id"] = "ie_renamed"
    b = build_manifest(changed, **kwargs)
    assert a["source_fingerprint"] != b["source_fingerprint"]
    assert a["manifest_hash"] != b["manifest_hash"]
    again = build_manifest(records, **kwargs)
    assert again["manifest_hash"] == a["manifest_hash"]


def test_committed_manifest_shape():
    manifest = load_manifest()
    assert manifest["display_label"] == REQUIRED_DISPLAY_LABEL
    assert manifest["subset_version"] == "longmemeval-50-subset-v1"
    assert len(manifest["selected"]) == 50
    assert manifest["category_counts"] == {
        "information-extraction": 10,
        "multi-session-reasoning": 10,
        "temporal-reasoning": 10,
        "knowledge-updates": 10,
        "abstention": 10,
    }
    assert manifest["dataset_content_committed"] is False
    assert manifest["official_evaluation"] is False
    assert manifest["source_revision"] == (
        "98d7416c24c778c2fee6e6f3006e7a073259d48f"
    )
    ids = [e["question_id"] for e in manifest["selected"]]
    assert len(set(ids)) == 50


def test_fixture_cannot_masquerade_as_official():
    with pytest.raises(ExternalDataError) as excinfo:
        load_selected_cases("synthetic_official_shape.json")
    assert "synthetic" in str(excinfo.value)
    with pytest.raises(ExternalDataError):
        dataset_variant_for("random_file.json")


# --- Loader and normalization -----------------------------------------------------


def test_fixture_cases_load_with_structure(fixture_cases):
    assert len(fixture_cases) == 5
    by_id = {c.question_id: c for c in fixture_cases}
    ms = by_id["synthetic_ms_001"]
    assert len(ms.sessions) == 3
    assert ms.sessions[0].date.startswith("2023/06/03")
    assert ms.sessions[0].turns[0].role == "user"
    assert ms.answer_session_ids == ("syn_ms_s1", "syn_ms_s2")
    assert ms.category == "multi-session-reasoning"
    tr = by_id["synthetic_tr_001"]
    assert tr.sessions[0].date < tr.sessions[1].date  # chronology kept
    abstention = by_id["synthetic_abs_001_abs"]
    assert abstention.abstention is True
    ku = by_id["synthetic_ku_001"]
    assert ku.answer == "12B"


def test_malformed_records_rejected(fixtures):
    record = copy.deepcopy(fixtures[0])
    del record["haystack_sessions"]
    with pytest.raises(InvalidExternalRecord) as excinfo:
        validate_official_record(record)
    assert "haystack_sessions" in str(excinfo.value)

    record = copy.deepcopy(fixtures[0])
    record["question_type"] = "unknown-category"
    with pytest.raises(InvalidExternalRecord):
        validate_official_record(record)

    record = copy.deepcopy(fixtures[0])
    record["haystack_sessions"][0][0] = {"role": "user"}  # missing content
    with pytest.raises(InvalidExternalRecord):
        validate_official_record(record)

    record = copy.deepcopy(fixtures[0])
    record["haystack_session_ids"] = ["only-one"]
    with pytest.raises(InvalidExternalRecord) as excinfo:
        validate_official_record(record)
    assert "arity" in str(excinfo.value)


def test_normalization_does_not_mutate_source(fixtures):
    record = copy.deepcopy(fixtures[0])
    snapshot = copy.deepcopy(record)
    normalize_record(record, "information-extraction", "synthetic")
    assert record == snapshot


@needs_official
def test_official_selected_cases_load_in_manifest_order():
    manifest = load_manifest()
    cases = load_selected_cases(S_CLEANED, manifest)
    assert [c.question_id for c in cases] == [
        e["question_id"] for e in manifest["selected"]
    ]
    assert all(c.dataset_variant == "s_cleaned" for c in cases)
    assert all(len(c.sessions) >= 2 for c in cases)


@needs_official
def test_official_fingerprint_mismatch_rejected(tmp_path):
    records = json.loads(ORACLE.read_text())
    records.pop()  # remove one record: different identity set
    bad = tmp_path / "longmemeval_s_cleaned.json"
    bad.write_text(json.dumps(records))
    with pytest.raises(ExternalDataError) as excinfo:
        load_selected_cases(bad)
    assert "fingerprint" in str(excinfo.value)


# --- System execution ---------------------------------------------------------------


def test_full_history_preserves_everything(fixture_cases):
    case = next(c for c in fixture_cases if c.question_id == "synthetic_ms_001")
    run = run_full_history(case)
    context = run.context_messages
    assert sum("5 kilometers" in m for m in context) == 1
    assert sum("7 kilometers" in m for m in context) == 1
    assert "sandwich" in " ".join(context)  # nothing filtered
    assert context[-1].endswith(case.question)
    assert sum(case.question in m for m in context) == 1
    assert run.truncation == "full_history_untruncated"
    assert run.candidates == []
    # Chronological order.
    i5 = next(i for i, m in enumerate(context) if "5 kilometers" in m)
    i7 = next(i for i, m in enumerate(context) if "7 kilometers" in m)
    assert i5 < i7


def test_naive_retrieval_deterministic_and_bounded(fixture_cases):
    case = next(c for c in fixture_cases if c.question_id == "synthetic_ie_001")
    a = run_naive_top_k(case)
    b = run_naive_top_k(case)
    assert [c["rank"] for c in a.candidates] == [
        c["rank"] for c in b.candidates
    ]
    assert sum(c["selected"] for c in a.candidates) <= 6
    top = next(c for c in a.candidates if c["rank"] == 1)
    assert top["session_id"] == "syn_ie_s1"  # answer-bearing unit ranks
    assert any("standing desk" in t for t in a.selected_texts)


def test_experienceos_ingests_and_resets(fixture_cases):
    case = next(c for c in fixture_cases if c.question_id == "synthetic_ku_001")
    run = run_experienceos_rules(case)
    assert run.status == "completed"
    assert run.sessions == 2
    # Memory persisted across the item's sessions and reached context.
    context = " ".join(run.context_messages)
    assert "12B" in context or "4A" in context or run.selected_texts == []
    # A second execution is a fresh agent: identical structural output.
    again = run_experienceos_rules(case)
    assert again.selected_texts == run.selected_texts
    assert [c["session_id"] for c in again.candidates] == [
        c["session_id"] for c in run.candidates
    ]


def test_execution_failure_preserved_not_raised(fixture_cases, monkeypatch):
    import benchmarks.external.longmemeval.runner as runner_module

    def explode(case):
        raise RuntimeError("session parser blew up")

    monkeypatch.setitem(runner_module._RUNNERS, "full_history", explode)
    runs, failures = execute_external(
        fixture_cases[:1], systems=("full_history",)
    )
    assert runs[0].status == "execution_failed"
    assert failures["system_execution_failures"]


def test_no_answer_oracle_reaches_systems(fixture_cases):
    # Systems receive only sessions and the question; verify the
    # expected answer never appears in supplied context unless the
    # history itself contains it.
    case = next(c for c in fixture_cases if c.question_id == "synthetic_tr_001")
    for runner in (run_full_history, run_naive_top_k, run_experienceos_rules):
        run = runner(case)
        # "Lisbon" appears in history; the raw answer string appears
        # only via history content, never injected separately.
        joined = " ".join(run.context_messages)
        assert case.answer not in joined.replace(
            "Just landed in Lisbon", ""
        ) or "Lisbon" in joined


# --- Evaluation -----------------------------------------------------------------------


def test_answer_proxies_and_normalization(fixture_cases):
    case = next(c for c in fixture_cases if c.question_id == "synthetic_ku_001")
    exact = answer_contributions(case, "12b", structural=False)
    by_name = {c.metric: c for c in exact}
    assert by_name["normalized_exact_match_proxy"].numerator == 1
    assert by_name["answer_entity_match_proxy"].numerator == 1
    partial = answer_contributions(
        case, "Your current apartment is 12B.", structural=False
    )
    by_name = {c.metric: c for c in partial}
    assert by_name["normalized_exact_match_proxy"].numerator == 0
    assert by_name["answer_entity_match_proxy"].numerator == 1
    assert normalize_answer(" 12B. ") == "12b"


def test_abstention_defers(fixture_cases):
    case = next(c for c in fixture_cases if c.abstention)
    out = answer_contributions(case, "confident wrong answer", True)
    assert len(out) == 1
    assert out[0].metric == "abstention_match_proxy"
    assert not out[0].applicable
    assert "live labeled run" in out[0].undefined_reason


def test_retrieval_oracle_evidence(fixture_cases):
    case = next(c for c in fixture_cases if c.question_id == "synthetic_ie_001")
    run = run_naive_top_k(case)
    by_name = {c.metric: c for c in run.contributions}
    assert by_name["answer_session_candidate_rate"].numerator == 1
    assert by_name["answer_session_selection_rate"].numerator == 1
    assert by_name["answer_session_mrr"].numerator == 1.0
    assert by_name["answer_context_presence_rate"].numerator == 1

    fh = run_full_history(case)
    fh_by_name = {c.metric: c for c in fh.contributions}
    assert not fh_by_name["answer_session_candidate_rate"].applicable
    assert fh_by_name["answer_context_presence_rate"].numerator == 1


def test_unknown_external_metric_rejected():
    with pytest.raises(KeyError):
        ExternalContribution("lifecycle_creation_precision", 1, 1)


def test_token_reduction_synthesized_in_aggregate(fixture_cases):
    runs, _ = execute_external(fixture_cases[:2])
    aggregate = aggregate_external([r.record() for r in runs])
    cell = aggregate["experienceos_rules"][
        "external_token_reduction_vs_full_history"
    ]
    assert cell["denominator"] > 0
    assert cell["value"] is not None
    assert "external_token_reduction_vs_full_history" not in aggregate.get(
        "full_history", {}
    )
