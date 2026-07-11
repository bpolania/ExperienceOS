"""Phase 11 Prompt 2: embedding contract, metadata, and factory tests."""

import math

import pytest

from experienceos.embeddings import (
    DEFAULT_DIMENSIONS,
    DeterministicEmbeddingProvider,
    EMBEDDING_MODES,
    EmbeddingConfigError,
    EmbeddingDimensionError,
    EmbeddingInputError,
    cosine_similarity,
    create_embedding_provider,
    validate_vector,
)


def test_deterministic_provider_metadata_is_frozen():
    provider = DeterministicEmbeddingProvider()
    assert provider.provider_id == "deterministic"
    assert provider.model_id == "stable-feature-hash-v1"
    assert provider.dimensions == DEFAULT_DIMENSIONS == 512


def test_availability_reports_available():
    availability = DeterministicEmbeddingProvider().availability()
    assert availability.available is True
    assert availability.reason is None


def test_result_metadata_matches_provider_and_is_serializable():
    import json

    provider = DeterministicEmbeddingProvider()
    result = provider.embed_query("I prefer green tea in the morning")
    assert result.provider_id == provider.provider_id
    assert result.model_id == provider.model_id
    assert result.dimensions == provider.dimensions
    assert result.deterministic is True
    metadata = result.to_metadata()
    assert json.loads(json.dumps(metadata)) == metadata
    # Digest-stable metadata excludes non-deterministic timing.
    assert "elapsed_ms" not in metadata
    assert "vector" not in metadata


def test_batch_results_carry_consistent_metadata():
    provider = DeterministicEmbeddingProvider()
    results = provider.embed_memories(["coffee", "tea", "matcha"])
    assert len(results) == 3
    assert {r.dimensions for r in results} == {provider.dimensions}
    assert {r.provider_id for r in results} == {"deterministic"}


def test_invalid_input_types_are_rejected():
    provider = DeterministicEmbeddingProvider()
    with pytest.raises(EmbeddingInputError):
        provider.embed_query(42)  # type: ignore[arg-type]
    with pytest.raises(EmbeddingInputError):
        provider.embed_memories("one string is not a batch")
    with pytest.raises(EmbeddingInputError):
        provider.embed_memories(["ok", None])  # type: ignore[list-item]


def test_empty_batch_returns_empty_tuple():
    assert DeterministicEmbeddingProvider().embed_memories([]) == ()


def test_too_small_dimensions_rejected():
    with pytest.raises(EmbeddingDimensionError):
        DeterministicEmbeddingProvider(dimensions=4)


def test_validate_vector_rules():
    assert validate_vector((0.0, 1.0)) == (0.0, 1.0)
    with pytest.raises(EmbeddingDimensionError):
        validate_vector(())
    with pytest.raises(EmbeddingDimensionError):
        validate_vector((1.0, float("nan")))
    with pytest.raises(EmbeddingDimensionError):
        validate_vector((1.0, float("inf")))
    with pytest.raises(EmbeddingDimensionError):
        validate_vector((1.0, 2.0), expected_dimensions=3)


def test_cosine_similarity_contract():
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)
    # Zero vectors have no direction: similarity is 0.0, never an error.
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) == 0.0
    with pytest.raises(EmbeddingDimensionError):
        cosine_similarity((1.0,), (1.0, 0.0))


def test_factory_modes():
    assert EMBEDDING_MODES == ("disabled", "deterministic", "local")
    assert create_embedding_provider() is None
    assert create_embedding_provider("disabled") is None
    provider = create_embedding_provider("deterministic")
    assert isinstance(provider, DeterministicEmbeddingProvider)
    assert create_embedding_provider(
        "deterministic", dimensions=64
    ).dimensions == 64
    with pytest.raises(EmbeddingConfigError):
        create_embedding_provider("qwen-cloud")


def test_factory_local_mode_constructs_without_loading():
    provider = create_embedding_provider("local")
    # Construction succeeds even without the optional dependency; the
    # provider reports unavailability instead of raising.
    assert provider is not None
    assert provider.provider_id == "sentence-transformers-local"


def test_vectors_are_immutable_tuples_of_finite_floats():
    result = DeterministicEmbeddingProvider().embed_query("stable output")
    assert isinstance(result.vector, tuple)
    assert all(isinstance(v, float) and math.isfinite(v)
               for v in result.vector)
