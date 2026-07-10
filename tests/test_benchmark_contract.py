"""Phase 8 Prompt 1 benchmark-contract tests.

These tests pin the measurement contract: schemas, validation,
deterministic serialization, manifest hashing, metric definitions,
provenance sanitization, and repository hygiene. They require no
network, no credentials, no local model, and no optional dependency.
"""

import json
from pathlib import Path

import pytest

from benchmarks.contract import (
    METRIC_DEFINITIONS,
    CaseResult,
    CaseStatus,
    ContextAccounting,
    EvaluationMode,
    InvalidBenchmarkCase,
    MemorySnapshotEntry,
    ProposalRecord,
    RejectedActionRecord,
    RunProvenance,
    TurnEvidence,
    UnsafeProvenance,
    assert_provenance_safe,
    canonical_json,
    case_from_dict,
    manifest_hash,
    metric,
    percentile,
    ratio,
    safe_model_name,
    validate_case_result,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "benchmarks" / "fixtures" / "contract"

VALID_FIXTURES = (
    "create_case.json",
    "update_case.json",
    "forget_case.json",
    "abstention_case.json",
)


def load_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


# --- Case contract -----------------------------------------------------------


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_valid_fixture_loads(name):
    case = case_from_dict(load_fixture(name))
    assert case.scenario_id.strip()
    assert case.schema_version == "1"
    assert case.evaluation_mode in ("deterministic", "model_scored")


def test_malformed_fixture_fails_with_useful_error():
    with pytest.raises(InvalidBenchmarkCase) as excinfo:
        case_from_dict(load_fixture("malformed_case.json"))
    # The first failure (empty scenario_id) is named in the message.
    assert "scenario_id" in str(excinfo.value)


def test_unknown_category_rejected_with_named_field():
    data = load_fixture("create_case.json")
    data["category"] = "not-a-real-category"
    with pytest.raises(InvalidBenchmarkCase) as excinfo:
        case_from_dict(data)
    assert "category" in str(excinfo.value)
    assert "fixture-create-001" in str(excinfo.value)


def test_tags_must_be_nonempty_strings():
    data = load_fixture("create_case.json")
    data["tags"] = ["travel", ""]
    with pytest.raises(InvalidBenchmarkCase) as excinfo:
        case_from_dict(data)
    assert "tags" in str(excinfo.value)


def test_turn_ordering_is_list_order():
    case = case_from_dict(load_fixture("forget_case.json"))
    messages = [t.message for t in case.turns]
    assert messages == [
        "I prefer aisle seats for work trips.",
        "I prefer morning flights for work trips.",
        "Forget that I prefer morning flights.",
    ]
    # Round-trips deterministically through the payload.
    assert [
        t["message"] for t in case.to_payload()["turns"]
    ] == messages


def test_logical_memory_reference_must_be_resolvable():
    data = load_fixture("create_case.json")
    data["expected"]["active"] = [
        {"logical_id": "dangling", "match_terms": [], "memory_id": None}
    ]
    with pytest.raises(InvalidBenchmarkCase) as excinfo:
        case_from_dict(data)
    assert "resolvable" in str(excinfo.value)
    assert "dangling" in str(excinfo.value)


def test_supersede_expectation_requires_target():
    data = load_fixture("update_case.json")
    data["expected"]["memory_actions"][0]["target"] = None
    with pytest.raises(InvalidBenchmarkCase) as excinfo:
        case_from_dict(data)
    assert "target" in str(excinfo.value)


def test_deterministic_and_model_scored_are_distinguishable():
    deterministic = case_from_dict(load_fixture("create_case.json"))
    scored = case_from_dict(load_fixture("abstention_case.json"))
    assert deterministic.evaluation_mode == EvaluationMode.DETERMINISTIC
    assert scored.evaluation_mode == EvaluationMode.MODEL_SCORED
    assert scored.requires_provider is True
    assert deterministic.requires_provider is False


def test_invalid_evaluation_mode_rejected():
    data = load_fixture("create_case.json")
    data["evaluation_mode"] = "vibes"
    with pytest.raises(InvalidBenchmarkCase):
        case_from_dict(data)


# --- Result contract ---------------------------------------------------------


def make_result(**overrides):
    defaults = dict(
        scenario_id="fixture-create-001",
        system_id="experienceos_rules",
        run_id="run-1",
        suite_version="1",
        status=CaseStatus.PASSED,
    )
    defaults.update(overrides)
    return CaseResult(**defaults)


def test_result_serializes_to_json_compatible_data():
    result = make_result(
        turns=[
            TurnEvidence(
                turn_index=0,
                session_id="session-1",
                message="I prefer aisle seats for work trips.",
                proposals=(
                    ProposalRecord(
                        action="create",
                        kind="preference",
                        text="Prefers aisle seats for work trips.",
                        confidence=1.0,
                        decision_source="rule_based",
                    ),
                ),
            )
        ],
        context_accounting=ContextAccounting(
            method="approximation",
            total_context_tokens=120,
            memory_context_tokens=30,
            total_context_chars=480,
            memory_context_chars=120,
            selected_memory_count=1,
            candidate_memory_count=1,
            context_budget=4,
        ),
    )
    payload = result.to_payload()
    json.dumps(payload)  # must not raise
    assert payload["schema_version"] == "1"
    assert payload["turns"][0]["proposals"][0]["decision_source"] == (
        "rule_based"
    )


def test_result_supports_pass_fail_skip_partial():
    validate_case_result(make_result(status=CaseStatus.PASSED))
    validate_case_result(
        make_result(status=CaseStatus.FAILED, failure_reason="constraint")
    )
    validate_case_result(
        make_result(
            status=CaseStatus.SKIPPED, skip_reason="requires_local_model"
        )
    )
    validate_case_result(
        make_result(
            status=CaseStatus.PARTIAL, failure_reason="provider_error"
        )
    )
    with pytest.raises(ValueError):
        validate_case_result(make_result(status="unknown"))
    with pytest.raises(ValueError):
        validate_case_result(make_result(status=CaseStatus.SKIPPED))
    with pytest.raises(ValueError):
        validate_case_result(make_result(status=CaseStatus.PARTIAL))


def test_partial_failure_preserves_earlier_evidence():
    turn = TurnEvidence(
        turn_index=0,
        session_id="session-1",
        message="I prefer aisle seats.",
        proposals=(ProposalRecord(action="create", text="Prefers aisle."),),
    )
    result = make_result(
        status=CaseStatus.PARTIAL,
        failure_reason="provider_error: timeout",
        turns=[turn],
    )
    payload = result.to_payload()
    assert payload["failure_reason"].startswith("provider_error")
    assert payload["turns"][0]["proposals"]  # evidence survived


def test_rejected_proposal_is_separate_from_applied_and_not_corruption():
    turn = TurnEvidence(
        turn_index=1,
        session_id="session-1",
        message="Plan a trip.",
        proposals=(
            ProposalRecord(
                action="create",
                text="Aisle seats are preferred.",
                decision_source="local_model",
            ),
        ),
        rejected_actions=(
            RejectedActionRecord(
                action="create",
                rejected_reason="duplicate_of_active",
                text="Aisle seats are preferred.",
            ),
        ),
        applied_actions=(),
    )
    result = make_result(
        status=CaseStatus.PASSED,
        turns=[turn],
        final_active=[
            MemorySnapshotEntry(
                memory_id="m1",
                kind="preference",
                text="Aisle seats are preferred.",
                status="active",
            )
        ],
    )
    payload = result.to_payload()
    # Proposal evidence survives even though nothing was applied...
    assert payload["turns"][0]["proposals"]
    assert payload["turns"][0]["rejected_actions"][0]["rejected_reason"] == (
        "duplicate_of_active"
    )
    assert payload["turns"][0]["applied_actions"] == []
    # ...and the final state remains clean: containment, not corruption.
    assert len(payload["final_active"]) == 1
    validate_case_result(result)


def test_context_accounting_method_validated():
    result = make_result(
        context_accounting=ContextAccounting(
            method="guesswork",
            total_context_tokens=None,
            memory_context_tokens=None,
            total_context_chars=0,
            memory_context_chars=0,
            selected_memory_count=0,
            candidate_memory_count=0,
            context_budget=4,
        )
    )
    with pytest.raises(ValueError) as excinfo:
        validate_case_result(result)
    assert "guesswork" in str(excinfo.value)


# --- Provenance --------------------------------------------------------------


def make_provenance(**overrides):
    defaults = dict(
        run_id="run-1",
        repository_commit="e0ce79c",
        working_tree_clean=True,
        suite_version="1",
        manifest_version="1",
        manifest_hash="abc123",
        run_timestamp_utc="2026-07-10T00:00:00+00:00",
        provider_name="mock",
        response_model="mock",
        memory_policy="rule_based",
        storage_mode="in_memory",
        retrieval_description="deterministic keyword ranking",
        context_budget=4,
        selection_k=4,
        temperature=0.0,
        max_output_tokens=None,
        seed=7,
        retry_policy="none",
        platform="darwin-arm64",
        python_version="3.14.3",
    )
    defaults.update(overrides)
    return RunProvenance(**defaults)


def test_model_provenance_stores_safe_basename_only():
    full = "/Users/someone/.cache/experienceos/models/qwen2.5-0.5b.gguf"
    assert safe_model_name(full) == "qwen2.5-0.5b.gguf"
    assert safe_model_name(None) is None
    provenance = make_provenance(local_model_name=safe_model_name(full))
    assert_provenance_safe(provenance)  # must not raise


def test_provenance_rejects_personal_absolute_paths():
    provenance = make_provenance(
        local_model_name="/Users/someone/.cache/model.gguf"
    )
    with pytest.raises(UnsafeProvenance):
        assert_provenance_safe(provenance)


def test_provenance_serializes_json_compatible():
    payload = make_provenance().to_payload()
    json.dumps(payload)
    assert payload["schema_version"] == "1"
    assert payload["used_mock"] is True


# --- Serialization and manifest hashing --------------------------------------


def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_manifest_hash_deterministic_for_equivalent_content():
    case = case_from_dict(load_fixture("create_case.json"))
    again = case_from_dict(load_fixture("create_case.json"))
    assert manifest_hash([case.to_payload()]) == manifest_hash(
        [again.to_payload()]
    )


def test_manifest_hash_changes_when_content_changes():
    data = load_fixture("create_case.json")
    original = case_from_dict(data).to_payload()
    data["current_message"] = "I prefer window seats for work trips."
    changed = case_from_dict(data).to_payload()
    assert manifest_hash([original]) != manifest_hash([changed])


def test_manifest_hash_is_order_sensitive():
    one = case_from_dict(load_fixture("create_case.json")).to_payload()
    two = case_from_dict(load_fixture("forget_case.json")).to_payload()
    assert manifest_hash([one, two]) != manifest_hash([two, one])


def test_case_payload_serialization_is_stable():
    case = case_from_dict(load_fixture("update_case.json"))
    assert canonical_json(case.to_payload()) == canonical_json(
        case.to_payload()
    )


# --- Metrics -----------------------------------------------------------------


def test_every_metric_exposes_numerator_and_denominator():
    assert len(METRIC_DEFINITIONS) >= 40
    for definition in METRIC_DEFINITIONS:
        assert definition.name.strip()
        assert definition.numerator.strip()
        assert definition.denominator.strip()
        assert definition.zero_denominator == "undefined"


def test_metric_names_are_unique_and_lookup_works():
    names = [m.name for m in METRIC_DEFINITIONS]
    assert len(names) == len(set(names))
    leakage = metric("stale_context_leakage_rate")
    assert "context actually supplied" in leakage.numerator or (
        "context" in leakage.description
    )
    with pytest.raises(KeyError):
        metric("composite_awesomeness_score")


def test_zero_denominator_is_undefined_not_a_number():
    assert ratio(0, 0) is None
    assert ratio(5, 0) is None
    assert ratio(1, 2) == 0.5


def test_percentile_is_deterministic_nearest_rank():
    samples = [50.0, 10.0, 40.0, 30.0, 20.0]
    assert percentile(samples, 50) == 30.0
    assert percentile(samples, 95) == 50.0
    assert percentile(samples, 100) == 50.0
    assert percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile(samples, 0)


# --- Repository hygiene ------------------------------------------------------


def test_gguf_files_are_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert "*.gguf" in gitignore.splitlines()


def test_fixtures_and_contract_docs_contain_no_personal_paths():
    paths = list(FIXTURE_DIR.glob("*.json"))
    paths.append(REPO_ROOT / "docs" / "benchmark_contract.md")
    assert paths
    for path in paths:
        body = path.read_text()
        for marker in ("/Users/", "/home/", "\\Users\\"):
            assert marker not in body, f"{path.name} contains {marker!r}"
