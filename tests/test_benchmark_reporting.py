"""Benchmark reporting tests: extraction, tables, failures, claims,
validation, determinism, and safety. All offline; sources are the two
committed canonical artifacts."""

import json
import shutil
from pathlib import Path

import pytest

from benchmarks.reporting.build import (
    build_claims,
    build_external_failures,
    build_lifecycle_failures,
    build_report_data,
    format_cell,
)
from benchmarks.reporting.load import (
    ReportSourceError,
    external_cell,
    lifecycle_cell,
    load_sources,
    load_spec,
    report_data_digest,
)
from benchmarks.reporting.render import (
    render_csvs,
    render_markdown,
    render_readme_section,
)
from benchmarks.reporting.validation import (
    ReportValidationError,
    validate_claims_text,
    validate_report,
)

REPORT_DIR = Path("benchmarks/results/committed/report-v1")

needs_report = pytest.mark.skipif(
    not REPORT_DIR.exists(),
    reason="generated report artifact not present",
)


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def sources(spec):
    return load_sources(spec)


@pytest.fixture(scope="module")
def data(spec, sources):
    return build_report_data(spec, sources, "test-commit", True)


# --- Extraction ---------------------------------------------------------------


def test_sources_load_with_digest_verification(sources):
    assert sources["lifecycle"]["digest"].startswith("8b0e245d")
    assert sources["external"]["digest"].startswith("2b3e2000")
    assert len(sources["lifecycle"]["cases"]) == 240
    assert len(sources["external"]["cases"]) == 150


def test_digest_mismatch_rejected(spec):
    import copy

    broken = copy.deepcopy(spec)
    broken["sources"]["lifecycle"]["required_digest"] = "0" * 64
    with pytest.raises(ReportSourceError) as excinfo:
        load_sources(broken)
    assert "digest" in str(excinfo.value)


def test_metric_lookup_and_unknown_rejection(sources):
    cell = lifecycle_cell(sources, "experienceos_rules", "recall_at_k")
    assert cell["denominator"] == 17
    with pytest.raises(KeyError):
        lifecycle_cell(sources, "experienceos_rules", "made_up_metric")
    ext = external_cell(
        sources, "naive_top_k", "answer_session_selection_rate"
    )
    assert ext["denominator"] == 50
    with pytest.raises(KeyError):
        external_cell(sources, "naive_top_k", "recall_at_k")


def test_undefined_formatting():
    assert format_cell(
        {"numerator": 0, "denominator": 0, "undefined_count": 3}
    ).startswith("N/A")
    assert "0%" not in format_cell(
        {"numerator": 0, "denominator": 0, "undefined_count": 0}
    )
    display = format_cell({"numerator": 3, "denominator": 4})
    assert display == "3/4 (75.0%)"


# --- Tables --------------------------------------------------------------------


def test_lifecycle_tables_match_source(data, sources):
    for table in data["lifecycle_tables"].values():
        for row in table:
            for system, cell in row["cells"].items():
                stored = sources["lifecycle"]["aggregate"]["metrics"].get(
                    system, {}
                ).get(row["metric"])
                if stored:
                    assert cell["numerator"] == stored["numerator"]
                    assert cell["denominator"] == stored["denominator"]
                if cell["denominator"]:
                    assert "%" in cell["display"]
                else:
                    assert cell["display"].startswith("N/A")


def test_external_tables_labeled_and_separate(data):
    metrics = {row["metric"] for row in data["external_tables"]["headline"]}
    assert "answer_session_selection_rate" in metrics
    assert "recall_at_k" not in metrics  # lifecycle metrics never leak in
    assert data["sources"]["external"]["display_label"] == (
        "LongMemEval 50-case stratified subset"
    )
    assert "scripted" in data["flags"]["lifecycle_local_mode"]


def test_context_stats_derived_from_cases(data):
    stats = data["lifecycle_context_stats"]
    assert stats["stateless"]["avg_memory_context_tokens"] == 0.0
    assert (
        stats["full_history"]["avg_total_context_tokens"]
        > stats["stateless"]["avg_total_context_tokens"]
    )
    ext = data["external_context_stats"]
    assert ext["full_history"]["avg_total_context_tokens"] > (
        ext["experienceos_rules"]["avg_total_context_tokens"]
    )


def test_csvs_render_with_denominators(data):
    files = render_csvs(data)
    assert set(files) == {
        "lifecycle_headline.csv",
        "lifecycle_by_category.csv",
        "leakage_comparison.csv",
        "context_efficiency.csv",
        "local_policy_containment.csv",
        "longmemeval_subset_headline.csv",
        "longmemeval_by_category.csv",
        "failure_analysis.csv",
    }
    header = files["lifecycle_headline.csv"].splitlines()[0]
    for column in ("numerator", "denominator", "source_digest"):
        assert column in header


# --- Failure selection ------------------------------------------------------------


def test_failure_selection_is_deterministic(spec, sources):
    a = build_lifecycle_failures(spec, sources)
    b = build_lifecycle_failures(spec, sources)
    assert a == b
    assert any(e["system"].startswith("experienceos") for e in a)
    rules = {e["rule"] for e in a}
    assert "first failed case per system" in rules
    assert any("containment" in r for r in rules)
    assert any("deferred" in r for r in rules)


def test_external_failures_include_required_patterns(spec, sources):
    examples = build_external_failures(spec, sources)
    rules = {e["rule"] for e in examples}
    assert any("missed answer-bearing" in r for r in rules)
    assert any("context advantage" in r for r in rules)
    assert any("abstention" in r for r in rules)
    # No full official histories: notes and IDs only.
    for example in examples:
        assert len(json.dumps(example)) < 2000


# --- Claims -------------------------------------------------------------------------


def test_claims_are_condition_gated(data):
    claims = data["claims"]
    emitted_ids = {c["id"] for c in claims["emitted"]}
    withheld_ids = {c["id"] for c in claims["withheld"]}
    # Honest withholding: stale/forgotten exclusion failed their gates.
    assert "stale-exclusion" in withheld_ids
    assert "forgotten-exclusion" in withheld_ids
    assert "lifecycle-context-reduction" in emitted_ids
    assert "local-containment" in emitted_ids
    for claim in claims["emitted"]:
        assert claim["condition"]
        assert "/" in claim["text"] or "%" in claim["text"]


def test_forbidden_wording_rejected():
    for phrase in (
        "This is state of the art.",
        "the best memory system available",
        "guaranteed cost savings",
        "zero leakage",
        "an official LongMemEval score of 61",
        "production-ready performance",
    ):
        with pytest.raises(ReportValidationError):
            validate_claims_text(phrase)
    validate_claims_text(
        "not an official LongMemEval score; scripted-plus-fallback"
    )


def test_local_claim_carries_scripted_warning(data):
    claim = next(
        c for c in data["claims"]["emitted"] if c["id"] == "local-containment"
    )
    assert "scripted" in claim["text"]
    assert "real-GGUF" in claim["text"]


def test_external_claims_carry_subset_and_proxy_scope(data):
    for claim in data["claims"]["emitted"]:
        if claim["id"].startswith("external"):
            assert "LongMemEval 50-case stratified subset" in claim["text"]


# --- Rendering and generated-report validation ---------------------------------------


def test_markdown_contains_required_boundaries(data, spec):
    markdown = render_markdown(data, spec)
    for required in (
        "LongMemEval 50-case stratified subset",
        "not an official LongMemEval score",
        "scripted-plus-fallback",
        "## 14. Limitations",
        "## 15. Reproduction",
        "N/A",
    ):
        assert required in markdown
    validate_claims_text(markdown)


def test_readme_section_from_report_data(data, spec):
    section = render_readme_section(data, spec["systems"]["display"])
    assert "docs/benchmark_report.md" in section
    assert "not a real-GGUF result" in section
    assert "not an official LongMemEval score" in section
    # every rate in the table carries n/d
    for line in section.splitlines():
        if line.startswith("| Old-value") or line.startswith("| Answer-"):
            assert "/" in line


@needs_report
def test_generated_report_validates():
    summary = validate_report(REPORT_DIR)
    assert summary["report_data_digest"]


@needs_report
def test_edited_number_detected(tmp_path):
    copy_dir = tmp_path / "report-v1"
    shutil.copytree(REPORT_DIR, copy_dir)
    data_path = copy_dir / "report_data.json"
    body = data_path.read_text()
    data = json.loads(body)
    data["lifecycle_tables"]["correctness"][0]["cells"][
        "experienceos_rules"
    ]["numerator"] += 1
    data_path.write_text(json.dumps(data, sort_keys=True, indent=2))
    with pytest.raises(ReportValidationError):
        validate_report(copy_dir)


@needs_report
def test_edited_csv_detected(tmp_path):
    copy_dir = tmp_path / "report-v1"
    shutil.copytree(REPORT_DIR, copy_dir)
    csv_path = copy_dir / "lifecycle_headline.csv"
    csv_path.write_text(csv_path.read_text().replace("10/11", "11/11"))
    with pytest.raises(ReportValidationError) as excinfo:
        validate_report(copy_dir)
    assert "hash mismatch" in str(excinfo.value)


@needs_report
def test_incomplete_report_rejected(tmp_path):
    incomplete = tmp_path / "report-v1.incomplete"
    shutil.copytree(REPORT_DIR, incomplete)
    with pytest.raises(ReportValidationError):
        validate_report(incomplete)


# --- Determinism ------------------------------------------------------------------


def test_report_data_digest_deterministic(spec, sources):
    a = build_report_data(spec, sources, "commit-x", True)
    b = build_report_data(spec, sources, "commit-x", True)
    assert report_data_digest(a) == report_data_digest(b)
    # Behavioral changes change the digest.
    b["lifecycle_tables"]["correctness"][0]["cells"]["stateless"][
        "numerator"
    ] += 1
    assert report_data_digest(a) != report_data_digest(b)


def test_no_personal_paths_in_report_data(data):
    body = json.dumps(data)
    for marker in ("/Users/", "/home/"):
        assert marker not in body
