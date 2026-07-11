"""Phase 11 Prompt 2: optional local provider unavailability tests.

Every test here runs without sentence-transformers installed, without
a model, and without network access: unavailability must be a clean,
display-safe report, never a download attempt or a path leak.
"""

import importlib.util
import os
import socket
import sys

import pytest

from experienceos.embeddings import (
    EmbeddingInputError,
    EmbeddingUnavailableError,
    EmbeddingUnavailableReason,
)
from experienceos.embeddings.local import (
    MODEL_PATH_ENV,
    SentenceTransformerEmbeddingProvider,
)


@pytest.fixture(autouse=True)
def _no_model_env(monkeypatch):
    monkeypatch.delenv(MODEL_PATH_ENV, raising=False)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


def _force_dependency_missing(monkeypatch):
    original = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "sentence_transformers":
            return None
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)


def test_missing_dependency_reports_unavailable(monkeypatch):
    _force_dependency_missing(monkeypatch)
    availability = SentenceTransformerEmbeddingProvider().availability()
    assert availability.available is False
    assert availability.reason == (
        EmbeddingUnavailableReason.DEPENDENCY_MISSING
    )
    assert "embeddings-local" in availability.detail


def test_unconfigured_model_reports_unavailable(monkeypatch):
    monkeypatch.setattr(
        importlib.util, "find_spec",
        lambda name, *a, **k: object()
        if name == "sentence_transformers" else None,
    )
    availability = SentenceTransformerEmbeddingProvider().availability()
    assert availability.available is False
    assert availability.reason == (
        EmbeddingUnavailableReason.MODEL_NOT_CONFIGURED
    )
    assert MODEL_PATH_ENV in availability.detail


def test_missing_model_path_reports_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        importlib.util, "find_spec",
        lambda name, *a, **k: object()
        if name == "sentence_transformers" else None,
    )
    provider = SentenceTransformerEmbeddingProvider(
        model_path=tmp_path / "no-such-model"
    )
    availability = provider.availability()
    assert availability.available is False
    assert availability.reason == EmbeddingUnavailableReason.MODEL_MISSING
    assert "never downloaded" in availability.detail


def test_embedding_while_unavailable_raises_clean_error(monkeypatch):
    _force_dependency_missing(monkeypatch)
    provider = SentenceTransformerEmbeddingProvider()
    with pytest.raises(EmbeddingUnavailableError) as excinfo:
        provider.embed_query("hello")
    assert excinfo.value.availability.reason == (
        EmbeddingUnavailableReason.DEPENDENCY_MISSING
    )
    with pytest.raises(EmbeddingUnavailableError):
        provider.embed_memories(["hello", "world"])


def test_no_import_and_no_download_attempted_when_unavailable(monkeypatch):
    _force_dependency_missing(monkeypatch)
    provider = SentenceTransformerEmbeddingProvider()
    provider.availability()
    with pytest.raises(EmbeddingUnavailableError):
        provider.embed_query("hello")
    # The optional library was never imported (a download path would
    # require it), and the network fixture proved no socket was opened.
    assert "sentence_transformers" not in sys.modules


def test_diagnostics_never_contain_paths(monkeypatch, tmp_path):
    provider = SentenceTransformerEmbeddingProvider(
        model_path=tmp_path / "secret-location" / "model-dir"
    )
    availability = provider.availability()
    text = f"{availability.reason} {availability.detail} {provider.model_id}"
    assert str(tmp_path) not in text
    assert "/Users/" not in text and "/home/" not in text
    assert "secret-location" not in text
    # model_id exposes the basename only.
    assert provider.model_id == "local:model-dir"


def test_explicit_model_label_overrides_basename(tmp_path):
    provider = SentenceTransformerEmbeddingProvider(
        model_path=tmp_path, model_label="all-MiniLM-L6-v2"
    )
    assert provider.model_id == "all-MiniLM-L6-v2"


def test_construction_does_not_mutate_global_state():
    env_before = dict(os.environ)
    modules_before = set(sys.modules)
    SentenceTransformerEmbeddingProvider()
    assert dict(os.environ) == env_before
    assert set(sys.modules) == modules_before


def test_env_var_configuration_is_read_at_construction(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_PATH_ENV, str(tmp_path))
    provider = SentenceTransformerEmbeddingProvider()
    assert provider.model_id == f"local:{tmp_path.name}"


def test_dimensions_unknown_until_first_embed():
    assert SentenceTransformerEmbeddingProvider().dimensions is None


def test_invalid_input_rejected_before_any_model_work(monkeypatch):
    _force_dependency_missing(monkeypatch)
    provider = SentenceTransformerEmbeddingProvider()
    with pytest.raises(EmbeddingInputError):
        provider.embed_query(3.14)  # type: ignore[arg-type]
    with pytest.raises(EmbeddingInputError):
        provider.embed_memories("not a batch")
