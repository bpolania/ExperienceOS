"""Render-level tests for the transition dashboard.

Proves the dashboard renders committed transition evidence honestly —
candidate-only, gate 1 failed, gate 6 inconclusive — that projected and
applied state are never conflated, that adopted is offered as the
canonical default (its per-request authorization coming from the bounded
runtime authority), and that rendering mutates nothing.
"""

import json
from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from demo import transition_diagnostics as td  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "benchmarks/results/committed/report-transition-verification"

ADOPTED = "Adopted (canonical, deterministic lifecycle)"
DISABLED = "Disabled (observe nothing)"
SHADOW = "Shadow (observe, non-mutating)"
CANDIDATE = "Candidate (full path, non-mutating)"
VERIFY_ONLY = "Verify-only (check planner actions)"
DURABLE = "I prefer aisle seats for short work trips."
UPDATE = "I now prefer window seats for short work trips."


def _app():
    at = AppTest.from_file("demo/app.py", default_timeout=90)
    at.run()
    return at


def _text(at) -> str:
    parts = []
    for group in (at.markdown, at.caption, at.warning, at.info, at.success):
        parts.extend(str(e.value) for e in group)
    return " ".join(parts)


def _selectbox(at, label):
    return next(s for s in at.selectbox if s.label == label)


@pytest.fixture(scope="module")
def committed():
    return {
        "gates": json.loads((REPORT_DIR / "gate_summary.json").read_text()),
        "headline": json.loads((REPORT_DIR / "headline_metrics.json").read_text()),
        "claims": json.loads((REPORT_DIR / "claims.json").read_text()),
        "limitations": json.loads((REPORT_DIR / "limitations.json").read_text()),
    }


# --- Default state ------------------------------------------------------------


def test_dashboard_starts_without_exception():
    at = _app()
    assert not at.exception


def test_transition_mode_defaults_to_adopted():
    at = _app()
    selector = _selectbox(at, "Transition intelligence")
    assert selector.value == ADOPTED
    coordinator = at.session_state.agent.transition_coordinator
    assert coordinator is not None
    assert coordinator.mode == "adopted"


def test_adopted_mode_is_offered_as_the_canonical_control():
    at = _app()
    options = _selectbox(at, "Transition intelligence").options
    assert len(options) == 5
    assert options[0] == ADOPTED


def test_adopted_mode_is_built_from_the_presentation_layer():
    cfg = td.build_transition_config("adopted")
    assert cfg.mode == "adopted"
    assert cfg.runtime_authority is not None
    assert cfg.planner_precedence is True


def test_status_header_shows_the_committed_status():
    at = _app()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Runtime default"] == "Disabled"
    assert metrics["Transition path"] == "Candidate only"
    assert metrics["Canonical controller"] == "None"
    assert metrics["Latest applied controller action"] == "No"


def test_gate_summary_is_visible_and_not_styled_as_success():
    at = _app()
    warnings = " ".join(str(w.value) for w in at.warning)
    assert "18 passed, 1 failed, 1 inconclusive" in warnings
    # Candidate-only must never read as success while gate 1 fails.
    successes = " ".join(str(s.value) for s in at.success)
    assert "Candidate only" not in successes


def test_existing_dashboard_surfaces_still_render():
    at = _app()
    text = _text(at)
    assert "Chat" in text or any("Chat" in str(s.value) for s in at.subheader)
    assert _selectbox(at, "Provider")
    assert _selectbox(at, "Memory policy")
    assert _selectbox(at, "Grounded extraction")


# --- Committed evidence integrity ---------------------------------------------


def test_classification_matches_the_committed_artifact(committed):
    assert td.status_summary()["classification"] == committed["gates"]["classification"]
    assert td.status_summary()["classification"] == "TRANSITION_PATH_CANDIDATE_ONLY"


def test_gate_counts_match_the_committed_artifact(committed):
    status = td.status_summary()
    assert status["gates_passed"] == committed["gates"]["passed"] == 18
    assert status["gates_failed"] == committed["gates"]["failed"] == 1
    assert status["gates_inconclusive"] == committed["gates"]["inconclusive"] == 1


def test_all_twenty_gates_are_rendered_in_contract_order():
    rows = td.gate_rows()
    assert [r["gate"] for r in rows] == list(range(1, 21))
    for row in rows:
        assert row["justification"].strip()
        assert row["evidence"]


def test_gate_one_is_rendered_as_failed_with_committed_values(committed):
    gate = next(g for g in td.gate_rows() if g["gate"] == 1)
    source = next(g for g in committed["gates"]["gates"] if g["gate"] == 1)
    assert gate["decision"] == "fail"
    assert gate["reference"] == source["reference"] == "0"
    assert gate["candidate"] == source["candidate"] == "10"
    assert gate in td.highlighted_gates()


def test_gate_six_is_rendered_as_inconclusive_not_pass(committed):
    gate = next(g for g in td.gate_rows() if g["gate"] == 6)
    source = next(g for g in committed["gates"]["gates"] if g["gate"] == 6)
    assert gate["decision"] == "inconclusive" == source["decision"]
    assert gate in td.highlighted_gates()


def test_blocking_gates_are_marked_and_all_pass(committed):
    # The committed artifact decides which gates block; the count is read
    # from it rather than restated, so the UI cannot drift from evidence.
    blocking = td.blocking_gates()
    source = [g for g in committed["gates"]["gates"] if g["blocking"]]
    assert [g["gate"] for g in blocking] == [g["gate"] for g in source]
    assert [g["gate"] for g in blocking] == [4, 5, 8, 9, 10, 11, 12, 19, 20]
    assert all(g["decision"] == "pass" for g in blocking)


def test_duplicate_and_stale_values_match_the_committed_headline(committed):
    head = committed["headline"]
    rows = {r["metric"]: r for r in td.duplicate_stale_rows()}
    stale = rows["Stale active pairs"]
    duplicates = rows["Duplicate pairs"]
    assert stale["reference"] == head["reference_stale_pairs"] == 6
    assert stale["isolated_applied"] == head["adopted_stale_pairs"] == 1
    assert duplicates["reference"] == head["reference_duplicate_pairs"] == 0
    assert duplicates["isolated_applied"] == head["adopted_duplicate_pairs"] == 10


def test_projected_and_applied_are_separate_columns():
    rows = {r["metric"]: r for r in td.duplicate_stale_rows()}
    duplicates = rows["Duplicate pairs"]
    # The projection is clean; the applied result is not. Conflating them
    # would report an improvement that never happens.
    assert duplicates["candidate_projection"] == 0
    assert duplicates["isolated_applied"] == 10
    assert duplicates["candidate_projection"] != duplicates["isolated_applied"]


def test_duplicate_finding_names_the_cause_and_consequence():
    finding = td.duplicate_finding()
    assert finding["available"]
    assert "alongside" in finding["cause"]
    assert "candidate only" in finding["consequence"]
    assert "action-replacement" in finding["future_work"]


def test_system_rows_match_committed_systems():
    rows = td.system_rows()
    assert len(rows) == 7
    ids = {r["system_id"] for r in rows}
    assert "experienceos_hybrid_full_v2_reference" in ids
    assert "experienceos_transition_adopted_v1" in ids


def test_unavailable_systems_are_not_scored_as_zero():
    unavailable = [r for r in td.system_rows() if not r["available"]]
    assert len(unavailable) == 2
    for row in unavailable:
        assert row["unavailable_reason"]
        assert row["duplicate_pairs"] == "Unavailable"
        assert row["classification"] == "Unavailable"
        assert row["actions_applied"] != 0


def test_historical_and_development_partitions_are_separate():
    counts = td.partition_counts()
    assert counts["historical_scored"] == 28
    assert counts["development_fixtures"] == 27


def test_all_ten_ablations_render_and_none_is_runtime_eligible():
    rows = td.ablation_rows()
    assert len(rows) == 10
    assert all(r["runtime_eligible"] is False for r in rows)


def test_claims_and_limitations_load_from_committed_files(committed):
    claims = td.claim_rows()
    assert len(claims["supported"]) == len(committed["claims"]["supported"]) == 7
    assert len(claims["unsupported"]) == len(committed["claims"]["unsupported"]) == 12
    unsupported = {c["claim"] for c in claims["unsupported"]}
    assert "canonical adoption" in unsupported
    assert "improved final answer quality" in unsupported
    limitations = td.limitation_rows()
    assert limitations == committed["limitations"]["limitations"]
    assert len(limitations) == 15


def test_case_records_are_available_and_deterministically_ordered():
    rows = td.case_rows()
    assert len(rows) == 275
    assert rows == td.case_rows()
    historical = td.case_rows(partition="historical_scored")
    assert historical and all(r["partition"] == "historical_scored" for r in historical)
    by_system = td.case_rows(system_id="experienceos_transition_candidate_v1")
    assert by_system and all(
        r["system_id"] == "experienceos_transition_candidate_v1" for r in by_system
    )


def test_lifecycle_chain_has_ten_turns():
    chain = td.lifecycle_chain()
    assert chain["turns"] == 10
    for system in chain["systems"].values():
        assert len(system["turns"]) == 10


def test_artifact_paths_are_repository_relative():
    assert not td.REPORT_DOC.startswith("/")
    for gate in td.gate_rows():
        for path in gate["evidence"]:
            assert not path.startswith("/")


# --- Live trace ---------------------------------------------------------------


def test_disabled_mode_renders_a_truthful_empty_state():
    at = _app()
    text = _text(at)
    assert "integration is disabled" in text


def test_shadow_mode_renders_a_trace_and_mutates_nothing():
    at = _app()
    _selectbox(at, "Transition intelligence").select(SHADOW).run()
    at.chat_input[0].set_value(DURABLE).run()
    at.chat_input[0].set_value(UPDATE).run()
    assert not at.exception
    agent = at.session_state.agent
    assert agent.transition_coordinator.mode == "shadow"
    trace = td.transition_trace(agent.events)
    assert trace
    assert all(not r["action_applied"] for r in trace)
    # Shadow proposes; durable memory is untouched by the controller.
    assert all(
        r["canonical_action_effect"] in ("diagnostics_only", "unchanged")
        for r in trace
    )


def test_candidate_mode_renders_and_inserts_nothing():
    at = _app()
    _selectbox(at, "Transition intelligence").select(CANDIDATE).run()
    at.chat_input[0].set_value(DURABLE).run()
    at.chat_input[0].set_value(UPDATE).run()
    assert not at.exception
    trace = td.transition_trace(at.session_state.agent.events)
    assert trace
    assert all(not r["action_applied"] for r in trace)
    assert any(r["canonical_action_effect"] == "candidate_only" for r in trace)


def test_verify_only_mode_renders_and_changes_no_actions():
    at = _app()
    _selectbox(at, "Transition intelligence").select(VERIFY_ONLY).run()
    at.chat_input[0].set_value(DURABLE).run()
    assert not at.exception
    trace = td.transition_trace(at.session_state.agent.events)
    assert all(not r["action_applied"] for r in trace)


def test_pipeline_stages_never_imply_a_skipped_stage_passed():
    at = _app()
    _selectbox(at, "Transition intelligence").select(SHADOW).run()
    at.chat_input[0].set_value(UPDATE).run()
    trace = td.transition_trace(at.session_state.agent.events)
    stages = td.pipeline_stages(trace[-1])
    assert [s["stage"] for s in stages] == list(td.STAGE_ORDER)
    by_stage = {s["stage"]: s for s in stages}
    # Shadow: authorization never runs and nothing is applied.
    assert by_stage["Authorization"]["status"] == "not_run"
    assert by_stage["Application"]["status"] == "not_run"
    assert by_stage["Verification"]["status"] == "passed"


def test_shadow_mode_does_not_change_memory_versus_disabled():
    def run(mode_label):
        at = _app()
        if mode_label:
            _selectbox(at, "Transition intelligence").select(mode_label).run()
        at.chat_input[0].set_value(DURABLE).run()
        at.chat_input[0].set_value(UPDATE).run()
        agent = at.session_state.agent
        user = _selectbox_text(at)
        return sorted(
            (m.text, m.status)
            for m in agent.memory_store.list_memories(user_id=user)
        )

    def _selectbox_text(at):
        return next(t.value for t in at.text_input if t.label == "User ID")

    assert run(None) == run(SHADOW) == run(CANDIDATE)


# --- Annotation compatibility -------------------------------------------------


def test_old_events_without_transition_annotations_render():
    at = _app()
    # Select disabled so no transition annotation is emitted at all, then
    # confirm the trace renderer handles annotation-free events.
    _selectbox(at, "Transition intelligence").set_value(DISABLED).run()
    at.chat_input[0].set_value(DURABLE).run()
    assert not at.exception
    assert td.transition_trace(at.session_state.agent.events) == []


def test_malformed_annotation_fails_boundedly():
    for payload in (None, "not a dict", 42, []):
        record = td.normalize_transition_event(payload)
        assert record["malformed"] is True
        assert record["reason"]
        assert td.pipeline_stages(record) == []


def test_partial_annotation_renders_without_crashing():
    record = td.normalize_transition_event({"configured_mode": "shadow"})
    assert record["malformed"] is False
    assert record["effective_mode"] == "Unavailable"
    assert record["transition_type"] is None
    stages = td.pipeline_stages(record)
    assert [s["stage"] for s in stages] == list(td.STAGE_ORDER)


def test_unknown_future_fields_are_ignored_safely():
    record = td.normalize_transition_event(
        {
            "configured_mode": "shadow",
            "effective_mode": "shadow",
            "a_field_from_the_future": {"nested": True},
        }
    )
    assert record["malformed"] is False
    assert "a_field_from_the_future" not in record


def test_annotation_version_is_surfaced():
    at = _app()
    _selectbox(at, "Transition intelligence").select(SHADOW).run()
    at.chat_input[0].set_value(UPDATE).run()
    trace = td.transition_trace(at.session_state.agent.events)
    assert trace[-1]["annotation_version"] == "1"


# --- Artifact failure ---------------------------------------------------------


def test_missing_artifacts_yield_truthful_empty_state(monkeypatch, tmp_path):
    monkeypatch.setattr(td, "REPORT_DIR", tmp_path / "absent")
    td.reload_artifacts()
    try:
        assert td.benchmark_available() is False
        status = td.status_summary()
        assert status["available"] is False
        # Missing data must never read as zero or as a passing status.
        assert status["classification"] == "Unavailable"
        assert status["gates_passed"] is None
        assert td.gate_rows() == []
        assert td.ablation_rows() == []
        assert td.limitation_rows() == []
        assert td.duplicate_finding() == {"available": False}
    finally:
        td.reload_artifacts()


def test_malformed_artifact_is_handled_without_fabricating_metrics(
    monkeypatch, tmp_path
):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "report_data.json").write_text("{ not json")
    monkeypatch.setattr(td, "REPORT_DIR", broken)
    td.reload_artifacts()
    try:
        assert td.benchmark_available() is False
        assert td.status_summary()["gates_failed"] is None
    finally:
        td.reload_artifacts()


def test_missing_case_file_returns_no_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(td, "VERIFICATION_DIR", tmp_path / "absent")
    td.reload_artifacts()
    try:
        assert td.case_rows() == []
        assert td.case_ids() == []
    finally:
        td.reload_artifacts()


# --- Non-mutation -------------------------------------------------------------


def test_artifact_readers_do_not_modify_artifacts():
    import hashlib

    def digests():
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(REPORT_DIR.iterdir())
            if p.is_file()
        }

    before = digests()
    td.reload_artifacts()
    td.status_summary()
    td.gate_rows()
    td.system_rows()
    td.ablation_rows()
    td.claim_rows()
    td.case_rows()
    assert digests() == before


def test_presentation_module_imports_no_provider_or_network():
    import ast

    with open(td.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in (
        "experienceos.providers", "requests", "urllib", "httpx", "socket",
        "benchmarks.transition_benchmark",
    ):
        assert not any(
            n == banned or n.startswith(f"{banned}.") for n in imported
        ), f"presentation layer imports {banned}"


def test_presentation_module_does_not_recompute_benchmark_metrics():
    import inspect

    source = inspect.getsource(td)
    # The committed report is authoritative; the dashboard must not
    # re-derive a classification or re-run a gate. Mapping a committed
    # classification onto a display label is not deriving one.
    assert "evaluate_gates" not in source
    assert "def classify(" not in source
    assert "MATERIALITY" not in source
    # The classification is read from the artifact, never assigned.
    assert 'gates["classification"]' in source


def test_rendering_the_benchmark_view_constructs_no_provider(monkeypatch):
    import experienceos.providers.qwen_cloud as qwen

    def deny(*args, **kwargs):
        raise AssertionError("dashboard constructed a cloud provider")

    monkeypatch.setattr(qwen.QwenCloudProvider, "__init__", deny)
    at = _app()
    assert not at.exception
    td.reload_artifacts()
    td.status_summary()
    td.gate_rows()


def test_artifact_readers_perform_no_network_access(monkeypatch):
    import socket

    def deny(*args, **kwargs):
        raise AssertionError("artifact reader attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    td.reload_artifacts()
    assert td.benchmark_available()
    assert len(td.gate_rows()) == 20


def test_lifecycle_view_does_not_mutate_the_store():
    at = _app()
    at.chat_input[0].set_value(DURABLE).run()
    agent = at.session_state.agent
    user = next(t.value for t in at.text_input if t.label == "User ID")
    before = [
        (m.id, m.status) for m in agent.memory_store.list_memories(user_id=user)
    ]
    cards = td.lifecycle_cards(agent, user)
    td.lifecycle_groups(cards)
    td.lineage_rows(cards)
    assert [
        (m.id, m.status) for m in agent.memory_store.list_memories(user_id=user)
    ] == before
