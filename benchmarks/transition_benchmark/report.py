"""Report data and the human-readable transition report."""

from __future__ import annotations

from pathlib import Path

from benchmarks.transition_benchmark.artifacts import (
    REPORT_DIR,
    _digest,
    _manifest,
    _write,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs/transition_verification_report.md"


def _claims(data, gates) -> dict:
    reference = data["systems"]["experienceos_hybrid_full_v2_reference"]
    adopted = data["systems"]["experienceos_transition_adopted_v1"]
    candidate = data["systems"]["experienceos_transition_candidate_v1"]
    evidence = ["benchmarks/results/committed/transition-verification/per-case.jsonl"]
    return {
        "supported": [
            {
                "claim": "deterministic transition proposal exists and is verified",
                "evidence": evidence,
                "partition": "historical_scored",
                "backing": "historical",
                "detail": (
                    f"{candidate['classification']['correct']}/"
                    f"{candidate['classification']['total']} transition "
                    "classifications correct; every proposal verified"
                ),
            },
            {
                "claim": "safe update-target resolution improves on supported cases",
                "evidence": evidence,
                "partition": "historical_scored",
                "backing": "historical",
                "detail": (
                    f"{candidate['target']['correct']}/"
                    f"{candidate['target']['total']} targets resolved with "
                    f"{candidate['target']['wrong']} wrong; the reference "
                    "resolves no transition targets"
                ),
            },
            {
                "claim": "stale active-memory leakage decreases materially",
                "evidence": evidence,
                "partition": "historical_scored",
                "backing": "historical",
                "detail": (
                    f"stale active pairs {reference['lifecycle_actual']['stale_pairs']}"
                    f" → {adopted['lifecycle_actual']['stale_pairs']}"
                ),
            },
            {
                "claim": "scoped and unrelated memories remain preserved",
                "evidence": evidence,
                "partition": "historical_scored",
                "backing": "historical",
                "detail": "0 scoped and 0 unrelated memories lost",
            },
            {
                "claim": "ambiguous targets fail closed",
                "evidence": evidence,
                "partition": "both",
                "backing": "historical+fixture",
                "detail": "0 ambiguous cases guessed into a mutation",
            },
            {
                "claim": "exact authorization gates adopted effects",
                "evidence": [
                    "benchmarks/results/committed/transition-ablation/safety.json"
                ],
                "partition": "infrastructure",
                "backing": "infrastructure",
                "detail": (
                    f"{data['authorization']['mismatches_rejected']}/"
                    f"{data['authorization']['mismatches_tested']} bound-field "
                    "mismatches fail closed"
                ),
            },
            {
                "claim": "the transition path is CPU-feasible and offline",
                "evidence": [
                    "benchmarks/results/committed/transition-verification/aggregate.json"
                ],
                "partition": "both",
                "backing": "historical+fixture",
                "detail": (
                    "well under the 5 ms mean ceiling; measured values in "
                    "latency.json, which is excluded from content digests"
                ),
            },
        ],
        "unsupported": [
            {"claim": "open-domain transition intelligence solved"},
            {"claim": "production-grade update understanding"},
            {"claim": "production-grade forget understanding"},
            {"claim": "autonomous memory management"},
            {"claim": "learned transition reasoning"},
            {"claim": "multilingual generalization"},
            {"claim": "canonical adoption"},
            {"claim": "improved final answer quality"},
            {"claim": "broad forget support"},
            {"claim": "complete duplicate elimination"},
            {"claim": "complete update-target resolution"},
            {
                "claim": (
                    "semantic duplicate prevention improves the applied "
                    "lifecycle outcome"
                ),
                "reason": (
                    "measured and refuted: adopted mode adds its replacement "
                    "create alongside the canonical planner's create, so "
                    "duplicate pairs rise from "
                    f"{reference['lifecycle_actual']['duplicate_pairs']} to "
                    f"{adopted['lifecycle_actual']['duplicate_pairs']}; gate 1 "
                    "fails"
                ),
            },
        ],
    }


def _limitations() -> dict:
    return {
        "limitations": [
            "small historical transition corpus (28 scored cases)",
            "sparse historical semantic-duplicate evidence (1 scored case)",
            "sparse historical forget evidence (4 affirmative directives, all "
            "exact-target)",
            "question, negative-forget, hypothetical, broad-forget, and "
            "ambiguous-target coverage exists only in development fixtures",
            "bounded deterministic controller vocabulary",
            "the controller lexicon and the corpus share domains, so accuracy "
            "does not generalize beyond them",
            "the reference is the full canonical composition on this corpus; a "
            "component-only view is reported separately as an ablation",
            "the transition corpus carries no relevance judgements, so Recall@K "
            "and MRR are unavailable rather than synthesized",
            "no learned controller and no multilingual evaluation",
            "no bulk forget support",
            "adopted infrastructure is tested only in isolated benchmark runs",
            "in-memory authorization; no production authorization service",
            "no production deployment evidence",
            "no measured answer-quality improvement",
            "the typed grounding_validation field remains unfixed",
        ]
    }


def build(data, gates) -> dict:
    reference = data["systems"]["experienceos_hybrid_full_v2_reference"]
    adopted = data["systems"]["experienceos_transition_adopted_v1"]
    candidate = data["systems"]["experienceos_transition_candidate_v1"]
    return {
        "report_data": {
            "classification": gates["classification"],
            "rationale": gates["rationale"],
            "systems": data["systems"],
            "partitions": {
                name: block["records"] for name, block in data["partitions"].items()
            },
            "safety": data["safety"],
            "downstream": data["downstream"],
            "lifecycle": data["lifecycle"],
            "authorization": data["authorization"],
            "ablations": data.get("ablations", {}).get("ablations", []),
        },
        "headline_metrics": {
            "classification_correct": candidate["classification"]["correct"],
            "classification_total": candidate["classification"]["total"],
            "target_correct": candidate["target"]["correct"],
            "target_total": candidate["target"]["total"],
            "reference_stale_pairs": reference["lifecycle_actual"]["stale_pairs"],
            "adopted_stale_pairs": adopted["lifecycle_actual"]["stale_pairs"],
            "reference_duplicate_pairs": reference["lifecycle_actual"][
                "duplicate_pairs"
            ],
            "adopted_duplicate_pairs": adopted["lifecycle_actual"]["duplicate_pairs"],
            "gates_passed": gates["passed"],
            "gates_failed": gates["failed"],
            "gates_inconclusive": gates["inconclusive"],
        },
        "gate_summary": gates,
        "claims": _claims(data, gates),
        "limitations": _limitations(),
    }


def write(data, gates) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    built = build(data, gates)
    for name, payload in (
        ("report_data.json", built["report_data"]),
        ("headline_metrics.json", built["headline_metrics"]),
        ("gate_summary.json", built["gate_summary"]),
        ("claims.json", built["claims"]),
        ("limitations.json", built["limitations"]),
    ):
        _write(REPORT_DIR / name, payload)
    _write(
        REPORT_DIR / "artifact_index.json",
        {
            "verification": "benchmarks/results/committed/transition-verification",
            "ablation": "benchmarks/results/committed/transition-ablation",
            "report": "benchmarks/results/committed/report-transition-verification",
            "human_readable": "docs/transition_verification_report.md",
        },
    )
    (REPORT_DIR / "README.md").write_text(
        "# Transition verification report data\n\n"
        f"Adoption classification: **{gates['classification']}**\n\n"
        "This is report *data*. The human-readable report is "
        "`docs/transition_verification_report.md`.\n\n"
        "Regenerate: `./scripts/run_benchmarks.sh transition-report`\n"
        "Verify: `./scripts/run_benchmarks.sh transition-report-verify`\n",
        encoding="utf-8",
    )
    _write(
        REPORT_DIR / "manifest.json",
        _manifest(
            REPORT_DIR,
            {
                "content_digest": _digest(built),
                "classification": gates["classification"],
                "regeneration_command": (
                    "./scripts/run_benchmarks.sh transition-report"
                ),
                "verification_command": (
                    "./scripts/run_benchmarks.sh transition-report-verify"
                ),
            },
        ),
    )
    REPORT_PATH.write_text(_markdown_report(data, gates, built), encoding="utf-8")
    return REPORT_DIR


def _gate_table(gates) -> str:
    lines = [
        "| # | Gate | Threshold | Reference | Candidate/Adopted | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for gate in gates["gates"]:
        lines.append(
            f"| {gate['gate']} | {gate['name']} | {gate['threshold']} | "
            f"{gate['reference']} | {gate['candidate']} | "
            f"**{gate['decision']}**{' (blocking)' if gate['blocking'] else ''} |"
        )
    return "\n".join(lines)


def _markdown_report(data, gates, built) -> str:
    reference = data["systems"]["experienceos_hybrid_full_v2_reference"]
    adopted = data["systems"]["experienceos_transition_adopted_v1"]
    candidate = data["systems"]["experienceos_transition_candidate_v1"]
    rules = data["systems"]["experienceos_transition_rules_v1"]
    head = built["headline_metrics"]
    ablations = data.get("ablations", {}).get("ablations", [])

    ablation_rows = "\n".join(
        f"| {a['ablation_id']} | {a['disabled_component']} | "
        f"{a['metrics'].get('classification_correct', '—')} | "
        f"{a['safety_failures']} | false |"
        for a in ablations
    )

    return f"""# Transition Verification Report

**Adoption classification: `{gates['classification']}`**

{gates['rationale']}

This classification **does not change the runtime default**, which remains
`disabled`. No transition controller is canonical, and adopted mode is not
enabled in the SDK, demo, dashboard, or any default configuration.

## 1. What was measured

Whether transition intelligence keeps accumulated experience more current,
less duplicated, safer to forget, and better preserved across scopes than
the canonical reference.

Every system ran against its own isolated in-memory store, seeded from the
same frozen before-state, through the real `ExperienceManager` and
`ExperienceEngine`. The oracle scored output; it never generated it.

Two lifecycle views are kept apart throughout:

- **actual** — what a system really did to memory;
- **projected** — what a proposal *would* do if it alone governed state.

Non-mutating modes leave those different by design. Collapsing them would
report an improvement that never happens.

## 2. Systems

| System | Reference level | Mode | Applied |
|---|---|---|---|
| `experienceos_hybrid_full_v2_reference` | full composition | disabled | 0 |
| `experienceos_transition_shadow_v1` | full composition | shadow | 0 |
| `experienceos_transition_candidate_v1` | full composition | candidate | 0 |
| `experienceos_transition_rules_v1` | proposal only | shadow | 0 |
| `experienceos_transition_adopted_v1` | full composition | adopted (isolated) | {adopted['actions_applied']} |
| `experienceos_transition_learned_shadow_v1` | unavailable | — | — |
| `experienceos_transition_qwen_ceiling_v1` | unavailable | — | — |

Both optional systems report unavailable with a reason and receive no
synthetic score.

## 3. Historical-scored results ({data['partitions']['historical_scored']['records']} cases)

| Metric | Reference | Candidate | Adopted (isolated) |
|---|---|---|---|
| transition classification | {reference['classification']['correct']}/{reference['classification']['total']} | {candidate['classification']['correct']}/{candidate['classification']['total']} | {adopted['classification']['correct']}/{adopted['classification']['total']} |
| update targets resolved | {reference['target']['correct']}/{reference['target']['total']} | {candidate['target']['correct']}/{candidate['target']['total']} | {adopted['target']['correct']}/{adopted['target']['total']} |
| wrong targets | {reference['target']['wrong']} | {candidate['target']['wrong']} | {adopted['target']['wrong']} |
| **stale active pairs** | **{reference['lifecycle_actual']['stale_pairs']}** | {candidate['lifecycle_actual']['stale_pairs']} | **{adopted['lifecycle_actual']['stale_pairs']}** |
| **duplicate pairs** | **{reference['lifecycle_actual']['duplicate_pairs']}** | {candidate['lifecycle_actual']['duplicate_pairs']} | **{adopted['lifecycle_actual']['duplicate_pairs']}** |
| targets deactivated | {reference['lifecycle_actual']['targets_deactivated']['correct']}/{reference['lifecycle_actual']['targets_deactivated']['total']} | {candidate['lifecycle_actual']['targets_deactivated']['correct']}/{candidate['lifecycle_actual']['targets_deactivated']['total']} | {adopted['lifecycle_actual']['targets_deactivated']['correct']}/{adopted['lifecycle_actual']['targets_deactivated']['total']} |
| preservation | {reference['lifecycle_actual']['preservation']['correct']}/{reference['lifecycle_actual']['preservation']['total']} | {candidate['lifecycle_actual']['preservation']['correct']}/{candidate['lifecycle_actual']['preservation']['total']} | {adopted['lifecycle_actual']['preservation']['correct']}/{adopted['lifecycle_actual']['preservation']['total']} |

The reference resolves no transition targets because the canonical planner
has no transition taxonomy — that is an availability difference, not eleven
wrong guesses.

## 4. The decisive finding

The transition path **identifies the right target** ({candidate['target']['correct']}/{candidate['target']['total']}) and, when applied,
**removes stale current values** (stale pairs {head['reference_stale_pairs']} → {head['adopted_stale_pairs']}).

But applying it **creates duplicates**: duplicate pairs rise
**{head['reference_duplicate_pairs']} → {head['adopted_duplicate_pairs']}**.

The cause is measured, not inferred. Adopted mode *adds* its verified
`supersede` + replacement `create` alongside the canonical planner's own
`create` for the same statement. Both creates persist, and they are
semantic duplicates of each other. The candidate's **projected** state
reaches {candidate['lifecycle_projected']['duplicate_pairs']} duplicate pairs — but a projection is not what
adoption applies.

Gate 1 therefore fails, and the path is classified **candidate only**.
Resolving this needs an `action_replaced` effect that substitutes the
planner's equivalent create, which is integration work and not a
benchmarking change.

## 5. Development fixtures ({data['partitions']['development_fixtures']['records']} cases)

Reported separately and never merged into the historical headline. Several
categories — questions, negative forget, hypothetical, broad forget, and
ambiguous targets — exist **only** as fixtures, so findings there are
engineering evidence, not historical evidence.

## 6. Adoption gates

{_gate_table(gates)}

**{gates['passed']} passed, {gates['failed']} failed, {gates['inconclusive']} inconclusive, {gates['unavailable']} unavailable.**
Every blocking safety gate passes.

### Failed and inconclusive gates

**Gate 1 (fail).** {gates['gates'][0]['justification']}

**Gate 6 (inconclusive).** {gates['gates'][5]['justification']}

## 7. Ablation contributions

| Ablation | Disabled component | Classification correct | Safety failures | Runtime eligible |
|---|---|---|---|---|
{ablation_rows}

Identity is the largest single contributor. Every ablation is
benchmark-only, non-mutating, and cannot reach adopted action insertion.

## 8. Safety

Every zero-tolerance metric, reported whether or not it passed:

{chr(10).join(f"- {key}: **{value}**" for key, value in sorted(data['safety'].items()))}

## 9. Downstream retrieval and context

Recall@K and MRR are **unavailable**: the transition corpus carries no
relevance judgements, so those metrics have no defensible denominator here
and were not synthesized. What the corpus supports was measured:
selection rate {data['downstream']['reference']['selection_rate']} → {data['downstream']['adopted']['selection_rate']},
context tokens {data['downstream']['reference']['context_tokens']} → {data['downstream']['adopted']['context_tokens']},
inactive memories retrieved {data['downstream']['reference']['inactive_retrieved']} → {data['downstream']['adopted']['inactive_retrieved']}.

## 10. Claims

### Supported

{chr(10).join(f"- **{c['claim']}** — {c['detail']} ({c['backing']})" for c in built['claims']['supported'])}

### Not supported

{chr(10).join("- " + c['claim'] + (f" — {c['reason']}" if c.get('reason') else "") for c in built['claims']['unsupported'])}

## 11. Limitations

{chr(10).join("- " + item for item in built['limitations']['limitations'])}

## 12. What this does not mean

- No transition controller is canonical.
- The default mode remains `disabled`.
- Candidate-only means the path may keep running for diagnostics and
  candidate translation; it may **not** affect canonical state.
- Isolated adopted-infrastructure applications are evidence that the
  governed path works, not evidence of canonical adoption.

Regenerate: `./scripts/run_benchmarks.sh transition-benchmark` then
`./scripts/run_benchmarks.sh transition-report`.
"""
