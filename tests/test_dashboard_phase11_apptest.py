"""Phase 11 Prompt 8: Streamlit AppTest and import-safety coverage.

Streamlit 1.59 ships AppTest, so real render coverage is possible:
the dashboard is executed end to end (initial render, reset, chat) and
must never load optional model dependencies or crash.
"""

import os
import subprocess
import sys

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

HEAVY_MODULES = (
    "sentence_transformers", "torch", "onnxruntime", "transformers",
)


def _fresh_app() -> AppTest:
    at = AppTest.from_file("demo/app.py", default_timeout=30)
    at.run()
    return at


def _all_text(at: AppTest) -> str:
    parts = [c.value for c in at.caption]
    parts += [m.value for m in at.markdown]
    return " \n".join(str(p) for p in parts)


def test_initial_render_no_exception_and_no_heavy_imports():
    at = _fresh_app()
    assert not at.exception
    assert not any(m in sys.modules for m in HEAVY_MODULES)


def test_initial_render_shows_lifecycle_authority_and_empty_states():
    at = _fresh_app()
    text = _all_text(at)
    assert "Lifecycle rules are applied before semantic scoring" in text
    assert "No retrieval event yet" in text
    assert "Retrieval diagnostics (Phase 11)" in text


def test_benchmark_summary_renders_from_committed_data():
    at = _fresh_app()
    labels = [str(e.label) for e in at.expander]
    assert any("Phase 11 benchmark summary" in label for label in labels)
    text = _all_text(at)
    assert "deterministic test" in text.lower()
    assert "official longmemeval score" in text.lower()
    assert "experimental" in text.lower()
    assert "docs/phase11_semantic_retrieval_report.md" in text


def test_chat_turn_renders_diagnostics_without_model_load():
    at = _fresh_app()
    chat_inputs = at.chat_input
    if not len(chat_inputs):
        pytest.skip("no chat input rendered in this configuration")
    at.chat_input[0].set_value(
        "I always drink green tea in the morning"
    ).run()
    assert not at.exception
    text = _all_text(at)
    # The default demo path is lexical: labeled honestly, no semantic
    # values fabricated.
    assert (
        "No retrieval event yet" in text
        or "Retrieval mode: lexical" in text
    )
    assert not any(m in sys.modules for m in HEAVY_MODULES)


def test_reset_keeps_dashboard_stable():
    at = _fresh_app()
    reset_buttons = [
        b for b in at.button if "reset" in str(b.label).lower()
    ]
    if not reset_buttons:
        pytest.skip("no reset button exposed")
    reset_buttons[0].click().run()
    assert not at.exception
    assert "Retrieval diagnostics (Phase 11)" in _all_text(at)


def test_dashboard_render_does_not_mutate_benchmark_artifacts():
    from pathlib import Path

    target = Path(
        "benchmarks/results/committed/report-phase11/"
        "report_data_phase11.json"
    )
    before = target.read_bytes()
    _fresh_app()
    assert target.read_bytes() == before


def test_support_import_is_lightweight_subprocess():
    probe = (
        "import sys\n"
        "import demo.support\n"
        "flagged = [m for m in sys.modules if m in ("
        "'sentence_transformers', 'torch', 'onnxruntime', "
        "'transformers', 'llama_cpp', 'streamlit')]\n"
        "print(','.join(flagged) or 'clean')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        check=True, env=dict(os.environ, PYTHONPATH="."),
    )
    assert completed.stdout.strip() == "clean"


def test_no_provider_construction_during_render(monkeypatch):
    import experienceos.embeddings.local as local_module

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "embedding provider constructed during dashboard render"
        )

    monkeypatch.setattr(
        local_module.SentenceTransformerEmbeddingProvider,
        "__init__", _forbidden,
    )
    at = _fresh_app()
    assert not at.exception
