"""Phase 11 Prompt 3: lifecycle safety and store isolation.

Adversarial design: every excluded fixture is deliberately the
highest-similarity memory for its query — if lifecycle filtering ran
after semantic scoring, these memories would win.
"""

from experienceos.context.builder import ContextBuilder
from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.context.semantic import SemanticCandidateGenerator
from experienceos.embeddings import DeterministicEmbeddingProvider
from experienceos.events.bus import EventBus
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.memory.store import InMemoryMemoryStore

QUERY = "favorite green tea ritual"
MATCHING_TEXT = "favorite green tea ritual every morning"


class SpyingProvider(DeterministicEmbeddingProvider):
    """Records every text embedded so exclusion can be observed."""

    def __init__(self):
        super().__init__()
        self.embedded_texts = []

    def embed_query(self, text):
        self.embedded_texts.append(text)
        return super().embed_query(text)

    def embed_memories(self, texts):
        self.embedded_texts.extend(texts)
        return super().embed_memories(texts)


def strategy_with_spy():
    provider = SpyingProvider()
    return (
        HybridRetrievalStrategy(
            semantic_generator=SemanticCandidateGenerator(provider),
            semantic_mode="semantic_only",
        ),
        provider,
    )


def entry(text, status=MemoryStatus.ACTIVE, user="u1"):
    return ExperienceEntry(user_id=user, text=text, status=status)


def _retrieve(strategy, memories, query=QUERY, k=3):
    return strategy.retrieve(
        RetrievalRequest(query=query, memories=tuple(memories), k=k)
    )


def test_forgotten_memory_is_excluded_and_never_embedded():
    strategy, provider = strategy_with_spy()
    forgotten = entry(MATCHING_TEXT, status=MemoryStatus.FORGOTTEN)
    other = entry("budget report due Friday")
    result = _retrieve(strategy, [forgotten, other])
    assert forgotten.id not in {m.id for m in result.selected}
    excluded = next(
        c for c in result.candidates if c.memory.id == forgotten.id
    )
    assert excluded.exclusion_reason == "inactive_forgotten"
    assert excluded.semantic == {"considered": False}
    # The forgotten text was never sent to the provider.
    assert all(MATCHING_TEXT not in text for text in provider.embedded_texts
               if text != QUERY)


def test_superseded_memory_is_excluded_from_current_retrieval():
    strategy, provider = strategy_with_spy()
    superseded = entry(MATCHING_TEXT, status=MemoryStatus.SUPERSEDED)
    result = _retrieve(strategy, [superseded, entry("green tea daily")])
    assert superseded.id not in {m.id for m in result.selected}
    excluded = next(
        c for c in result.candidates if c.memory.id == superseded.id
    )
    assert excluded.exclusion_reason == "inactive_superseded"
    assert excluded.semantic == {"considered": False}
    assert all(MATCHING_TEXT not in t for t in provider.embedded_texts
               if t != QUERY)


def test_similarity_cannot_reactivate_inactive_record():
    strategy, _ = strategy_with_spy()
    superseded = entry(MATCHING_TEXT, status=MemoryStatus.SUPERSEDED)
    _retrieve(strategy, [superseded])
    # Retrieval changed nothing about the record.
    assert superseded.status == MemoryStatus.SUPERSEDED


def test_cross_user_memories_never_reach_the_strategy():
    """User scoping happens at the store: the engine fetches
    ``active_for_user`` / ``list_memories`` per user, so another
    user's high-similarity memory is never in the request pool."""
    store = InMemoryMemoryStore()
    store.add(entry(MATCHING_TEXT, user="intruder"))
    store.add(entry("green tea daily", user="u1"))
    pool = store.active_for_user("u1")
    assert {m.user_id for m in pool} == {"u1"}
    strategy, _ = strategy_with_spy()
    result = _retrieve(strategy, pool)
    assert all(m.user_id == "u1" for m in result.selected)


def test_semantic_summary_counts_only_eligible_memories():
    strategy, _ = strategy_with_spy()
    result = _retrieve(
        strategy,
        [
            entry("green tea daily"),
            entry(MATCHING_TEXT, status=MemoryStatus.FORGOTTEN),
            entry(MATCHING_TEXT, status=MemoryStatus.SUPERSEDED),
        ],
    )
    assert result.semantic["eligible_count"] == 1
    assert result.semantic["scored_count"] == 1
    assert result.inactive_filtered == 2


def test_store_state_identical_after_semantic_retrieval():
    store = InMemoryMemoryStore()
    bus = EventBus()
    store.add(entry("green tea daily"))
    store.add(entry("budget report Friday"))
    snapshot = [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ]
    strategy, _ = strategy_with_spy()
    _retrieve(strategy, store.active_for_user("u1"))
    after = [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ]
    assert after == snapshot
    assert bus.history() == []


def test_no_vectors_written_into_memory_metadata():
    store = InMemoryMemoryStore()
    store.add(entry("green tea daily"))
    strategy, _ = strategy_with_spy()
    _retrieve(strategy, store.active_for_user("u1"))
    for memory in store.list_memories("u1"):
        assert "embedding" not in str(memory.metadata)
        assert "vector" not in str(memory.metadata)


def test_sqlite_backed_memories_behave_identically(tmp_path):
    db = SQLiteMemoryStore(tmp_path / "test.sqlite3")
    db.add(entry("green tea daily"))
    db.add(entry(MATCHING_TEXT, status=MemoryStatus.FORGOTTEN))
    before = [
        (m.id, m.status, m.text) for m in db.list_memories("u1")
    ]
    strategy, _ = strategy_with_spy()
    # The engine only fetches active records for current retrieval;
    # pass the full list here to prove the strategy filter alone holds.
    result = _retrieve(strategy, db.list_memories("u1"))
    assert all(
        m.status == MemoryStatus.ACTIVE for m in result.selected
    )
    assert [
        (m.id, m.status, m.text) for m in db.list_memories("u1")
    ] == before


def test_end_to_end_builder_path_with_semantic_strategy():
    store = InMemoryMemoryStore()
    target = entry("prefers green tea daily")
    store.add(target)
    store.add(entry("budget report due Friday"))
    strategy, _ = strategy_with_spy()
    builder = ContextBuilder(memory_budget=2, retrieval_strategy=strategy)
    built = builder.build_context(
        user_id="u1",
        session_id="s1",
        message="green tea preference",
        memories=store.active_for_user("u1"),
    )
    assert [m.id for m in built.selected_memories] == [target.id]
    rendered = "\n".join(m["content"] for m in built.messages)
    assert "prefers green tea daily" in rendered


def test_semantic_components_hold_no_store_handles():
    import inspect

    from experienceos.context.semantic import SemanticCandidateGenerator
    from experienceos.embeddings.cache import EmbeddingCache

    for cls in (SemanticCandidateGenerator, EmbeddingCache):
        parameters = inspect.signature(cls).parameters
        assert not any(
            "store" in name or "bus" in name or "engine" in name
            or "callback" in name
            for name in parameters
        ), cls.__name__
