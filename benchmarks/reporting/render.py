"""Rendering: Markdown report, CSV tables, and the README section —
all from report_data.json content, never freehand numbers."""

from __future__ import annotations

import csv
import io

LIFECYCLE_SCOPE_NOTE = (
    "Custom lifecycle benchmark: 40 committed scenarios, 6 systems, "
    "deterministic offline provider, approximated token accounting "
    "(ceil(chars/4)); ExperienceOS local runs scripted proposals plus "
    "rule fallback — not a real-GGUF result."
)

EXTERNAL_SCOPE_NOTE = (
    "LongMemEval 50-case stratified subset: 50 of 500 official "
    "questions (official s_cleaned data, deterministic metadata-based "
    "selection, 10 per category), structural offline run with labeled "
    "proxy answer metrics — the official GPT-4o judge was not used and "
    "this is not an official LongMemEval result or leaderboard entry."
)


def _md_table(rows, systems, display_names) -> str:
    header = "| Metric | " + " | ".join(
        display_names.get(s, s) for s in systems
    ) + " |"
    divider = "|" + "---|" * (len(systems) + 1)
    lines = [header, divider]
    for row in rows:
        cells = " | ".join(
            row["cells"][s]["display"] for s in systems
        )
        lines.append(f"| `{row['metric']}` | {cells} |")
    return "\n".join(lines)


def _csv_rows(table_name, rows, systems, source_path, source_digest):
    out = []
    for row in rows:
        for system in systems:
            cell = row["cells"][system]
            out.append(
                {
                    "table": table_name,
                    "system": system,
                    "metric": row["metric"],
                    "numerator": cell["numerator"],
                    "denominator": cell["denominator"],
                    "value": "" if cell["value"] is None else cell["value"],
                    "undefined_count": cell["undefined_count"],
                    "display": cell["display"],
                    "source_artifact": source_path,
                    "source_digest": source_digest,
                }
            )
    return out


def render_csvs(data: dict) -> dict:
    """CSV name -> content string."""
    lifecycle_source = data["sources"]["lifecycle"]
    external_source = data["sources"]["external"]
    lifecycle_systems = list(
        data["lifecycle_tables"]["correctness"][0]["cells"].keys()
    )
    external_systems = list(
        data["external_tables"]["headline"][0]["cells"].keys()
    )

    files = {}

    def write(name, rows):
        if not rows:
            files[name] = ""
            return
        fieldnames = []
        for row in rows:  # union of keys, first-seen order
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=fieldnames, restval="", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
        files[name] = buffer.getvalue()

    headline = []
    for table_name in ("correctness", "retrieval_downstream"):
        headline.extend(
            _csv_rows(
                table_name,
                data["lifecycle_tables"][table_name],
                lifecycle_systems,
                lifecycle_source["path"],
                lifecycle_source["digest"],
            )
        )
    write("lifecycle_headline.csv", headline)

    by_category = []
    for group, rows in data["lifecycle_group_tables"].items():
        for entry in _csv_rows(
            f"group:{group}",
            rows,
            lifecycle_systems,
            lifecycle_source["path"],
            lifecycle_source["digest"],
        ):
            by_category.append(entry)
    write("lifecycle_by_category.csv", by_category)

    write(
        "leakage_comparison.csv",
        _csv_rows(
            "leakage",
            data["lifecycle_tables"]["leakage"],
            lifecycle_systems,
            lifecycle_source["path"],
            lifecycle_source["digest"],
        ),
    )

    context_rows = []
    for system, stats in data["lifecycle_context_stats"].items():
        context_rows.append(
            {
                "table": "context_stats",
                "system": system,
                "metric": "context_averages",
                "cases": stats["cases"],
                "avg_total_context_tokens": stats[
                    "avg_total_context_tokens"
                ],
                "avg_memory_context_tokens": stats[
                    "avg_memory_context_tokens"
                ],
                "avg_selected_memories": stats["avg_selected_memories"],
                "avg_candidate_memories": stats["avg_candidate_memories"],
                "source_artifact": lifecycle_source["path"],
                "source_digest": lifecycle_source["digest"],
            }
        )
    context_rows.extend(
        _csv_rows(
            "context_operational",
            data["lifecycle_tables"]["context_operational"],
            lifecycle_systems,
            lifecycle_source["path"],
            lifecycle_source["digest"],
        )
    )
    write("context_efficiency.csv", context_rows)

    write(
        "local_policy_containment.csv",
        _csv_rows(
            "containment",
            data["containment_table"],
            ["experienceos_local"],
            lifecycle_source["path"],
            lifecycle_source["digest"],
        ),
    )
    write(
        "longmemeval_subset_headline.csv",
        _csv_rows(
            "external_headline",
            data["external_tables"]["headline"],
            external_systems,
            external_source["path"],
            external_source["digest"],
        ),
    )
    external_by_category = []
    for category, rows in data["external_tables"]["categories"].items():
        external_by_category.extend(
            _csv_rows(
                f"external:{category}",
                rows,
                external_systems,
                external_source["path"],
                external_source["digest"],
            )
        )
    write("longmemeval_by_category.csv", external_by_category)

    failure_rows = [
        {
            "track": e["track"],
            "rule": e["rule"],
            "id": e["id"],
            "system": e["system"],
            "outcome": e["outcome"],
            "unmet_metrics": "; ".join(e["unmet_metrics"]),
            "note": e["note"],
        }
        for e in data["failure_examples"]
    ]
    write("failure_analysis.csv", failure_rows)
    return files


def render_readme_section(data: dict, display_names: dict) -> str:
    """Compact README section between markers, from report_data only."""

    def cell(track, table, metric, system):
        rows = (
            data["lifecycle_tables"][table]
            if track == "lifecycle"
            else data["external_tables"][table]
        )
        for row in rows:
            if row["metric"] == metric:
                return row["cells"][system]["display"]
        return "N/A"

    stats = data["lifecycle_context_stats"]
    ext_stats = data["external_context_stats"]
    lines = [
        "## Benchmark Evidence",
        "",
        "Two separate evidence tracks, both fully offline and generated "
        "from committed raw artifacts (deterministic provider, "
        "approximated `ceil(chars/4)` token accounting): the **custom "
        "lifecycle benchmark** (40 scenarios × 6 systems) measures "
        "whether accumulated experience stays current, relevant, and "
        "bounded; the **LongMemEval 50-case stratified subset** "
        "(official data, structural run, proxy answer metrics, no "
        "official judge — not an official LongMemEval score) probes "
        "long-history retrieval. ExperienceOS local is the "
        "scripted-plus-fallback offline mode, not a real-GGUF result. "
        "Full detail, denominators, failures, and limitations: "
        "[docs/benchmark_report.md](docs/benchmark_report.md).",
        "",
        "**Custom lifecycle (ExperienceOS rules vs strongest contrasts; "
        "raw n/d shown):**",
        "",
        "| Metric | ExperienceOS rules | Append-only | Full history |",
        "|---|---|---|---|",
        f"| Old-value deactivation | {cell('lifecycle', 'correctness', 'old_value_deactivation_rate', 'experienceos_rules')} "
        f"| {cell('lifecycle', 'correctness', 'old_value_deactivation_rate', 'append_only')} "
        f"| {cell('lifecycle', 'correctness', 'old_value_deactivation_rate', 'full_history')} |",
        f"| Expected-memory Recall@K | {cell('lifecycle', 'retrieval_downstream', 'recall_at_k', 'experienceos_rules')} "
        f"| {cell('lifecycle', 'retrieval_downstream', 'recall_at_k', 'append_only')} "
        f"| {cell('lifecycle', 'retrieval_downstream', 'recall_at_k', 'full_history')} |",
        f"| Duplicate acceptance | {cell('lifecycle', 'correctness', 'duplicate_acceptance_rate', 'experienceos_rules')} "
        f"| {cell('lifecycle', 'correctness', 'duplicate_acceptance_rate', 'append_only')} "
        f"| {cell('lifecycle', 'correctness', 'duplicate_acceptance_rate', 'full_history')} |",
        f"| Avg context tokens (38 cases) | {stats['experienceos_rules']['avg_total_context_tokens']} "
        f"| {stats['append_only']['avg_total_context_tokens']} "
        f"| {stats['full_history']['avg_total_context_tokens']} |",
        "",
        "Honest hard-case results stay visible: stale rendered-context "
        "leakage for ExperienceOS rules is "
        f"{cell('lifecycle', 'leakage', 'stale_context_leakage_rate', 'experienceos_rules')} "
        "(the dataset's aspirational unkeyed-domain update oracles), and "
        "forgotten-content exclusion is "
        f"{cell('lifecycle', 'leakage', 'forgotten_exclusion_rate', 'experienceos_rules')} "
        "on its two eligible probes.",
        "",
        "**LongMemEval 50-case stratified subset (structural offline "
        "run):**",
        "",
        "| Metric | ExperienceOS rules | Naive top-K | Full history |",
        "|---|---|---|---|",
        f"| Answer-session selection | {cell('external', 'headline', 'answer_session_selection_rate', 'experienceos_rules')} "
        f"| {cell('external', 'headline', 'answer_session_selection_rate', 'naive_top_k')} "
        f"| {cell('external', 'headline', 'answer_session_selection_rate', 'full_history')} |",
        f"| Answer-session MRR | {cell('external', 'headline', 'answer_session_mrr', 'experienceos_rules')} "
        f"| {cell('external', 'headline', 'answer_session_mrr', 'naive_top_k')} "
        f"| {cell('external', 'headline', 'answer_session_mrr', 'full_history')} |",
        f"| Avg supplied context tokens (50 cases) | {ext_stats['experienceos_rules']['avg_total_context_tokens']} "
        f"| {ext_stats['naive_top_k']['avg_total_context_tokens']} "
        f"| {ext_stats['full_history']['avg_total_context_tokens']} |",
        "",
        "Naive lexical retrieval outperforms ExperienceOS's sparse "
        "rule-based extraction on this conversational subset — a "
        "measured limitation, reported as such. Reproduce/verify: "
        "`./scripts/run_benchmarks.sh validate "
        "benchmarks/results/committed/lifecycle-offline-v1`, "
        "`./scripts/run_benchmarks.sh validate-external "
        "benchmarks/results/committed/longmemeval-50-subset-v1`, "
        "`./scripts/run_benchmarks.sh report`.",
    ]
    return "\n".join(lines)


def render_markdown(data: dict, spec: dict) -> str:
    display = spec["systems"]["display"]
    lifecycle_systems = spec["systems"]["lifecycle"]
    external_systems = spec["systems"]["external"]
    claims = data["claims"]
    sources = data["sources"]

    def table(track, name):
        if track == "lifecycle":
            return _md_table(
                data["lifecycle_tables"][name], lifecycle_systems, display
            )
        return _md_table(
            data["external_tables"][name], external_systems, display
        )

    sections = []
    sections.append(f"""# ExperienceOS Benchmark Report ({data['report_version']})

> Generated from committed raw artifacts by
> `./scripts/run_benchmarks.sh report` at commit
> `{data['report_generating_commit']}`. Do not edit manually — the
> validator detects edited numbers. No benchmark system was rerun; no
> network, provider, or model was used during generation.

## 1. Executive Summary

Six systems were compared on the custom 40-scenario lifecycle
benchmark and three on the {sources['external']['display_label']}
(official data, structural offline run). {LIFECYCLE_SCOPE_NOTE}

Strongest bounded findings (full conditions in section 12):
""")
    for claim in claims["emitted"]:
        sections.append(f"- {claim['text']}")
    sections.append("""
Visible limitations up front: the answer provider is a deterministic
offline echo (response-inclusion metrics are floor evidence applied
equally to every system); the dataset's update oracles are
deliberately aspirational, so ExperienceOS rules honestly fails
unkeyed-domain supersession; naive lexical retrieval beats
ExperienceOS retrieval on the external conversational subset; and the
local policy ran in scripted-plus-fallback mode, never a real GGUF.

## 2. What Was Measured

The custom lifecycle track measures whether an experience layer keeps
accumulated experience **current** (updates and supersession),
**relevant** (retrieval, selection, budget adherence), **bounded**
(context tokens, compression), and **safe** (four-level stale and
forgotten leakage, duplicate containment, invalid-proposal
containment). The external track measures long-history retrieval and
context cost on recognized official data. The two tracks are never
combined into one score, and no composite score exists anywhere in
the artifacts.

## 3. Systems Compared

| System | Description |
|---|---|
| Stateless | current request only; no accumulated experience |
| Full history | entire transcript replayed every turn; no lifecycle |
| Append-only | durable-looking statements stored forever; no updates or forgetting |
| Naive top-K | lexical + recency retrieval over an append-only store |
| ExperienceOS rules | the real engine with the deterministic rule policy |
| ExperienceOS local (scripted + fallback) | the real engine with the local-model policy driven by scripted proposals plus rule fallback — **not a real-GGUF run** |

## 4. Custom Lifecycle Benchmark

40 scenarios (creation 6, updates 8, forgetting 6, retrieval 8,
context 6, containment 6) across 13 domains, fixed hash-locked oracle
(manifest `{manifest}`), six systems, deterministic provider. 240
case-system runs: 228 executed, 12 skipped (2 requires-local-model
scenarios x 6 systems), 12 partial (deferred abstention/model-scored
response evaluation), 0 execution failures.

Case outcomes by system (navigation aid only — conclusions come from
the metric tables): """.replace("{manifest}", sources["lifecycle"]["manifest_hash"]))
    for system in lifecycle_systems:
        outcomes = data["lifecycle_case_outcomes"].get(system, {})
        sections.append(
            f"- {display[system]}: "
            + ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items()))
        )
    sections.append(f"""
## 5. Lifecycle Correctness Results

{table('lifecycle', 'correctness')}

Reading notes: `duplicate_acceptance_rate` is undefined where no
duplicate was ever proposed (rule dedupe prevents the proposal
itself); ExperienceOS supersession succeeds in keyed conflict domains
(seats, flight times, keyed facts) and honestly fails the dataset's
aspirational unkeyed-domain corrections — see the failure analysis.

## 6. Leakage Results

{table('lifecycle', 'leakage')}

The primary lifecycle safety measure is **rendered-context** leakage:
stored inactive history is not leakage, and candidate-level
contamination is less severe than content actually supplied to the
answer provider. Stateless rows are vacuously clean (no context at
all). `{data['display_label_mappings']['stale_context_leakage_rate']}`;
`{data['display_label_mappings']['forgotten_exclusion_rate']}`.
Response contamination is scored only where the oracle carries a
deterministic forbidden constraint.

## 7. Retrieval and Downstream Use

{table('lifecycle', 'retrieval_downstream')}

Downstream response-inclusion metrics reflect the deterministic echo
provider applied equally to every system — they are configuration
floor evidence, not live answer quality.

## 8. Context Efficiency

Average approximated context per executed case (38 cases per system;
`ceil(chars/4)`; these are not provider-billed tokens and no cost
claim is made):

| System | Avg total context tokens | Avg memory tokens | Avg selected | Avg candidates |
|---|---|---|---|---|""")
    for system in lifecycle_systems:
        stats = data["lifecycle_context_stats"][system]
        sections.append(
            f"| {display[system]} | {stats['avg_total_context_tokens']} "
            f"| {stats['avg_memory_context_tokens']} "
            f"| {stats['avg_selected_memories']} "
            f"| {stats['avg_candidate_memories']} |"
        )
    sections.append(f"""
{table('lifecycle', 'context_operational')}

Conventions: stateless has zero structured memory tokens; full
history carries transcript context rather than structured memory, so
its comparable cost is total context; zero-token ratios stay
undefined; `answers_per_1k_memory_tokens` is undefined for zero-memory
systems rather than infinite.

## 9. Local Memory-Policy Containment

Scripted-plus-fallback offline mode (provenance:
`used_real_local_model: false`) — proposal quality, engine
validation, rejection, fallback, applied action, and final state are
separate layers:

{_md_table(data['containment_table'], ['experienceos_local'], display)}

Canonical containment patterns in the artifact: a valid scripted
create applied; the Phase 7 over-eager duplicate rejected
(`duplicate_of_active`); an inactive-target supersede and a
nonexistent-target forget rejected (`target_not_active`); malformed
output triggering the typed `invalid_output` fallback with the rules
producing the correct final state; unrelated memories preserved
throughout. `{data['display_label_mappings']['local_state_corruption_rate']}`.
None of this measures real-GGUF proposal accuracy.

## 10. LongMemEval 50-case Stratified Subset

> **Scope.** 50 of 500 official questions; official `s_cleaned` data
> at revision `{sources['external']['source_revision']}`;
> deterministic metadata-based selection (10 per category:
> information extraction, multi-session reasoning, temporal
> reasoning, knowledge updates, abstention); subset manifest
> `{sources['external']['subset_manifest_hash']}`; structural offline
> run with labeled proxy answer metrics; **no official GPT-4o judge;
> not an official LongMemEval score; no leaderboard claim.**

{table('external', 'headline')}

Retrieval metrics use the official `answer_session_ids` relevance
oracle (not proxies). Answer metrics marked `_proxy` are
deterministic checks against the offline echo provider — floor
evidence only. `{data['display_label_mappings']['answer_context_presence_rate']}`.
Abstention answer evaluation is deferred (30 case-evaluations across
the three systems).

Average supplied context (50 cases per system, approximated):
""")
    for system in external_systems:
        stats = data["external_context_stats"][system]
        sections.append(
            f"- {display[system]}: {stats['avg_total_context_tokens']} "
            f"total tokens, {stats['avg_history_or_memory_tokens']} "
            f"history/memory tokens, {stats['avg_selected_items']} "
            "selected items on average"
        )
    sections.append("""
Category tables (metrics eligible per category; temporal cases keep
session dates in the source representation, though ExperienceOS
memory text may lose structured date context; knowledge-update cases
carry no custom-style lifecycle oracle, so no lifecycle accuracy is
derived; abstention shows execution and deferral only — no invented
accuracy):
""")
    for category, rows in data["external_tables"]["categories"].items():
        sections.append(f"### {category}\n")
        sections.append(
            _md_table(rows, external_systems, display) + "\n"
        )
    sections.append("""## 11. Failure Analysis

Examples are selected by fixed deterministic rules (first matching
case in canonical execution order per rule — never by favorable
performance):
""")
    sections.append(
        "| Track | Rule | Case | System | Outcome | Unmet metrics | Note |"
    )
    sections.append("|---|---|---|---|---|---|---|")
    for example in data["failure_examples"]:
        sections.append(
            f"| {example['track']} | {example['rule']} | `{example['id']}` "
            f"| {example['system']} | {example['outcome']} | "
            f"{'; '.join(example['unmet_metrics']) or '—'} | "
            f"{example['note']} |"
        )
    sections.append("""
Mixed outcomes are explicit: full history and naive retrieval each
beat ExperienceOS rules on cases the rules pass over (lexical
overlap, verbatim retention); append-only recall exceeds ExperienceOS
recall on creation because it stores raw statements the normalizing
planner skips; ExperienceOS wins are concentrated in lifecycle
correctness, duplicate containment, inactive-memory exclusion in
keyed domains, and context economy.

## 12. What the Evidence Supports
""")
    for claim in claims["emitted"]:
        sections.append(f"- {claim['text']}\n  - condition: {claim['condition']}")
    sections.append("""
## 13. What the Evidence Does Not Support

Withheld claims (conditions failed, honestly):
""")
    for withheld in claims["withheld"]:
        sections.append(f"- `{withheld['id']}`: {withheld['reason']}")
    sections.append("""
Never claimed, regardless of results: any official LongMemEval score
or leaderboard placement; superiority beyond the measured scenarios;
live Qwen answer quality (the provider was a deterministic echo);
real-GGUF local-policy accuracy; provider cost or pricing outcomes;
production-scale behavior; any combined lifecycle-plus-external
score.

## 14. Limitations

- Deterministic echo provider: response-inclusion metrics are floor
  evidence, identical in kind for every system.
- No official LongMemEval judge; external answer metrics are labeled
  proxies; abstention evaluation deferred.
- No real-GGUF benchmark run; local mode is scripted-plus-fallback.
- 40 custom scenarios and a 50-case external subset bound
  generalization.
- Token accounting is a documented approximation, not billed tokens.
- Rule-based extraction misses paraphrases and conversational
  phrasing; assistant turns are not ingested; session-date structure
  can be lost in memory text.
- Latency was measured on one machine and is not comparable across
  hardware.

## 15. Reproduction

```bash
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1
./scripts/run_benchmarks.sh report                 # regenerate report + CSVs
./scripts/run_benchmarks.sh validate-report benchmarks/results/committed/report-v1
./scripts/run_benchmarks.sh quick                  # offline benchmark smoke
./scripts/run_benchmarks.sh full-offline           # full 240-run benchmark
./scripts/run_benchmarks.sh longmemeval-fixture    # external offline smoke
# with official data present under benchmarks/data/external/longmemeval/:
./scripts/run_benchmarks.sh longmemeval-structural benchmarks/data/external/longmemeval/longmemeval_s_cleaned.json
```

## 16. Provenance
""")
    sections.append(
        f"- Report version: {data['report_version']}; generating commit "
        f"`{data['report_generating_commit']}` (clean tree: "
        f"{data['working_tree_clean']}).\n"
        f"- Lifecycle artifact: `{sources['lifecycle']['path']}`, digest "
        f"`{sources['lifecycle']['digest']}`, generated at commit "
        f"`{sources['lifecycle']['generating_commit']}`, dataset manifest "
        f"`{sources['lifecycle']['manifest_hash']}`.\n"
        f"- External artifact: `{sources['external']['path']}`, digest "
        f"`{sources['external']['digest']}`, generated at commit "
        f"`{sources['external']['generating_commit']}`, subset manifest "
        f"`{sources['external']['subset_manifest_hash']}`.\n"
        f"- Flags: network={data['flags']['network_used']}, provider "
        f"invoked={data['flags']['provider_invoked']}, model "
        f"invoked={data['flags']['model_invoked']}, systems "
        f"rerun={data['flags']['systems_rerun']}; local mode: "
        f"{data['flags']['lifecycle_local_mode']}; external evaluation: "
        f"{data['flags']['external_evaluation']}."
    )
    sections.append("""
## 17. Appendix

Machine-readable data: `benchmarks/results/committed/report-v1/report_data.json`
(every table above, with raw numerators/denominators). CSV exports in
the same directory. Category-level lifecycle tables:
""")
    for group, rows in data["lifecycle_group_tables"].items():
        sections.append(f"### {group}\n")
        sections.append(_md_table(rows, lifecycle_systems, display) + "\n")
    sections.append(
        "\nDenominator notes: undefined cells state their exclusion "
        "reason inline; skipped and deferred counts appear in section 4; "
        "per-metric undefined counts are preserved in report_data.json "
        "and the source aggregates.\n"
    )
    return "\n".join(sections)
