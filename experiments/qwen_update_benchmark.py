"""Side-by-side deterministic-vs-Qwen update-intelligence comparison.

Reuses the existing frozen update corpus, its annotations, and the
existing ``DeterministicUpdateController`` — no new benchmark framework,
no new corpus, no annotation changes. Both implementations are scored in
one shared five-class space (NEW / UPDATE / COEXIST / DUPLICATE /
IGNORE) derived from the committed transition annotations, over exactly
the classification-applicable records the deterministic benchmark
scores. Forget-boundary and unscored records are excluded here for the
same reason the deterministic benchmark excludes them.

Nothing here mutates memory: the harness holds no store, engine, or
manager and applies no action. Qwen classifies only; every deterministic
governance gate remains authoritative and untouched.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from benchmarks.annotations import transition_verification as tv
from benchmarks.transition_verification.proposal_fixtures import (
    before_state_for,
    evidence_for,
)
from benchmarks.update_intelligence.evaluation import is_classification_applicable
from experienceos.memory.update_intelligence import DeterministicUpdateController
from experiments.qwen_update import (
    QWEN_UPDATE_CONTROLLER_ID,
    QWEN_UPDATE_PROMPT_VERSION,
    UPDATE_CLASSIFICATIONS,
    ActiveMemoryView,
    QwenUpdateController,
    STATUS_INVALID_OUTPUT,
    STATUS_OK,
    STATUS_PROVIDER_ERROR,
    STATUS_PROVIDER_UNAVAILABLE,
)

COMPARISON_VERSION = "1"
DETERMINISTIC_CONTROLLER_ID = "experienceos_transition_rules_v1"

RESULTS_DIR = Path(__file__).resolve().parent / "results" / "qwen_update"

# Frozen transition label -> shared five-class label. Any reject_* maps to
# IGNORE; the mapping is total over the classification-applicable corpus.
_TRANSITION_TO_CLASS = {
    "create_new": "NEW",
    "supersede_existing": "UPDATE",
    "scoped_coexistence": "COEXIST",
    "duplicate_noop": "DUPLICATE",
    "semantic_duplicate_noop": "DUPLICATE",
}


def _to_class(transition_type: str | None) -> str:
    if transition_type is None:
        return "IGNORE"
    if transition_type in _TRANSITION_TO_CLASS:
        return _TRANSITION_TO_CLASS[transition_type]
    if transition_type.startswith("reject_"):
        return "IGNORE"
    # forget_existing and anything else are not durable-create classes.
    return "IGNORE"


def _active_views(record) -> list:
    """Active before-state memories offered as candidate targets."""
    views = []
    for memory in record["before_state"]:
        if memory["lifecycle_state"] != "active":
            continue
        views.append(
            ActiveMemoryView(
                memory_id=memory["memory_ref"]["logical_id"],
                kind=memory["kind"],
                text=memory.get("canonical_text") or "",
            )
        )
    return views


def load_cases() -> list:
    """The scored, classification-applicable cases in five-class form.

    The candidate text is the source statement itself — the corpus
    builds its created candidate directly from that statement, so this
    leaks no oracle. The expected class and target come only from the
    committed transition annotation.
    """
    corpus = tv.load_corpus()
    cases = []
    for partition in ("historical_scored", "development_fixtures"):
        for record in corpus[partition]:
            if not is_classification_applicable(record):
                continue
            transition = record["expected_transition"]
            expected_class = _to_class(transition["primary_type"])
            superseded = [
                r["logical_id"] for r in transition["superseded_refs"]
            ]
            expected_target = (
                superseded[0]
                if expected_class == "UPDATE" and superseded
                else None
            )
            cases.append(
                {
                    "case_id": record["case_id"],
                    "partition": partition,
                    "message": record.get("source_statement") or "",
                    "candidate_text": record.get("source_statement") or "",
                    "candidate_kind": transition_kind(record),
                    "active": _active_views(record),
                    "expected_class": expected_class,
                    "expected_target": expected_target,
                }
            )
    return cases


def transition_kind(record) -> str | None:
    """Kind of the created candidate, if the annotation specifies one.

    Present in the before-state / created spec, not part of the class
    answer being scored.
    """
    created = record["expected_transition"].get("created") or ()
    if created:
        return created[0].get("kind")
    return None


def deterministic_classify(controller, case) -> dict:
    """Run the existing deterministic controller and map to five classes."""
    started = time.perf_counter()
    result = controller.propose(
        case["message"],
        _deterministic_evidence(case),
        _deterministic_before(case),
    )
    elapsed = (time.perf_counter() - started) * 1000.0
    transition_type = result.transition_type
    classification = _to_class(transition_type)
    target = None
    if classification == "UPDATE" and result.proposal:
        supersedes = list(result.proposal.superseded_ids)
        target = supersedes[0] if supersedes else None
    return {
        "classification": classification,
        "target": target,
        "transition_type": transition_type,
        "latency_ms": elapsed,
    }


def _deterministic_before(case):
    # Rebuild the same detached before-state the deterministic benchmark
    # uses, from the frozen record, so both sides see identical inputs.
    return case["_before_state"]


def _deterministic_evidence(case):
    return case["_evidence"]


def _attach_deterministic_inputs(cases) -> None:
    corpus = tv.load_corpus()
    by_id = {}
    for partition in ("historical_scored", "development_fixtures"):
        for record in corpus[partition]:
            by_id[record["case_id"]] = record
    for case in cases:
        record = by_id[case["case_id"]]
        case["_before_state"] = before_state_for(record)
        case["_evidence"] = evidence_for(record)


def qwen_classify(controller, case) -> dict:
    result = controller.classify(
        message=case["message"],
        candidate_text=case["candidate_text"],
        candidate_kind=case["candidate_kind"],
        active_memories=case["active"],
    )
    return {
        "classification": result.classification,
        "target": result.target_memory_id,
        "status": result.status,
        "failed": result.failed,
        "latency_ms": result.latency_ms,
        "reason": result.diagnostics.get("reason"),
    }


def _class_metrics(rows, key) -> dict:
    """Per-class recall and precision plus overall accuracy.

    recall  = correct predictions of C / annotated C (support).
    precision = correct predictions of C / times C was predicted.
    A prediction is correct on class only (target correctness is scored
    separately as wrong_target).
    """
    per_class = {}
    for cls in UPDATE_CLASSIFICATIONS:
        support = sum(1 for r in rows if r["expected_class"] == cls)
        predicted = sum(1 for r in rows if r[key]["classification"] == cls)
        correct = sum(
            1 for r in rows
            if r["expected_class"] == cls and r[key]["classification"] == cls
        )
        per_class[cls] = {
            "support": support,
            "predicted": predicted,
            "correct": correct,
            "recall": round(correct / support, 4) if support else None,
            "precision": round(correct / predicted, 4) if predicted else None,
        }
    scored = [r for r in rows if r[key]["classification"] is not None]
    accuracy_correct = sum(
        1 for r in scored if r[key]["classification"] == r["expected_class"]
    )
    # Wrong target: class is UPDATE and correct, but the chosen memory is
    # not the annotated replacement target.
    update_rows = [
        r for r in rows
        if r["expected_class"] == "UPDATE"
        and r[key]["classification"] == "UPDATE"
    ]
    wrong_target = sum(
        1 for r in update_rows if r[key]["target"] != r["expected_target"]
    )
    correct_target = sum(
        1 for r in update_rows if r[key]["target"] == r["expected_target"]
    )
    # False / missed UPDATE relative to the annotation.
    false_update = sum(
        1 for r in rows
        if r[key]["classification"] == "UPDATE" and r["expected_class"] != "UPDATE"
    )
    missed_update = sum(
        1 for r in rows
        if r["expected_class"] == "UPDATE" and r[key]["classification"] != "UPDATE"
    )
    latencies = [r[key]["latency_ms"] for r in rows]
    return {
        "cases": len(rows),
        "scored": len(scored),
        "overall_accuracy": {
            "correct": accuracy_correct,
            "total": len(scored),
            "value": round(accuracy_correct / len(scored), 4) if scored else None,
        },
        "per_class": per_class,
        "update_target": {
            "update_cases": len(update_rows),
            "correct_target": correct_target,
            "wrong_target": wrong_target,
        },
        "false_update": false_update,
        "missed_update": missed_update,
        "latency": _latency(latencies),
    }


def _latency(values) -> dict:
    clean = [v for v in values if v]
    if not clean:
        return {"count": 0}
    ordered = sorted(clean)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "count": len(ordered),
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[index], 4),
        "max_ms": round(ordered[-1], 4),
        "total_ms": round(sum(ordered), 4),
    }


def _qwen_safety(rows) -> dict:
    """Structured-output validation and mutation-authority safety.

    The controller's strict parser is the structured-output validator:
    it rejects fabricated ids, missing/extra targets, and malformed
    output. The harness holds no store, engine, or manager and applies
    nothing, so no proposal — valid or rejected — can reach mutation
    authority.
    """
    provider_failures = sum(
        1 for r in rows
        if r["qwen"]["status"] in (STATUS_PROVIDER_ERROR, STATUS_PROVIDER_UNAVAILABLE)
    )
    invalid = [r for r in rows if r["qwen"]["status"] == STATUS_INVALID_OUTPUT]
    accepted = sum(1 for r in rows if r["qwen"]["status"] == STATUS_OK)
    fabricated_target = sum(1 for r in invalid if r["qwen"]["reason"] == "fabricated_target")
    return {
        "validator_accepted": accepted,
        "validator_rejected": len(invalid),
        "fabricated_target_rejected": fabricated_target,
        "invalid_reasons": _reason_counts(invalid),
        "provider_failures": provider_failures,
        "unsafe_proposals": 0,
        "rejected_reaching_mutation_authority": 0,
    }


def _reason_counts(rows) -> dict:
    counts = {}
    for row in rows:
        reason = row["qwen"]["reason"] or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def run_comparison(provider, *, cases=None) -> dict:
    """Score deterministic and Qwen over the same cases. Live if provider
    is configured; the deterministic side is always offline."""
    if cases is None:
        cases = load_cases()
    _attach_deterministic_inputs(cases)
    deterministic = DeterministicUpdateController()
    qwen = QwenUpdateController(provider)

    rows = []
    for case in cases:
        det = deterministic_classify(deterministic, case)
        qw = qwen_classify(qwen, case)
        rows.append(
            {
                "case_id": case["case_id"],
                "partition": case["partition"],
                "expected_class": case["expected_class"],
                "expected_target": case["expected_target"],
                "deterministic": det,
                "qwen": qw,
            }
        )

    return {
        "comparison_version": COMPARISON_VERSION,
        "corpus": "transition_verification_frozen",
        "case_count": len(rows),
        "class_support": {
            cls: sum(1 for r in rows if r["expected_class"] == cls)
            for cls in UPDATE_CLASSIFICATIONS
        },
        "qwen_config": {
            "controller_id": QWEN_UPDATE_CONTROLLER_ID,
            "prompt_version": QWEN_UPDATE_PROMPT_VERSION,
            "model": getattr(provider, "model", None),
            "temperature": getattr(provider, "temperature", None),
            "timeout_s": getattr(provider, "timeout", None),
            "inference_count_per_case": 1,
        },
        "deterministic": _class_metrics(rows, "deterministic"),
        "qwen": _class_metrics(rows, "qwen"),
        "qwen_safety": _qwen_safety(rows),
        "rows": rows,
    }


def _serialisable_row(row) -> dict:
    return {
        "case_id": row["case_id"],
        "partition": row["partition"],
        "expected_class": row["expected_class"],
        "expected_target": row["expected_target"],
        "deterministic": {
            "classification": row["deterministic"]["classification"],
            "target": row["deterministic"]["target"],
            "transition_type": row["deterministic"]["transition_type"],
        },
        "qwen": {
            "classification": row["qwen"]["classification"],
            "target": row["qwen"]["target"],
            "status": row["qwen"]["status"],
            "reason": row["qwen"]["reason"],
        },
    }


def to_results_json(data: dict) -> dict:
    """Machine-readable results with per-case text stripped (ids only)."""
    out = {k: v for k, v in data.items() if k != "rows"}
    out["rows"] = [_serialisable_row(r) for r in data["rows"]]
    return out


def _pct(metric: dict, field: str) -> str:
    value = metric[field].get("value") if field == "overall_accuracy" else None
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def _class_line(metric: dict, cls: str) -> str:
    c = metric["per_class"][cls]
    recall = "n/a" if c["recall"] is None else f"{c['recall']:.3f}"
    precision = "n/a" if c["precision"] is None else f"{c['precision']:.3f}"
    return (
        f"| {cls} | {c['support']} | {c['predicted']} | {c['correct']} "
        f"| {recall} | {precision} |"
    )


def render_report(data: dict) -> str:
    det = data["deterministic"]
    qw = data["qwen"]
    safety = data["qwen_safety"]
    cfg = data["qwen_config"]
    lines = [
        "# Qwen vs deterministic update intelligence",
        "",
        "Classification-only comparison over the frozen update corpus "
        "(`transition_verification_frozen`). Both implementations are "
        "scored in one shared five-class space (NEW / UPDATE / COEXIST / "
        "DUPLICATE / IGNORE) derived from the committed transition "
        "annotations. Qwen classifies only; it holds no mutation "
        "authority and every deterministic governance gate is unchanged.",
        "",
        f"- comparison version: {data['comparison_version']}",
        f"- cases: {data['case_count']}",
        f"- class support: {data['class_support']}",
        f"- deterministic controller: {DETERMINISTIC_CONTROLLER_ID}",
        f"- Qwen controller: {cfg['controller_id']} "
        f"(prompt v{cfg['prompt_version']})",
        f"- model: {cfg['model']} · temperature: {cfg['temperature']} · "
        f"timeout(s): {cfg['timeout_s']} · inferences/case: "
        f"{cfg['inference_count_per_case']}",
        "",
        "## Headline metrics",
        "",
        "| metric | deterministic | qwen |",
        "|---|---|---|",
        f"| overall accuracy (correct/scored) | "
        f"{det['overall_accuracy']['correct']}/{det['overall_accuracy']['total']} "
        f"| {qw['overall_accuracy']['correct']}/{qw['overall_accuracy']['total']} |",
        f"| scored (non-failed) | {det['scored']} | {qw['scored']} |",
        f"| UPDATE cases | {det['update_target']['update_cases']} "
        f"| {qw['update_target']['update_cases']} |",
        f"| UPDATE correct target | {det['update_target']['correct_target']} "
        f"| {qw['update_target']['correct_target']} |",
        f"| UPDATE wrong target | {det['update_target']['wrong_target']} "
        f"| {qw['update_target']['wrong_target']} |",
        f"| false UPDATE | {det['false_update']} | {qw['false_update']} |",
        f"| missed UPDATE | {det['missed_update']} | {qw['missed_update']} |",
        "",
        "Per-class values are recall = correct/support and precision = "
        "correct/predicted (class only; target correctness is the "
        "separate wrong-target row).",
        "",
        "### Deterministic per class",
        "",
        "| class | support | predicted | correct | recall | precision |",
        "|---|---|---|---|---|---|",
    ]
    for cls in ("NEW", "UPDATE", "COEXIST", "DUPLICATE", "IGNORE"):
        lines.append(_class_line(det, cls))
    lines += [
        "",
        "### Qwen per class",
        "",
        "| class | support | predicted | correct | recall | precision |",
        "|---|---|---|---|---|---|",
    ]
    for cls in ("NEW", "UPDATE", "COEXIST", "DUPLICATE", "IGNORE"):
        lines.append(_class_line(qw, cls))
    lines += [
        "",
        "## Safety and structured output (Qwen)",
        "",
        f"- structured-output accepted: {safety['validator_accepted']}",
        f"- structured-output rejected: {safety['validator_rejected']} "
        f"{safety['invalid_reasons']}",
        f"- fabricated-target rejected: {safety['fabricated_target_rejected']}",
        f"- provider failures: {safety['provider_failures']}",
        f"- unsafe proposals: {safety['unsafe_proposals']}",
        f"- rejected proposals reaching mutation authority: "
        f"{safety['rejected_reaching_mutation_authority']}",
        "",
        "The strict parser is the structured-output validator (it rejects "
        "fabricated ids, missing / extra targets, and malformed output). "
        "The harness holds no store, engine, or manager and applies "
        "nothing, so no proposal — valid or rejected — reaches mutation "
        "authority. The full transition verifier remains downstream and "
        "unchanged; this experiment is classification-only and never "
        "constructs an applied transition.",
        "",
        "## Latency",
        "",
        f"- deterministic: {det['latency']}",
        f"- qwen: {qw['latency']}",
        "",
    ]
    return "\n".join(lines)


def run_and_write(provider, out_dir: Path | None = None) -> dict:
    """Run the live comparison once and write both evidence artifacts."""
    out_dir = out_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    data = run_comparison(provider)
    (out_dir / "results.json").write_text(
        json.dumps(to_results_json(data), indent=2, sort_keys=True) + "\n"
    )
    (out_dir / "report.md").write_text(render_report(data).rstrip("\n") + "\n")
    return data
