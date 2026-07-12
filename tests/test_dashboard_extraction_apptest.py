"""Render-level tests for the grounded-extraction dashboard diagnostics.

Proves the diagnostics render safely, the live trace and committed
benchmark summary appear, shadow/candidate selection never mutates
durable memory through extraction, and initial render constructs no
optional runtime.
"""

import sys

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

HEAVY_MODULES = (
    "sentence_transformers", "torch", "onnxruntime", "transformers",
    "llama_cpp",
)
SHADOW = "Shadow (observe, non-mutating)"
CANDIDATE = "Candidate (lifecycle eval, non-mutating)"
DURABLE_MSG = "I prefer aisle seats for short work trips."


def _fresh_app():
    at = AppTest.from_file("demo/app.py", default_timeout=60)
    at.run()
    return at


def _all_text(at):
    return " ".join(
        [c.value for c in at.caption]
        + [m.value for m in at.markdown]
    )


def _select_mode(at, label):
    box = [s for s in at.selectbox if s.label == "Grounded extraction"][0]
    box.set_value(label).run()
    return at


# ---- initial render ------------------------------------------------------


def test_initial_render_disabled_no_heavy_imports():
    at = _fresh_app()
    assert not at.exception
    assert not any(m in sys.modules for m in HEAVY_MODULES)
    text = _all_text(at)
    assert "Extraction decision trace" in text
    assert "Grounded extraction integration is disabled" in text


def test_initial_render_has_extraction_mode_selector_defaulting_disabled():
    at = _fresh_app()
    box = [s for s in at.selectbox if s.label == "Grounded extraction"][0]
    assert box.value == "Disabled (default)"


def test_no_provider_or_runner_constructed_on_render(monkeypatch):
    import experienceos.memory.grounded_extraction as gx

    def _forbidden(*args, **kwargs):
        raise AssertionError("controller constructed during render")

    monkeypatch.setattr(
        gx.DeterministicGroundedExtractionController, "__init__", _forbidden)
    at = _fresh_app()
    assert not at.exception


# ---- committed benchmark summary -----------------------------------------


def test_benchmark_summary_expander_present():
    at = _fresh_app()
    labels = [e.label for e in at.expander]
    assert "Grounded extraction evaluation (committed evidence)" in labels


def test_benchmark_summary_shows_shadow_only_and_failed_gates():
    at = _fresh_app()
    text = _all_text(at)
    assert "Shadow only" in text
    assert "12/15 passed" in text
    assert "creation_recall_or_absence_improvement" in text
    assert "duplicate_active_memories" in text


def test_benchmark_summary_shows_explicit_ratios_not_just_percent():
    at = _fresh_app()
    # dataframes carry the ratio cells
    frames = [f for f in at.dataframe]
    blob = " ".join(str(f.value.to_dict()) for f in frames)
    assert "5/6" in blob and "5/13" in blob and "6/6" in blob


def test_benchmark_summary_shows_learned_unavailable():
    at = _fresh_app()
    text = _all_text(at)
    assert "not executed" in text
    assert "grounded_learned_shadow_v1" in text


def test_benchmark_case_examples_render():
    at = _fresh_app()
    text = _all_text(at)
    assert "creation_002_durable_user_fact" in text
    assert "forgetting_003_forget_one_of_several" in text


# ---- live shadow / candidate flows ---------------------------------------


def test_shadow_flow_renders_candidate_and_canonical_effect_false():
    at = _select_mode(_fresh_app(), SHADOW)
    at.chat_input[0].set_value(DURABLE_MSG).run()
    assert not at.exception
    text = _all_text(at)
    assert "Candidate proposed" in text
    assert "canonical effect: no" in text.lower()


def test_shadow_does_not_mutate_memory_via_extraction():
    # Shadow must leave durable state byte-identical to disabled: any
    # memory present comes from the canonical planner, not extraction.
    disabled = _fresh_app()
    disabled.chat_input[0].set_value(DURABLE_MSG).run()
    disabled_mems = [
        (m.kind, m.text)
        for m in disabled.session_state["agent"].memories_for_user(
            "demo-user")]

    shadow = _select_mode(_fresh_app(), SHADOW)
    shadow.chat_input[0].set_value(DURABLE_MSG).run()
    shadow_mems = [
        (m.kind, m.text)
        for m in shadow.session_state["agent"].memories_for_user(
            "demo-user")]
    assert shadow_mems == disabled_mems

    from experienceos.events.schema import EventType
    events = shadow.session_state["agent"].events
    extraction = [e for e in events
                  if e.type == EventType.EXTRACTION_INTEGRATION_EVALUATED]
    assert extraction
    assert all(e.payload.get("canonical_effect") is False for e in extraction)


def test_candidate_flow_non_mutating_and_lifecycle_visible():
    at = _select_mode(_fresh_app(), CANDIDATE)
    at.chat_input[0].set_value(DURABLE_MSG).run()
    assert not at.exception
    from experienceos.events.schema import EventType
    events = at.session_state["agent"].events
    extraction = [e for e in events
                  if e.type == EventType.EXTRACTION_INTEGRATION_EVALUATED]
    assert extraction
    assert all(not e.payload.get("action_applied") for e in extraction)
    assert all(e.payload.get("canonical_effect") is False
               for e in extraction)


def test_abstention_message_renders_first_class():
    at = _select_mode(_fresh_app(), SHADOW)
    at.chat_input[0].set_value("What is 15% of 240?").run()
    assert not at.exception
    text = _all_text(at)
    assert "abstained" in text.lower() or "No candidate" in text


# ---- reset ---------------------------------------------------------------


def test_reset_clears_live_trace_keeps_benchmark_summary():
    at = _select_mode(_fresh_app(), SHADOW)
    at.chat_input[0].set_value(DURABLE_MSG).run()
    # reset demo button
    reset_btn = [b for b in at.button if b.label == "Reset demo"][0]
    reset_btn.click().run()
    assert not at.exception
    from experienceos.events.schema import EventType
    events = at.session_state["agent"].events
    assert not [e for e in events
                if e.type == EventType.EXTRACTION_INTEGRATION_EVALUATED]
    text = _all_text(at)
    # committed benchmark summary remains available
    assert "Shadow only" in text
    assert not any(m in sys.modules for m in HEAVY_MODULES)
