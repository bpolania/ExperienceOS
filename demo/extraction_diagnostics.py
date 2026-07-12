"""Read-only view models for grounded-extraction dashboard visibility.

Two distinct surfaces, kept separate:

- a live decision trace normalized from ``extraction_integration_evaluated``
  events (old, partial, and unknown-field events are tolerated); and
- a committed benchmark summary loaded read-only from the feature-named
  result directories.

Nothing here constructs a controller, runner, or provider; loads a model;
reads credentials; touches the network; runs a benchmark; or mutates any
state. A live shadow proposal is never presented as benchmark proof, and
a benchmark classification is never presented as a live action.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

EXTRACTION_EVENT = "extraction_integration_evaluated"

# Display-only mode vocabulary. Adopted is intentionally absent from the
# selectable set: it requires an explicit authorization object that the
# dashboard never synthesizes.
MODE_DISABLED = "disabled"
MODE_SHADOW = "shadow"
MODE_CANDIDATE = "candidate"
SELECTABLE_MODES = (MODE_DISABLED, MODE_SHADOW, MODE_CANDIDATE)

_UNAVAILABLE = "Unavailable"
_MAX_TEXT = 240
_MAX_EVIDENCE = 200

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_DATA_PATH = (
    REPO_ROOT
    / "benchmarks/results/committed/report-grounded-extraction/report_data.json"
)
ADOPTION_GATES_PATH = (
    REPO_ROOT
    / "benchmarks/results/committed/report-grounded-extraction/adoption_gates.json"
)
CASES_PATH = (
    REPO_ROOT
    / "benchmarks/results/committed/grounded-extraction-ablation/cases.jsonl"
)
ANNOTATIONS_PATH = (
    REPO_ROOT / "benchmarks/annotations/grounded-extraction/lifecycle.jsonl"
)
REPORT_DOC = "docs/grounded_extraction_report.md"

GROUNDED_RULES_ID = "experienceos_grounded_rules_v1"
REFERENCE_ID = "experienceos_hybrid_full_v2_reference"

# The judge-facing example cases the benchmark report calls out, resolved
# to stable committed case IDs.
CASE_EXAMPLES = (
    ("creation_002_durable_user_fact",
     "A durable fact the deterministic controller missed."),
    ("forgetting_003_forget_one_of_several",
     "A forget directive the controller wrongly extracted from."),
    ("updates_003_instruction_replacement",
     "A semantic-duplicate active memory under benchmark-only adoption."),
)

CLASSIFICATION_LABELS = {
    "shadow_only": "Shadow only",
    "candidate_only": "Candidate only",
    "eligible_for_future_adoption_review": "Eligible for future review",
    "not_justified": "Not justified",
    "unavailable": "Unavailable",
    "insufficient_evidence": "Insufficient evidence",
}


# -- demo mode selection (non-mutating only) -------------------------------

# Display labels for the sidebar selector, mapped to effect modes. Adopted
# is deliberately excluded — it needs an explicit authorization object the
# dashboard never creates.
MODE_LABELS = {
    "Disabled (default)": MODE_DISABLED,
    "Shadow (observe, non-mutating)": MODE_SHADOW,
    "Candidate (lifecycle eval, non-mutating)": MODE_CANDIDATE,
}
MODE_CHOICES = tuple(MODE_LABELS.keys())


def build_extraction_config(mode: str):
    """Build a non-mutating extraction config for a selectable mode.

    Returns None for disabled. Never builds adopted mode and never
    synthesizes an adoption authorization, so no dashboard selection can
    mutate durable memory.
    """
    if mode not in (MODE_SHADOW, MODE_CANDIDATE):
        return None
    from experienceos.memory.extraction_integration import (
        ExtractionIntegrationConfig,
    )

    return ExtractionIntegrationConfig(effect_mode=mode)


# -- configured mode (read-only) -------------------------------------------

def configured_extraction_mode(agent) -> str:
    """The agent's configured effect mode, read without side effects."""
    coordinator = getattr(agent, "extraction_coordinator", None)
    if coordinator is None:
        return MODE_DISABLED
    config = getattr(coordinator, "config", None)
    mode = getattr(config, "effect_mode", None)
    return mode or MODE_DISABLED


# -- live event view model -------------------------------------------------

def _bounded(text, limit=_MAX_TEXT):
    if not isinstance(text, str):
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def normalize_extraction_event(payload) -> dict:
    """Bounded presentation view of one integration event payload.

    Missing fields become ``None`` (rendered as distinct unavailable
    states, never misleading false values); unknown additive fields are
    ignored rather than invalidating the event.
    """
    payload = payload if isinstance(payload, dict) else {}

    def get(key):
        return payload.get(key)

    return {
        "effect_mode": get("effect_mode"),
        "controller_type": get("controller_type"),
        "controller_id": get("controller_id"),
        "controller_version": get("controller_version"),
        "controller_outcome": get("controller_outcome"),
        "proposal_present": get("proposal_present"),
        "proposed_kind": get("proposed_kind"),
        "normalized_text": _bounded(get("normalized_text")),
        "evidence_start": get("evidence_start"),
        "evidence_end": get("evidence_end"),
        "evidence_length": get("evidence_length"),
        "source_provenance": get("source_provenance"),
        "grounding_status": get("grounding_status"),
        "grounding_code": get("grounding_code"),
        "lifecycle_evaluation": get("lifecycle_evaluation"),
        "lifecycle_rejection_reason": get("lifecycle_rejection_reason"),
        "duplicate_or_conflict": get("duplicate_or_conflict"),
        "fallback_mode": get("fallback_mode"),
        "fallback_used": get("fallback_used"),
        "fallback_reason": get("fallback_reason"),
        "final_proposal_source": get("final_proposal_source"),
        "adoption_authorized": get("adoption_authorized"),
        "action_generated": get("action_generated"),
        "action_applied": get("action_applied"),
        "canonical_effect": get("canonical_effect"),
        "runner_status": get("runner_status"),
        "parser_status": get("parser_status"),
        "integration_status": get("integration_status"),
        "error_class": get("error_class"),
    }


def extraction_trace(events, limit=8) -> list:
    """Normalized extraction views, most recent first (bounded history)."""
    views = [
        normalize_extraction_event(getattr(e, "payload", {}))
        for e in (events or [])
        if getattr(e, "type", None) == EXTRACTION_EVENT
    ]
    views.reverse()
    return views[:limit]


def outcome_label(view) -> str:
    """A first-class, non-error phrase for candidate-or-none outcomes."""
    status = view.get("integration_status")
    if status == "controller_error":
        return "Controller error (contained)"
    if view.get("proposal_present"):
        return "Candidate proposed"
    if view.get("runner_status") in ("unavailable", "error"):
        return "Learned runner unavailable"
    return {
        "no_candidate": "Controller abstained — no candidate",
        "grounding_rejected": "Grounding rejected the candidate",
        "integration_rejected": "Integration re-validation rejected it",
        "authorization_missing": "Adoption not authorized",
        "authorization_mismatch": "Adoption authorization mismatch",
    }.get(status, "No candidate proposed")


def canonical_effect_label(view) -> str:
    effect = view.get("canonical_effect")
    if effect is True:
        return "Yes — durable memory changed"
    if effect is False:
        return "No — durable state unchanged"
    return _UNAVAILABLE


# -- evidence rendering (bounded, escaped) ---------------------------------

def evidence_block(source_text, start, end) -> dict:
    """Bounded, injection-safe evidence view.

    Highlights only the verified span within an escaped, bounded excerpt.
    Never reconstructs evidence from the normalized candidate; when the
    source text or offsets are unusable, returns offsets only.
    """
    offsets_label = None
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
        offsets_label = f"[{start}, {end}) zero-based, end-exclusive"
    if not isinstance(source_text, str) or offsets_label is None or (
        end > len(source_text)
    ):
        return {
            "available": False,
            "offsets_label": offsets_label,
            "excerpt_html": None,
            "excerpt_text": None,
            "exact_span_valid": None,
        }
    # window the excerpt around the span, bounded
    window_start = max(0, start - 40)
    window_end = min(len(source_text), end + 40)
    excerpt = source_text[window_start:window_end]
    rel_start = start - window_start
    rel_end = end - window_start
    before = html.escape(excerpt[:rel_start])
    span = html.escape(excerpt[rel_start:rel_end])
    after = html.escape(excerpt[rel_end:])
    prefix = "…" if window_start > 0 else ""
    suffix = "…" if window_end < len(source_text) else ""
    highlighted = f"{prefix}{before}<mark>{span}</mark>{after}{suffix}"
    return {
        "available": True,
        "offsets_label": offsets_label,
        "excerpt_html": highlighted[: _MAX_EVIDENCE * 4],
        "excerpt_text": _bounded(source_text[start:end], _MAX_EVIDENCE),
        "exact_span_valid": True,
    }


# -- committed benchmark summary (read-only) -------------------------------

def _ratio(block) -> str:
    """num/den (pct) from an artifact ratio block; unavailable stays so."""
    if not isinstance(block, dict):
        return _UNAVAILABLE
    num, den, rate = (block.get("numerator"), block.get("denominator"),
                      block.get("rate"))
    if num is None or den in (None, 0):
        return _UNAVAILABLE if rate is None else f"{num}/{den}"
    return f"{num}/{den} ({rate * 100:.1f}%)"


def classification_label(value) -> str:
    return CLASSIFICATION_LABELS.get(value, value or _UNAVAILABLE)


def grounded_extraction_summary(
    report_data_path=REPORT_DATA_PATH,
    adoption_path=ADOPTION_GATES_PATH,
) -> dict | None:
    """Compact grounded-extraction evaluation read from committed data.

    Returns None when artifacts are missing or malformed — the dashboard
    renders an unavailable state and never regenerates evidence.
    """
    try:
        data = json.loads(Path(report_data_path).read_text())
        gates = json.loads(Path(adoption_path).read_text())
        aggs = {a["system_id"]: a for a in data["aggregates"]}
        grd = aggs[GROUNDED_RULES_ID]
        ref = aggs[REFERENCE_ID]
        cm = grd["creation_metrics"]
        gm = grd["grounding_metrics"]
        nc = grd["no_candidate_metrics"]
        sf = grd["safety_metrics"]
        classifications = {
            c["system_id"]: c for c in data["classifications"]
        }
        f1 = cm["f1"].get("value") if isinstance(cm["f1"], dict) else None
        return {
            "classification": classifications[GROUNDED_RULES_ID][
                "classification"],
            "classification_reason": classifications[GROUNDED_RULES_ID][
                "reason"],
            "metrics": {
                "precision": _ratio(cm["precision"]),
                "recall": _ratio(cm["recall"]),
                "f1": (f"{f1:.3f}" if isinstance(f1, (int, float))
                       else _UNAVAILABLE),
                "grounded_span_validity": _ratio(
                    gm["grounded_span_validity"]),
                "no_candidate_recall": _ratio(nc["no_candidate_recall"]),
                "durable_creation_reference": _ratio(
                    ref["creation_metrics"]["durable_creation_recall"]),
                "durable_creation_grounded": _ratio(
                    cm["durable_creation_recall"]),
                "duplicate_active_memories": sf["duplicate_active_memories"],
                "state_corruption": sf["state_corruption"],
                "latency_mean_ms": grd["latency_metrics"].get("mean_ms"),
            },
            "gates": {
                "passed": gates["passed"],
                "failed": gates["failed"],
                "not_measurable": gates["not_measurable"],
                "total": gates["gate_count"],
                "all_pass": gates["all_pass"],
                "rows": [
                    {
                        "gate": g["gate"],
                        "threshold": g["threshold"],
                        "measured": g["measured"],
                        "status": g["status"],
                    }
                    for g in gates["gates"]
                ],
                "failed_gates": [
                    g["gate"] for g in gates["gates"]
                    if g["status"] == "fail"
                ],
            },
            "learned": [
                {
                    "system_id": run["system_id"],
                    "executed": run["executed"],
                    "skip_reason": run["skip_reason"],
                }
                for run in data["optional_runs"]
            ],
            "systems": {
                "reference": REFERENCE_ID,
                "grounded_rules": GROUNDED_RULES_ID,
            },
            "report_doc": REPORT_DOC,
            "provider_note": (
                "Committed evidence on the frozen lifecycle annotations. "
                "The deterministic controller is classified shadow-only and "
                "no controller is adopted; passing most gates is not "
                "adoption approval — the failed gates are decisive."),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def extraction_case_examples(
    cases_path=CASES_PATH, annotations_path=ANNOTATIONS_PATH,
) -> list:
    """Bounded judge-facing case cards from committed per-case artifacts."""
    try:
        rows = {}
        for line in Path(cases_path).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("system_id") == GROUNDED_RULES_ID:
                rows[rec["case_id"]] = rec
        sources = {}
        for line in Path(annotations_path).read_text().splitlines():
            if not line.strip():
                continue
            ann = json.loads(line)
            sources[ann["case_id"]] = ann.get("source_text")
    except (OSError, ValueError):
        return []

    cards = []
    for case_id, why in CASE_EXAMPLES:
        rec = rows.get(case_id)
        if rec is None:
            continue
        source = sources.get(case_id)
        evidence = evidence_block(
            source, rec.get("evidence_start"), rec.get("evidence_end"))
        cards.append({
            "case_id": case_id,
            "why": why,
            "expected_candidate": rec.get("expected_candidate_status"),
            "proposal_present": rec.get("proposal_present"),
            "proposed_kind": rec.get("proposed_kind"),
            "normalized_text": _bounded(rec.get("normalized_text")),
            "grounding_code": rec.get("grounding_code"),
            "proposal_score": rec.get("proposal_score"),
            "lifecycle_evaluation": rec.get("lifecycle_evaluation_status"),
            "durable_creation_correct": rec.get("durable_creation_correct"),
            "duplicate_active_leak": rec.get("duplicate_active_leak"),
            "canonical_effect": rec.get("canonical_effect"),
            "evidence": evidence,
            "source_excerpt": _bounded(source, _MAX_EVIDENCE),
        })
    return cards
