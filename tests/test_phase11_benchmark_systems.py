"""Phase 11 Prompt 7: benchmark system registration and configuration."""

import pytest

from benchmarks.adapters.factory import ADAPTER_SYSTEM_IDS, create_system
from benchmarks.contract import KNOWN_SYSTEM_IDS, SystemId
from benchmarks.phase11 import PHASE11_SYSTEMS

PHASE11_IDS = (
    "experienceos_hybrid_full_v2_reference",
    "experienceos_embedding_only_v1",
    "experienceos_fused_retrieval_v1",
    "experienceos_gate_shadow_v1",
)


def test_phase11_system_ids_registered():
    assert PHASE11_SYSTEMS == PHASE11_IDS
    for system_id in PHASE11_IDS:
        assert system_id in KNOWN_SYSTEM_IDS
        assert system_id in ADAPTER_SYSTEM_IDS


def test_historical_system_ids_unchanged():
    assert SystemId.EXPERIENCEOS_RULES == "experienceos_rules"
    assert SystemId.EXPERIENCEOS_LOCAL == "experienceos_local"
    assert SystemId.EXPERIENCEOS_HYBRID_FULL_V2 == (
        "experienceos_hybrid_full_v2"
    )
    assert SystemId.NAIVE_TOP_K == "naive_top_k"


def test_reference_uses_no_embeddings_cache_fusion_or_gate():
    adapter = create_system("experienceos_hybrid_full_v2_reference")

    class _Case:
        selection_k = 3
        context_budget = 400
        scenario_id = "probe"
        user_id = "u1"

    kwargs = adapter._retrieval_kwargs(_Case())
    assert kwargs == {}  # exact Phase 9 strategy construction


def test_embedding_only_configuration():
    adapter = create_system("experienceos_embedding_only_v1")
    kwargs = adapter._retrieval_kwargs(object())
    assert kwargs["semantic_mode"] == "semantic_only"
    generator = kwargs["semantic_generator"]
    assert generator.provider.provider_id == "deterministic"
    assert generator.provider.model_id == "stable-feature-hash-v1"
    assert generator.relevance_floor == 0.30
    assert "fusion_profile" not in kwargs
    assert "memory_gate" not in kwargs


def test_fused_configuration():
    adapter = create_system("experienceos_fused_retrieval_v1")
    kwargs = adapter._retrieval_kwargs(object())
    assert kwargs["semantic_mode"] == "fused"
    assert kwargs["fusion_profile"] == "full_fusion"
    assert "memory_gate" not in kwargs


def test_gate_shadow_configuration_matches_fused_plus_gate():
    adapter = create_system("experienceos_gate_shadow_v1")
    adapter._clear()
    kwargs = adapter._retrieval_kwargs(object())
    assert kwargs["semantic_mode"] == "fused"
    assert kwargs["fusion_profile"] == "full_fusion"
    gate = kwargs["memory_gate"]
    assert gate.controller_id == "gate_shadow_heuristic-1"
    assert gate.counters["gate_affected_selection"] == 0


def test_counting_gate_cannot_report_affected_selection():
    """The counter is structurally never incremented: proposals are
    shadow-only and the wrapper has no code path that changes it."""
    import inspect

    from benchmarks.adapters.experienceos_phase11 import CountingShadowGate

    source = inspect.getsource(CountingShadowGate.evaluate)
    assert "gate_affected_selection" not in source


def test_phase11_lifecycle_smoke_zero_failures():
    from benchmarks.runner.config import RunConfig
    from benchmarks.runner.execute import execute_run

    config = RunConfig(
        profile="full-offline",
        output_dir="/tmp/unused",
        run_id="phase11-test-smoke",
        systems=PHASE11_IDS,
        scenario_ids=("retrieval_003_lexical_mismatch",),
    )
    output = execute_run(config)
    assert not output.failures["system_execution_failures"]
    by_system = {
        run.result.system_id: run.result.diagnostics
        for run in output.case_runs
    }
    reference = by_system["experienceos_hybrid_full_v2_reference"]
    assert reference["phase11_role"] == "reference"
    assert "semantic_retrieval" not in reference.get("retrieval_v2", {})
    fused = by_system["experienceos_fused_retrieval_v1"]
    assert fused["retrieval_v2"]["semantic_retrieval"]["mode"] == "fused"
    gate = by_system["experienceos_gate_shadow_v1"]
    assert gate["gate_shadow_v1"]["gate_affected_selection"] == 0


def test_external_runner_dispatch_registered():
    from benchmarks.external.longmemeval.runner import _RUNNERS

    for system_id in PHASE11_IDS:
        assert system_id in _RUNNERS


def test_v2_systems_still_construct_identically():
    """The `_retrieval_kwargs` seam must stay empty for every earlier
    system so Phase 9 configurations are untouched."""
    for system_id in (
        "experienceos_local_v2", "experienceos_hybrid_full_v2",
    ):
        adapter = create_system(system_id)
        assert adapter._retrieval_kwargs(object()) == {}
