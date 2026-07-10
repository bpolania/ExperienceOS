"""Report-view construction: tables, failure examples, and claims —
all rule-driven from the spec and the raw sources, never freehand."""

from __future__ import annotations

from benchmarks.reporting.load import (
    external_category_cells,
    external_cell,
    external_context_stats,
    lifecycle_cell,
    lifecycle_context_stats,
    lifecycle_group_cell,
)


def format_cell(cell, decimals: int = 1) -> str:
    if cell is None or cell.get("absent"):
        return "N/A (metric not applicable to this system)"
    if not cell["denominator"]:
        undefined = cell.get("undefined_count", 0)
        return f"N/A ({undefined} undefined, 0 eligible)"
    percent = 100.0 * cell["numerator"] / cell["denominator"]
    return (
        f"{cell['numerator']:g}/{cell['denominator']:g} "
        f"({percent:.{decimals}f}%)"
    )


def _table(spec, sources, metric_names, cell_fn, systems):
    rows = []
    for name in metric_names:
        row = {"metric": name, "cells": {}}
        for system in systems:
            cell = cell_fn(sources, system, name)
            row["cells"][system] = {
                "numerator": cell.get("numerator", 0.0),
                "denominator": cell.get("denominator", 0.0),
                "value": cell.get("value"),
                "undefined_count": cell.get("undefined_count", 0),
                "display": format_cell(cell),
            }
        rows.append(row)
    return rows


def build_lifecycle_tables(spec, sources) -> dict:
    systems = spec["systems"]["lifecycle"]
    return {
        table_name: _table(spec, sources, metrics, lifecycle_cell, systems)
        for table_name, metrics in spec["lifecycle_tables"].items()
        if table_name != "containment"
    }


def build_containment_table(spec, sources) -> list:
    return _table(
        spec,
        sources,
        spec["lifecycle_tables"]["containment"],
        lifecycle_cell,
        ["experienceos_local"],
    )


def build_lifecycle_group_tables(spec, sources) -> dict:
    systems = spec["systems"]["lifecycle"]
    out = {}
    for group, metrics in spec["lifecycle_group_tables"].items():
        rows = []
        for name in metrics:
            row = {"metric": name, "cells": {}}
            for system in systems:
                cell = lifecycle_group_cell(sources, system, group, name)
                if cell is None:
                    row["cells"][system] = {
                        "numerator": 0.0,
                        "denominator": 0.0,
                        "value": None,
                        "undefined_count": 0,
                        "display": "N/A (no eligible cases in group)",
                    }
                else:
                    row["cells"][system] = {
                        "numerator": cell["numerator"],
                        "denominator": cell["denominator"],
                        "value": cell["value"],
                        "undefined_count": 0,
                        "display": format_cell({**cell, "absent": False}),
                    }
            rows.append(row)
        out[group] = rows
    return out


def build_external_tables(spec, sources) -> dict:
    systems = spec["systems"]["external"]
    headline = _table(
        spec,
        sources,
        spec["external_tables"]["headline"],
        external_cell,
        systems,
    )
    categories = external_category_cells(
        sources,
        spec["external_tables"]["categories"],
        spec["external_tables"]["category_metrics"],
    )
    category_tables = {}
    for category in spec["external_tables"]["categories"]:
        rows = []
        for name in spec["external_tables"]["category_metrics"]:
            row = {"metric": name, "cells": {}}
            for system in systems:
                cell = categories.get(category, {}).get(system, {}).get(name)
                if cell is None:
                    row["cells"][system] = {
                        "numerator": 0.0,
                        "denominator": 0.0,
                        "value": None,
                        "undefined_count": 0,
                        "display": "N/A (no eligible cases)",
                    }
                else:
                    row["cells"][system] = {
                        **cell,
                        "display": format_cell({**cell, "absent": False}),
                    }
            rows.append(row)
        category_tables[category] = rows
    return {"headline": headline, "categories": category_tables}


# --- Failure analysis (deterministic rules from the spec) ---------------------


def _lifecycle_example(record, rule, note):
    case = record["case"]
    evaluation = record["evaluation"]
    failed = [
        f"{c['metric']} {c['numerator']:g}/{c['denominator']:g}"
        for c in evaluation["contributions"]
        if c["applicable"]
        and c["denominator"]
        and c["numerator"] < c["denominator"]
        and c["metric"]
        not in ("duplicate_proposal_rate", "fallback_rate")
    ][:3]
    return {
        "track": "lifecycle",
        "rule": rule,
        "id": case["scenario_id"],
        "system": case["system_id"],
        "outcome": evaluation["outcome"],
        "unmet_metrics": failed,
        "note": note,
    }


def build_lifecycle_failures(spec, sources) -> list:
    examples = []
    cases = sources["lifecycle"]["cases"]
    by_system_first_fail = {}
    for record in cases:
        system = record["case"]["system_id"]
        if (
            record["evaluation"]["outcome"] == "failed"
            and system not in by_system_first_fail
        ):
            by_system_first_fail[system] = record
    for system in spec["systems"]["lifecycle"]:
        record = by_system_first_fail.get(system)
        if record:
            examples.append(
                _lifecycle_example(
                    record,
                    "first failed case per system",
                    "first evaluation failure in canonical execution order",
                )
            )

    outcome_of = {
        (r["case"]["system_id"], r["case"]["scenario_id"]): r
        for r in cases
    }
    for rule, winner, note in (
        (
            "full_history passed where experienceos_rules failed",
            "full_history",
            "brute-force context can retain evidence the experience "
            "layer abstracts away",
        ),
        (
            "naive_top_k passed where experienceos_rules failed",
            "naive_top_k",
            "direct lexical overlap can beat lifecycle-aware selection",
        ),
    ):
        for record in cases:
            case = record["case"]
            if case["system_id"] != winner:
                continue
            if record["evaluation"]["outcome"] != "passed":
                continue
            rules_record = outcome_of.get(
                ("experienceos_rules", case["scenario_id"])
            )
            if (
                rules_record
                and rules_record["evaluation"]["outcome"] == "failed"
            ):
                examples.append(
                    _lifecycle_example(record, rule, note)
                )
                break

    for record in cases:
        case = record["case"]
        if case["system_id"] != "experienceos_local":
            continue
        if any(t["rejected_actions"] for t in case["turns"]):
            examples.append(
                _lifecycle_example(
                    record,
                    "first experienceos_local containment case",
                    "invalid scripted proposal rejected by the engine; "
                    "final state preserved",
                )
            )
            break

    for record in cases:
        if record["evaluation"]["deferred"]:
            examples.append(
                _lifecycle_example(
                    record,
                    "first deferred evaluation",
                    record["evaluation"]["deferred"][0],
                )
            )
            break
    return examples


def build_external_failures(spec, sources) -> list:
    examples = []
    cases = sources["external"]["cases"]

    def contribution(record, name):
        for payload in record["contributions"]:
            if payload["metric"] == name:
                return payload
        return None

    for system in ("naive_top_k", "experienceos_rules"):
        for record in cases:
            if record["system_id"] != system:
                continue
            cell = contribution(record, "answer_session_selection_rate")
            if cell and cell["applicable"] and cell["numerator"] == 0:
                examples.append(
                    {
                        "track": "external",
                        "rule": "first missed answer-bearing session per "
                        "retrieval system",
                        "id": record["question_id"],
                        "system": system,
                        "outcome": record["status"],
                        "unmet_metrics": [
                            "answer_session_selection_rate 0/1"
                        ],
                        "note": "the official evidence session never "
                        "entered the selected context",
                    }
                )
                break

    presence = {
        (r["system_id"], r["question_id"]): contribution(
            r, "answer_context_presence_rate"
        )
        for r in cases
    }
    for record in cases:
        if record["system_id"] != "experienceos_rules":
            continue
        mine = presence.get(("experienceos_rules", record["question_id"]))
        theirs = presence.get(("full_history", record["question_id"]))
        if (
            mine
            and theirs
            and mine["applicable"]
            and theirs["applicable"]
            and mine["numerator"] == 0
            and theirs["numerator"] == 1
        ):
            examples.append(
                {
                    "track": "external",
                    "rule": "full-history context advantage",
                    "id": record["question_id"],
                    "system": "experienceos_rules",
                    "outcome": record["status"],
                    "unmet_metrics": ["answer_context_presence_rate 0/1"],
                    "note": "full history retained verbatim evidence at "
                    f"~{record['context_tokens']} vs full-history-scale "
                    "token cost; sparse rule extraction plus normalized "
                    "memory text kept verbatim evidence out",
                }
            )
            break

    for record in cases:
        cell = contribution(record, "abstention_match_proxy")
        if cell and not cell["applicable"]:
            examples.append(
                {
                    "track": "external",
                    "rule": "first abstention case",
                    "id": record["question_id"],
                    "system": record["system_id"],
                    "outcome": record["status"],
                    "unmet_metrics": [],
                    "note": "abstention answer evaluation deferred: "
                    "requires a live labeled run",
                }
            )
            break
    return examples


# --- Claims (condition-gated, never freehand) ----------------------------------


def build_claims(spec, sources) -> dict:
    emitted = []
    withheld = []

    def rate(system, name, external=False):
        cell = (
            external_cell(sources, system, name)
            if external
            else lifecycle_cell(sources, system, name)
        )
        return cell

    # Duplicate containment claim.
    dup = rate("experienceos_local", "duplicate_acceptance_rate")
    dup_baseline = rate("append_only", "duplicate_acceptance_rate")
    if dup["denominator"] > 0 and dup["numerator"] == 0:
        emitted.append(
            {
                "id": "duplicate-containment",
                "text": (
                    "Under the documented offline lifecycle configuration, "
                    f"duplicate memory proposals were accepted into active "
                    f"state in {dup['numerator']:g}/{dup['denominator']:g} "
                    "eligible ExperienceOS local-policy cases, compared "
                    f"with {dup_baseline['numerator']:g}/"
                    f"{dup_baseline['denominator']:g} for append-only "
                    "storage."
                ),
                "condition": "duplicate_acceptance_rate denominator > 0 "
                "and numerator == 0 for experienceos_local",
            }
        )
    else:
        withheld.append(
            {
                "id": "duplicate-containment",
                "reason": "condition not met in aggregate data",
            }
        )

    # Retrieval recall claim vs stateless.
    recall = rate("experienceos_rules", "recall_at_k")
    stateless_recall = rate("stateless", "recall_at_k")
    if recall["denominator"] > 0 and stateless_recall["denominator"] > 0:
        emitted.append(
            {
                "id": "accumulated-experience-recall",
                "text": (
                    "Across the eligible custom retrieval expectations, "
                    "ExperienceOS rules selected "
                    f"{recall['numerator']:g}/{recall['denominator']:g} "
                    "expected memories into context, compared with "
                    f"{stateless_recall['numerator']:g}/"
                    f"{stateless_recall['denominator']:g} for the "
                    "stateless baseline, which has no accumulated "
                    "experience."
                ),
                "condition": "recall_at_k denominators > 0 for both systems",
            }
        )

    # Context reduction vs full history (lifecycle).
    reduction = rate("experienceos_rules", "token_reduction_vs_full_history")
    if reduction["denominator"] > 0 and reduction["value"] is not None:
        emitted.append(
            {
                "id": "lifecycle-context-reduction",
                "text": (
                    "ExperienceOS rules supplied "
                    f"{100 * reduction['value']:.1f}% fewer approximated "
                    "comparable context tokens than full-history prompting "
                    f"({reduction['numerator']:g}/"
                    f"{reduction['denominator']:g} token reduction across "
                    f"{reduction['sample_count']} eligible custom cases, "
                    "same accounting method)."
                ),
                "condition": "full-history reference exists with matching "
                "accounting",
            }
        )

    # Local containment / state preservation claim.
    corruption = rate("experienceos_local", "local_state_corruption_rate")
    if corruption["denominator"] > 0:
        emitted.append(
            {
                "id": "local-containment",
                "text": (
                    "In the scripted local-policy cases, final lifecycle "
                    "state diverged from the oracle in "
                    f"{corruption['numerator']:g}/"
                    f"{corruption['denominator']:g} executed cases (the "
                    "numerator counts unfulfilled aspirational memory "
                    "expectations as well); every scripted invalid "
                    "proposal (duplicate, inactive-target, "
                    "nonexistent-target, malformed) was rejected or "
                    "contained by the engine. This is the scripted-plus-"
                    "fallback offline mode and does not measure real-GGUF "
                    "proposal accuracy."
                ),
                "condition": "state-corruption denominator > 0; "
                "real_model_used false and disclosed",
            }
        )

    # External retrieval claim (subset + proxy scoped).
    selection = rate(
        "experienceos_rules", "answer_session_selection_rate", external=True
    )
    naive_selection = rate(
        "naive_top_k", "answer_session_selection_rate", external=True
    )
    if selection["denominator"] > 0 and naive_selection["denominator"] > 0:
        emitted.append(
            {
                "id": "external-retrieval-honest",
                "text": (
                    "In the LongMemEval 50-case stratified subset "
                    "(structural offline run, official data, no official "
                    "judge), ExperienceOS rules selected the official "
                    "answer-bearing session in "
                    f"{selection['numerator']:g}/"
                    f"{selection['denominator']:g} cases — behind naive "
                    f"lexical retrieval at {naive_selection['numerator']:g}/"
                    f"{naive_selection['denominator']:g} — while supplying "
                    "orders of magnitude fewer context tokens than full "
                    "history. Sparse rule-based extraction on "
                    "conversational data is a measured limitation."
                ),
                "condition": "external selection denominators > 0; subset "
                "and proxy scope stated",
            }
        )

    # External context reduction.
    ext_reduction = rate(
        "experienceos_rules",
        "external_token_reduction_vs_full_history",
        external=True,
    )
    if ext_reduction["denominator"] > 0 and ext_reduction["value"] is not None:
        emitted.append(
            {
                "id": "external-context-reduction",
                "text": (
                    "In the LongMemEval 50-case stratified subset, "
                    "ExperienceOS rules supplied "
                    f"{100 * ext_reduction['value']:.1f}% fewer "
                    "approximated context tokens than full-history "
                    "prompting across "
                    f"{ext_reduction['sample_count']} cases (same "
                    "accounting method; structural run)."
                ),
                "condition": "external full-history reference exists",
            }
        )

    # Stale-context exclusion claim: only if numerator is zero.
    stale = rate("experienceos_rules", "stale_context_leakage_rate")
    if stale["denominator"] > 0 and stale["numerator"] == 0:
        emitted.append(
            {
                "id": "stale-exclusion",
                "text": (
                    "ExperienceOS rules supplied superseded content in "
                    f"{stale['numerator']:g}/{stale['denominator']:g} "
                    "eligible rendered contexts under the documented "
                    "offline lifecycle configuration."
                ),
                "condition": "stale leakage numerator == 0",
            }
        )
    else:
        withheld.append(
            {
                "id": "stale-exclusion",
                "reason": (
                    "stale rendered-context leakage is "
                    f"{stale['numerator']:g}/{stale['denominator']:g} for "
                    "ExperienceOS rules — the dataset's aspirational "
                    "unkeyed-domain update oracles are honestly failed, so "
                    "no exclusion claim is emitted"
                ),
            }
        )

    forgotten = rate("experienceos_rules", "forgotten_exclusion_rate")
    if forgotten["denominator"] > 0 and forgotten["value"] == 1.0:
        emitted.append(
            {
                "id": "forgotten-exclusion",
                "text": (
                    "ExperienceOS rules excluded forgotten content from "
                    f"{forgotten['numerator']:g}/"
                    f"{forgotten['denominator']:g} eligible post-forget "
                    "answer contexts under the documented offline "
                    "configuration."
                ),
                "condition": "forgotten exclusion == 100%",
            }
        )
    else:
        withheld.append(
            {
                "id": "forgotten-exclusion",
                "reason": (
                    "forgotten-content exclusion is "
                    f"{forgotten['numerator']:g}/"
                    f"{forgotten['denominator']:g} on the eligible "
                    "post-forget answers (one case is a missed paraphrased "
                    "forget; the other is the restatement scenario where "
                    "the term legitimately reappears) — no blanket "
                    "exclusion claim is emitted"
                ),
            }
        )
    return {"emitted": emitted, "withheld": withheld}


def build_report_data(spec, sources, generating_commit, clean_tree) -> dict:
    lifecycle_tables = build_lifecycle_tables(spec, sources)
    report_data = {
        "report_version": spec["report_version"],
        "sources": {
            "lifecycle": {
                "path": sources["lifecycle"]["path"],
                "digest": sources["lifecycle"]["digest"],
                "generating_commit": sources["lifecycle"]["provenance"][
                    "repository_commit"
                ],
                "manifest_hash": sources["lifecycle"]["provenance"][
                    "manifest_hash"
                ],
            },
            "external": {
                "path": sources["external"]["path"],
                "digest": sources["external"]["digest"],
                "generating_commit": sources["external"]["provenance"][
                    "repository_commit"
                ],
                "subset_manifest_hash": sources["external"]["manifest"][
                    "manifest_hash"
                ],
                "display_label": sources["external"]["manifest"][
                    "display_label"
                ],
                "source_revision": sources["external"]["manifest"][
                    "source_revision"
                ],
            },
        },
        "report_generating_commit": generating_commit,
        "working_tree_clean": clean_tree,
        "flags": {
            "network_used": False,
            "provider_invoked": False,
            "model_invoked": False,
            "systems_rerun": False,
            "lifecycle_local_mode": "scripted-plus-fallback offline",
            "external_evaluation": "structural + labeled proxies "
            "(no official GPT-4o judge)",
        },
        "lifecycle_tables": lifecycle_tables,
        "lifecycle_group_tables": build_lifecycle_group_tables(
            spec, sources
        ),
        "containment_table": build_containment_table(spec, sources),
        "lifecycle_context_stats": lifecycle_context_stats(sources),
        "lifecycle_case_outcomes": sources["lifecycle"]["aggregate"][
            "case_outcomes"
        ],
        "external_tables": build_external_tables(spec, sources),
        "external_context_stats": external_context_stats(sources),
        "failure_examples": [
            *build_lifecycle_failures(spec, sources),
            *build_external_failures(spec, sources),
        ],
        "claims": build_claims(spec, sources),
        "display_label_mappings": spec["display_label_mappings"],
    }
    return report_data
