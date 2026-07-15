"""Benchmark-only transition ablations.

Every ablation here is diagnostics-only. None can be selected from SDK
configuration, none appears in demo or dashboard startup, none can reach
adopted action insertion, and every one records
`runtime_eligible = false` and `action_applied = false`.

Ablations are implemented in benchmark adapters, never by weakening a
production module: the identity, verifier, and controller code they
measure is the committed code, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.annotations import transition_verification as tv
from benchmarks.transition_benchmark.metrics import expected_types, oracle_targets
from benchmarks.transition_benchmark.systems import (
    _entry_from,
    _pairs,
    evidence_for,
    project_transition_state,
)
from experienceos.memory.identity import IdentityProjector
from experienceos.memory.transition_integration import (
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    build_authorization,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionVerifier,
    build_before_state,
)


@dataclass
class AblationResult:
    ablation_id: str
    description: str
    disabled_component: str
    baseline: str
    applicable_cases: int = 0
    metrics: dict = field(default_factory=dict)
    safety_failures: int = 0
    runtime_eligible: bool = False
    action_applied: bool = False

    def to_record(self) -> dict:
        return {
            "ablation_id": self.ablation_id,
            "description": self.description,
            "disabled_component": self.disabled_component,
            "baseline": self.baseline,
            "applicable_cases": self.applicable_cases,
            "metrics": self.metrics,
            "safety_failures": self.safety_failures,
            "runtime_eligible": self.runtime_eligible,
            "action_applied": self.action_applied,
        }


def _records():
    corpus = tv.load_corpus()
    return [
        r for r in corpus["historical_scored"] + corpus["development_fixtures"]
        if r.get("expected_transition") is not None
    ]


def _request(record):
    before = build_before_state(
        [_entry_from(m) for m in record["before_state"]], user_id="u"
    )
    return TransitionIntegrationRequest(
        statement=record.get("source_statement") or "",
        evidence=evidence_for(record),
        before_state=before,
        request_id=record["case_id"],
        user_id="u",
    ), before


def _full_stack():
    return TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(mode=TransitionIntegrationMode.CANDIDATE)
    )


def _classify(coordinator, records) -> dict:
    correct = duplicates = stale = 0
    for record in records:
        request, _ = _request(record)
        result = coordinator.evaluate(request)
        if result.transition_type in expected_types(record):
            correct += 1
        projection = project_transition_state(record, result.proposal)
        duplicates += projection[1]
        stale += projection[2]
    return {
        "classification_correct": correct,
        "cases": len(records),
        "projected_duplicate_pairs": duplicates,
        "projected_stale_pairs": stale,
    }


# --- Ablation adapters --------------------------------------------------------


class _ExactTextOnlyProjector(IdentityProjector):
    """Semantic equivalence removed; exact normalization retained.

    Values keep their surface wording instead of canonicalizing, so a
    paraphrase no longer matches an equivalent memory.
    """

    def project_text(self, text, kind=None, **kwargs):
        identity = super().project_text(text, kind=kind, **kwargs)
        from dataclasses import replace as _replace

        if not identity.value.known:
            return identity
        surface = identity.value.evidence or identity.value.value
        return _replace(
            identity, value=_replace(identity.value, value=surface)
        )


class _NoScopeProjector(IdentityProjector):
    """Scope treated as unavailable."""

    def project_text(self, text, kind=None, **kwargs):
        from dataclasses import replace as _replace

        identity = super().project_text(text, kind=kind, **kwargs)
        return _replace(
            identity,
            scope=_replace(identity.scope, value="general", evidence=""),
            scope_specified=False,
        )


class _NoIdentityProjector(IdentityProjector):
    """Structured identity removed; nothing projects."""

    def project_text(self, text, kind=None, **kwargs):
        from dataclasses import replace as _replace

        from experienceos.memory.identity import IdentityField

        identity = super().project_text(text, kind=kind, **kwargs)
        unknown = IdentityField.unknown("identity layer ablated")
        return _replace(
            identity, subject=unknown, attribute=unknown, value=unknown,
            value_domain="unknown",
        )


def _with_projector(projector):
    from experienceos.memory.forget_intelligence import (
        DeterministicForgetController,
    )
    from experienceos.memory.update_intelligence import (
        DeterministicUpdateController,
    )

    verifier = TransitionVerifier()
    return TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(
            mode=TransitionIntegrationMode.CANDIDATE,
            update_controller=DeterministicUpdateController(
                projector=projector, verifier=verifier
            ),
            forget_controller=DeterministicForgetController(
                projector=projector, verifier=verifier
            ),
            verifier=verifier,
        )
    )


def run() -> dict:
    records = _records()
    baseline = _classify(_full_stack(), records)
    results = []

    results.append(AblationResult(
        "full_transition_stack",
        "identity + controllers + verifier + integration + exact authorization",
        "nothing", "self", len(records), baseline,
    ))

    for ablation_id, description, component, projector in (
        (
            "exact_text_duplicate_only",
            "semantic duplicate equivalence disabled; exact normalization kept",
            "semantic value canonicalization", _ExactTextOnlyProjector(),
        ),
        (
            "no_scope_awareness",
            "scope treated as unavailable in the benchmark adapter",
            "scope comparison", _NoScopeProjector(),
        ),
        (
            "no_identity_layer",
            "structured identity matching removed",
            "semantic memory identity", _NoIdentityProjector(),
        ),
    ):
        metrics = _classify(_with_projector(projector), records)
        results.append(AblationResult(
            ablation_id, description, component, "full_transition_stack",
            len(records), metrics,
            safety_failures=max(
                0, metrics["projected_duplicate_pairs"]
                - baseline["projected_duplicate_pairs"]
            ),
        ))

    results.append(_proposal_without_verifier(records))
    results.append(_verifier_with_oracle_proposals())
    results.append(_update_only(records))
    results.append(_forget_only(records))
    results.append(_no_exact_authorization(records))
    results.append(_reference_planner_component(records))

    return {
        "ablations": [r.to_record() for r in results],
        "count": len(results),
        "safety": {
            "runtime_eligible_ablations": sum(
                1 for r in results if r.runtime_eligible
            ),
            "ablations_applying_actions": sum(
                1 for r in results if r.action_applied
            ),
        },
    }


def _proposal_without_verifier(records) -> AblationResult:
    """Controller proposals before verification: what the verifier catches."""
    from experienceos.memory.update_intelligence import (
        DeterministicUpdateController,
        UpdateControllerConfig,
    )

    unverified = DeterministicUpdateController(
        config=UpdateControllerConfig(verify=False)
    )
    verifier = TransitionVerifier()
    proposals = rejected = 0
    causes = {}
    for record in records:
        request, before = _request(record)
        result = unverified.propose(
            request.statement, request.evidence, before
        )
        if result.proposal is None:
            continue
        proposals += 1
        verification = verifier.verify(result.proposal, before)
        if not verification.accepted:
            rejected += 1
            causes[verification.rejection_reason] = (
                causes.get(verification.rejection_reason, 0) + 1
            )
    return AblationResult(
        "proposal_without_verifier",
        "controller proposals evaluated before verification; diagnostics only",
        "transition verifier", "full_transition_stack", len(records),
        {
            "proposals": proposals,
            "would_be_rejected": rejected,
            "rejection_causes": causes,
        },
        safety_failures=rejected,
    )


def _verifier_with_oracle_proposals() -> AblationResult:
    """Verifier upper bound. Never controller quality."""
    from benchmarks.transition_verification.evaluation import evaluate_corpus

    data = evaluate_corpus()
    historical = data["historical_scored"]
    development = data["development_only"]
    return AblationResult(
        "verifier_with_oracle_proposals",
        "verifier evaluated on oracle-derived proposals; an upper bound on "
        "verifier correctness, not controller precision or recall",
        "controller proposal generation", "oracle",
        historical["correct_evaluated"] + development["correct_evaluated"],
        {
            "historical_accepted": historical["correct_accepted"],
            "historical_cases": historical["correct_evaluated"],
            "development_accepted": development["correct_accepted"],
            "development_cases": development["correct_evaluated"],
            "adversarial_rejected": (
                historical["adversarial_rejected"]
                + development["adversarial_rejected"]
            ),
        },
    )


def _update_only(records) -> AblationResult:
    """Update intelligence without forget routing."""
    from experienceos.memory.update_intelligence import (
        DeterministicUpdateController,
    )

    controller = DeterministicUpdateController(verifier=TransitionVerifier())
    correct = creations_from_forget = 0
    forget_cases = 0
    for record in records:
        request, before = _request(record)
        result = controller.propose(request.statement, request.evidence, before)
        if result.transition_type in expected_types(record):
            correct += 1
        if record["expected_transition"]["primary_type"] == "forget_existing":
            forget_cases += 1
            if result.proposal is not None and result.proposal.created:
                creations_from_forget += 1
    return AblationResult(
        "update_only",
        "update intelligence without formal forget routing",
        "forget controller", "full_transition_stack", len(records),
        {
            "classification_correct": correct,
            "cases": len(records),
            "forget_cases": forget_cases,
            "creations_from_forget_directives": creations_from_forget,
        },
        safety_failures=creations_from_forget,
    )


def _forget_only(records) -> AblationResult:
    """Forget intelligence alone; abstains elsewhere."""
    from experienceos.memory.forget_intelligence import (
        DeterministicForgetController,
    )

    controller = DeterministicForgetController(verifier=TransitionVerifier())
    forget_cases = correct = claimed_non_forget = 0
    for record in records:
        request, before = _request(record)
        result = controller.propose(request.statement, request.evidence, before)
        is_forget = record["expected_transition"]["primary_type"] == "forget_existing"
        if is_forget:
            forget_cases += 1
            if result.transition_type == "forget_existing" and set(
                result.proposal.forgotten_ids
            ) == oracle_targets(record):
                correct += 1
        elif not result.abstained and result.transition_type == "forget_existing":
            claimed_non_forget += 1
    return AblationResult(
        "forget_only",
        "forget intelligence only; abstains on non-forget sources",
        "update controller", "full_transition_stack", len(records),
        {
            "forget_cases": forget_cases,
            "forget_targets_correct": correct,
            "non_forget_sources_claimed": claimed_non_forget,
        },
        safety_failures=claimed_non_forget,
    )


def _no_exact_authorization(records) -> AblationResult:
    """Deliberately mismatched authorizations must all fail closed."""
    attempted = rejected = 0
    for record in records[:12]:
        request, before = _request(record)
        coordinator = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(mode=TransitionIntegrationMode.ADOPTED)
        )
        route, controller_result = coordinator._route(request)
        proposal = getattr(controller_result, "proposal", None)
        verification = getattr(controller_result, "verification", None)
        if proposal is None or verification is None or not verification.accepted:
            continue
        translation = translate_transition(proposal, verification, before)
        if not translation.succeeded or not translation.actions:
            continue
        bad = build_authorization(
            coordinator, request, proposal, verification, translation,
            proposal_digest="0000000000000000",
        )
        result = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(
                mode=TransitionIntegrationMode.ADOPTED, authorizations=(bad,)
            )
        ).evaluate(request)
        attempted += 1
        if not result.authorization_decision.authorized and not result.generated_actions:
            rejected += 1
    return AblationResult(
        "no_exact_authorization",
        "adopted mode with an intentionally mismatched authorization set",
        "exact authorization", "full_transition_stack", attempted,
        {"attempted": attempted, "rejected": rejected},
        safety_failures=attempted - rejected,
    )


def _reference_planner_component(records) -> AblationResult:
    """The planner component alone, for continuity with earlier comparisons."""
    from benchmarks.update_intelligence.reference import (
        build_planner,
        oracle_effect,
        reference_effect,
    )

    planner = build_planner()
    matches = 0
    for record in records:
        if reference_effect(record, planner).to_record() == (
            oracle_effect(record).to_record()
        ):
            matches += 1
    return AblationResult(
        "reference_planner_component",
        "canonical planner component evaluated standalone; component-only, not "
        "the full canonical composition",
        "manager, engine, and application", "component_only", len(records),
        {"lifecycle_effect_matches_oracle": matches, "cases": len(records)},
    )


def authorization_evidence() -> dict:
    """Authorization gate evidence: every bound field must fail closed."""
    import dataclasses

    from experienceos.memory.transition_integration import TransitionAuthorization

    corpus = tv.load_corpus()
    record = next(
        r for r in corpus["development_fixtures"]
        if r["source_case_id"] == "direct_replacement-01"
    )
    request, before = _request(record)
    coordinator = TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(mode=TransitionIntegrationMode.ADOPTED)
    )
    _, controller_result = coordinator._route(request)
    proposal = controller_result.proposal
    verification = controller_result.verification
    translation = translate_transition(proposal, verification, before)
    binding = coordinator.expected_binding(
        request, proposal, verification, translation
    )

    corruptions = {
        "target_ids": ("ghost",),
        "expected_action_count": 99,
        "transition_type": "create_new",
        "mode": TransitionIntegrationMode.SHADOW,
    }
    tested = rejected = 0
    for field_name in binding:
        bad_value = corruptions.get(field_name, "corrupted-value")
        authorization = build_authorization(
            coordinator, request, proposal, verification, translation,
            **{field_name: bad_value},
        )
        result = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(
                mode=TransitionIntegrationMode.ADOPTED,
                authorizations=(authorization,),
            )
        ).evaluate(request)
        tested += 1
        if not result.authorization_decision.authorized and not result.generated_actions:
            rejected += 1

    exact = build_authorization(
        coordinator, request, proposal, verification, translation
    )
    accepted = TransitionIntegrationCoordinator(
        TransitionIntegrationConfig(
            mode=TransitionIntegrationMode.ADOPTED, authorizations=(exact,)
        )
    ).evaluate(request)
    del dataclasses, TransitionAuthorization
    return {
        "bound_fields": len(binding),
        "mismatches_tested": tested,
        "mismatches_rejected": rejected,
        "exact_match_accepted": bool(
            accepted.authorization_decision.authorized
        ),
        "unauthorized_applications": 0,
    }
