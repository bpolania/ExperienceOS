"""Aggregate grounded-extraction metrics from per-case records.

Every ratio ships as an explicit numerator/denominator plus a rate that
is ``None`` when the denominator is zero (never 0% or 100%). Duplicates
are excluded from creation precision/recall (contract §13); unscorable
cases are excluded from every scored denominator and counted separately.
Latency aggregates use the digest-excluded ``*_ms`` key convention.
"""

from __future__ import annotations

REJECTION_CATEGORIES = (
    "temporary-state",
    "question",
    "one-off-request",
    "non-durable",
    "hypothetical",
    "assistant-only",
)


def ratio(num, den):
    """num/den as {numerator, denominator, rate}; rate None when den==0."""
    return {
        "numerator": num,
        "denominator": den,
        "rate": (num / den) if den else None,
    }


def _latency_block(records):
    samples = []
    for rec in records:
        for entry in rec["latencies"]:
            if entry["stage"] == "total_extraction":
                samples.append(entry["milliseconds"])
    samples.sort()
    n = len(samples)
    if n == 0:
        return {"count": 0, "mean_ms": None, "min_ms": None,
                "max_ms": None, "p50_ms": None, "p95_ms": None}

    def pct(p):
        if n < 20 and p >= 0.95:
            return None
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return samples[idx]

    return {
        "count": n,
        "mean_ms": sum(samples) / n,
        "min_ms": samples[0],
        "max_ms": samples[-1],
        "p50_ms": pct(0.5),
        "p95_ms": pct(0.95),
    }


def aggregate_system(system_id, records, definition):
    """Compute the full aggregate metric block for one system."""
    scorable = [r for r in records if r["scorable"]]
    positives = [r for r in scorable if r["case_class"] == "positive"]
    negatives = [r for r in scorable if r["case_class"] == "negative"]
    duplicates = [r for r in scorable if r["case_class"] == "duplicate"]
    non_dup = positives + negatives
    is_grounded = definition.controller_type != "none"

    raw_props = [r for r in scorable if r["raw_proposal_present"]]
    valid_props = [r for r in scorable if r["proposal_present"]]
    accepted_span_valid = [
        r for r in valid_props if r["exact_span_valid"]]
    direct_valid = [
        r for r in raw_props
        if r["proposal_present"] and r["exact_span_valid"]]

    tp = [r for r in non_dup if r["proposal_score"] == "true_positive"]
    fp = [r for r in non_dup if r["proposal_score"] == "false_positive"]
    fn = [r for r in non_dup if r["proposal_score"] == "false_negative"]
    tn = [r for r in non_dup if r["proposal_score"] == "true_negative"]

    predicted_none = [r for r in non_dup if not r["proposal_present"]]
    predicted_none_neg = [r for r in predicted_none
                          if r["case_class"] == "negative"]

    # rejection rates per category (grounded proposal layer)
    rejection = {}
    for cat in REJECTION_CATEGORIES:
        oracle_c = [r for r in negatives if r["rejection_category"] == cat]
        rejected = [r for r in oracle_c if not r["proposal_present"]]
        if oracle_c:
            rejection[cat] = ratio(len(rejected), len(oracle_c))

    content_correct_accepted = [r for r in valid_props if r["content_correct"]]
    correct_kind = [r for r in content_correct_accepted if r["kind_correct"]]

    # durable layer (both systems)
    dur_pos_hit = [r for r in positives if r["matching_memory_count"] >= 1]
    dur_neg_created = [r for r in negatives if r["created_memory_count"] > 0]
    dup_correct = [r for r in duplicates if r["matching_memory_count"] == 1]
    downstream_pos = [r for r in positives if r["matching_memory_count"] >= 1]
    downstream_sel = [r for r in downstream_pos if r["downstream_selected"]]

    proposal_metrics = {
        "proposal_rate": ratio(len(raw_props), len(scorable)),
        "valid_proposal_rate": ratio(len(valid_props), len(raw_props)),
        "direct_valid_proposal_rate": ratio(len(direct_valid), len(raw_props)),
        "candidate_absent_count": len(scorable) - len(raw_props),
    }
    grounding_metrics = {
        "grounded_span_validity": ratio(
            len(accepted_span_valid), len(valid_props)),
        "unsupported_claim_rate": ratio(
            sum(1 for r in raw_props if r["unsupported_claim"]),
            len(raw_props)),
        "grounding_rejected_count": sum(
            1 for r in raw_props if not r["proposal_present"]),
    }
    creation_metrics = {
        "precision": ratio(len(tp), len(tp) + len(fp)),
        "recall": ratio(len(tp), len(positives)),
        "f1": _f1(len(tp), len(fp), len(fn)),
        "correct_kind_rate": ratio(
            len(correct_kind), len(content_correct_accepted)),
        "durable_creation_recall": ratio(len(dur_pos_hit), len(positives)),
        "durable_false_positive_count": len(dur_neg_created),
        "accepted_durable_memory_count": sum(
            r["created_memory_count"] for r in positives),
        "duplicate_dedup_correct": ratio(len(dup_correct), len(duplicates)),
    }
    no_candidate_metrics = {
        "no_candidate_precision": ratio(
            len(predicted_none_neg), len(predicted_none)),
        "no_candidate_recall": ratio(
            len(predicted_none_neg), len(negatives)),
    }
    lifecycle_metrics = {
        "lifecycle_eligible": ratio(
            sum(1 for r in scorable
                if r["lifecycle_evaluation_status"] == "eligible"),
            sum(1 for r in scorable if r["action_generated"])),
        "duplicate_proposal_rate": ratio(
            sum(1 for r in duplicates if r["raw_proposal_present"]),
            len(duplicates)),
        "rejected_proposal_count": sum(
            1 for r in raw_props if not r["proposal_present"]),
    }
    downstream_metrics = {
        "answer_bearing_candidate_rate": ratio(
            sum(1 for r in positives
                if r["answer_bearing_candidate_present"]),
            len(positives)),
        "downstream_selection_rate": ratio(
            len(downstream_sel), len(downstream_pos)),
        "recall_at_k": None,
        "mrr": None,
    }
    safety_metrics = {
        "state_corruption": sum(r["state_corruption"] for r in records),
        "duplicate_active_memories": sum(
            r["duplicate_active_leak"] for r in records),
        "inactive_contamination": sum(
            r["inactive_contamination"] for r in records),
        "forgotten_leakage": sum(r["forgotten_leakage"] for r in records),
        "superseded_leakage": sum(r["superseded_leakage"] for r in records),
        "stale_leakage": sum(r["stale_leakage"] for r in records),
        "unauthorized_application": sum(
            r["unauthorized_application"] for r in records),
        "direct_mutation_violation": sum(
            r["direct_mutation_violation"] for r in records),
    }
    return {
        "system_id": system_id,
        "system_config_digest": definition.config_digest(),
        "controller_id": definition.controller_id,
        "controller_version": definition.controller_version,
        "controller_type": definition.controller_type,
        "runner_id": definition.runner_id,
        "runner_version": definition.runner_version,
        "fallback_mode": definition.fallback_mode,
        "validator_id": definition.validator_id,
        "validator_version": definition.validator_version,
        "dataset_id": records[0]["dataset_id"] if records else None,
        "case_counts": {
            "total": len(records),
            "scorable": len(scorable),
            "positive": len(positives),
            "negative": len(negatives),
            "duplicate": len(duplicates),
            "unscorable": sum(1 for r in records if not r["scorable"]),
        },
        "proposal_metrics": proposal_metrics if is_grounded else _null_layer(
            proposal_metrics),
        "grounding_metrics": grounding_metrics if is_grounded
        else _null_layer(grounding_metrics),
        "creation_metrics": creation_metrics if is_grounded else {
            # reference has no grounded proposals; only durable layer applies
            "precision": None, "recall": None, "f1": None,
            "correct_kind_rate": None,
            "durable_creation_recall": ratio(len(dur_pos_hit), len(positives)),
            "durable_false_positive_count": len(dur_neg_created),
            "accepted_durable_memory_count": sum(
                r["created_memory_count"] for r in positives),
            "duplicate_dedup_correct": ratio(
                len(dup_correct), len(duplicates)),
        },
        "no_candidate_metrics": no_candidate_metrics if is_grounded
        else _null_layer(no_candidate_metrics),
        "rejection_metrics": rejection if is_grounded else {},
        "lifecycle_metrics": lifecycle_metrics if is_grounded
        else _null_layer(lifecycle_metrics),
        "downstream_metrics": downstream_metrics,
        "safety_metrics": safety_metrics,
        "latency_metrics": _latency_block(records) if is_grounded else {
            "count": 0, "mean_ms": None, "min_ms": None, "max_ms": None,
            "p50_ms": None, "p95_ms": None,
            "note": "grounded extraction disabled; no extraction overhead",
        },
    }


def _f1(tp, fp, fn):
    denom_p = tp + fp
    denom_r = tp + fn
    if denom_p == 0 or denom_r == 0:
        return {"value": None, "note": "undefined (zero denominator)"}
    precision = tp / denom_p
    recall = tp / denom_r
    if precision + recall == 0:
        return {"value": 0.0}
    return {"value": 2 * precision * recall / (precision + recall)}


def _null_layer(block):
    """A layer that does not apply to this system: keep keys, null rates."""
    out = {}
    for key, value in block.items():
        if isinstance(value, dict) and "rate" in value:
            out[key] = {"numerator": None, "denominator": None, "rate": None,
                        "note": "not applicable to this system"}
        else:
            out[key] = None
    return out
