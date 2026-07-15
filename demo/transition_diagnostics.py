"""Presentation layer for transition intelligence.

Read-only. This module renders two kinds of evidence and never produces
either:

- **live runtime diagnostics** from the optional
  `transition_integration_evaluated` event;
- **committed benchmark evidence** from the frozen transition result
  artifacts.

The committed artifacts are authoritative. Nothing here recomputes a
metric, re-derives the adoption classification, or reinterprets a gate:
if a display value ever disagrees with an artifact, the artifact wins and
the display is the bug.

Every benchmark number the dashboard shows comes from this module, so
there is exactly one source and no chance of two panels drifting apart.

Safety boundaries this module keeps:

- it constructs no provider, calls no model, and touches no network;
- it never writes to a store and never mutates an artifact;
- adopted mode is **not** offered as a selectable runtime mode — it needs
  an authorization bound to an exact verified proposal, which no UI
  control can supply.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TRANSITION_EVENT = "transition_integration_evaluated"

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = REPO_ROOT / "benchmarks/results/committed/transition-verification"
ABLATION_DIR = REPO_ROOT / "benchmarks/results/committed/transition-ablation"
REPORT_DIR = REPO_ROOT / "benchmarks/results/committed/report-transition-verification"
REPORT_DOC = "docs/transition_verification_report.md"

_MAX_TEXT = 240
_MAX_CANDIDATES = 6
_UNAVAILABLE = "Unavailable"

# Selectable runtime modes. Adopted is deliberately absent: it requires a
# structured authorization bound to an exact verified proposal, so it can
# never be reachable from a dropdown.
MODE_DISABLED = "disabled"
MODE_SHADOW = "shadow"
MODE_CANDIDATE = "candidate"
MODE_VERIFY_ONLY = "verify_only"

MODE_LABELS = {
    "Disabled (default)": MODE_DISABLED,
    "Shadow (observe, non-mutating)": MODE_SHADOW,
    "Candidate (full path, non-mutating)": MODE_CANDIDATE,
    "Verify-only (check planner actions)": MODE_VERIFY_ONLY,
}
MODE_CHOICES = tuple(MODE_LABELS.keys())

#: User-readable transition labels. The frozen taxonomy is not renamed —
#: these are display strings for the same committed values.
TRANSITION_LABELS = {
    "create_new": "Create new experience",
    "duplicate_noop": "Exact duplicate: no change",
    "semantic_duplicate_noop": "Semantic duplicate: no change",
    "supersede_existing": "Replace current experience",
    "scoped_coexistence": "Add scoped experience",
    "forget_existing": "Forget existing experience",
    "reject_forget_directive_as_creation": "Reject forget-as-creation",
    "reject_unsupported": "Reject unsupported",
    "reject_ambiguous": "Reject ambiguous",
    "reject_temporary": "Reject temporary",
    "reject_question": "Reject question",
    "reject_hypothetical": "Reject hypothetical",
    "reject_unrelated": "Reject unrelated",
    "shadow_only": "Shadow only",
}

ROUTE_LABELS = {
    "not_invoked": "Not invoked",
    "update_controller": "Update intelligence",
    "forget_controller": "Forget intelligence (handoff)",
    "abstained": "Abstained",
    "routing_error": "Routing error",
}

EFFECT_LABELS = {
    "unchanged": "Canonical actions unchanged",
    "diagnostics_only": "Diagnostics only",
    "candidate_only": "Candidate only (not inserted)",
    "verified_existing_actions": "Existing actions verified",
    "action_added": "Canonical action added",
    "action_replaced": "Canonical action replaced",
    "action_suppressed": "Canonical action suppressed",
    "authorization_denied": "Authorization denied",
    "translation_failed": "Translation failed",
    "lifecycle_rejected": "Lifecycle rejected",
    "engine_rejected": "Engine rejected",
    "applied": "Applied by the engine",
}

#: Categories that exist only as authored development fixtures. Naming
#: them keeps fixture findings from reading as historical evidence.
FIXTURE_ONLY_CATEGORIES = (
    "negative forget",
    "forget questions",
    "inspection questions",
    "hypothetical forget",
    "broad forget",
    "ambiguous forget target",
    "switched-from-to replacement",
    "no-longer-now replacement",
    "overlapping scope",
)


def build_transition_config(mode: str):
    """A config for a selectable non-mutating mode, or None when disabled.

    Adopted is rejected outright: a UI selection can never authorize a
    canonical effect.
    """
    if mode == MODE_DISABLED:
        return None
    if mode not in (MODE_SHADOW, MODE_CANDIDATE, MODE_VERIFY_ONLY):
        raise ValueError(
            f"{mode!r} is not selectable; adopted mode requires an "
            "authorization bound to an exact verified proposal"
        )
    from experienceos.memory.transition_integration import (
        TransitionIntegrationConfig,
    )

    return TransitionIntegrationConfig(mode=mode)


def configured_transition_mode(agent) -> str:
    coordinator = getattr(agent, "transition_coordinator", None)
    if coordinator is None:
        return MODE_DISABLED
    return getattr(coordinator, "mode", MODE_DISABLED)


def _bounded(text, limit=_MAX_TEXT) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- Committed artifact readers ----------------------------------------------


def _load(path: Path):
    """Read one committed artifact, or None when it is absent."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=1)
def _report_bundle() -> dict | None:
    """Every committed report artifact, or None when unavailable.

    Cached for the process: the artifacts are committed files that only
    change when the benchmark is regenerated, which does not happen while
    the dashboard runs. `reload_artifacts()` clears the cache for tests
    and for anyone regenerating them in place.
    """
    report = _load(REPORT_DIR / "report_data.json")
    gates = _load(REPORT_DIR / "gate_summary.json")
    headline = _load(REPORT_DIR / "headline_metrics.json")
    claims = _load(REPORT_DIR / "claims.json")
    limitations = _load(REPORT_DIR / "limitations.json")
    if not all((report, gates, headline, claims, limitations)):
        return None
    return {
        "report": report,
        "gates": gates,
        "headline": headline,
        "claims": claims,
        "limitations": limitations,
        "systems": (_load(VERIFICATION_DIR / "systems.json") or {}).get(
            "systems", []
        ),
        "ablations": (_load(ABLATION_DIR / "ablations.json") or {}).get(
            "ablations", []
        ),
    }


def reload_artifacts() -> None:
    """Drop cached artifact reads so the next call re-reads from disk."""
    _report_bundle.cache_clear()
    _cases.cache_clear()


def benchmark_available() -> bool:
    return _report_bundle() is not None


def status_summary() -> dict:
    """The persistent header. Values come from committed evidence only."""
    bundle = _report_bundle()
    if bundle is None:
        return {
            "available": False,
            "runtime_default": "Disabled",
            "classification": _UNAVAILABLE,
            "classification_label": _UNAVAILABLE,
            "canonical_controller": "None",
            "gate_summary": _UNAVAILABLE,
            "gates_passed": None,
            "gates_failed": None,
            "gates_inconclusive": None,
            "rationale": "",
        }
    gates = bundle["gates"]
    return {
        "available": True,
        "runtime_default": "Disabled",
        "classification": gates["classification"],
        "classification_label": _classification_label(gates["classification"]),
        "canonical_controller": "None",
        "gate_summary": (
            f"{gates['passed']} passed, {gates['failed']} failed, "
            f"{gates['inconclusive']} inconclusive, "
            f"{gates['unavailable']} unavailable"
        ),
        "gates_passed": gates["passed"],
        "gates_failed": gates["failed"],
        "gates_inconclusive": gates["inconclusive"],
        "rationale": gates["rationale"],
    }


def _classification_label(classification: str) -> str:
    return {
        "TRANSITION_PATH_ELIGIBLE_FOR_ADOPTION": "Eligible for adoption",
        "TRANSITION_PATH_CANDIDATE_ONLY": "Candidate only",
        "TRANSITION_PATH_SHADOW_ONLY": "Shadow only",
        "TRANSITION_PATH_DISABLED": "Disabled",
        "TRANSITION_PATH_EVIDENCE_INCONCLUSIVE": "Evidence inconclusive",
    }.get(classification, classification)


def gate_rows() -> list:
    """All twenty gates, in contract order, exactly as committed."""
    bundle = _report_bundle()
    if bundle is None:
        return []
    return [
        {
            "gate": g["gate"],
            "name": g["name"],
            "role": g["role"],
            "threshold": g["threshold"],
            "reference": g["reference"],
            "candidate": g["candidate"],
            "absolute_delta": g["absolute_delta"],
            "relative_delta": g["relative_delta"],
            "decision": g["decision"],
            "decision_label": g["decision"].replace("_", " ").title(),
            "blocking": g["blocking"],
            "justification": g["justification"],
            "evidence": g["evidence"],
        }
        for g in bundle["gates"]["gates"]
    ]


def blocking_gates() -> list:
    """Gates whose failure blocks adoption, per the committed artifact.

    Derived, never hardcoded: the artifact decides which gates block, and
    a stale constant in the UI would be a second source of truth.
    """
    return [g for g in gate_rows() if g["blocking"]]


def highlighted_gates() -> list:
    """Gates a judge must see: anything not passing."""
    return [g for g in gate_rows() if g["decision"] != "pass"]


def system_rows() -> list:
    """Every registered system, including unavailable ones.

    An unavailable system carries its committed reason and **no metrics**;
    rendering it as a zero-scoring system would invent a result.
    """
    bundle = _report_bundle()
    if bundle is None:
        return []
    metrics = bundle["report"]["systems"]
    rows = []
    for spec in bundle["systems"]:
        system_id = spec["system_id"]
        row = {
            "system_id": system_id,
            "reference_level": spec["reference_level"],
            "mode": spec["mode"],
            "available": spec["available"],
            "unavailable_reason": spec["unavailable_reason"],
            "description": spec["description"],
        }
        measured = metrics.get(system_id)
        if measured is None:
            row.update(
                {
                    "classification": _UNAVAILABLE,
                    "targets": _UNAVAILABLE,
                    "stale_pairs": _UNAVAILABLE,
                    "duplicate_pairs": _UNAVAILABLE,
                    "preservation": _UNAVAILABLE,
                    "actions_applied": _UNAVAILABLE,
                }
            )
        else:
            actual = measured["lifecycle_actual"]
            row.update(
                {
                    "classification": (
                        f"{measured['classification']['correct']}"
                        f"/{measured['classification']['total']}"
                    ),
                    "targets": (
                        f"{measured['target']['correct']}"
                        f"/{measured['target']['total']}"
                    ),
                    "stale_pairs": actual["stale_pairs"],
                    "duplicate_pairs": actual["duplicate_pairs"],
                    "preservation": (
                        f"{actual['preservation']['correct']}"
                        f"/{actual['preservation']['total']}"
                    ),
                    "actions_applied": measured["actions_applied"],
                }
            )
        rows.append(row)
    return rows


def duplicate_stale_rows() -> list:
    """The decisive trade-off, as committed.

    Three columns that must never be conflated: what the reference really
    does, what the candidate's verified proposal *would* do, and what the
    isolated adopted path really did.
    """
    bundle = _report_bundle()
    if bundle is None:
        return []
    systems = bundle["report"]["systems"]
    reference = systems["experienceos_hybrid_full_v2_reference"]
    candidate = systems["experienceos_transition_candidate_v1"]
    adopted = systems["experienceos_transition_adopted_v1"]
    safety = bundle["report"]["safety"]
    return [
        {
            "metric": "Stale active pairs",
            "reference": reference["lifecycle_actual"]["stale_pairs"],
            "candidate_projection": candidate["lifecycle_projected"]["stale_pairs"],
            "isolated_applied": adopted["lifecycle_actual"]["stale_pairs"],
        },
        {
            "metric": "Duplicate pairs",
            "reference": reference["lifecycle_actual"]["duplicate_pairs"],
            "candidate_projection": (
                candidate["lifecycle_projected"]["duplicate_pairs"]
            ),
            "isolated_applied": adopted["lifecycle_actual"]["duplicate_pairs"],
        },
        {
            "metric": "Targets deactivated",
            "reference": (
                f"{reference['lifecycle_actual']['targets_deactivated']['correct']}"
                f"/{reference['lifecycle_actual']['targets_deactivated']['total']}"
            ),
            "candidate_projection": "n/a (non-mutating)",
            "isolated_applied": (
                f"{adopted['lifecycle_actual']['targets_deactivated']['correct']}"
                f"/{adopted['lifecycle_actual']['targets_deactivated']['total']}"
            ),
        },
        {
            "metric": "Scoped memories lost",
            "reference": 0,
            "candidate_projection": 0,
            "isolated_applied": safety["scoped_memories_lost"],
        },
        {
            "metric": "Unrelated memories lost",
            "reference": 0,
            "candidate_projection": 0,
            "isolated_applied": safety["unrelated_memories_lost"],
        },
    ]


def duplicate_finding() -> dict:
    """The narrative for the central trade-off, from committed values."""
    bundle = _report_bundle()
    if bundle is None:
        return {"available": False}
    head = bundle["headline"]
    gate_one = next(
        (g for g in bundle["gates"]["gates"] if g["gate"] == 1), None
    )
    return {
        "available": True,
        "reference_stale": head["reference_stale_pairs"],
        "applied_stale": head["adopted_stale_pairs"],
        "reference_duplicates": head["reference_duplicate_pairs"],
        "applied_duplicates": head["adopted_duplicate_pairs"],
        "cause": (
            "the transition replacement create was added alongside the "
            "canonical planner's create, so both persist"
        ),
        "consequence": "Gate 1 fails; the path remains candidate only",
        "future_work": "action-replacement integration semantics",
        "gate_one_justification": gate_one["justification"] if gate_one else "",
    }


def partition_counts() -> dict:
    bundle = _report_bundle()
    if bundle is None:
        return {}
    return dict(bundle["report"]["partitions"])


def safety_rows() -> list:
    bundle = _report_bundle()
    if bundle is None:
        return []
    return [
        {"metric": key.replace("_", " "), "value": str(value)}
        for key, value in sorted(bundle["report"]["safety"].items())
    ]


def ablation_rows() -> list:
    bundle = _report_bundle()
    if bundle is None:
        return []
    return [
        {
            "ablation_id": a["ablation_id"],
            "disabled_component": a["disabled_component"],
            "applicable_cases": a["applicable_cases"],
            "score": a["metrics"].get("classification_correct", _UNAVAILABLE),
            "safety_failures": a["safety_failures"],
            "runtime_eligible": a["runtime_eligible"],
            "description": a["description"],
        }
        for a in bundle["ablations"]
    ]


def claim_rows() -> dict:
    bundle = _report_bundle()
    if bundle is None:
        return {"supported": [], "unsupported": []}
    return bundle["claims"]


def limitation_rows() -> list:
    bundle = _report_bundle()
    if bundle is None:
        return []
    return list(bundle["limitations"]["limitations"])


def downstream_summary() -> dict:
    bundle = _report_bundle()
    if bundle is None:
        return {}
    return bundle["report"]["downstream"]


def lifecycle_chain() -> dict:
    bundle = _report_bundle()
    if bundle is None:
        return {}
    return bundle["report"]["lifecycle"]


@lru_cache(maxsize=1)
def _cases() -> tuple:
    path = VERIFICATION_DIR / "per-case.jsonl"
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return ()
    return tuple(rows)


def case_rows(system_id=None, partition=None, transition_type=None,
              verifier_status=None, applied=None, source_case_id=None) -> list:
    """Committed per-case records, filtered. Deterministic ordering."""
    rows = list(_cases())
    if system_id:
        rows = [r for r in rows if r["system_id"] == system_id]
    if partition:
        rows = [r for r in rows if r["partition"] == partition]
    if transition_type:
        rows = [r for r in rows if r["observed_type"] == transition_type]
    if verifier_status:
        rows = [r for r in rows if r["verifier_status"] == verifier_status]
    if applied is not None:
        rows = [r for r in rows if r["action_applied"] is applied]
    if source_case_id:
        rows = [r for r in rows if r["source_case_id"] == source_case_id]
    return sorted(rows, key=lambda r: (r["system_id"], r["case_id"]))


def case_ids() -> list:
    return sorted({r["source_case_id"] for r in _cases()})


def case_systems() -> list:
    return sorted({r["system_id"] for r in _cases()})


# --- Live runtime trace -------------------------------------------------------

#: The ordered pipeline a judge should be able to read top to bottom.
STAGE_ORDER = (
    "Source",
    "Routing",
    "Controller",
    "Identity",
    "Target resolution",
    "Proposal",
    "Verification",
    "Canonical-effect eligibility",
    "Authorization",
    "Translation",
    "Manager / engine admission",
    "Application",
    "Resulting lifecycle state",
)

_NOT_RUN = "not_run"
_PASSED = "passed"
_REJECTED = "rejected"
_SKIPPED = "skipped"
_INFO = "info"


def normalize_transition_event(payload) -> dict:
    """Bounded, defensive view of one transition annotation.

    Old events carry no transition annotation at all, and a future
    version may add fields this build has never seen. Both must render
    rather than crash, so every field is read defensively and unknown
    keys are ignored.
    """
    if not isinstance(payload, dict):
        return {"malformed": True, "reason": "annotation is not an object"}
    try:
        authorization = payload.get("authorization") or {}
        translation = payload.get("translation") or {}
        return {
            "malformed": False,
            "annotation_version": payload.get("annotation_version", _UNAVAILABLE),
            "configured_mode": payload.get("configured_mode", _UNAVAILABLE),
            "effective_mode": payload.get("effective_mode", _UNAVAILABLE),
            "system_id": payload.get("system_id"),
            "route": payload.get("route", "not_invoked"),
            "controller_id": payload.get("controller_id"),
            "controller_version": payload.get("controller_version"),
            "controller_invoked": bool(payload.get("controller_invoked")),
            "verifier_invoked": bool(payload.get("verifier_invoked")),
            "authorization_checked": bool(payload.get("authorization_checked")),
            "translation_attempted": bool(payload.get("translation_attempted")),
            "transition_type": payload.get("transition_type"),
            "proposal_id": payload.get("proposal_id"),
            "target_ids": list(payload.get("target_ids") or []),
            "preserved_ids": list(payload.get("preserved_ids") or []),
            "verifier_status": payload.get("verifier_status"),
            "verifier_rejection_reason": payload.get("verifier_rejection_reason"),
            "canonical_effect_eligible": bool(
                payload.get("canonical_effect_eligible")
            ),
            "authorized": authorization.get("authorized"),
            "authorization_reason": authorization.get("reason", ""),
            "mismatched_fields": list(authorization.get("mismatched_fields") or []),
            "translation_succeeded": translation.get("succeeded"),
            "translation_reason": translation.get("reason", ""),
            "generated_action_types": list(
                payload.get("generated_action_types") or []
            ),
            "canonical_action_effect": payload.get(
                "canonical_action_effect", "unchanged"
            ),
            "canonical_effect_status": payload.get("canonical_effect_status"),
            "existing_action_verifications": list(
                payload.get("existing_action_verifications") or []
            ),
            "fallback_used": bool(payload.get("fallback_used")),
            "failure_stage": payload.get("failure_stage", "none"),
            "failure_reason": payload.get("failure_reason", ""),
            "action_applied": bool(payload.get("action_applied")),
            "diagnostics": [
                {
                    "code": d.get("code", ""),
                    "category": d.get("category", ""),
                    "detail": _bounded(d.get("detail", ""), 160),
                }
                for d in (payload.get("diagnostics") or [])
                if isinstance(d, dict)
            ],
        }
    except (AttributeError, TypeError, ValueError) as exc:
        return {"malformed": True, "reason": type(exc).__name__}


def transition_trace(events, limit=8) -> list:
    """Most recent transition annotations, newest last."""
    payloads = [
        normalize_transition_event(e.payload)
        for e in events
        if getattr(e, "type", None) == TRANSITION_EVENT
    ]
    return payloads[-limit:]


def pipeline_stages(record) -> list:
    """The live trace as ordered stages.

    A skipped stage is never shown as passed, a verified proposal never as
    authorized, and an authorized proposal never as applied.
    """
    if not record or record.get("malformed"):
        return []
    stages = []

    def add(name, status, detail, code=""):
        stages.append(
            {"stage": name, "status": status, "detail": detail, "code": code}
        )

    mode = record["effective_mode"]
    add("Source", _INFO, f"evidence mode carried into the seam; mode: {mode}")

    route = record["route"]
    add(
        "Routing",
        _INFO if route != "routing_error" else _REJECTED,
        ROUTE_LABELS.get(route, route),
    )

    if not record["controller_invoked"]:
        add("Controller", _NOT_RUN, "no controller ran")
    else:
        add(
            "Controller", _INFO,
            f"{record['controller_id'] or 'controller'} "
            f"v{record['controller_version'] or '?'}",
        )

    add(
        "Identity", _INFO if record["controller_invoked"] else _NOT_RUN,
        "semantic identity projected by the controller"
        if record["controller_invoked"] else "not projected",
    )

    targets = record["target_ids"]
    add(
        "Target resolution",
        _INFO if record["controller_invoked"] else _NOT_RUN,
        ", ".join(targets[:_MAX_CANDIDATES]) if targets else "no target selected",
    )

    transition = record["transition_type"]
    add(
        "Proposal",
        _INFO if transition else _NOT_RUN,
        TRANSITION_LABELS.get(transition, transition) if transition
        else "controller abstained; no proposal",
    )

    if not record["verifier_invoked"]:
        add("Verification", _NOT_RUN, "verification was not invoked")
    else:
        status = record["verifier_status"]
        add(
            "Verification",
            _PASSED if status == "accepted" else _REJECTED,
            record["verifier_rejection_reason"] or status or "",
        )

    add(
        "Canonical-effect eligibility",
        _PASSED if record["canonical_effect_eligible"] else _REJECTED,
        "eligible for later canonical consideration"
        if record["canonical_effect_eligible"]
        else "not eligible; no canonical effect possible",
    )

    if not record["authorization_checked"]:
        add(
            "Authorization", _NOT_RUN,
            "authorization not required in this mode",
        )
    elif record["authorized"]:
        add("Authorization", _PASSED, "exact match")
    else:
        detail = record["authorization_reason"] or "denied"
        if record["mismatched_fields"]:
            detail += f" ({', '.join(record['mismatched_fields'][:4])})"
        add("Authorization", _REJECTED, detail)

    if not record["translation_attempted"]:
        add("Translation", _NOT_RUN, "translation not attempted")
    else:
        add(
            "Translation",
            _PASSED if record["translation_succeeded"] else _REJECTED,
            ", ".join(record["generated_action_types"])
            or record["translation_reason"]
            or "no action produced",
        )

    effect = record["canonical_action_effect"]
    add(
        "Manager / engine admission",
        _PASSED if effect == "applied"
        else _REJECTED if effect in ("lifecycle_rejected", "engine_rejected")
        else _NOT_RUN,
        EFFECT_LABELS.get(effect, effect),
    )

    add(
        "Application",
        _PASSED if record["action_applied"] else _NOT_RUN,
        "the engine applied the action"
        if record["action_applied"]
        else "no action was applied",
    )

    add(
        "Resulting lifecycle state",
        _INFO,
        EFFECT_LABELS.get(effect, effect),
    )
    return stages


STATUS_BADGES = {
    _PASSED: "PASS",
    _REJECTED: "REJECTED",
    _NOT_RUN: "NOT RUN",
    _SKIPPED: "SKIPPED",
    _INFO: "INFO",
}


# --- Live lifecycle view ------------------------------------------------------


def lifecycle_cards(agent, user_id: str) -> list:
    """Bounded cards for the live store's memories.

    Superseded and forgotten records are included on purpose: accumulated
    experience is the product, and hiding its history would hide the point.
    """
    from experienceos.memory.identity import IdentityProjector

    projector = IdentityProjector()
    try:
        entries = agent.memory_store.list_memories(user_id=user_id)
    except Exception:
        return []
    cards = []
    for entry in entries:
        identity = projector.project_text(entry.text, kind=entry.kind)
        cards.append(
            {
                "memory_id": entry.id,
                "kind": entry.kind,
                "status": entry.status,
                "text": _bounded(entry.text),
                "subject": identity.subject.value,
                "attribute": identity.attribute.value,
                "value": identity.value.value,
                "scope": identity.scope.value,
                "target_key": identity.target_key(),
                "replaces": (entry.metadata or {}).get("superseded_by"),
            }
        )
    return cards


def lifecycle_groups(cards) -> dict:
    """Duplicate, stale, and scoped groupings over the live active set."""
    from experienceos.memory.identity import (
        IdentityProjector,
        IdentityRelation,
        compare_memory_identity,
    )

    projector = IdentityProjector()
    active = [c for c in cards if c["status"] == "active"]
    identities = {
        c["memory_id"]: projector.project_text(c["text"]) for c in active
    }
    duplicates, stale, scoped = [], [], []
    for index, first in enumerate(active):
        for second in active[index + 1:]:
            relation = compare_memory_identity(
                identities[first["memory_id"]], identities[second["memory_id"]]
            ).relation
            pair = (first["memory_id"], second["memory_id"])
            if relation in (
                IdentityRelation.EXACT_DUPLICATE,
                IdentityRelation.SEMANTIC_DUPLICATE,
            ):
                duplicates.append(pair)
            elif relation == IdentityRelation.CURRENT_STATE_CONFLICT:
                stale.append(pair)
            elif relation == IdentityRelation.SCOPED_COEXISTENCE:
                scoped.append(pair)
    return {
        "active": len(active),
        "superseded": sum(1 for c in cards if c["status"] == "superseded"),
        "forgotten": sum(1 for c in cards if c["status"] == "forgotten"),
        "duplicate_pairs": duplicates,
        "stale_pairs": stale,
        "scoped_pairs": scoped,
    }


def lineage_rows(cards) -> list:
    """Predecessor → replacement chains, plus forgotten audit records."""
    rows = []
    for card in cards:
        if card["status"] == "superseded":
            rows.append(
                {
                    "memory_id": card["memory_id"],
                    "state": "superseded (audit record)",
                    "text": card["text"],
                    "successor": card["replaces"] or "—",
                }
            )
        elif card["status"] == "forgotten":
            rows.append(
                {
                    "memory_id": card["memory_id"],
                    "state": "forgotten (audit record)",
                    "text": card["text"],
                    "successor": "—",
                }
            )
    return rows
