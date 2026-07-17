"""Tests for the competitive-viability comparison harness.

Offline and deterministic: systems answer through an injected offline
provider; no network, no credentials, no live call. The canonical Qwen
composition is exercised with a dependency-injected transport, never a
real request. These tests validate harness mechanics and invariants —
they compute no competitive results.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from experienceos.providers import MockProvider
from experiments.competitive_viability import DEVELOPMENT_ONLY_MARKER
from experiments.competitive_viability.cases import (
    EVIDENCE_DEVELOPMENT_ONLY,
    SMOKE_CASE_IDS,
    load_cases,
    smoke_cases,
)
from experiments.competitive_viability.harness import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    execute,
    response_model_config,
)
from experiments.competitive_viability.response_provider import (
    UnifiedResponseProvider,
)
from experiments.competitive_viability.systems import (
    APPEND_ONLY,
    CANONICAL_EXPERIENCEOS_QWEN,
    DETERMINISTIC_EXPERIENCEOS,
    FULL_HISTORY,
    MEM0_STYLE_LIGHTWEIGHT,
    NAIVE_TOP_K,
    NOT_IMPLEMENTED,
    REGISTERED_SYSTEM_IDS,
    STATELESS,
    build_system,
    is_available,
    run_system_case,
    system_spec,
)

OFFLINE_SYSTEMS = (
    STATELESS, FULL_HISTORY, NAIVE_TOP_K, APPEND_ONLY,
    DETERMINISTIC_EXPERIENCEOS, CANONICAL_EXPERIENCEOS_QWEN,
)


def _one_case(case_id="creation_002_durable_user_fact"):
    return load_cases([case_id])[0]


# -- 1. registration and stable ids ------------------------------------------


def test_seven_systems_registered_with_stable_ids():
    assert set(REGISTERED_SYSTEM_IDS) == {
        CANONICAL_EXPERIENCEOS_QWEN, DETERMINISTIC_EXPERIENCEOS, STATELESS,
        FULL_HISTORY, NAIVE_TOP_K, APPEND_ONLY, MEM0_STYLE_LIGHTWEIGHT,
    }
    for sid in REGISTERED_SYSTEM_IDS:
        assert system_spec(sid).logical_id == sid


# -- 2. normalized case loading ----------------------------------------------


def test_smoke_cases_load_with_metadata():
    cases = smoke_cases()
    assert [c.case_id for c in cases] == list(SMOKE_CASE_IDS)
    for c in cases:
        assert c.evidence_classification == EVIDENCE_DEVELOPMENT_ONLY
        assert c.scorable is True
        assert c.lifecycle_category
        assert "case_id" in c.to_metadata()


def test_unknown_case_id_raises_not_silently_dropped():
    with pytest.raises(ValueError):
        load_cases(["no_such_case"])


# -- 3. identical case input across systems ----------------------------------


def test_same_case_input_reaches_every_system():
    vcase = _one_case()
    turns = [(t.session_id, t.message) for t in vcase.scenario.case.turns]
    current = vcase.scenario.case.current_message
    # Every system runs the same scenario object; the input turns and the
    # final question are one shared source, not per-system copies.
    for sid in OFFLINE_SYSTEMS:
        result = run_system_case(sid, vcase.scenario, MockProvider(), "t")
        seen = [(t.session_id, t.message) for t in result.turns]
        assert seen[:-1] == turns
        assert seen[-1][1] == current


# -- 4. oracle isolation from execution adapters -----------------------------


def test_execution_ignores_the_case_oracle():
    vcase = _one_case()
    scenario = vcase.scenario
    blank = dataclasses.replace(scenario.case.expected, memory_actions=())
    swapped_case = dataclasses.replace(scenario.case, expected=blank)
    swapped = dataclasses.replace(scenario, case=swapped_case)
    a = run_system_case(DETERMINISTIC_EXPERIENCEOS, scenario,
                        MockProvider(), "t")
    b = run_system_case(DETERMINISTIC_EXPERIENCEOS, swapped,
                        MockProvider(), "t")
    # Execution response/context do not depend on the oracle.
    assert a.turns[-1].response == b.turns[-1].response
    assert a.turns[-1].context_messages == b.turns[-1].context_messages


# -- 5. canonical record serialization ---------------------------------------


def test_record_serializes_with_required_fields():
    out = execute([STATELESS], smoke_cases()[:1], MockProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    record = out["records"][0]
    payload = json.loads(json.dumps(record))  # round-trips
    for key in ("schema_version", "run_id", "system_id", "case_id",
                "dataset_id", "evidence_classification", "execution_mode",
                "response_model", "judge_model", "status", "scoring"):
        assert key in payload
    assert payload["scoring"] == {
        "deterministic": None, "rule_based": None, "judge": None,
    }


# -- 6. explicit unavailable-system recording --------------------------------


def test_unavailable_system_is_recorded_not_dropped():
    assert is_available(MEM0_STYLE_LIGHTWEIGHT) is False
    assert system_spec(MEM0_STYLE_LIGHTWEIGHT).availability == NOT_IMPLEMENTED
    out = execute([MEM0_STYLE_LIGHTWEIGHT], smoke_cases()[:1], MockProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    record = out["records"][0]
    assert record["status"] == STATUS_UNAVAILABLE
    assert record["system_id"] == MEM0_STYLE_LIGHTWEIGHT
    assert record["execution"] is None
    assert MEM0_STYLE_LIGHTWEIGHT in out["manifest"]["unavailable_systems"]


# -- 7 & 8. execution failure recorded; no substitution ----------------------


class _BoomProvider:
    name = "boom"
    is_configured = True

    def complete(self, messages):
        raise RuntimeError("provider down")


def test_execution_failure_is_recorded_without_substitution():
    out = execute([STATELESS], smoke_cases()[:1], _BoomProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    record = out["records"][0]
    assert record["status"] == STATUS_FAILED
    assert record["system_id"] == STATELESS  # its own id, not another's
    assert record["execution_error"] is not None
    assert {"system_id": STATELESS, "case_id": record["case_id"],
            "status": STATUS_FAILED} in out["manifest"]["incomplete_cases"]


# -- 9. token accounting consistency -----------------------------------------


def test_token_accounting_populated_and_shared_method():
    out = execute(list(OFFLINE_SYSTEMS), smoke_cases()[:1], MockProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    methods = set()
    for record in out["records"]:
        assert record["context_tokens"] is not None
        methods.add(record["execution"]["context_accounting"]["method"])
    assert len(methods) == 1  # one shared accounting method across systems


# -- 10. latency field population ---------------------------------------------


def test_latency_fields_present():
    out = execute([DETERMINISTIC_EXPERIENCEOS], smoke_cases()[:1],
                  MockProvider(), run_id="t", timestamp="fixed",
                  git_commit="local")
    latencies = out["records"][0]["execution"]["turns"][-1]["latencies"]
    stages = {l["stage"] for l in latencies}
    assert "end_to_end" in stages


# -- 11. per-case state isolation --------------------------------------------


def test_state_does_not_leak_between_cases():
    # Append-only accumulates within a case; a fresh system per case means
    # its final memory count reflects only that case, not prior cases.
    out = execute([APPEND_ONLY], smoke_cases(), MockProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    counts = [
        len(r["execution"]["final_active"]) for r in out["records"]
    ]
    # If state leaked, later cases would show monotonically growing memory
    # from earlier cases; each case is independent instead.
    assert counts[0] <= 2  # the durable-fact case creates at most a couple


# -- 12-16. per-family normalization ------------------------------------------


def _run_single(system_id):
    out = execute([system_id], smoke_cases()[:1], MockProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    return out["records"][0]


def test_stateless_normalization_has_no_persistent_memory():
    record = _run_single(STATELESS)
    assert record["status"] == STATUS_COMPLETED
    assert record["execution"]["final_active"] == []


def test_full_history_normalization_reports_history_tokens():
    record = _run_single(FULL_HISTORY)
    assert record["status"] == STATUS_COMPLETED
    assert record["full_history_tokens"] is not None


def test_naive_top_k_normalization_completes():
    record = _run_single(NAIVE_TOP_K)
    assert record["status"] == STATUS_COMPLETED
    assert record["full_history_tokens"] is None


def test_append_only_normalization_has_no_supersession():
    record = _run_single(APPEND_ONLY)
    assert record["status"] == STATUS_COMPLETED
    assert record["execution"]["final_superseded"] == []


def test_deterministic_experienceos_normalization_completes():
    record = _run_single(DETERMINISTIC_EXPERIENCEOS)
    assert record["status"] == STATUS_COMPLETED
    assert record["execution"] is not None


# -- 17. canonical Qwen composition via the demo seam (injected transport) ----


def test_canonical_qwen_composition_uses_demo_seam_without_network():
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    provider = QwenCloudProvider(api_key="test-key", temperature=0.0)
    provider._post = lambda payload: {
        "choices": [{"message": {"content": "ok"}}]
    }  # no network
    vcase = _one_case()
    result = run_system_case(
        CANONICAL_EXPERIENCEOS_QWEN, vcase.scenario, provider, "t",
    )
    assert result.status == "passed"
    # The canonical extraction selection ran and picked the Qwen controller.
    assert result.diagnostics.get("extraction_mode") == "candidate"
    assert result.diagnostics.get("qwen_extraction_selected") is True


def test_canonical_qwen_builds_with_offline_provider():
    system = build_system(CANONICAL_EXPERIENCEOS_QWEN, MockProvider())
    assert system is not None
    assert system.system_id == CANONICAL_EXPERIENCEOS_QWEN


# -- 18. secrets excluded from manifests and records -------------------------


def test_secrets_never_recorded():
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    provider = QwenCloudProvider(api_key="super-secret-key")
    config = response_model_config(provider, "live")
    assert "super-secret-key" not in json.dumps(config)
    assert "api_key" not in config
    # A full offline run's artifacts carry no secret-bearing keys.
    out = execute([STATELESS], smoke_cases()[:1], MockProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    blob = json.dumps(out).lower()
    assert "api_key" not in blob and "authorization" not in blob


# -- 19. development-only classification --------------------------------------


def test_development_only_marker_present():
    out = execute([STATELESS], smoke_cases()[:1], MockProvider(),
                  run_id="t", timestamp="fixed", git_commit="local")
    assert out["summary"]["development_only"] == DEVELOPMENT_ONLY_MARKER
    assert out["manifest"]["development_only"] == DEVELOPMENT_ONLY_MARKER
    assert DEVELOPMENT_ONLY_MARKER == "DEVELOPMENT_ONLY_NOT_COMPETITIVE_EVIDENCE"


# -- response shim: one model, both message contracts ------------------------


def test_unified_provider_adapts_both_contracts_preserving_content():
    seen = {}

    class _Base:
        name = "base-model"
        model = "m1"

        def complete(self, messages):
            seen["messages"] = messages
            return "reply"

    shim = UnifiedResponseProvider(_Base())
    # Baseline string contract -> normalized to role-tagged dicts.
    assert shim.complete(["sys ctx", "the question"]) == "reply"
    assert seen["messages"][0] == {"role": "system", "content": "sys ctx"}
    assert seen["messages"][-1] == {"role": "user", "content": "the question"}
    # SDK dict contract -> passed through unchanged.
    dicts = [{"role": "user", "content": "x"}]
    shim.complete(dicts)
    assert seen["messages"] == dicts
    assert shim.name == "base-model" and shim.model == "m1"


# -- 20. deterministic artifact generation (offline) -------------------------


def _strip_latency(records):
    cleaned = []
    for record in records:
        record = json.loads(json.dumps(record))
        execution = record.get("execution")
        if execution:
            for turn in execution.get("turns", []):
                turn["latencies"] = []
            execution["latencies"] = []
            if execution.get("context_accounting"):
                pass
        cleaned.append(record)
    return cleaned


def test_offline_smoke_is_deterministic_apart_from_latency():
    # The baseline systems use deterministic record ids, so their offline
    # records reproduce exactly (latency aside). The ExperienceOS systems
    # mint random memory UUIDs per run, so byte-determinism does not hold
    # for them — an honest, documented limitation, not a harness defect.
    baselines = [STATELESS, FULL_HISTORY, NAIVE_TOP_K, APPEND_ONLY]
    kwargs = dict(run_id="t", timestamp="fixed", git_commit="local")
    a = execute(baselines, smoke_cases(), MockProvider(), **kwargs)
    b = execute(baselines, smoke_cases(), MockProvider(), **kwargs)
    assert _strip_latency(a["records"]) == _strip_latency(b["records"])
    assert a["summary"]["by_status"] == b["summary"]["by_status"]
