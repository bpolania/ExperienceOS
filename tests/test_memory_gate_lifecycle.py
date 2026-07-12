"""Phase 11 Prompt 5: gate lifecycle safety and store isolation.

A poisoned gate fails the test if any lifecycle-excluded memory ID
ever reaches evaluation — excluded records carry maximum lexical and
semantic evidence (their text is the query) to make any ordering
defect visible.
"""

from experienceos.context.retrieval import (
    HybridRetrievalStrategy,
    RetrievalRequest,
)
from experienceos.context.semantic import SemanticCandidateGenerator
from experienceos.controllers.gate import (
    GateProposal,
    PassThroughMemoryGate,
)
from experienceos.embeddings import DeterministicEmbeddingProvider
from experienceos.events.bus import EventBus
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.store import InMemoryMemoryStore
from experienceos.memory.temporal import TemporalRetrievalPolicy

QUERY = "favorite green tea ritual"


def entry(text, status=MemoryStatus.ACTIVE, user="u1"):
    return ExperienceEntry(user_id=user, text=text, status=status)


class PoisonedForExcludedGate:
    """Fails hard if it sees an ID from the excluded set."""

    controller_id = "gate_test_poisoned-1"

    def __init__(self, excluded_ids):
        self.excluded_ids = set(excluded_ids)
        self.seen_ids = []

    def evaluate(self, evidence):
        assert evidence.memory_id not in self.excluded_ids, (
            f"lifecycle-excluded memory {evidence.memory_id} reached "
            "the gate"
        )
        self.seen_ids.append(evidence.memory_id)
        return GateProposal(
            proposal="admit", score=1.0, confidence=1.0, reason="ok",
            controller_id=self.controller_id,
        )


def fused_with_gate(gate):
    return HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            DeterministicEmbeddingProvider()
        ),
        semantic_mode="fused",
        memory_gate=gate,
    )


def test_excluded_memories_never_reach_gate():
    forgotten = entry(QUERY, status=MemoryStatus.FORGOTTEN)
    superseded = entry(QUERY, status=MemoryStatus.SUPERSEDED)
    active = entry("prefers green tea daily")
    gate = PoisonedForExcludedGate({forgotten.id, superseded.id})
    result = fused_with_gate(gate).retrieve(
        RetrievalRequest(
            query=QUERY, memories=(forgotten, superseded, active), k=2
        )
    )
    assert gate.seen_ids == [active.id]
    for candidate in result.candidates:
        if candidate.memory.id in {forgotten.id, superseded.id}:
            assert candidate.gate == {"considered": False}
            assert candidate.exclusion_reason.startswith("inactive_")


def test_zero_evidence_and_prelimit_exclusions_not_gated():
    active_noise = entry("unrelated budget spreadsheet")
    gate = PoisonedForExcludedGate({active_noise.id})
    fused_with_gate(gate).retrieve(
        RetrievalRequest(
            query=QUERY,
            memories=(entry("prefers green tea daily"), active_noise),
            k=2,
        )
    )
    # no_fused_evidence records are eligible but unranked: not gated.
    assert active_noise.id not in gate.seen_ids


def test_cross_user_memories_never_reach_gate():
    store = InMemoryMemoryStore()
    intruder = entry(QUERY, user="intruder")
    store.add(intruder)
    store.add(entry("prefers green tea daily", user="u1"))
    gate = PoisonedForExcludedGate({intruder.id})
    fused_with_gate(gate).retrieve(
        RetrievalRequest(
            query=QUERY, memories=store.active_for_user("u1"), k=2
        )
    )
    assert intruder.id not in gate.seen_ids


def test_forgotten_excluded_under_historical_intent():
    forgotten = entry("previous drink was coffee",
                      status=MemoryStatus.FORGOTTEN)
    superseded = entry("previous drink was coffee",
                       status=MemoryStatus.SUPERSEDED)
    active = entry("drinks green tea now")
    gate = PoisonedForExcludedGate({forgotten.id})
    strategy = HybridRetrievalStrategy(
        temporal_policy=TemporalRetrievalPolicy(
            reference_time="2026-01-01"
        ),
        memory_gate=gate,
    )
    result = strategy.retrieve(
        RetrievalRequest(
            query="what did I previously drink",
            memories=(forgotten, superseded, active),
            k=3,
        )
    )
    # Forgotten never reaches the gate even under historical intent;
    # a temporally admitted superseded record is canonically eligible
    # and MAY be gate-evaluated — that is the existing audited door.
    assert forgotten.id not in gate.seen_ids
    forgotten_candidate = next(
        c for c in result.candidates if c.memory.id == forgotten.id
    )
    assert forgotten_candidate.gate == {"considered": False}


def test_gate_cannot_change_status_or_exclusion_reason():
    superseded = entry(QUERY, status=MemoryStatus.SUPERSEDED)
    result = fused_with_gate(PassThroughMemoryGate()).retrieve(
        RetrievalRequest(
            query=QUERY,
            memories=(superseded, entry("prefers green tea daily")),
            k=2,
        )
    )
    assert superseded.status == MemoryStatus.SUPERSEDED  # unchanged
    candidate = next(
        c for c in result.candidates if c.memory.id == superseded.id
    )
    assert candidate.exclusion_reason == "inactive_superseded"


def test_store_and_events_untouched_by_gate_evaluation():
    store = InMemoryMemoryStore()
    bus = EventBus()
    store.add(entry("prefers green tea daily"))
    store.add(entry(QUERY, status=MemoryStatus.FORGOTTEN))
    before = [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ]
    fused_with_gate(PassThroughMemoryGate()).retrieve(
        RetrievalRequest(
            query=QUERY, memories=store.list_memories("u1"), k=2
        )
    )
    assert [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ] == before
    assert bus.history() == []
    for memory in store.list_memories("u1"):
        text = str(memory.metadata)
        assert "gate" not in text and "proposal" not in text


def test_gate_constructors_accept_no_authority_handles():
    import inspect

    from experienceos.controllers.gate import (
        HeuristicShadowMemoryGate,
        PassThroughMemoryGate,
    )

    for cls in (PassThroughMemoryGate, HeuristicShadowMemoryGate):
        parameters = inspect.signature(cls).parameters
        assert not any(
            token in name
            for name in parameters
            for token in ("store", "engine", "manager", "bus",
                          "callback", "session")
        ), cls.__name__
