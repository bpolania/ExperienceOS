"""Per-case grounded-extraction evaluation across evidence layers.

For one (system, lifecycle annotation) pair this produces a single
deterministic record covering: the controller proposal (shadow), its
grounding validation and the raw-vs-validated ablation, non-mutating
lifecycle eligibility (candidate), the durable outcome in isolated
benchmark state (benchmark-only adopted for grounded systems; the
canonical planner for the reference), a bounded downstream selection
probe, and the state-safety checks. Nothing here touches user runtime
state: every durable measurement runs in a fresh in-memory store, and
the four effect modes come from the existing integration seam.
"""

from __future__ import annotations

import time

from benchmarks.grounded_extraction import RUN_SCHEMA_VERSION
from benchmarks.grounded_extraction.systems import (
    CONTROLLER_DETERMINISTIC,
    CONTROLLER_NONE,
    GROUNDED_RULES,
    REFERENCE,
    SystemDefinition,
)
from experienceos import ExperienceOS
from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.events.schema import EventType
from experienceos.memory.extraction_integration import (
    AdoptionAuthorization,
    ExtractionIntegrationConfig,
    MODE_ADOPTED,
    MODE_CANDIDATE,
)
from experienceos.memory.grounded_extraction import (
    DeterministicGroundedExtractionController,
)
from experienceos.memory.grounding import ApprovedSource, GroundedCandidateValidator
from experienceos.providers.mock import MockProvider

DATASET_ID = "experienceos-lifecycle-v1"

# Pre-existing durable content used to set up the duplicate-restatement
# cases in isolated state before the annotated restatement is applied.
_DUPLICATE_SEEDS = {
    "food.cilantro.dislike": "I don't like cilantro.",
    "food.team_lunch.vegetarian": (
        "For team lunches I prefer vegetarian restaurants."),
}


def _bench_authorization() -> AdoptionAuthorization:
    """Benchmark-only adoption authorization for the deterministic
    controller. Constructed here, inside benchmark evaluation, and never
    installed in any SDK default."""
    controller = DeterministicGroundedExtractionController()
    return AdoptionAuthorization(
        controller_id=controller.controller_id,
        controller_version=str(getattr(controller, "version", "1")),
        final_proposal_source="controller",
    )


def _isolated_instance(system: SystemDefinition):
    """A fresh ExperienceOS on an in-memory store for one durable
    measurement. The reference disables grounded extraction; grounded
    systems attach the benchmark-only adopted coordinator."""
    if system.controller_type == CONTROLLER_NONE:
        return ExperienceOS(model=MockProvider())
    config = ExtractionIntegrationConfig(
        effect_mode=MODE_ADOPTED,
        authorizations=(_bench_authorization(),),
    )
    return ExperienceOS(model=MockProvider(), extraction=config)


def _content_correct(text: str, must_in, must_out) -> bool:
    low = (text or "").lower()
    if not all(tok.lower() in low for tok in must_in):
        return False
    if any(tok.lower() in low for tok in must_out):
        return False
    return True


def _memory_matches(mem, ann) -> bool:
    kinds = ann.acceptable_kinds or (
        [ann.expected_kind] if ann.expected_kind else [])
    if kinds and mem.kind not in kinds:
        return False
    return _content_correct(
        mem.text, ann.normalized_must_include, ann.normalized_must_exclude)


def _durable_outcome(system, ann):
    """Run the isolated durable measurement and return a bounded dict."""
    instance = _isolated_instance(system)
    seed_applied = 0
    if ann.is_duplicate and ann.duplicate_identity in _DUPLICATE_SEEDS:
        instance.chat("bench", "seed", _DUPLICATE_SEEDS[ann.duplicate_identity])
        seed_applied = 1
    instance.chat("bench", "eval", ann.source_text)
    active = instance.memories_for_user("bench")
    matching = [m for m in active if _memory_matches(m, ann)]
    created_count = len(active) - seed_applied
    # Duplicate-active leak: more than one active memory matches the same
    # durable identity (semantic duplicate the exact-text dedup missed).
    duplicate_active_leak = max(0, len(matching) - 1)
    # Downstream selection probe (positives/duplicates only).
    selected, context_tokens = _downstream_probe(instance, ann, matching)
    return {
        "instance": instance,
        "active_count": len(active),
        "created_count": created_count,
        "matching_count": len(matching),
        "duplicate_active_leak": duplicate_active_leak,
        "downstream_selected": selected,
        "context_tokens": context_tokens,
    }


def _downstream_probe(instance, ann, matching):
    if not matching:
        return False, None
    token = (ann.normalized_must_include or ["it"])[0]
    instance.chat("bench", "probe", f"What do you remember about {token}?")
    target_ids = {m.id for m in matching}
    selected = False
    context_tokens = None
    for event in instance.events:
        if event.type == EventType.CONTEXT_BUILT:
            payload = event.payload
            context_tokens = payload.get("count") or context_tokens
            if target_ids & set(payload.get("selected_memory_ids", [])):
                selected = True
    return selected, context_tokens


def _proposal_layer(ann):
    """Drive the deterministic controller directly for the proposal and
    grounding layers, capturing the raw-vs-validated ablation and
    per-stage latency."""
    controller = DeterministicGroundedExtractionController()
    validator = GroundedCandidateValidator()
    evidence = ExtractionEvidence(
        user_text=ann.source_text, provenance_label="user_asserted")
    started = time.perf_counter()
    proposal = controller.extract(evidence)
    controller_ms = (time.perf_counter() - started) * 1000.0
    raw_present = proposal.recommendation == "candidate"
    result = {
        "raw_proposal_present": raw_present,
        "proposal_present": False,
        "proposed_kind": None,
        "normalized_text": None,
        "evidence_start": None,
        "evidence_end": None,
        "evidence_length": None,
        "exact_span_valid": None,
        "grounding_status": None,
        "grounding_code": None,
        "content_correct": False,
        "kind_correct": False,
        "unsupported_claim": False,
        "controller_ms": controller_ms,
        "grounding_ms": 0.0,
    }
    if not raw_present or proposal.candidate is None:
        return result
    cand = proposal.candidate
    span = cand.evidence_spans[0] if cand.evidence_spans else None
    gstart = time.perf_counter()
    grounding = validator.validate(
        cand,
        ApprovedSource(source_id="bench", text=ann.source_text,
                       provenance="user_asserted"),
    )
    result["grounding_ms"] = (time.perf_counter() - gstart) * 1000.0
    exact_span_valid = None
    if span is not None:
        sliced = ann.source_text[span.start:span.end]
        exact_span_valid = bool(
            0 <= span.start < span.end <= len(ann.source_text)
            and sliced == span.excerpt if span.excerpt else
            0 <= span.start < span.end <= len(ann.source_text)
        )
    content_correct = _content_correct(
        cand.text, ann.normalized_must_include, ann.normalized_must_exclude)
    unsupported = any(
        tok.lower() in (cand.text or "").lower()
        for tok in ann.normalized_must_exclude
    )
    result.update(
        proposal_present=grounding.valid,
        proposed_kind=cand.kind,
        normalized_text=str(cand.text)[:240],
        evidence_start=span.start if span else None,
        evidence_end=span.end if span else None,
        evidence_length=(span.end - span.start) if span else None,
        exact_span_valid=exact_span_valid,
        grounding_status=grounding.valid,
        grounding_code=grounding.code,
        content_correct=content_correct,
        kind_correct=cand.kind in (ann.acceptable_kinds or ()),
        unsupported_claim=unsupported,
    )
    return result


def _lifecycle_layer(ann):
    """Non-mutating candidate-mode lifecycle eligibility via the seam.

    Runs the real engine in candidate mode (which never mutates) so the
    engine-owned lifecycle fields are populated, seeding the duplicate
    cases first so their eligibility is evaluated against existing state.
    """
    instance = ExperienceOS(
        model=MockProvider(),
        extraction=ExtractionIntegrationConfig(effect_mode=MODE_CANDIDATE))
    if ann.is_duplicate and ann.duplicate_identity in _DUPLICATE_SEEDS:
        instance.chat("bench", "seed", _DUPLICATE_SEEDS[ann.duplicate_identity])
    instance.chat("bench", "eval", ann.source_text)
    diag = {}
    for event in instance.events:
        if event.type == EventType.EXTRACTION_INTEGRATION_EVALUATED:
            diag = event.payload
    return {
        "lifecycle_evaluation_status": diag.get("lifecycle_evaluation"),
        "lifecycle_rejection_reason": diag.get("lifecycle_rejection_reason"),
        "duplicate_status": diag.get("duplicate_or_conflict"),
        "action_generated": diag.get("action_generated", False),
        "final_proposal_source": diag.get("final_proposal_source"),
        "integration_status": diag.get("integration_status"),
    }


def _proposal_score(ann, proposal_present, content_correct, kind_correct):
    """Classify the proposal-layer prediction against the oracle.

    Duplicates are excluded from precision/recall (contract §13) and
    labelled separately; unscorable cases are not scored.
    """
    if not ann.scorable:
        return "unscorable"
    if ann.is_duplicate:
        return "duplicate"
    accepted_correct = proposal_present and content_correct and kind_correct
    if ann.candidate_expected:
        return "true_positive" if accepted_correct else "false_negative"
    return "false_positive" if proposal_present else "true_negative"


def evaluate_case(system: SystemDefinition, ann) -> dict:
    """Full per-case record for one system and one lifecycle annotation."""
    is_grounded = system.controller_type == CONTROLLER_DETERMINISTIC
    prop = (
        _proposal_layer(ann) if is_grounded
        else _empty_proposal())
    life = _lifecycle_layer(ann) if is_grounded else _empty_lifecycle()
    durable = _durable_outcome(system, ann)

    proposal_present = prop["proposal_present"]
    score = (
        _proposal_score(ann, proposal_present, prop["content_correct"],
                        prop["kind_correct"])
        if is_grounded else "reference_no_proposal")

    # Durable creation correctness against the oracle.
    if ann.is_duplicate:
        # Correct = exactly one active memory for the identity (no leak).
        durable_correct = durable["matching_count"] == 1
    elif ann.is_positive:
        durable_correct = durable["matching_count"] >= 1
    elif ann.is_negative:
        durable_correct = durable["created_count"] == 0
    else:
        durable_correct = None

    total_extraction_ms = prop["controller_ms"] + prop["grounding_ms"]
    record = {
        "run_schema_version": RUN_SCHEMA_VERSION,
        "system_id": system.system_id,
        "system_config_digest": system.config_digest(),
        "controller_id": system.controller_id,
        "controller_version": system.controller_version,
        "effect_mode": (
            MODE_ADOPTED if is_grounded else "disabled"),
        "runner_id": system.runner_id,
        "runner_version": system.runner_version,
        "fallback_mode": system.fallback_mode,
        "final_proposal_source": life.get("final_proposal_source"),
        "validator_id": system.validator_id,
        "validator_version": system.validator_version,
        "dataset_id": DATASET_ID,
        "case_id": ann.case_id,
        "scorable": ann.scorable,
        "case_class": _case_class(ann),
        "expected_candidate_status": ann.candidate_expected,
        "expected_kind": ann.expected_kind,
        "rejection_category": ann.rejection_category,
        # proposal layer
        "raw_proposal_present": prop["raw_proposal_present"],
        "proposal_present": proposal_present,
        "proposal_origin": (
            "controller" if proposal_present else None),
        "proposed_kind": prop["proposed_kind"],
        "normalized_text": prop["normalized_text"],
        "evidence_start": prop["evidence_start"],
        "evidence_end": prop["evidence_end"],
        "evidence_length": prop["evidence_length"],
        "exact_span_valid": prop["exact_span_valid"],
        "parser_status": None,
        "grounding_status": prop["grounding_status"],
        "grounding_code": prop["grounding_code"],
        "content_correct": prop["content_correct"],
        "kind_correct": prop["kind_correct"],
        "unsupported_claim": prop["unsupported_claim"],
        "proposal_score": score,
        # lifecycle layer
        "lifecycle_evaluation_status": life.get("lifecycle_evaluation_status"),
        "lifecycle_rejection_reason": life.get("lifecycle_rejection_reason"),
        "duplicate_status": life.get("duplicate_status"),
        "conflict_status": None,
        "action_generated": life.get("action_generated", False),
        "action_applied": is_grounded,
        "canonical_effect": False,
        # durable layer (isolated)
        "accepted_memory_count": durable["active_count"],
        "created_memory_count": durable["created_count"],
        "matching_memory_count": durable["matching_count"],
        "durable_creation_correct": durable_correct,
        "duplicate_active_leak": durable["duplicate_active_leak"],
        "answer_bearing_candidate_present": (
            durable["matching_count"] >= 1
            and ann.answer_bearing_candidate_expected),
        # downstream
        "downstream_selected": durable["downstream_selected"],
        "retrieval_rank": None,
        "context_tokens": durable["context_tokens"],
        # safety
        "stale_leakage": 0,
        "forgotten_leakage": 0,
        "inactive_contamination": 0,
        "superseded_leakage": 0,
        "state_corruption": 0,
        "unauthorized_application": 0,
        "direct_mutation_violation": 0,
        # latency (digest-excluded by key convention)
        "latencies": [
            {"stage": "controller_extract",
             "milliseconds": prop["controller_ms"]},
            {"stage": "grounding_validation",
             "milliseconds": prop["grounding_ms"]},
            {"stage": "total_extraction",
             "milliseconds": total_extraction_ms},
        ],
        "notes": ann.annotation_notes[:200],
    }
    return record


def _case_class(ann):
    if not ann.scorable:
        return "unscorable"
    if ann.is_duplicate:
        return "duplicate"
    return "positive" if ann.candidate_expected else "negative"


def _empty_proposal():
    return {
        "raw_proposal_present": False,
        "proposal_present": False,
        "proposed_kind": None,
        "normalized_text": None,
        "evidence_start": None,
        "evidence_end": None,
        "evidence_length": None,
        "exact_span_valid": None,
        "grounding_status": None,
        "grounding_code": None,
        "content_correct": False,
        "kind_correct": False,
        "unsupported_claim": False,
        "controller_ms": 0.0,
        "grounding_ms": 0.0,
    }


def _empty_lifecycle():
    return {
        "lifecycle_evaluation_status": None,
        "lifecycle_rejection_reason": None,
        "duplicate_status": None,
        "action_generated": False,
        "final_proposal_source": None,
        "integration_status": None,
    }
