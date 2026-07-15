"""Oracle-derived and adversarial proposals from the frozen corpus.

Correct proposals are constructed *directly from the committed expected
transition* — they are labelled `oracle_derived` everywhere and are not
evidence about any controller's ability to produce them.

Adversarial proposals are deterministic corruptions of those correct
proposals, one defect each, so a rejection can be attributed to exactly
one cause.
"""

from __future__ import annotations

from dataclasses import replace

from experienceos.controllers.base import MemorySnapshot
from experienceos.controllers.extraction import ProposedMemoryCandidate
from experienceos.memory.identity import (
    IdentityProjector,
    IdentityRelation,
    compare_memory_identity,
)
from experienceos.memory.schema import MemoryStatus
from experienceos.memory.transition_verification import (
    AfterStateExpectation,
    CreatedMemorySpec,
    EvidenceMode,
    ProposedTransition,
    TransitionSourceEvidence,
    build_before_state,
)

_PROJECTOR = IdentityProjector()

PROPOSAL_SOURCE = "oracle_derived"
PROPOSER_ID = "frozen_annotation_oracle"

#: Neither corpus partition carries production grounding: historical
#: cases predate the grounded-extraction infrastructure and fixtures are
#: synthetic. Both are usable for audit-only verification and neither can
#: ever authorize canonical effect.
_EVIDENCE_MODE = {
    "historical_scored": EvidenceMode.HISTORICAL_ORACLE,
    "development_only": EvidenceMode.DEVELOPMENT_FIXTURE,
}


def _lid(ref) -> str:
    return ref["logical_id"]


def before_state_for(record):
    """Detached snapshot built from the frozen before-state."""
    return build_before_state(
        [
            MemorySnapshot(
                memory_id=_lid(memory["memory_ref"]),
                kind=memory["kind"],
                text=memory.get("canonical_text") or "",
                status=memory["lifecycle_state"],
            )
            for memory in record["before_state"]
        ],
        snapshot_source="frozen_annotation_before_state",
    )


def evidence_for(record) -> TransitionSourceEvidence:
    return TransitionSourceEvidence(
        source_statement=record.get("source_statement") or "",
        source_event_id=record["case_id"],
        source_role=record.get("source_role") or "user",
        session_id=record.get("source_session_id") or "",
        evidence_mode=_EVIDENCE_MODE[record["annotation_classification"]],
        grounded_candidate_ref=str(record.get("grounded_candidate_ref") or ""),
        evidence_span_ref=str(record.get("evidence_span_ref") or ""),
        provenance_ref="user_asserted",
    )


def oracle_proposal(record, before_state) -> ProposedTransition:
    """Build the correct proposal the committed oracle describes."""
    transition = record["expected_transition"]
    superseded = tuple(_lid(r) for r in transition["superseded_refs"])
    forgotten = tuple(_lid(r) for r in transition["forgotten_refs"])
    statement = record.get("source_statement") or ""

    created = tuple(
        CreatedMemorySpec(
            candidate=ProposedMemoryCandidate(kind=spec["kind"], text=statement),
            local_ref=f"created:{index}",
            must_include=tuple(spec.get("must_include") or ()),
            replaces=(superseded[0] if spec.get("replaces") and superseded else None),
        )
        for index, spec in enumerate(transition.get("created") or ())
    )

    after = record.get("after_state") or {}
    known = {m.memory_id for m in before_state.memories}
    # Created memories appear in the frozen after-state under new logical
    # ids that cannot exist before application; they are represented by
    # proposal-local refs instead.
    expected_active = tuple(
        _lid(r) for r in (after.get("active") or []) if _lid(r) in known
    )
    lineage = (
        tuple((target, "created:0") for target in superseded)
        if created and superseded
        else ()
    )
    expectation = AfterStateExpectation(
        active_ids=expected_active,
        superseded_ids=superseded,
        forgotten_ids=forgotten,
        created_refs=tuple(spec.local_ref for spec in created),
        preserved_ids=tuple(_lid(r) for r in transition["preserved_refs"]),
        unchanged_ids=tuple(_lid(r) for r in transition["unchanged_refs"]),
        lineage_edges=lineage,
        semantic_duplicate_count=int(after.get("semantic_duplicate_count") or 0),
        stale_active_count=int(after.get("stale_active_count") or 0),
        no_mutation=not transition["canonical_effect"],
        final_active_summary=str(after.get("final_active_summary") or ""),
    )
    return ProposedTransition(
        proposal_id=f"oracle:{record['case_id']}",
        transition_type=transition["primary_type"],
        evidence=evidence_for(record),
        before_state_digest=before_state.digest(),
        target_ids=tuple(_lid(r) for r in transition["target_refs"]),
        created=created,
        superseded_ids=superseded,
        forgotten_ids=forgotten,
        preserved_ids=tuple(_lid(r) for r in transition["preserved_refs"]),
        unchanged_ids=tuple(_lid(r) for r in transition["unchanged_refs"]),
        lineage_edges=lineage,
        expected_after_state=expectation,
        proposer_id=PROPOSER_ID,
        proposal_source=PROPOSAL_SOURCE,
        rationale="constructed from the committed expected transition",
        requests_canonical_effect=transition["canonical_effect"],
    )


# --- Adversarial variants -----------------------------------------------------

#: Every adversarial category this module can generate.
ADVERSARIAL_CATEGORIES = (
    "invalid_target",
    "inactive_target",
    "unrelated_target",
    "unsupported_value",
    "unsupported_scope",
    "contradictory_structure",
    "invalid_lineage",
    "ambiguous_target",
    "forget_as_creation",
    "temporary_as_durable",
    "historical_as_current",
    "question_mutation",
    "hypothetical_mutation",
    "missing_preservation",
)

#: Categories whose defect is a durable mutation the oracle refuses.
_NON_DURABLE_SOURCE = {
    "reject_temporary": "temporary_as_durable",
    "reject_historical": "historical_as_current",
    "reject_question": "question_mutation",
    "reject_hypothetical": "hypothetical_mutation",
}


def _drop_expectation(proposal) -> ProposedTransition:
    """Remove the after-state expectation.

    A corrupted proposal must be rejected for its *own* defect, not for
    disagreeing with an expectation copied from the oracle.
    """
    return replace(proposal, expected_after_state=None)


def _retarget(base, targets) -> ProposedTransition:
    """Point a supersession at different targets, and nothing else.

    The new targets are dropped from `unchanged_ids`/`preserved_ids` so
    the variant carries exactly one defect: a contradictory-sets
    rejection would otherwise mask the target defect under test.
    """
    targets = tuple(targets)
    return replace(
        base,
        superseded_ids=targets,
        lineage_edges=tuple((target, "created:0") for target in targets),
        unchanged_ids=tuple(
            m for m in base.unchanged_ids if m not in targets
        ),
        preserved_ids=tuple(
            m for m in base.preserved_ids if m not in targets
        ),
    )


def adversarial_variants(record, before_state, proposal) -> list:
    """Deterministic single-defect corruptions of a correct proposal."""
    variants = []
    active = list(before_state.active())
    transition_type = proposal.transition_type
    statement = (record.get("source_statement") or "").lower()

    def emit(category, corrupted):
        variants.append(
            (
                category,
                replace(
                    corrupted,
                    proposal_id=f"adversarial:{category}:{record['case_id']}",
                    proposal_source="adversarial_derived",
                ),
            )
        )

    if transition_type == "supersede_existing" and proposal.superseded_ids:
        base = _drop_expectation(proposal)
        emit("invalid_target", _retarget(base, ("no.such.memory",)))
        inactive = [
            m for m in before_state.memories if m.status != MemoryStatus.ACTIVE
        ]
        if inactive:
            emit("inactive_target", _retarget(base, (inactive[0].memory_id,)))
        unrelated = _unrelated_active(before_state, proposal)
        if unrelated:
            emit("unrelated_target", _retarget(base, (unrelated,)))
        if len(active) > 1:
            emit(
                "ambiguous_target",
                _retarget(base, tuple(m.memory_id for m in active[:2])),
            )
        emit(
            "invalid_lineage",
            replace(base, lineage_edges=(("created:0", "created:0"),)),
        )
        emit(
            "contradictory_structure",
            replace(base, unchanged_ids=proposal.superseded_ids),
        )
        if proposal.created:
            emit(
                "unsupported_value",
                replace(
                    base,
                    created=(
                        replace(
                            proposal.created[0],
                            must_include=("teleportation",),
                        ),
                    ),
                ),
            )
            if "for antarctic expeditions" not in statement:
                emit(
                    "unsupported_scope",
                    replace(
                        base,
                        created=(
                            replace(
                                proposal.created[0],
                                scope="for antarctic expeditions",
                            ),
                        ),
                    ),
                )
        if len(active) > 1:
            # Claims every active memory stays untouched, including the
            # one the proposal itself supersedes.
            emit(
                "missing_preservation",
                replace(base, unchanged_ids=tuple(m.memory_id for m in active)),
            )

    if transition_type == "forget_existing" and proposal.forgotten_ids:
        base = _drop_expectation(proposal)
        emit(
            "forget_as_creation",
            replace(
                base,
                created=(
                    CreatedMemorySpec(
                        candidate=ProposedMemoryCandidate(
                            kind="preference",
                            text=record.get("source_statement") or "x",
                        ),
                        local_ref="created:0",
                    ),
                ),
            ),
        )
        emit("invalid_target", replace(base, forgotten_ids=("no.such.memory",)))
        inactive = [
            m for m in before_state.memories if m.status != MemoryStatus.ACTIVE
        ]
        if inactive:
            emit(
                "inactive_target",
                replace(base, forgotten_ids=(inactive[0].memory_id,)),
            )

    # A refusal the oracle justifies, re-proposed as a durable mutation.
    category = _NON_DURABLE_SOURCE.get(transition_type)
    if category is None and "historical_statement" in (
        record.get("scoring_categories") or ()
    ):
        category = "historical_as_current"
    if category and active:
        target = active[0].memory_id
        emit(
            category,
            replace(
                _drop_expectation(proposal),
                transition_type="supersede_existing",
                superseded_ids=(target,),
                preserved_ids=(target,),
                unchanged_ids=(),
                created=(
                    CreatedMemorySpec(
                        candidate=ProposedMemoryCandidate(
                            kind=active[0].kind,
                            text=record.get("source_statement") or "x",
                        ),
                        local_ref="created:0",
                        replaces=target,
                    ),
                ),
                lineage_edges=((target, "created:0"),),
                requests_canonical_effect=True,
            ),
        )

    if transition_type in ("duplicate_noop", "semantic_duplicate_noop"):
        emit(
            "contradictory_structure",
            replace(
                _drop_expectation(proposal),
                created=(
                    CreatedMemorySpec(
                        candidate=ProposedMemoryCandidate(
                            kind="preference",
                            text=record.get("source_statement") or "x",
                        ),
                        local_ref="created:0",
                    ),
                ),
            ),
        )

    if transition_type == "scoped_coexistence" and active:
        emit(
            "contradictory_structure",
            replace(
                _drop_expectation(proposal),
                superseded_ids=(active[0].memory_id,),
            ),
        )

    return variants


def _unrelated_active(before_state, proposal) -> str | None:
    """An active memory the source statement is unrelated to."""
    proposed = _PROJECTOR.project_text(proposal.evidence.source_statement or "")
    for memory in before_state.active():
        existing = before_state.identity_of(memory.memory_id)
        if existing is None:
            continue
        if (
            compare_memory_identity(existing, proposed).relation
            == IdentityRelation.UNRELATED
        ):
            return memory.memory_id
    return None
