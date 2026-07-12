"""Phase 11 Prompt 6: controller contract and validation tests."""

import dataclasses
import json

import pytest

from experienceos.controllers import (
    AbstainingAdmissionController,
    AbstainingTransitionVerifier,
    AbstainingUpdateController,
    AdmissionEvidence,
    AdmissionProposal,
    ControllerInputError,
    ControllerProposalError,
    EvidenceSpan,
    ExtractionEvidence,
    ExtractionProposal,
    ForgetIntentEvidence,
    ForgetIntentProposal,
    MemorySnapshot,
    NoForgetIntentController,
    NoOpExtractionController,
    ProposedMemoryCandidate,
    TransitionEvidence,
    TransitionProposal,
    UpdateEvidence,
    UpdateProposal,
)

SNAPSHOT = MemorySnapshot(
    memory_id="m1", kind="fact", text="lives in Porto", status="active",
    tags=("location",), attribute="residence", value="porto",
)
CANDIDATE = ProposedMemoryCandidate(
    kind="fact", text="lives in Lisbon", confidence=0.8,
)


def _proposal_kwargs(**overrides):
    base = dict(score=0.5, confidence=0.5, reason="r",
                controller_id="test-1")
    base.update(overrides)
    return base


# -- protocols and API surface ----------------------------------------------------


def test_defaults_satisfy_protocols_and_expose_no_mutation_api():
    from experienceos.controllers import (
        PassThroughMemoryGate,
    )

    controllers = {
        AbstainingAdmissionController(): "evaluate",
        NoOpExtractionController(): "extract",
        AbstainingUpdateController(): "evaluate",
        NoForgetIntentController(): "evaluate",
        AbstainingTransitionVerifier(): "verify",
        PassThroughMemoryGate(): "evaluate",
    }
    forbidden = {
        "apply", "commit", "persist", "save", "forget", "update_memory",
        "transition_memory", "delete", "mutate", "execute_action",
        "admit_memory", "reject_memory", "select_context",
    }
    for controller, method in controllers.items():
        public = {n for n in dir(controller) if not n.startswith("_")}
        assert public == {"controller_id", method}, type(controller)
        assert not public & forbidden


def test_no_controller_registry_exists():
    import experienceos.controllers as pkg

    assert not any(
        "registry" in name.lower() or "Registry" in name
        for name in dir(pkg)
    )


# -- evidence validation ----------------------------------------------------------


def test_memory_snapshot_validation():
    with pytest.raises(ControllerInputError):
        MemorySnapshot(memory_id="", kind="fact", text="t",
                       status="active")
    with pytest.raises(ControllerInputError):
        MemorySnapshot(memory_id="m", kind="opinion", text="t",
                       status="active")
    with pytest.raises(ControllerInputError):
        MemorySnapshot(memory_id="m", kind="fact", text="t",
                       status="deleted")
    bounded = MemorySnapshot(
        memory_id="m", kind="fact", text="x" * 5000, status="active"
    )
    assert len(bounded.text) == 2000
    with pytest.raises(Exception):
        SNAPSHOT.status = "forgotten"  # frozen


def test_evidence_span_validation():
    span = EvidenceSpan(source="user", start=0, end=5, excerpt="hello")
    assert span.end == 5
    with pytest.raises(ControllerInputError):
        EvidenceSpan(source="system", start=0, end=5)
    with pytest.raises(ControllerInputError):
        EvidenceSpan(source="user", start=-1, end=5)
    with pytest.raises(ControllerInputError):
        EvidenceSpan(source="user", start=5, end=5)
    with pytest.raises(ControllerInputError):
        EvidenceSpan(source="user", start=0, end=5, excerpt="x" * 500)


def test_admission_evidence_validation():
    evidence = AdmissionEvidence(
        user_message="x" * 5000, metadata={"turn": 3}
    )
    assert len(evidence.user_message) == 2000
    with pytest.raises(ControllerInputError):
        AdmissionEvidence(user_message="hi", active_memory_count=-1)
    with pytest.raises(ControllerInputError):
        AdmissionEvidence(user_message="hi", metadata={"o": object()})
    with pytest.raises(Exception):
        evidence.user_message = "changed"  # frozen


def test_extraction_evidence_and_candidate_validation():
    with pytest.raises(ControllerInputError):
        ExtractionEvidence(user_text="hi", source_role="system")
    with pytest.raises(ControllerInputError):
        ProposedMemoryCandidate(kind="fact", text="   ")
    with pytest.raises(ControllerInputError):
        ProposedMemoryCandidate(kind="opinion", text="t")
    with pytest.raises(ControllerInputError):
        ProposedMemoryCandidate(
            kind="fact", text="t", evidence_spans=("not a span",)
        )
    with pytest.raises(ControllerProposalError):
        ProposedMemoryCandidate(kind="fact", text="t", confidence=1.5)
    # A candidate is deliberately NOT a memory record.
    fields = {f.name for f in dataclasses.fields(ProposedMemoryCandidate)}
    assert "id" not in fields
    assert "status" not in fields
    assert "created_at" not in fields
    assert "metadata" not in fields


def test_update_evidence_validation():
    with pytest.raises(ControllerInputError):
        UpdateEvidence(candidate="not a candidate", existing=SNAPSHOT)
    with pytest.raises(ControllerInputError):
        UpdateEvidence(candidate=CANDIDATE, existing="not a snapshot")
    with pytest.raises(ControllerInputError):
        UpdateEvidence(
            candidate=CANDIDATE, existing=SNAPSHOT,
            similarity_signals={"overlap": float("nan")},
        )
    evidence = UpdateEvidence(
        candidate=CANDIDATE, existing=SNAPSHOT,
        similarity_signals={"overlap": 0.7},
    )
    assert evidence.similarity_signals == {"overlap": 0.7}


def test_forget_evidence_validation():
    with pytest.raises(ControllerInputError):
        ForgetIntentEvidence(
            user_message="forget it", candidate_memories=("no",)
        )
    evidence = ForgetIntentEvidence(
        user_message="forget my old city",
        candidate_memories=(SNAPSHOT,),
        detected_phrases=("forget",),
    )
    assert evidence.candidate_memories[0].memory_id == "m1"


def test_transition_evidence_validation():
    with pytest.raises(ControllerInputError):
        TransitionEvidence(transition_type="promote",
                           target_state="active")
    with pytest.raises(ControllerInputError):
        TransitionEvidence(transition_type="forget",
                           target_state="deleted", memory=SNAPSHOT)
    with pytest.raises(ControllerInputError):
        # supersede/forget require a memory snapshot.
        TransitionEvidence(transition_type="supersede",
                           target_state="superseded")
    create = TransitionEvidence(
        transition_type="create", target_state="active",
        candidate=CANDIDATE,
    )
    assert create.memory is None


# -- proposal validation ----------------------------------------------------------


def test_admission_proposal_validation():
    with pytest.raises(ControllerProposalError):
        AdmissionProposal(recommendation="approve", **_proposal_kwargs())
    with pytest.raises(ControllerProposalError):
        AdmissionProposal(
            recommendation="admit",
            **_proposal_kwargs(score=float("nan")),
        )
    with pytest.raises(ControllerProposalError):
        AdmissionProposal(
            recommendation="admit", **_proposal_kwargs(confidence=2.0)
        )
    with pytest.raises(ControllerProposalError):
        AdmissionProposal(
            recommendation="admit",
            **_proposal_kwargs(reason="x" * 301),
        )
    with pytest.raises(ControllerProposalError):
        AdmissionProposal(
            recommendation="admit",
            **_proposal_kwargs(diagnostics={"o": object()}),
        )
    with pytest.raises(ControllerProposalError):
        AdmissionProposal(
            recommendation="admit",
            proposal_only=False,
            **_proposal_kwargs(),
        )


def test_extraction_proposal_consistency():
    with pytest.raises(ControllerProposalError):
        ExtractionProposal(
            recommendation="candidate", candidate=None,
            **_proposal_kwargs(),
        )
    with pytest.raises(ControllerProposalError):
        ExtractionProposal(
            recommendation="none", candidate=CANDIDATE,
            **_proposal_kwargs(),
        )
    ok = ExtractionProposal(
        recommendation="candidate", candidate=CANDIDATE,
        **_proposal_kwargs(),
    )
    assert ok.candidate.text == "lives in Lisbon"


def test_update_proposal_consistency():
    with pytest.raises(ControllerProposalError):
        UpdateProposal(
            relationship="supersede", target_memory_id=None,
            **_proposal_kwargs(),
        )
    with pytest.raises(ControllerProposalError):
        UpdateProposal(
            relationship="no_relation", target_memory_id="m1",
            **_proposal_kwargs(),
        )
    with pytest.raises(ControllerProposalError):
        UpdateProposal(
            relationship="duplicate", target_memory_id="m1",
            proposed_text="new text", **_proposal_kwargs(),
        )
    ok = UpdateProposal(
        relationship="supersede", target_memory_id="m1",
        proposed_text="lives in Lisbon", **_proposal_kwargs(),
    )
    assert ok.target_memory_id == "m1"


def test_forget_proposal_consistency():
    with pytest.raises(ControllerProposalError):
        ForgetIntentProposal(
            recommendation="forget_candidate", target_memory_ids=(),
            **_proposal_kwargs(),
        )
    with pytest.raises(ControllerProposalError):
        ForgetIntentProposal(
            recommendation="no_forget_intent",
            target_memory_ids=("m1",), **_proposal_kwargs(),
        )
    ambiguous = ForgetIntentProposal(
        recommendation="ambiguous", target_memory_ids=("m1", "m2"),
        **_proposal_kwargs(),
    )
    assert ambiguous.target_memory_ids == ("m1", "m2")


def test_transition_proposal_validation():
    with pytest.raises(ControllerProposalError):
        TransitionProposal(recommendation="apply", **_proposal_kwargs())
    ok = TransitionProposal(
        recommendation="approve", rule_ids=("supersede_rules-1",),
        **_proposal_kwargs(),
    )
    assert ok.rule_ids == ("supersede_rules-1",)


def test_proposals_are_immutable_and_serializable():
    proposals = [
        AdmissionProposal(recommendation="abstain", **_proposal_kwargs()),
        ExtractionProposal(recommendation="none", candidate=None,
                           **_proposal_kwargs()),
        UpdateProposal(relationship="abstain", target_memory_id=None,
                       **_proposal_kwargs()),
        ForgetIntentProposal(recommendation="abstain",
                             **_proposal_kwargs()),
        TransitionProposal(recommendation="abstain", **_proposal_kwargs()),
    ]
    for proposal in proposals:
        with pytest.raises(Exception):
            proposal.score = 0.9
        payload = json.dumps(dataclasses.asdict(proposal))
        assert "object at 0x" not in payload
        assert "/Users/" not in payload and "/home/" not in payload
        # No applied-action vocabulary anywhere in the proposal shape.
        field_names = {f.name for f in dataclasses.fields(proposal)}
        assert not field_names & {"applied", "action_taken", "decision"}
        assert proposal.proposal_only is True
