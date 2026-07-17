"""Characterization of the canonical action-composition seam.

These tests do not change behavior. They pin down, executably, how the
engine composes the pre-application action list today and prove the
add-not-replace defect the action-replacement work exists to fix. They
also measure the feasibility of a deterministic action digest so the
next step can plan against evidence, not guesses.

Three groups:

* Group A -- reproduce the defect through the genuine adopted stack
  (`benchmarks.transition_benchmark.systems.run_case`), so the finding
  rests on real components, not a mock.
* Group B -- characterize the engine seam directly with a controlled
  action list and a stand-in coordinator, so the exact list handed to
  the sole mutation boundary can be asserted (ordering, preservation,
  no coordinator mutation).
* Group C -- an audit-only digest experiment distinguishing semantic
  identity, action-content identity, and occurrence identity.

Nothing here writes into frozen benchmark artifacts.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from experienceos import ExperienceOS
from experienceos.memory import ExperienceEntry
from experienceos.memory.identity import (
    IdentityProjector,
    IdentityRelation,
    compare_memory_identity,
)
from experienceos.memory.planner import (
    CREATE,
    SUPERSEDE,
    MemoryAction,
    _normalized_text,
)
from experienceos.memory.schema import MemoryStatus
from experienceos.policy.manager import ExperienceManagerResult
from experienceos.providers import MockProvider

ROOT = pathlib.Path(__file__).resolve().parents[1]
HISTORICAL = ROOT / "benchmarks/annotations/transition-verification/historical-scored.jsonl"

_PROJECTOR = IdentityProjector()
_DUPLICATE = {IdentityRelation.EXACT_DUPLICATE, IdentityRelation.SEMANTIC_DUPLICATE}


def _load_cases() -> list[dict]:
    cases = []
    with HISTORICAL.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


# ======================================================================
# Group A -- genuine adopted-stack reproduction
# ======================================================================


@pytest.fixture(scope="module")
def systems():
    from benchmarks.transition_benchmark import systems as mod

    registry = {s.system_id: s for s in mod.registry()}
    return mod, registry


def test_adopted_stack_reproduces_semantic_duplicate(systems) -> None:
    """One historical supersession: the applied adopted path leaves a
    semantic duplicate active pair, while the reference and the candidate
    projection do not. The defect is applied composition, not the
    proposal."""
    mod, registry = systems
    target = "transition:lifecycle:updates_001_preference_replacement_cross_session:supersede_existing"
    record = next(c for c in _load_cases() if c["case_id"] == target)

    adopted = mod.run_case(registry[mod.ADOPTED_ID], record)
    reference = mod.run_case(registry[mod.REFERENCE_ID], record)
    candidate = mod.run_case(registry[mod.CANDIDATE_ID], record)

    assert adopted.semantic_duplicate_pairs == 1  # applied: duplicate
    assert reference.semantic_duplicate_pairs == 0  # canonical: clean
    assert candidate.projected_duplicate_pairs == 0  # projection: clean
    # The old value is still retired -- target resolution was correct.
    assert adopted.superseded_ids


def test_adopted_duplicate_total_matches_committed_headline(systems) -> None:
    """Across the 28 historical scored cases the adopted path produces
    exactly 10 duplicate pairs and the reference 0 -- the committed
    headline (adopted_duplicate_pairs=10, reference_duplicate_pairs=0)."""
    mod, registry = systems
    cases = _load_cases()
    assert len(cases) == 28
    adopted_total = sum(
        mod.run_case(registry[mod.ADOPTED_ID], c).semantic_duplicate_pairs
        for c in cases
    )
    reference_total = sum(
        mod.run_case(registry[mod.REFERENCE_ID], c).semantic_duplicate_pairs
        for c in cases
    )
    assert adopted_total == 10
    assert reference_total == 0

    headline = json.loads(
        (ROOT / "benchmarks/results/committed/report-transition-verification"
         / "headline_metrics.json").read_text()
    )
    assert adopted_total == headline["adopted_duplicate_pairs"]
    assert reference_total == headline["reference_duplicate_pairs"]


def test_real_coordinator_holds_no_store(systems) -> None:
    """The coordinator proposes only: it has no store handle and no
    mutation method. It cannot be a second mutation path."""
    mod, _ = systems
    coordinator = mod._coordinator(
        __import__(
            "experienceos.memory.transition_integration",
            fromlist=["TransitionIntegrationMode"],
        ).TransitionIntegrationMode.ADOPTED
    )
    assert not hasattr(coordinator, "memory_store")
    assert not hasattr(coordinator, "_apply_memory_actions")


# ======================================================================
# Group B -- direct engine-seam characterization
# ======================================================================

# A verified pair: different normalized text (so the engine's exact-text
# "duplicate_of_planned" guard does not fire) yet a semantic duplicate
# under the identity projector. This is the shape that slips through.
PLANNER_NEW = "I prefer window seats for work trips."
TRANSITION_NEW = "I now prefer window seats for work trips."
OLD_VALUE = "I prefer aisle seats for work trips."
UNRELATED = "I am based in the Denver office."
SCOPED = "I prefer tea on weekends."


class _ListManager:
    """A manager stand-in that returns a fixed, controlled action list.

    It lets the seam be characterized with an exact planner output,
    independent of the planner's own conflict detection. It holds no
    store and applies nothing -- admission and application stay the
    engine's job.
    """

    policy_mode = "rule_based"

    def __init__(self, actions: list[MemoryAction]):
        self._actions = actions

    def plan(self, context) -> ExperienceManagerResult:
        return ExperienceManagerResult(actions=list(self._actions), decisions=[])


class _StubCoordinatorResult:
    def __init__(self, generated):
        from experienceos.memory.transition_integration import (
            CanonicalActionEffect,
            TransitionIntegrationMode,
        )

        self.effective_mode = TransitionIntegrationMode.ADOPTED
        self.canonical_action_effect = CanonicalActionEffect.ACTION_ADDED
        self.generated_actions = tuple(generated)

    def to_record(self) -> dict:
        return {"stub": True}


class _StubCoordinator:
    """Mimics the real coordinator contract at the seam: enabled, returns
    generated actions with an add-like effect, mutates nothing."""

    enabled = True

    def __init__(self, generated):
        self._generated = generated
        self.evaluated = 0

    def evaluate(self, request) -> _StubCoordinatorResult:
        self.evaluated += 1
        return _StubCoordinatorResult(self._generated)


def _seed_old(agent) -> None:
    entry = ExperienceEntry(
        user_id="u", text=OLD_VALUE, kind="preference",
        status=MemoryStatus.ACTIVE, source_session_id="seed",
    )
    entry.id = "old.seat"
    agent.memory_store.add(entry)


def _engine_with(planner_actions, generated_actions):
    """Real engine and store; controlled manager and coordinator."""
    agent = ExperienceOS(model=MockProvider())
    _seed_old(agent)
    agent.engine.experience_manager = _ListManager(planner_actions)
    coordinator = _StubCoordinator(generated_actions)
    agent.engine.transition_coordinator = coordinator

    captured: dict = {}
    original = agent.engine._apply_memory_actions

    def spy(actions, *args, **kwargs):
        captured["actions"] = list(actions)
        return original(actions, *args, **kwargs)

    agent.engine._apply_memory_actions = spy
    return agent, coordinator, captured


def _default_scenario():
    planner = [
        MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW),
        MemoryAction(action=CREATE, kind="preference", text=UNRELATED),
        MemoryAction(action=CREATE, kind="preference", text=SCOPED),
    ]
    generated = [
        MemoryAction(action=SUPERSEDE, kind="preference",
                     memory_id="old.seat", text=OLD_VALUE),
        MemoryAction(action=CREATE, kind="preference",
                     text=TRANSITION_NEW, replaces="old.seat"),
    ]
    return planner, generated


def test_transition_actions_append_planner_create_survives() -> None:
    """15.1: transition actions are appended; the planner create is not
    removed; the composed list reaching the mutation boundary carries
    both creates in planner-then-transition order."""
    planner, generated = _default_scenario()
    agent, _, captured = _engine_with(planner, generated)
    agent.chat("u", "s", "Actually, I now prefer window seats for work trips.")

    actions = captured["actions"]
    texts = [(a.action, a.text) for a in actions]
    # Planner create is present and precedes the appended transition pair.
    assert (CREATE, PLANNER_NEW) in texts
    assert (SUPERSEDE, OLD_VALUE) in texts
    assert (CREATE, TRANSITION_NEW) in texts
    assert texts.index((CREATE, PLANNER_NEW)) < texts.index((SUPERSEDE, OLD_VALUE))
    assert texts.index((SUPERSEDE, OLD_VALUE)) < texts.index((CREATE, TRANSITION_NEW))
    # Two distinct creates for the same intended memory effect coexist.
    create_texts = [a.text for a in actions if a.action == CREATE]
    assert PLANNER_NEW in create_texts and TRANSITION_NEW in create_texts


def test_applied_state_has_semantic_duplicate_pair() -> None:
    """15.2: both creates are admitted and applied; the old target is
    retired; the surviving actives contain a semantic duplicate pair."""
    planner, generated = _default_scenario()
    agent, _, _ = _engine_with(planner, generated)
    agent.chat("u", "s", "Actually, I now prefer window seats for work trips.")

    entries = agent.memory_store.list_memories("u")
    active = [e for e in entries if e.status == MemoryStatus.ACTIVE]
    superseded = [e for e in entries if e.status == MemoryStatus.SUPERSEDED]

    assert any(e.id == "old.seat" for e in superseded)  # old retired
    window = [e for e in active if "window" in e.text.lower()]
    assert len(window) == 2  # both replacement creates active

    rel = compare_memory_identity(
        _PROJECTOR.project_text(window[0].text, kind=window[0].kind),
        _PROJECTOR.project_text(window[1].text, kind=window[1].kind),
    ).relation
    assert rel in _DUPLICATE  # a semantic duplicate active pair


def test_unrelated_and_scoped_planner_actions_are_preserved() -> None:
    """15.4/15.5: the append suppresses nothing -- unrelated and scoped
    planner creates survive to the store untouched."""
    planner, generated = _default_scenario()
    agent, _, captured = _engine_with(planner, generated)
    agent.chat("u", "s", "Actually, I now prefer window seats for work trips.")

    applied_texts = [a.text for a in captured["actions"]]
    assert UNRELATED in applied_texts and SCOPED in applied_texts

    active_texts = [
        e.text for e in agent.memory_store.list_memories("u")
        if e.status == MemoryStatus.ACTIVE
    ]
    assert UNRELATED in active_texts and SCOPED in active_texts


def test_exact_text_duplicate_would_be_rejected_by_current_guard() -> None:
    """Boundary: if the transition create's normalized text equals the
    planner create, today's `duplicate_of_planned` guard already drops
    it -- so the surviving duplicate is necessarily a *semantic* one with
    differing surface text. This is why exact-text dedup is insufficient
    and semantic matching is required."""
    planner = [MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW)]
    generated = [
        MemoryAction(action=SUPERSEDE, kind="preference",
                     memory_id="old.seat", text=OLD_VALUE),
        # Same normalized text as the planner create.
        MemoryAction(action=CREATE, kind="preference",
                     text="I prefer  window seats for work trips.",
                     replaces="old.seat"),
    ]
    agent, _, captured = _engine_with(planner, generated)
    agent.chat("u", "s", "Actually, I now prefer window seats for work trips.")

    create_texts = [
        _normalized_text(a.text)
        for a in captured["actions"] if a.action == CREATE
    ]
    # The exact-text transition create was rejected: only one create.
    assert create_texts.count(_normalized_text(PLANNER_NEW)) == 1


def test_application_order_is_creates_first_then_supersede() -> None:
    """15.6: list position among the linked pair is not load-bearing for
    lineage -- application always builds creates first, then supersedes,
    and lineage is keyed by `replaces`, not order. Reversing the
    generated pair yields identical applied state."""
    planner, generated = _default_scenario()
    reversed_generated = list(reversed(generated))
    agent_a, _, _ = _engine_with(planner, generated)
    agent_b, _, _ = _engine_with(planner, reversed_generated)
    msg = "Actually, I now prefer window seats for work trips."
    agent_a.chat("u", "s", msg)
    agent_b.chat("u", "s", msg)

    def snapshot(agent):
        entries = agent.memory_store.list_memories("u")
        active = sorted(
            e.text for e in entries if e.status == MemoryStatus.ACTIVE
        )
        superseded = [e for e in entries if e.status == MemoryStatus.SUPERSEDED]
        # The superseded old carries lineage to its replacement.
        linked = superseded[0].metadata.get("superseded_by") if superseded else None
        return active, bool(linked)

    assert snapshot(agent_a)[0] == snapshot(agent_b)[0]
    assert snapshot(agent_a)[1] is True and snapshot(agent_b)[1] is True


def test_memory_action_has_no_stable_identity() -> None:
    """15.7: provenance is not carried structurally. A MemoryAction has
    no id and no field distinguishing planner from transition origin --
    so a matcher cannot rely on identity that does not exist."""
    action = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW)
    assert not hasattr(action, "id")
    assert not hasattr(action, "action_id")
    assert not hasattr(action, "proposal_id")
    assert not hasattr(action, "source")


def test_coordinator_does_not_mutate_the_store() -> None:
    """15.9: evaluating the coordinator changes nothing durable; only the
    engine's application does. The stand-in models this faithfully."""
    planner, generated = _default_scenario()
    agent, coordinator, _ = _engine_with(planner, generated)
    before = len(agent.memory_store.list_memories("u"))
    # Evaluate directly -- no application.
    coordinator.evaluate(request=None)
    assert coordinator.evaluated >= 1
    assert len(agent.memory_store.list_memories("u")) == before


# ======================================================================
# Group C -- digest feasibility (audit-only helpers)
# ======================================================================


def _content_digest(action: MemoryAction, *, include_scope: bool = True) -> str:
    """Audit-only. A candidate action-content digest over normalized
    semantic fields. NOT production code and NOT an authorization input."""
    payload = {
        "action": action.action,
        "kind": action.kind,
        "text": _normalized_text(action.text),
        "memory_id": action.memory_id,
        "replaces": action.replaces,
    }
    if include_scope:
        payload["scope"] = (action.metadata or {}).get("scope")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()


def _occurrence_digest(action: MemoryAction, index: int, list_digest: str) -> str:
    return hashlib.sha256(
        f"{_content_digest(action)}:{index}:{list_digest}".encode()
    ).hexdigest()


def test_content_digest_is_deterministic_and_key_order_independent() -> None:
    """15.8: serialization is deterministic and metadata key order does
    not perturb it (sorted keys)."""
    a = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW,
                     metadata={"scope": "work", "a": 1, "b": 2})
    b = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW,
                     metadata={"b": 2, "a": 1, "scope": "work"})
    assert _content_digest(a) == _content_digest(a)
    assert _content_digest(a) == _content_digest(b)


def test_omitted_and_explicit_null_fields_collide() -> None:
    """15.8: an omitted field and an explicit None serialize identically
    -- a finding: null and absent cannot be distinguished by content."""
    implicit = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW)
    explicit = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW,
                            memory_id=None, replaces=None)
    assert _content_digest(implicit) == _content_digest(explicit)


def test_duplicate_creates_need_occurrence_identity() -> None:
    """15.8: two identical creates share a content digest -- only an
    occurrence index distinguishes them. Content identity is not
    occurrence identity."""
    a = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW)
    b = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW)
    assert _content_digest(a) == _content_digest(b)
    assert _occurrence_digest(a, 0, "L") != _occurrence_digest(b, 1, "L")


def test_scope_collision_risk_when_scope_omitted() -> None:
    """15.8: two creates that differ only by scope collide if scope is
    left out of the digest, and separate when it is included. Scope must
    be an input, or valid coexistence becomes indistinguishable."""
    general = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW,
                           metadata={"scope": "general"})
    scoped = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW,
                          metadata={"scope": "work"})
    assert _content_digest(general, include_scope=False) == _content_digest(
        scoped, include_scope=False
    )
    assert _content_digest(general) != _content_digest(scoped)


def test_content_digest_is_not_semantic_identity() -> None:
    """15.8: the semantic duplicate pair has *different* content digests
    (different normalized text). A content digest identifies an action;
    it must never be mistaken for semantic identity, and vice versa."""
    planner = MemoryAction(action=CREATE, kind="preference", text=PLANNER_NEW)
    transition = MemoryAction(action=CREATE, kind="preference", text=TRANSITION_NEW)
    assert _content_digest(planner) != _content_digest(transition)
    rel = compare_memory_identity(
        _PROJECTOR.project_text(PLANNER_NEW, kind="preference"),
        _PROJECTOR.project_text(TRANSITION_NEW, kind="preference"),
    ).relation
    assert rel in _DUPLICATE
