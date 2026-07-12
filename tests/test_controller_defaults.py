"""Phase 11 Prompt 6: deterministic default controller tests."""

import os
import subprocess
import sys

from experienceos.controllers import (
    AbstainingAdmissionController,
    AbstainingTransitionVerifier,
    AbstainingUpdateController,
    AdmissionEvidence,
    ExtractionEvidence,
    ForgetIntentEvidence,
    MemorySnapshot,
    NoForgetIntentController,
    NoOpExtractionController,
    ProposedMemoryCandidate,
    TransitionEvidence,
    UpdateEvidence,
)

SNAPSHOT = MemorySnapshot(
    memory_id="m1", kind="fact", text="lives in Porto", status="active"
)
CANDIDATE = ProposedMemoryCandidate(kind="fact", text="lives in Lisbon")


def _all_default_proposals():
    return [
        AbstainingAdmissionController().evaluate(
            AdmissionEvidence(user_message="I moved to Lisbon")
        ),
        NoOpExtractionController().extract(
            ExtractionEvidence(user_text="I moved to Lisbon")
        ),
        AbstainingUpdateController().evaluate(
            UpdateEvidence(candidate=CANDIDATE, existing=SNAPSHOT)
        ),
        NoForgetIntentController().evaluate(
            ForgetIntentEvidence(
                user_message="forget my old city",
                candidate_memories=(SNAPSHOT,),
            )
        ),
        AbstainingTransitionVerifier().verify(
            TransitionEvidence(
                transition_type="supersede", target_state="superseded",
                memory=SNAPSHOT,
            )
        ),
    ]


def test_default_controller_ids_are_stable():
    assert [p.controller_id for p in _all_default_proposals()] == [
        "admission_abstain-1",
        "extraction_noop-1",
        "update_abstain-1",
        "forget_intent_none-1",
        "transition_abstain-1",
    ]


def test_defaults_never_volunteer_actions():
    admission, extraction, update, forget, transition = (
        _all_default_proposals()
    )
    assert admission.recommendation == "abstain"
    assert extraction.recommendation == "none"
    assert extraction.candidate is None
    assert update.relationship == "abstain"
    assert update.target_memory_id is None
    assert update.proposed_text is None
    assert forget.recommendation == "no_forget_intent"
    assert forget.target_memory_ids == ()
    # Abstain, deliberately not pass-through: "approve" must never be
    # mistaken for applied or authorized.
    assert transition.recommendation == "abstain"


def test_defaults_are_deterministic_across_calls_and_instances():
    assert _all_default_proposals() == _all_default_proposals()


def test_defaults_are_deterministic_across_processes_and_hashseeds():
    script = (
        "from tests.test_controller_defaults import "
        "_all_default_proposals\n"
        "print(repr(_all_default_proposals()))\n"
    )
    outputs = set()
    for seed in ("0", "777"):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
            env=dict(os.environ, PYTHONPATH=".", PYTHONHASHSEED=seed),
        )
        outputs.add(completed.stdout.strip())
    assert len(outputs) == 1
    assert repr(_all_default_proposals()) in outputs


def test_extraction_default_constructs_no_memory_shapes():
    proposal = NoOpExtractionController().extract(
        ExtractionEvidence(user_text="my birthday is in June")
    )
    assert proposal.candidate is None
    assert proposal.recommendation == "none"
    # Reasons make the interface-only status explicit.
    assert "interface-only" in proposal.reason


def test_memory_gate_defaults_unchanged_by_prompt6():
    from experienceos.controllers import (
        GateCandidateEvidence,
        HeuristicShadowMemoryGate,
        PassThroughMemoryGate,
    )

    assert PassThroughMemoryGate.controller_id == "gate_pass_through-1"
    assert HeuristicShadowMemoryGate.controller_id == (
        "gate_shadow_heuristic-1"
    )
    proposal = PassThroughMemoryGate().evaluate(
        GateCandidateEvidence(
            query="q", memory_id="m", memory_kind="fact",
            memory_text="t", lifecycle_status="active",
            canonical_selected=True, canonical_rank=1,
            exclusion_reason=None, token_estimate=1,
        )
    )
    assert proposal.proposal == "admit"
    assert proposal.shadow_mode is True
    assert proposal.affected_selection is False
