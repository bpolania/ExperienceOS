"""Phase 11 Prompt 2: deterministic provider behavior tests."""

import hashlib
import json
import math
import os
import subprocess
import sys

import pytest

from experienceos.embeddings import (
    DeterministicEmbeddingProvider,
    cosine_similarity,
)
from experienceos.embeddings.deterministic import tokenize

PROVIDER = DeterministicEmbeddingProvider()


def _vector_digest(vector):
    return hashlib.sha256(
        json.dumps(list(vector)).encode("utf-8")
    ).hexdigest()


def test_repeated_query_embedding_is_byte_equal():
    first = PROVIDER.embed_query("I moved to Lisbon last spring")
    second = PROVIDER.embed_query("I moved to Lisbon last spring")
    assert first.vector == second.vector
    assert first == second  # elapsed_ms is None, so full equality holds


def test_repeated_batch_embedding_is_byte_equal():
    texts = ["prefers oat milk", "works at Initech", "allergic to cilantro"]
    assert [r.vector for r in PROVIDER.embed_memories(texts)] == [
        r.vector for r in PROVIDER.embed_memories(texts)
    ]


def test_independent_instances_agree():
    a = DeterministicEmbeddingProvider()
    b = DeterministicEmbeddingProvider()
    assert a.embed_query("tea").vector == b.embed_query("tea").vector


def test_cross_process_stability_and_hash_seed_independence():
    """Vectors are stable across processes and PYTHONHASHSEED values."""
    script = (
        "from experienceos.embeddings import DeterministicEmbeddingProvider\n"
        "import hashlib, json\n"
        "v = DeterministicEmbeddingProvider().embed_query("
        "'I moved to Lisbon last spring').vector\n"
        "print(hashlib.sha256(json.dumps(list(v)).encode()).hexdigest())\n"
    )
    digests = []
    for seed in ("0", "424242"):
        env = dict(os.environ, PYTHONPATH=".", PYTHONHASHSEED=seed)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env, check=True,
        )
        digests.append(completed.stdout.strip())
    local = _vector_digest(
        PROVIDER.embed_query("I moved to Lisbon last spring").vector
    )
    assert digests[0] == digests[1] == local


def test_tokenization_rule_is_documented_behavior():
    assert tokenize("I Prefer GREEN-tea!") == ["i", "prefer", "green", "tea"]
    # casefold() (not lower()) is the documented rule: ß becomes ss.
    assert tokenize("café schließen 東京") == ["café", "schliessen", "東京"]
    assert tokenize("under_score") == ["under", "score"]
    assert tokenize("...") == []


def test_identical_text_has_maximal_similarity():
    a = PROVIDER.embed_query("my favorite drink is green tea").vector
    b = PROVIDER.embed_query("my favorite drink is green tea").vector
    assert cosine_similarity(a, b) == pytest.approx(1.0)


def test_reordered_shared_tokens_remain_highly_similar():
    a = PROVIDER.embed_query("green tea is my favorite drink").vector
    b = PROVIDER.embed_query("my favorite drink is green tea").vector
    # Order-insensitive feature hashing: reordering is identity here.
    assert a == b
    assert cosine_similarity(a, b) == pytest.approx(1.0)


def test_shared_tokens_rank_above_unrelated_text():
    # Feature hashing measures token overlap: fixtures share meaningful
    # tokens (green, tea, user) or none at all. Stopword-only overlap
    # and hash-collision noise are known limits of this test provider.
    query = PROVIDER.embed_query("green tea preference of this user").vector
    related = PROVIDER.embed_query("user prefers green tea daily").vector
    unrelated = PROVIDER.embed_query("meeting rescheduled Thursday")
    related_similarity = cosine_similarity(query, related)
    unrelated_similarity = cosine_similarity(query, unrelated.vector)
    assert related_similarity > 0.3
    assert related_similarity > unrelated_similarity + 0.15


def test_repeated_tokens_shift_weight_not_direction_sign():
    once = PROVIDER.embed_query("coffee").vector
    thrice = PROVIDER.embed_query("coffee coffee coffee").vector
    assert cosine_similarity(once, thrice) == pytest.approx(1.0)


def test_empty_and_blank_text_embed_to_zero_vector():
    for text in ("", "   ", "\n\t", "!!! ..."):
        result = PROVIDER.embed_query(text)
        assert all(v == 0.0 for v in result.vector)
        assert cosine_similarity(
            result.vector, PROVIDER.embed_query("anything").vector
        ) == 0.0


def test_unicode_input_is_supported_and_stable():
    first = PROVIDER.embed_query("Schließen Sie das Café um 東京?")
    second = PROVIDER.embed_query("Schließen Sie das Café um 東京?")
    assert first.vector == second.vector
    assert any(v != 0.0 for v in first.vector)


def test_nonzero_vectors_are_l2_normalized():
    vector = PROVIDER.embed_query("normalize this vector please").vector
    norm = math.sqrt(sum(v * v for v in vector))
    assert abs(norm - 1.0) < 1e-9


def test_long_bounded_input_is_handled_without_truncation():
    # No truncation is applied; cost is linear in input size.
    text = " ".join(f"token{i}" for i in range(2000))
    result = PROVIDER.embed_query(text)
    assert result.dimensions == PROVIDER.dimensions
    assert abs(
        math.sqrt(sum(v * v for v in result.vector)) - 1.0
    ) < 1e-9


def test_every_vector_has_declared_dimension():
    results = PROVIDER.embed_memories(["a b c", "", "東京", "x" * 500])
    assert all(len(r.vector) == PROVIDER.dimensions for r in results)
