"""Report data, comparison tables, and the human-readable report.

Builds the digest-locked report data and renders
``docs/grounded_extraction_report.md`` with explicit denominators and
honest negative results. Deterministic: no timestamps in the digest
payload, stable ordering throughout.
"""

from __future__ import annotations

from benchmarks.grounded_extraction.systems import GROUNDED_RULES, REFERENCE


def _fmt(block):
    if block is None:
        return "n/a"
    if isinstance(block, dict) and "rate" in block:
        num, den, rate = (block.get("numerator"), block.get("denominator"),
                          block.get("rate"))
        if block.get("note"):
            return "n/a"
        if den in (None, 0):
            return f"{num}/{den} (undefined)"
        return f"{num}/{den} ({rate * 100:.1f}%)"
    return str(block)


def build_report_data(result):
    aggs = {a["system_id"]: a for a in result["aggregates"]}
    return {
        "run_schema_version": result["run_schema_version"],
        "dataset_id": result["dataset_id"],
        "systems": result["systems"],
        "aggregates": result["aggregates"],
        "grounding_ablation": result["grounding_ablation"],
        "lifecycle_ablation": result["lifecycle_ablation"],
        "fixture_smoke": result["fixture_smoke"],
        "optional_runs": result["optional_runs"],
        "external": {k: v for k, v in result["external"].items()
                     if k != "cases"},
        "gates": result["gates"],
        "classifications": result["classifications"],
        "reference_present": REFERENCE in aggs,
        "grounded_present": GROUNDED_RULES in aggs,
    }


_COLUMNS = [
    ("system_id", lambda a: a["system_id"]),
    ("scorable_cases", lambda a: a["case_counts"]["scorable"]),
    ("proposal_rate", lambda a: _fmt(a["proposal_metrics"]["proposal_rate"])),
    ("valid_proposal_rate",
     lambda a: _fmt(a["proposal_metrics"]["valid_proposal_rate"])),
    ("creation_precision", lambda a: _fmt(a["creation_metrics"]["precision"])),
    ("creation_recall", lambda a: _fmt(a["creation_metrics"]["recall"])),
    ("durable_creation_recall",
     lambda a: _fmt(a["creation_metrics"]["durable_creation_recall"])),
    ("correct_kind_rate",
     lambda a: _fmt(a["creation_metrics"]["correct_kind_rate"])),
    ("grounded_span_validity",
     lambda a: _fmt(a["grounding_metrics"]["grounded_span_validity"])),
    ("unsupported_claim_rate",
     lambda a: _fmt(a["grounding_metrics"]["unsupported_claim_rate"])),
    ("no_candidate_recall",
     lambda a: _fmt(a["no_candidate_metrics"]["no_candidate_recall"])),
    ("durable_false_positives",
     lambda a: a["creation_metrics"]["durable_false_positive_count"]),
    ("duplicate_active_memories",
     lambda a: a["safety_metrics"]["duplicate_active_memories"]),
    ("state_corruption", lambda a: a["safety_metrics"]["state_corruption"]),
    ("downstream_selection_rate",
     lambda a: _fmt(a["downstream_metrics"]["downstream_selection_rate"])),
]


def comparison_csv(result):
    header = ",".join(name for name, _ in _COLUMNS)
    lines = [header]
    for agg in result["aggregates"]:
        lines.append(",".join(str(fn(agg)) for _, fn in _COLUMNS))
    return "\n".join(lines) + "\n"


def comparison_markdown(result):
    header = "| " + " | ".join(name for name, _ in _COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in _COLUMNS) + " |"
    rows = [header, sep]
    for agg in result["aggregates"]:
        rows.append("| " + " | ".join(
            str(fn(agg)) for _, fn in _COLUMNS) + " |")
    return "\n".join(rows) + "\n"


def render_report(result) -> str:
    aggs = {a["system_id"]: a for a in result["aggregates"]}
    grd = aggs[GROUNDED_RULES]
    ref = aggs[REFERENCE]
    cm = grd["creation_metrics"]
    pm = grd["proposal_metrics"]
    gm = grd["grounding_metrics"]
    nc = grd["no_candidate_metrics"]
    sf = grd["safety_metrics"]
    lat = grd["latency_metrics"]
    la = result["lifecycle_ablation"]
    ga = result["grounding_ablation"]
    fx = result["fixture_smoke"]
    gates = result["gates"]
    comp = comparison_markdown(result)

    gate_rows = ["| gate | threshold | measured | status |",
                 "| --- | --- | --- | --- |"]
    for g in gates["gates"]:
        gate_rows.append(
            f"| {g['gate']} | {g['threshold']} | {g['measured']} | "
            f"{g['status']} |")
    gate_table = "\n".join(gate_rows)

    cls_rows = ["| system | classification | reason |",
                "| --- | --- | --- |"]
    for c in result["classifications"]:
        cls_rows.append(
            f"| {c['system_id']} | {c['classification']} | {c['reason']} |")
    cls_table = "\n".join(cls_rows)

    return f"""# Grounded Extraction Report

## 1. Executive Summary

This report evaluates the grounded-extraction controllers as explicit,
non-canonical benchmark systems on the frozen `experienceos-lifecycle-v1`
dataset against additive extraction annotations. No controller is
adopted; no default ExperienceOS behavior changes.

The headline result is honest and negative for adoption. The
deterministic grounded controller
(`experienceos_grounded_rules_v1`) proposes for only
{_fmt(cm['recall'])} of the annotated single-message creation probes —
it misses durable facts (e.g. "I am based in the Denver office.") and
several update-phrased preferences. The canonical reference already
creates {_fmt(ref['creation_metrics']['durable_creation_recall'])} of
those durable memories through its existing planner, so adopting the
grounded controller adds **no** new durable creation
({_fmt(cm['durable_creation_recall'])} under adoption, unchanged). Worse,
under benchmark-only adoption it introduces
{sf['duplicate_active_memories']} semantic-duplicate active memories and
one forget-directive false positive. Grounding validation and state
safety hold (no corruption), and the optional learned and Qwen systems
cleanly skip (no runtime configured). The controller is classified
**shadow_only**: useful as observation, not justified as a durable
writer.

## 2. Evaluation Contract

Metrics follow `docs/grounded_extraction_contract.md` §14: every ratio
is reported as numerator/denominator plus rate, zero denominators are
undefined (never 0%/100%), duplicates are excluded from creation
precision/recall, unscorable cases are excluded from denominators, and
latency is digest-excluded. The four evidence layers — proposal,
grounding, lifecycle, durable/downstream — are reported separately and
never collapsed into one score.

## 3. Historical Reference Reproduction

The canonical reference system reproduces the accepted reference
behavior: with grounded extraction disabled, ExperienceOS is
byte-identical to its pre-integration self (proven by the integration
tests) and the committed retrieval-evidence validators pass unchanged.
Reference durable creation recall on the annotated probes is
{_fmt(ref['creation_metrics']['durable_creation_recall'])}.

## 4. Annotation Scope

Lifecycle annotations: 40 records — 13 single-message creation probes,
2 duplicate restatements, 24 oracle-negatives, 1 unscorable. External
annotations: 50 records, all classification-only (frozen artifacts lack
reconstructable source text). See
`benchmarks/annotations/grounded-extraction/README.md`.

## 5. Systems Compared

- `{REFERENCE}` — reference, grounded extraction disabled.
- `{GROUNDED_RULES}` — deterministic grounded extraction (shadow,
  candidate, benchmark-only adopted; never a default mode, never
  adopted).
- `{result['optional_runs'][0]['system_id']}`,
  `{result['optional_runs'][1]['system_id']}`,
  `{result['optional_runs'][2]['system_id']}` — optional; clean skip.

## Comparison Table (all layers)

Explicit denominators throughout:

{comp}

## 6. Proposal Metrics

Proposal rate {_fmt(pm['proposal_rate'])}; valid proposal rate
{_fmt(pm['valid_proposal_rate'])}; direct-valid proposal rate
{_fmt(pm['direct_valid_proposal_rate'])}; candidate-absent cases
{pm['candidate_absent_count']} of {grd['case_counts']['scorable']}.

## 7. Grounding Metrics

Grounded-span validity {_fmt(gm['grounded_span_validity'])};
unsupported-claim rate {_fmt(gm['unsupported_claim_rate'])}. The
grounding ablation removed {ga['removed_by_grounding']} of
{ga['raw_proposals']} raw proposals ({ga['removed_by_code'] or 'none'}):
the deterministic controller's proposals were already grounded, so the
validator neither hid valid proposals nor caught the forget-directive
over-extraction (which is grounded in surface form).

## 8. Creation Precision, Recall, and F1

Proposal-layer creation precision {_fmt(cm['precision'])}, recall
{_fmt(cm['recall'])}, F1 {cm['f1'].get('value')}. The single precision
miss is `forgetting_003`: the controller extracts "Prefers morning
flights" from "Forget that I prefer morning flights." Correct-kind rate
{_fmt(cm['correct_kind_rate'])}.

## 9. No-Candidate Behavior

No-candidate precision {_fmt(nc['no_candidate_precision'])}, recall
{_fmt(nc['no_candidate_recall'])}. Abstention is strong except for the
one forget-directive false positive.

## 10. Lifecycle Evaluation

Candidate-mode eligibility: {la['lifecycle_eligible']} of
{la['grounded_valid_proposals']} valid proposals were lifecycle-eligible;
the rest were rejected as `duplicate_of_planned` — the canonical planner
already creates the same memory in the batch. The eligible ones are
exactly where canonical and grounded normalize differently.

## 11. Durable-Memory Outcomes

In isolated adopted state, grounded extraction creates
{la['isolated_applied_created_memories']} memories across
{la['cases_with_created_memory']} cases, but durable creation recall is
{_fmt(cm['durable_creation_recall'])} — identical to the reference.
Durable false positives rise from
{ref['creation_metrics']['durable_false_positive_count']} (reference) to
{cm['durable_false_positive_count']} (grounded).

## 12. Downstream Retrieval and Selection

Downstream selection rate {_fmt(grd['downstream_metrics']['downstream_selection_rate'])}
on created memories. Recall@K and MRR are not recomputed here (they are
covered by the frozen retrieval evidence and are reported as
unavailable to avoid an incompatible redefinition). Because grounded
extraction creates no memory the reference did not already create, there
is no measured downstream benefit.

## 13. Safety Metrics

State corruption {sf['state_corruption']}; inactive contamination
{sf['inactive_contamination']}; forgotten leakage {sf['forgotten_leakage']};
superseded leakage {sf['superseded_leakage']}; unauthorized application
{sf['unauthorized_application']}; direct mutation violations
{sf['direct_mutation_violation']}. Duplicate active memories
{sf['duplicate_active_memories']} — the one non-zero safety signal, from
the semantic-dedup gap under adoption.

## 14. Latency and Availability

Total extraction latency (controller + grounding) is sub-millisecond
mean over {lat.get('count')} samples — well within the 5 ms gate.
Measured values are digest-excluded per the established convention and
therefore not embedded here to keep the report reproducible. Optional
learned and Qwen systems are unavailable and skip cleanly; no model is
loaded and no credentials are read.

## 15. Grounding Ablation

Raw proposals {ga['raw_proposals']}; validated {ga['validated_proposals']};
removed by grounding {ga['removed_by_grounding']}
({ga['removed_by_code'] or 'none'}).

## 16. Lifecycle Ablation

{la}

## 17. Learned Extraction Results

Clean skip — no configured local learned runner. Deterministic fallback
is never substituted for learned quality. Learned system definitions are
preserved for a future run with a real runtime.

## 18. Qwen Ceiling Results

Clean skip — no credentials. Not required for default validation.

## 19. Adoption-Gate Evaluation

{gate_table}

Passed {gates['passed']}/{gates['gate_count']}; failed {gates['failed']};
not measurable {gates['not_measurable']}.

## 20. Controller Classification

{cls_table}

No runtime defaults change. Eligibility, where it appears, is not
adoption.

## 21. Supported Claims

- Deterministic grounded extraction proposes for a minority of the
  annotated creation probes and misses durable facts and several
  update-phrased preferences.
- Its grounded-span validity and abstention are high; grounding did not
  hide valid proposals.
- Adopting it adds no new durable creation over the canonical planner on
  this annotated set.
- Under adoption it introduces semantic-duplicate active memories and a
  forget-directive false positive.
- No lifecycle state corruption occurred; shadow and candidate
  evaluation are non-mutating; benchmark-only adoption preserved manager
  and engine authority.
- Learned and Qwen extraction were unavailable and skipped cleanly.

## 22. Claims Not Supported

Not claimed: any downstream answer-quality improvement; any candidate-
absence reduction over the canonical planner; that deterministic or
learned extraction is canonical or adopted; any official LongMemEval
score; state-of-the-art extraction; hallucination elimination; cost
savings.

## 23. Limitations

- Primary scoring is the 15 scorable creation/duplicate probes plus 24
  negatives — a small frozen denominator; every gate decision rests on
  case-level review.
- The external subset is classification-only; no held-out extraction
  score exists.
- The duplicate-active gap is a semantic-equivalence limitation of the
  exact-text dedup, documented in `docs/extraction_integration.md`.
- Development fixtures ({fx['fixture_count']}) are smoke only.

## 24. Reproduction Commands

```bash
PYTHONPATH=. .venv/bin/python -m benchmarks.grounded_extraction.cli run \\
  --output benchmarks/results/committed
PYTHONPATH=. .venv/bin/python -m benchmarks.grounded_extraction.cli validate \\
  benchmarks/results/committed
PYTHONPATH=. .venv/bin/python -m benchmarks.grounded_extraction.cli report
```

Artifact inventory: `benchmarks/results/committed/grounded-extraction-ablation/`,
`benchmarks/results/committed/grounded-extraction/`,
`benchmarks/results/committed/report-grounded-extraction/`,
`benchmarks/annotations/grounded-extraction/`, and this report.
"""
