"""External artifact integrity tests: layout, labels, hashes,
recomputation, separation from the custom lifecycle track, and
promotion protection. Offline (synthetic fixtures)."""

import json
import shutil

import pytest

from benchmarks.external.longmemeval.cli import FIXTURE_PATH
from benchmarks.external.longmemeval.loader import load_fixture_cases
from benchmarks.external.longmemeval.runner import (
    execute_external,
    write_external_artifacts,
)
from benchmarks.external.longmemeval.validation import (
    ExternalArtifactError,
    validate_external_artifact,
)


@pytest.fixture(scope="module")
def fixture_artifact(tmp_path_factory):
    cases = load_fixture_cases(FIXTURE_PATH)
    runs, failures = execute_external(cases)
    return write_external_artifacts(
        output_dir=str(tmp_path_factory.mktemp("lme") / "run"),
        mode="offline-fixture",
        data_file=str(FIXTURE_PATH),
        cases=cases,
        runs=runs,
        failures=failures,
    ), cases


def rebuild(tmp_path, name="run"):
    cases = load_fixture_cases(FIXTURE_PATH)
    runs, failures = execute_external(cases)
    return write_external_artifacts(
        output_dir=str(tmp_path / name),
        mode="offline-fixture",
        data_file=str(FIXTURE_PATH),
        cases=cases,
        runs=runs,
        failures=failures,
    )


def test_artifact_validates_and_is_labeled(fixture_artifact):
    path, cases = fixture_artifact
    summary = validate_external_artifact(path)
    assert summary["case_runs"] == len(cases) * 3
    assert summary["synthetic_data"] is True
    body = (path / "README.md").read_text()
    assert "LongMemEval 50-case stratified subset" in body
    assert "NOT a benchmark result" in body
    assert "GPT-4o judge was NOT used" in body
    provenance = json.loads((path / "external_provenance.json").read_text())
    assert provenance["official_evaluation"] is False
    assert provenance["proxy_evaluation"] is True
    assert provenance["synthetic_fixture_data"] is True
    assert provenance["used_real_provider"] is False


def test_digest_stable_across_rebuilds(tmp_path, fixture_artifact):
    path, _ = fixture_artifact
    first = json.loads((path / "artifact_manifest.json").read_text())
    second_path = rebuild(tmp_path)
    second = json.loads(
        (second_path / "artifact_manifest.json").read_text()
    )
    assert (
        first["normalized_result_digest"]
        == second["normalized_result_digest"]
    )


def test_tampered_metric_detected(tmp_path):
    path = rebuild(tmp_path, "tamper")
    lines = (path / "metric_contributions.jsonl").read_text().split("\n")
    record = json.loads(lines[0])
    record["numerator"] += 1
    lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    (path / "metric_contributions.jsonl").write_text("\n".join(lines))
    with pytest.raises(ExternalArtifactError) as excinfo:
        validate_external_artifact(path)
    assert "hash mismatch" in str(excinfo.value)


def test_wrong_display_label_rejected(tmp_path):
    path = rebuild(tmp_path, "label")
    manifest = json.loads((path / "artifact_manifest.json").read_text())
    manifest["display_label"] = "Official LongMemEval score"
    (path / "artifact_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2)
    )
    with pytest.raises(ExternalArtifactError) as excinfo:
        validate_external_artifact(path)
    assert "display label" in str(excinfo.value)


def test_synthetic_cannot_be_promoted_as_canonical(tmp_path):
    committed = tmp_path / "results" / "committed"
    committed.mkdir(parents=True)
    source = rebuild(tmp_path, "src")
    canonical = committed / "longmemeval-50-subset-v1"
    shutil.copytree(source, canonical)
    with pytest.raises(ExternalArtifactError) as excinfo:
        validate_external_artifact(canonical)
    assert "cannot be promoted" in str(excinfo.value)


def test_custom_lifecycle_records_rejected(tmp_path):
    path = rebuild(tmp_path, "mixing")
    lines = (path / "cases.jsonl").read_text().strip("\n").split("\n")
    record = json.loads(lines[0])
    record["question_id"] = "creation_001_explicit_scoped_preference"
    lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    body = "\n".join(lines) + "\n"
    (path / "cases.jsonl").write_text(body)
    # Fix the file hash so the mixing check itself is what fires.
    import hashlib

    manifest = json.loads((path / "artifact_manifest.json").read_text())
    manifest["files"]["cases.jsonl"]["sha256"] = hashlib.sha256(
        (path / "cases.jsonl").read_bytes()
    ).hexdigest()
    (path / "artifact_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2)
    )
    with pytest.raises(ExternalArtifactError) as excinfo:
        validate_external_artifact(path)
    assert "custom lifecycle scenario" in str(excinfo.value)


def test_incomplete_artifact_rejected(tmp_path):
    path = rebuild(tmp_path, "src2")
    incomplete = tmp_path / "run.incomplete"
    shutil.copytree(path, incomplete)
    with pytest.raises(ExternalArtifactError) as excinfo:
        validate_external_artifact(incomplete)
    assert "incomplete" in str(excinfo.value)


def test_overwrite_protection(tmp_path):
    rebuild(tmp_path, "protected")
    cases = load_fixture_cases(FIXTURE_PATH)
    runs, failures = execute_external(cases)
    with pytest.raises(FileExistsError):
        write_external_artifacts(
            output_dir=str(tmp_path / "protected"),
            mode="offline-fixture",
            data_file=str(FIXTURE_PATH),
            cases=cases,
            runs=runs,
            failures=failures,
        )


def test_jsonl_reading_survives_unicode_line_separators(tmp_path):
    # Official chat content contains U+2028/U+2029; JSONL readers must
    # split on newline only.
    path = rebuild(tmp_path, "unicode")
    cases_path = path / "cases.jsonl"
    lines = cases_path.read_text().strip("\n").split("\n")
    record = json.loads(lines[0])
    record["response"] = "line one line two line three"
    lines[0] = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    cases_path.write_text("\n".join(lines) + "\n")
    import hashlib

    manifest = json.loads((path / "artifact_manifest.json").read_text())
    manifest["files"]["cases.jsonl"]["sha256"] = hashlib.sha256(
        cases_path.read_bytes()
    ).hexdigest()
    (path / "artifact_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2)
    )
    # Parses cleanly (digest mismatch is expected and proves parsing
    # got far enough; anything JSON-decode related would raise first).
    with pytest.raises(ExternalArtifactError) as excinfo:
        validate_external_artifact(path)
    assert "digest" in str(excinfo.value)


def test_no_secrets_in_metadata(fixture_artifact):
    path, _ = fixture_artifact
    for name in (
        "external_provenance.json",
        "external_run_config.json",
        "aggregate.json",
    ):
        body = (path / name).read_text()
        assert "/Users/" not in body
        assert "api_key" not in body
