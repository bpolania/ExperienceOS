"""Governed action-replacement integration at the engine seam.

These tests drive the real ``ExperienceEngine``, real ``MemoryStore``,
real matcher, plan builder, authorization, and lifecycle admission. Only
the transition coordinator is a controlled stand-in returning what the
real coordinator returns in adopted mode (a verified supersede + create
with ``ACTION_ADDED``), so every mode, fallback, and authorization-
mismatch path can be exercised deterministically.

The invariant under test: when an authorized replacement succeeds, the
engine receives the transition replacement create exactly once and never
the conflicting planner create; on any failure it falls back to the
canonical planner list — never append-both.
"""

from __future__ import annotations

import dataclasses

import pytest

from experienceos import ExperienceOS
from experienceos.memory import ExperienceEntry
from experienceos.memory.schema import MemoryStatus
from experienceos.memory.planner import CREATE, SUPERSEDE, MemoryAction
from experienceos.policy.manager import ExperienceManagerResult
from experienceos.memory.transition_verification import build_before_state
from experienceos.memory.transition_integration import (
    CanonicalActionEffect,
    TransitionIntegrationMode,
)
from experienceos.memory.action_replacement import (
    authorization_from_plan,
    build_replacement,
)
from experienceos.providers import MockProvider

PLANNER_NEW = "I prefer window seats for work trips."
TRANSITION_NEW = "I now prefer window seats for work trips."
OLD_VALUE = "I prefer aisle seats for work trips."
UNRELATED = "I am based in the Denver office."
SCOPED = "I prefer window seats for personal trips."
MESSAGE = "Actually, I now prefer window seats for work trips."


# --- controlled collaborators ------------------------------------------------


class _ListManager:
    policy_mode = "rule_based"

    def __init__(self, actions):
        self._actions = actions

    def plan(self, context):
        return ExperienceManagerResult(actions=list(self._actions), decisions=[])


class _Verification:
    def __init__(self, accepted=True):
        self.accepted = accepted


class _Proposal:
    def __init__(self, proposal_id="prop-1", transition_type="supersede_existing"):
        self.proposal_id = proposal_id
        self.transition_type = transition_type


class _Translation:
    def __init__(self, actions):
        self.succeeded = bool(actions)
        self.actions = tuple(actions)


class _Result:
    def __init__(self, *, mode, effect, sequence, accepted=True,
                 has_proposal=True, transition_type="supersede_existing",
                 as_translation=False):
        self.effective_mode = mode
        self.canonical_action_effect = effect
        self.generated_actions = () if as_translation else tuple(sequence)
        self.translation = _Translation(sequence) if as_translation else None
        self.verification = _Verification(accepted)
        self.proposal = _Proposal(transition_type=transition_type) if has_proposal else None
        self.transition_type = transition_type

    def to_record(self):
        return {"effective_mode": self.effective_mode}


class _Config:
    def __init__(self, replacement_authorizations=()):
        self.replacement_authorizations = tuple(replacement_authorizations)


class _Coordinator:
    def __init__(self, result, *, enabled=True, replacement_authorizations=()):
        self.enabled = enabled
        self.mode = result.effective_mode
        self._result = result
        self.config = _Config(replacement_authorizations)
        self.evaluated = 0

    def evaluate(self, request):
        self.evaluated += 1
        return self._result


# --- helpers -----------------------------------------------------------------


def _create(text, **kw):
    return MemoryAction(action=CREATE, kind="preference", text=text, **kw)


def _default_sequence(target="old.seat"):
    return (
        MemoryAction(action=SUPERSEDE, kind="preference", memory_id=target, text=OLD_VALUE),
        MemoryAction(action=CREATE, kind="preference", text=TRANSITION_NEW, replaces=target),
    )


def _seed(agent, *, old=True):
    if old:
        entry = ExperienceEntry(
            user_id="u", text=OLD_VALUE, kind="preference",
            status=MemoryStatus.ACTIVE, source_session_id="seed",
        )
        entry.id = "old.seat"
        agent.memory_store.add(entry)


def _plan_and_auth(agent, planner_actions, sequence, *, proposal_id="prop-1",
                   transition_type="supersede_existing"):
    before_digest = build_before_state(
        agent.memory_store.active_for_user("u"), user_id="u"
    ).digest()
    _, plan = build_replacement(
        planner_actions, sequence, verification_accepted=True,
        transition_type=transition_type, source_digest="src",
        before_state_digest=before_digest, verified_transition_id=proposal_id,
    )
    return plan, authorization_from_plan(plan)


def _run(mode=TransitionIntegrationMode.ADOPTED,
         effect=CanonicalActionEffect.ACTION_ADDED,
         planner_texts=(PLANNER_NEW, UNRELATED),
         sequence=None, authorize=True, tamper=None, enabled=True,
         seed_old=True, as_translation=False, transition_type="supersede_existing",
         extra_auths=None):
    sequence = _default_sequence() if sequence is None else sequence
    planner_actions = tuple(_create(t) for t in planner_texts)
    agent = ExperienceOS(model=MockProvider())
    _seed(agent, old=seed_old)
    agent.engine.experience_manager = _ListManager(list(planner_actions))

    repl_auths = ()
    if authorize:
        _, auth = _plan_and_auth(agent, planner_actions, sequence,
                                 transition_type=transition_type)
        if tamper is not None:
            auth = dataclasses.replace(auth, **tamper)
        repl_auths = (auth,)
    if extra_auths:
        repl_auths = repl_auths + tuple(extra_auths)

    result = _Result(mode=mode, effect=effect, sequence=sequence,
                     transition_type=transition_type, as_translation=as_translation)
    agent.engine.transition_coordinator = _Coordinator(
        result, enabled=enabled, replacement_authorizations=repl_auths
    )
    agent.chat("u", "s", MESSAGE)
    events = [e for e in agent.event_bus.history()
              if e.type == "transition_integration_evaluated"]
    event = events[-1].payload if events else None
    return agent, event


def _actives(agent):
    return [e for e in agent.memory_store.list_memories("u")
            if e.status == MemoryStatus.ACTIVE]


def _window(agent):
    # The work-trip window value specifically (SCOPED is window/personal).
    return [
        e for e in _actives(agent)
        if "window" in e.text.lower() and "work" in e.text.lower()
    ]


def _superseded(agent):
    return [e for e in agent.memory_store.list_memories("u")
            if e.status == MemoryStatus.SUPERSEDED]


# ======================================================================
# 22.5 Adopted authorized replacement — the core result
# ======================================================================


def test_authorized_replacement_deduplicates() -> None:
    agent, event = _run(planner_texts=(PLANNER_NEW, UNRELATED, SCOPED))
    active = _actives(agent)
    assert len(_window(agent)) == 1  # replacement create only, no duplicate
    assert not any(e.text == PLANNER_NEW for e in active)  # planner create gone
    assert any(e.text == TRANSITION_NEW for e in active)  # transition create once
    assert any(e.text == UNRELATED for e in active)  # unrelated preserved
    assert any(e.text == SCOPED for e in active)  # scoped preserved
    assert any(e.id == "old.seat" for e in _superseded(agent))  # target retired
    assert event["canonical_action_effect"] == CanonicalActionEffect.ACTION_REPLACED
    assert event["action_applied"] is True
    assert event["replacement"]["applied"] is True


def test_replacement_lineage_preserved() -> None:
    agent, _ = _run()
    superseded = _superseded(agent)[0]
    replacement_id = superseded.metadata.get("superseded_by")
    assert replacement_id is not None
    replacement = agent.memory_store.get(replacement_id)
    assert replacement.text == TRANSITION_NEW


# ======================================================================
# 22.1–22.4 Mode semantics
# ======================================================================


def test_disabled_coordinator_never_replaces() -> None:
    agent, event = _run(enabled=False, authorize=True)
    assert event is None  # _evaluate_transition not invoked
    # canonical planner behavior: the planner create remains
    assert any(e.text == PLANNER_NEW for e in _actives(agent))


def test_shadow_projects_without_mutation() -> None:
    agent, event = _run(mode=TransitionIntegrationMode.SHADOW,
                        effect=CanonicalActionEffect.DIAGNOSTICS_ONLY,
                        authorize=False, as_translation=True)
    # runtime planner list unchanged: the planner create is still active,
    # old is NOT superseded, no transition create applied
    assert any(e.text == PLANNER_NEW for e in _actives(agent))
    assert not any(e.text == TRANSITION_NEW for e in _actives(agent))
    assert not _superseded(agent)
    assert event["replacement"]["attempted"] is True
    assert event["replacement"]["applied"] is False
    assert event["replacement"]["plan_status"] == "replacement_plan_ready"


def test_candidate_projects_without_mutation() -> None:
    agent, event = _run(mode=TransitionIntegrationMode.CANDIDATE,
                        effect=CanonicalActionEffect.CANDIDATE_ONLY,
                        authorize=False, as_translation=True)
    assert any(e.text == PLANNER_NEW for e in _actives(agent))
    assert not any(e.text == TRANSITION_NEW for e in _actives(agent))
    assert event["replacement"]["applied"] is False
    assert event["replacement"]["attempted"] is True


# ======================================================================
# 22.6 Missing authorization
# ======================================================================


def test_authorization_present_but_wrong_falls_back_to_planner() -> None:
    # Replacement is engaged (an authorization is configured) but it does
    # not match this plan: fail closed to the canonical planner list —
    # never append-both.
    agent, event = _run(tamper={"plan_digest": "does-not-match"})
    active = _actives(agent)
    assert any(e.text == PLANNER_NEW for e in active)  # planner create kept
    assert not any(e.text == TRANSITION_NEW for e in active)  # not appended
    assert not _superseded(agent)  # old not superseded
    assert event["replacement"]["fallback_used"] is True
    assert event["action_applied"] is False


def test_no_replacement_auth_preserves_existing_append() -> None:
    # With no replacement authorization configured at all, adopted mode
    # keeps the measured add-not-replace behavior (backward compatibility):
    # both work-trip window creates persist.
    agent, event = _run(authorize=False)
    assert len(_window(agent)) == 2  # the measured duplicate is preserved
    assert event["replacement"]["attempted"] is False
    assert event["action_applied"] is True  # append path applied


# ======================================================================
# 22.7 Authorization mismatch matrix
# ======================================================================


@pytest.mark.parametrize(
    "tamper",
    [
        {"plan_digest": "x"},
        {"before_state_digest": "x"},
        {"original_action_list_digest": "x"},
        {"matched_occurrence": ("x", 0, "y")},
        {"replaced_action_digest": "x"},
        {"preserved_occurrences_digest": "x"},
        {"inserted_action_digests": ("x",)},
        {"projected_action_list_digest": "x"},
        {"decision_type": "x"},
        {"verified_transition_id": "x"},
    ],
)
def test_authorization_field_mismatch_rejects(tamper) -> None:
    agent, event = _run(tamper=tamper)
    # Any single mismatched field fails closed to planner fallback.
    assert not _superseded(agent)
    assert any(e.text == PLANNER_NEW for e in _actives(agent))
    assert event["replacement"]["fallback_used"] is True
    assert event["canonical_action_effect"] != CanonicalActionEffect.ACTION_REPLACED


# ======================================================================
# 22.9 / 22.10 Manager / engine admission of the inserted sequence
# ======================================================================


def test_inserted_sequence_rejected_atomically_falls_back() -> None:
    # Supersede a target that is not active: admission rejects, so no
    # partial replacement occurs and the planner create is retained.
    sequence = _default_sequence(target="ghost.id")
    agent, event = _run(sequence=sequence)
    active = _actives(agent)
    assert any(e.text == PLANNER_NEW for e in active)  # planner fallback retained
    assert not any(e.text == TRANSITION_NEW for e in active)  # not appended
    assert not _superseded(agent)  # no partial supersede
    assert event["replacement"]["fallback_used"] is True


# ======================================================================
# 22.11 Preservation
# ======================================================================


def test_unrelated_before_and_after_and_scoped_preserved() -> None:
    agent, _ = _run(
        planner_texts=(UNRELATED, PLANNER_NEW, SCOPED, "I prefer tea in the morning.")
    )
    texts = [e.text for e in _actives(agent)]
    assert UNRELATED in texts
    assert SCOPED in texts
    assert "I prefer tea in the morning." in texts
    assert PLANNER_NEW not in texts  # only the matched create suppressed
    assert TRANSITION_NEW in texts


# ======================================================================
# 22.12 Duplicate prevention
# ======================================================================


def test_transition_create_appears_exactly_once() -> None:
    agent, _ = _run()
    texts = [e.text for e in _actives(agent)]
    assert texts.count(TRANSITION_NEW) == 1


# ======================================================================
# 22.13 Pure-create residual
# ======================================================================


def test_pure_create_transition_is_not_replaced() -> None:
    # A pure create (no supersede) is not a replacement scenario: the
    # existing append path runs, leaving the pure-create residual.
    sequence = (MemoryAction(action=CREATE, kind="preference", text=TRANSITION_NEW),)
    agent, event = _run(sequence=sequence, authorize=False,
                        transition_type="create_new")
    # Not supersede-bearing -> existing append; both window creates persist.
    assert len(_window(agent)) == 2
    assert event["replacement"]["attempted"] is False


# ======================================================================
# 22.15 Single mutation path / purity
# ======================================================================


def test_coordinator_and_plan_components_hold_no_store() -> None:
    from experienceos.memory.action_replacement import (
        ActionReplacementPlanner, ReplacementPlanBuilder,
    )

    for component in (ActionReplacementPlanner(), ReplacementPlanBuilder()):
        for forbidden in ("memory_store", "engine", "experience_manager"):
            assert not hasattr(component, forbidden)


def test_authorized_replacement_is_backward_compatible_event() -> None:
    # Older consumers that ignore the "replacement" key still see a valid
    # transition event with a canonical effect.
    agent, event = _run()
    assert "canonical_action_effect" in event
    assert "replacement" in event  # additive, ignorable by old consumers


# ======================================================================
# Real-coordinator end-to-end on the genuine historical defect case
# ======================================================================


def _real_case_replacement(case_id: str):
    """Drive the genuine adopted stack (real planner, coordinator,
    verifier, authorization) with a replacement authorization, for one
    historical case. No frozen artifact is written."""
    import json
    import pathlib

    from experienceos.policy.base import PolicyContext
    from experienceos.memory.planner import FORGET
    from experienceos.memory.transition_verification import (
        EvidenceMode, TransitionSourceEvidence, build_before_state,
    )
    from experienceos.memory.transition_integration import (
        TransitionIntegrationConfig, TransitionIntegrationCoordinator,
        TransitionIntegrationRequest, translate_transition,
    )
    from benchmarks.transition_benchmark import systems as S

    root = pathlib.Path(__file__).resolve().parents[1]
    path = root / "benchmarks/annotations/transition-verification/historical-scored.jsonl"
    record = next(
        c for c in (json.loads(l) for l in path.read_text().splitlines() if l.strip())
        if c["case_id"] == case_id
    )
    statement = record["source_statement"]
    transition_auth = S._authorization_for(record, statement)

    # Replicate the engine's admitted planner actions and before-state.
    agent = S._seed(record)
    memories = agent.memory_store.active_for_user("u")
    result = agent.engine.experience_manager.plan(
        PolicyContext(user_id="u", session_id="benchmark",
                      message=statement, active_memories=memories)
    )
    active_ids = {m.id for m in memories}
    retired = {
        a.memory_id for a in result.actions
        if a.action in (SUPERSEDE, FORGET) and a.memory_id in active_ids
    }
    planner_actions = tuple(
        a for a in result.actions
        if agent.engine._reject_reason(a, memories, active_ids, retired) is None
    )
    before_digest = build_before_state(memories, user_id="u").digest()

    # Route the real coordinator to get the verified proposal and sequence.
    probe = S._seed(record)
    probe.engine.transition_coordinator = S._coordinator(
        TransitionIntegrationMode.SHADOW
    )
    probe.chat("u", "benchmark", statement)
    request_id = f"benchmark:{S._hook_history_length(probe.event_bus.history())}"
    request = TransitionIntegrationRequest(
        statement=statement,
        evidence=TransitionSourceEvidence(
            source_statement=statement, source_event_id=request_id,
            session_id="benchmark", evidence_mode=EvidenceMode.GROUNDED_VALID,
            provenance_ref="user_asserted",
        ),
        before_state=build_before_state(
            [S._entry_from(m) for m in record["before_state"]], user_id="u"
        ),
        request_id=request_id, user_id="u",
    )
    _, controller_result = S._coordinator(
        TransitionIntegrationMode.ADOPTED
    )._route(request)
    proposal = controller_result.proposal
    verification = controller_result.verification
    sequence = translate_transition(proposal, verification, request.before_state).actions

    _, plan = build_replacement(
        planner_actions, sequence, verification_accepted=True,
        transition_type=proposal.transition_type,
        source_digest=request.source_digest(), before_state_digest=before_digest,
        verified_transition_id=str(proposal.proposal_id or ""),
    )
    replacement_auth = authorization_from_plan(plan)

    final = S._seed(record)
    final.engine.transition_coordinator = TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(
            mode=TransitionIntegrationMode.ADOPTED,
            authorizations=(transition_auth,),
            replacement_authorizations=(replacement_auth,),
        )
    )
    final.chat("u", "benchmark", statement)
    return final, S


def test_real_historical_case_deduplicates_through_replacement() -> None:
    case_id = (
        "transition:lifecycle:"
        "updates_001_preference_replacement_cross_session:supersede_existing"
    )
    final, systems = _real_case_replacement(case_id)
    entries = final.memory_store.list_memories("u")
    active = [e for e in entries if e.status == MemoryStatus.ACTIVE]
    superseded = [e for e in entries if e.status == MemoryStatus.SUPERSEDED]
    duplicates, _ = systems._pairs(active)
    event = [
        e for e in final.event_bus.history()
        if e.type == "transition_integration_evaluated"
    ][-1].payload

    assert duplicates == 0  # the applied duplicate is gone (was 1)
    assert len(superseded) == 1  # the old value is retired
    assert event["canonical_action_effect"] == CanonicalActionEffect.ACTION_REPLACED
    assert event["replacement"]["applied"] is True
