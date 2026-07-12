"""Phase 11 Prompt 3: bounded embedding cache tests."""

import pytest

from experienceos.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingCache,
    EmbeddingCacheKey,
    EmbeddingDimensionError,
    content_digest,
)


def _key(text="hello", provider="deterministic", model="m1", dims=4):
    return EmbeddingCacheKey(
        provider_id=provider,
        model_id=model,
        dimensions=dims,
        content_digest=content_digest(text),
    )


def test_first_lookup_misses_then_hits():
    cache = EmbeddingCache()
    key = _key()
    assert cache.get(key) is None
    cache.put(key, (1.0, 0.0, 0.0, 0.0))
    assert cache.get(key) == (1.0, 0.0, 0.0, 0.0)
    assert cache.counters["lookups"] == 2
    assert cache.counters["misses"] == 1
    assert cache.counters["hits"] == 1


def test_identical_text_same_identity_reuses_vector():
    cache = EmbeddingCache()
    cache.put(_key("same text"), (0.0, 1.0, 0.0, 0.0))
    assert cache.get(_key("same text")) == (0.0, 1.0, 0.0, 0.0)


def test_changed_text_misses():
    cache = EmbeddingCache()
    cache.put(_key("old text"), (1.0, 0.0, 0.0, 0.0))
    assert cache.get(_key("new text")) is None


def test_provider_model_and_dimension_changes_miss():
    cache = EmbeddingCache()
    cache.put(_key(), (1.0, 0.0, 0.0, 0.0))
    assert cache.get(_key(provider="other")) is None
    assert cache.get(_key(model="m2")) is None
    assert cache.get(_key(dims=8)) is None


def test_put_validates_vector_against_key_dimensions():
    cache = EmbeddingCache()
    with pytest.raises(EmbeddingDimensionError):
        cache.put(_key(dims=4), (1.0, 0.0))  # wrong width
    with pytest.raises(EmbeddingDimensionError):
        cache.put(_key(dims=2), (1.0, float("nan")))


def test_corrupted_entry_is_invalidated_not_returned():
    cache = EmbeddingCache()
    key = _key()
    cache.put(key, (1.0, 0.0, 0.0, 0.0))
    cache._entries[key] = (1.0, 0.0)  # simulate corruption
    assert cache.get(key) is None
    assert cache.counters["invalidated"] == 1
    assert len(cache) == 0


def test_cache_is_bounded_with_fifo_lru_eviction():
    cache = EmbeddingCache(max_entries=2)
    a, b, c = _key("a"), _key("b"), _key("c")
    cache.put(a, (1.0, 0.0, 0.0, 0.0))
    cache.put(b, (0.0, 1.0, 0.0, 0.0))
    cache.get(a)  # refresh a: b becomes least recently used
    cache.put(c, (0.0, 0.0, 1.0, 0.0))
    assert cache.counters["evictions"] == 1
    assert cache.get(b) is None  # evicted
    assert cache.get(a) is not None
    assert cache.get(c) is not None
    assert len(cache) == 2


def test_clear_empties_cache():
    cache = EmbeddingCache()
    cache.put(_key(), (1.0, 0.0, 0.0, 0.0))
    cache.clear()
    assert len(cache) == 0
    assert cache.get(_key()) is None


def test_invalid_max_entries_rejected():
    with pytest.raises(ValueError):
        EmbeddingCache(max_entries=0)


def test_summary_has_counters_but_no_vectors():
    cache = EmbeddingCache(max_entries=10)
    cache.put(_key(), (1.0, 0.0, 0.0, 0.0))
    summary = cache.summary()
    assert summary["size"] == 1
    assert summary["max_entries"] == 10
    assert summary["stores"] == 1
    flattened = str(summary)
    assert "1.0" not in flattened  # no vector values leak
    assert "vector" not in summary


def test_content_digest_is_stable_sha256():
    assert content_digest("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert content_digest("abc") != content_digest("abd")


def test_key_is_immutable_and_hashable():
    key = _key()
    assert key == _key()
    assert hash(key) == hash(_key())
    with pytest.raises(Exception):
        key.dimensions = 8  # frozen


def test_query_embeddings_are_not_cached_by_generator():
    """The generator caches memory embeddings only: repeated calls with
    the same query re-embed the query but hit the memory cache."""
    from experienceos.context.semantic import SemanticCandidateGenerator
    from experienceos.memory.schema import ExperienceEntry

    generator = SemanticCandidateGenerator(DeterministicEmbeddingProvider())
    entries = (ExperienceEntry(user_id="u", text="green tea daily"),)
    generator.score_memories("green tea", entries)
    generator.score_memories("green tea", entries)
    # Two calls, one memory: 2 lookups, 1 miss then 1 hit — the query
    # itself never entered the cache.
    assert generator.cache.counters["lookups"] == 2
    assert generator.cache.counters["hits"] == 1
    assert generator.cache.counters["stores"] == 1
