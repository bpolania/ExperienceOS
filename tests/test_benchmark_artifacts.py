"""Artifact integrity tests: layout, hashes, recomputation, safety,
normalized determinism, and corruption rejection. All offline."""

import json
import shutil

import pytest

from benchmarks.artifacts.validation import (
    ArtifactValidationError,
    validate_artifact_dir,
)
from benchmarks.artifacts.writer import normalize_for_digest, write_artifacts
from benchmarks.contract import canonical_json
from benchmarks.runner.config import QUICK_PROFILE_SCENARIOS, RunConfig
from benchmarks.runner.execute import execute_run

SMALL_SCENARIOS = (
    "creation_001_explicit_scoped_preference",
    "creation_006_paraphrased_duplicate",
    "updates_002_fact_correction",
    "retrieval_003_lexical_mismatch",
)


def small_run(tmp_path, name="run", **overrides):
    config = RunConfig(
        profile="quick",
        output_dir=str(tmp_path / name),
        scenario_ids=SMALL_SCENARIOS,
        **overrides,
    )
    output = execute_run(config)
    return write_artifacts(output)


@pytest.fixture(scope="module")
def artifact_dir(tmp_path_factory):
    return small_run(tmp_path_factory.mktemp("artifacts"))


def read_manifest(path):
    return json.loads((path / "artifact_manifest.json").read_text())


def test_required_files_and_validation(artifact_dir):
    summary = validate_artifact_dir(artifact_dir)
    assert summary["case_runs"] == len(SMALL_SCENARIOS) * 6
    assert summary["contributions"] > 0
    assert not (
        artifact_dir.parent / (artifact_dir.name + ".incomplete")
    ).exists()


def test_jsonl_ends_with_newline_and_counts_match(artifact_dir):
    manifest = read_manifest(artifact_dir)
    for name in ("cases.jsonl", "metric_contributions.jsonl"):
        body = (artifact_dir / name).read_text()
        assert body.endswith("\n")
        assert manifest["files"][name]["records"] == len(
            body.strip().splitlines()
        )


def test_failures_file_explicit_even_when_empty(artifact_dir):
    failures = json.loads((artifact_dir / "failures.json").read_text())
    assert failures["system_execution_failures"] == []
    assert failures["evaluator_failures"] == []
    assert "skipped_cases" in failures


def test_normalized_digest_stable_across_runs(tmp_path):
    a = small_run(tmp_path, "a")
    b = small_run(tmp_path, "b")
    assert (
        read_manifest(a)["normalized_result_digest"]
        == read_manifest(b)["normalized_result_digest"]
    )


def test_normalization_strips_only_nondeterministic_fields():
    data = {
        "memory_id": "12345678-1234-1234-1234-123456789012",
        "timestamp": "2026-07-10T05:00:00+00:00",
        "latencies": [{"stage": "end_to_end", "milliseconds": 12.5}],
        "rejected_reason": "duplicate_of_active",
        "response": "kept verbatim",
    }
    normalized = normalize_for_digest(data)
    assert normalized["memory_id"] == "mem-0000"
    assert normalized["timestamp"] == "<timestamp>"
    assert normalized["latencies"] == []
    assert normalized["rejected_reason"] == "duplicate_of_active"
    assert normalized["response"] == "kept verbatim"


@pytest.mark.parametrize(
    "mutation,field",
    [
        (lambda r: r["evaluation"]["contributions"][0].update(numerator=99),
         "metric numerator"),
        (lambda r: r["case"]["turns"][-1].update(response="changed"),
         "response text"),
    ],
)
def test_behavioral_changes_change_digest(tmp_path, mutation, field):
    from benchmarks.artifacts.writer import normalized_digest

    path = small_run(tmp_path, f"mut-{field.split()[0]}")
    cases = [
        json.loads(line)
        for line in (path / "cases.jsonl").read_text().strip().splitlines()
    ]
    aggregate = json.loads((path / "aggregate.json").read_text())
    original = normalized_digest(cases, aggregate)
    target = next(
        r for r in cases if r["evaluation"]["contributions"]
        and r["case"]["turns"]
    )
    mutation(target)
    assert normalized_digest(cases, aggregate) != original


def test_candidate_order_change_changes_digest(tmp_path):
    from benchmarks.artifacts.writer import normalized_digest

    path = small_run(tmp_path, "order")
    cases = [
        json.loads(line)
        for line in (path / "cases.jsonl").read_text().strip().splitlines()
    ]
    aggregate = json.loads((path / "aggregate.json").read_text())
    original = normalized_digest(cases, aggregate)
    target = next(
        r
        for r in cases
        if len(r["case"]["turns"][-1]["candidates"]) >= 2
    )
    target["case"]["turns"][-1]["candidates"].reverse()
    assert normalized_digest(cases, aggregate) != original


def test_hash_tamper_detected(tmp_path):
    path = small_run(tmp_path, "tamper")
    body = (path / "aggregate.json").read_text()
    (path / "aggregate.json").write_text(
        body.replace('"profile": "quick"', '"profile": "hacked"')
    )
    with pytest.raises(ArtifactValidationError) as excinfo:
        validate_artifact_dir(path)
    assert "hash mismatch" in str(excinfo.value)


def test_corrupted_jsonl_rejected(tmp_path):
    path = small_run(tmp_path, "corrupt")
    cases_path = path / "cases.jsonl"
    cases_path.write_text(cases_path.read_text() + "{not json\n")
    with pytest.raises(ArtifactValidationError):
        validate_artifact_dir(path)


def test_aggregate_tamper_fails_recomputation(tmp_path):
    path = small_run(tmp_path, "recompute")
    aggregate = json.loads((path / "aggregate.json").read_text())
    system = next(iter(aggregate["metrics"]))
    name = next(iter(aggregate["metrics"][system]))
    aggregate["metrics"][system][name]["numerator"] += 1
    (path / "aggregate.json").write_text(
        json.dumps(aggregate, sort_keys=True, indent=2) + "\n"
    )
    manifest = read_manifest(path)
    import hashlib

    manifest["files"]["aggregate.json"]["sha256"] = hashlib.sha256(
        (path / "aggregate.json").read_bytes()
    ).hexdigest()
    (path / "artifact_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    with pytest.raises(ArtifactValidationError) as excinfo:
        validate_artifact_dir(path)
    assert "recomputation" in str(excinfo.value) or "digest" in str(
        excinfo.value
    )


def test_missing_file_rejected(tmp_path):
    path = small_run(tmp_path, "missing")
    (path / "failures.json").unlink()
    with pytest.raises(ArtifactValidationError) as excinfo:
        validate_artifact_dir(path)
    assert "missing required" in str(excinfo.value)


def test_incomplete_canonical_artifact_rejected(tmp_path):
    committed = tmp_path / "committed"
    committed.mkdir()
    path = small_run(tmp_path, "src")
    incomplete = committed / "run.incomplete"
    shutil.copytree(path, incomplete)
    with pytest.raises(ArtifactValidationError) as excinfo:
        validate_artifact_dir(incomplete)
    assert "incomplete" in str(excinfo.value)


def test_interrupted_write_leaves_only_incomplete_dir(tmp_path, monkeypatch):
    import benchmarks.artifacts.writer as writer_module

    def explode(path):
        raise RuntimeError("disk gremlin")

    config = RunConfig(
        profile="quick",
        output_dir=str(tmp_path / "run"),
        scenario_ids=SMALL_SCENARIOS[:1],
    )
    output = execute_run(config)
    monkeypatch.setattr(writer_module, "_file_sha256", explode)
    with pytest.raises(RuntimeError):
        write_artifacts(output)
    assert not (tmp_path / "run").exists()
    assert (tmp_path / "run.incomplete").exists()  # clearly marked


def test_artifact_readme_states_boundaries(artifact_dir):
    body = (artifact_dir / "README.md").read_text()
    assert "NOT a real-GGUF score" in body
    assert "not" in body and "LongMemEval" in body
    assert "no final comparative interpretation" in body


def test_no_personal_paths_or_secrets_in_artifacts(artifact_dir):
    for name in (
        "run_config.json",
        "provenance.json",
        "cases.jsonl",
        "aggregate.json",
    ):
        body = (artifact_dir / name).read_text()
        for marker in ("/Users/", "/home/", "api_key", "sk-"):
            assert marker not in body, f"{name} contains {marker}"


def test_serialization_is_canonical(artifact_dir):
    aggregate = json.loads((artifact_dir / "aggregate.json").read_text())
    line = (
        (artifact_dir / "cases.jsonl").read_text().splitlines()[0]
    )
    assert canonical_json(json.loads(line)) == line
    assert list(aggregate["metrics"].keys()) == sorted(
        aggregate["metrics"].keys()
    )
