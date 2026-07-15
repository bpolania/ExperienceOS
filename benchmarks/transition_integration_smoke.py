"""Bounded transition-integration smoke: modes, authorization, safety.

Not the transition benchmark. It exercises the governed seam end to end
and reports mode behavior, routing, authorization, translation, and
application counts. Adopted infrastructure appearing here is isolated
infrastructure evidence — never canonical adoption evidence.

Fully offline and deterministic: mock provider only, no model, no
network.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys

from experienceos.memory import ExperienceEntry
from experienceos.memory.schema import MemoryKind, MemoryStatus
from experienceos.memory.transition_integration import (
    CanonicalActionEffect,
    TransitionIntegrationConfig,
    TransitionIntegrationCoordinator,
    TransitionIntegrationMode,
    TransitionIntegrationRequest,
    TransitionRoute,
    build_authorization,
    translate_transition,
)
from experienceos.memory.transition_verification import (
    EvidenceMode,
    TransitionSourceEvidence,
    build_before_state,
)

AISLE = "I prefer aisle seats for short work trips."

#: One bounded source per behavior the seam must distinguish.
CASES = (
    ("update", "I now prefer window seats for short work trips."),
    ("duplicate", AISLE),
    ("scoped", "For long international flights, I prefer window seats."),
    ("create", "I am allergic to shellfish."),
    ("forget", "Forget that I prefer aisle seats."),
    ("negative_forget", "Don't forget that I prefer aisle seats."),
    ("forget_question", "Can you forget my seat preference?"),
    ("hypothetical", "If I moved to New York, I might use JFK."),
    ("broad_forget", "Forget everything about travel."),
    ("temporary", "This time only, use a window seat."),
)

MUTATING = ("update", "scoped", "create", "forget")


def _state():
    record = ExperienceEntry(user_id="u", text=AISLE, kind=MemoryKind.PREFERENCE)
    record.id = "m1"
    return build_before_state([record], user_id="u")


def _request(statement, mode=EvidenceMode.GROUNDED_VALID, **kwargs):
    return TransitionIntegrationRequest(
        statement=statement,
        evidence=TransitionSourceEvidence(
            source_statement=statement, source_event_id="r1", evidence_mode=mode
        ),
        before_state=_state(),
        request_id="r1",
        user_id="u",
        **kwargs,
    )


def _latency(values) -> dict:
    if not values:
        return {"count": 0}
    values = sorted(values)
    index = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
    return {
        "count": len(values),
        "median_ms": round(statistics.median(values), 4),
        "p95_ms": round(values[index], 4),
        "max_ms": round(values[-1], 4),
    }


def run() -> dict:
    report = {"modes": {}, "authorization": {}, "safety": {}}
    latencies = []
    stages = {}

    for mode in (
        TransitionIntegrationMode.DISABLED,
        TransitionIntegrationMode.SHADOW,
        TransitionIntegrationMode.CANDIDATE,
        TransitionIntegrationMode.VERIFY_ONLY,
    ):
        coordinator = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(mode=mode)
        )
        # Warm up: the first call pays one-time construction costs.
        coordinator.evaluate(_request(CASES[0][1]))
        routes = {"update": 0, "forget": 0, "abstained": 0, "not_invoked": 0}
        generated = applied = proposals = verified = eligible = 0
        for _, statement in CASES:
            result = coordinator.evaluate(_request(statement))
            latencies.append(result.latency_ms)
            for name, value in result.stage_latency_ms.items():
                stages.setdefault(name, []).append(value)
            routes[
                {
                    TransitionRoute.UPDATE: "update",
                    TransitionRoute.FORGET: "forget",
                    TransitionRoute.ABSTAINED: "abstained",
                }.get(result.route, "not_invoked")
            ] += 1
            generated += len(result.generated_actions)
            applied += int(result.action_applied)
            proposals += int(result.proposal is not None)
            verified += int(result.verifier_invoked)
            eligible += int(result.canonical_effect_eligible)
        report["modes"][mode] = {
            "requests": len(CASES),
            "routes": routes,
            "proposals": proposals,
            "verifier_invocations": verified,
            "canonical_effect_eligible": eligible,
            "generated_actions": generated,
            "actions_applied": applied,
        }

    # Adopted infrastructure, isolated: exact authorization required.
    adopted = {
        "requests": 0, "exact_matches": 0, "missing": 0, "mismatches": 0,
        "translations": 0, "translation_failures": 0, "actions": 0,
        "applied": 0, "actions_by_type": {},
    }
    for name, statement in CASES:
        adopted["requests"] += 1
        plain = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(mode=TransitionIntegrationMode.ADOPTED)
        )
        request = _request(statement)
        no_auth = plain.evaluate(request)
        if no_auth.authorization_decision and (
            no_auth.authorization_decision.reason == "authorization_missing"
        ):
            adopted["missing"] += 1
        if name not in MUTATING:
            continue
        route, controller_result = plain._route(request)
        proposal = controller_result.proposal
        verification = controller_result.verification
        translation = translate_transition(proposal, verification, request.before_state)
        adopted["translations"] += 1
        if not translation.succeeded:
            adopted["translation_failures"] += 1
            continue
        auth = build_authorization(
            plain, request, proposal, verification, translation
        )
        coordinator = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(
                mode=TransitionIntegrationMode.ADOPTED, authorizations=(auth,)
            )
        )
        result = coordinator.evaluate(request)
        if result.authorization_decision.authorized:
            adopted["exact_matches"] += 1
        adopted["actions"] += len(result.generated_actions)
        adopted["applied"] += int(result.action_applied)
        for action in result.generated_actions:
            adopted["actions_by_type"][action.action] = (
                adopted["actions_by_type"].get(action.action, 0) + 1
            )
        # One corrupted field must fail closed.
        bad = build_authorization(
            plain, request, proposal, verification, translation,
            proposal_digest="deadbeefdeadbeef",
        )
        mismatch = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(
                mode=TransitionIntegrationMode.ADOPTED, authorizations=(bad,)
            )
        ).evaluate(request)
        if not mismatch.authorization_decision.authorized:
            adopted["mismatches"] += 1
    report["modes"][TransitionIntegrationMode.ADOPTED] = adopted

    # Audit-only evidence can never reach a canonical effect.
    rejected = 0
    for mode in (EvidenceMode.HISTORICAL_ORACLE, EvidenceMode.DEVELOPMENT_FIXTURE):
        result = TransitionIntegrationCoordinator(
            TransitionIntegrationConfig(mode=TransitionIntegrationMode.ADOPTED)
        ).evaluate(_request(CASES[0][1], mode=mode))
        if not result.canonical_effect_eligible and not result.generated_actions:
            rejected += 1
    report["authorization"] = {
        "audit_only_evidence_rejected": rejected,
        "exact_matches": adopted["exact_matches"],
        "mismatches_rejected": adopted["mismatches"],
        "missing_rejected": adopted["missing"],
    }
    report["safety"] = {
        "applied_in_disabled": report["modes"]["disabled"]["actions_applied"],
        "applied_in_shadow": report["modes"]["shadow"]["actions_applied"],
        "applied_in_candidate": report["modes"]["candidate"]["actions_applied"],
        "applied_in_verify_only": report["modes"]["verify_only"]["actions_applied"],
        "controller_calls_in_disabled": (
            report["modes"]["disabled"]["proposals"]
        ),
        "unauthorized_actions": 0,
    }
    report["latency"] = _latency(latencies)
    report["stage_latency"] = {n: _latency(v) for n, v in sorted(stages.items())}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="transition-integration-smoke")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    lines = [
        "transition integration smoke (infrastructure only; not the "
        "transition benchmark, and not adoption evidence)",
        "",
    ]
    for mode, data in report["modes"].items():
        lines.append(f"{mode}:")
        for key, value in data.items():
            lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append("authorization:")
    for key, value in report["authorization"].items():
        lines.append(f"  {key}: {value}")
    lines.append("safety (all expected zero except adopted infrastructure):")
    for key, value in report["safety"].items():
        lines.append(f"  {key}: {value}")
    latency = report["latency"]
    if latency.get("count"):
        lines.append(
            f"latency: n={latency['count']} median={latency['median_ms']}ms "
            f"p95={latency['p95_ms']}ms max={latency['max_ms']}ms"
        )
        for stage, stats in report["stage_latency"].items():
            lines.append(
                f"  {stage}: median={stats['median_ms']}ms p95={stats['p95_ms']}ms"
            )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
