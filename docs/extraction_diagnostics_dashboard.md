# Extraction Diagnostics Dashboard

Read-only visibility into how ExperienceOS proposes, grounds, evaluates,
rejects, and (only under explicit authorization) applies experience —
without changing extraction behavior, lifecycle authority, controller
defaults, or benchmark results.

## 1. Purpose

Let a judge or developer see the internal sequence: a message arrives,
the configured controller runs or stays disabled, it proposes one
candidate or abstains, the candidate cites an exact source span,
grounding validation passes or rejects it, lifecycle authority accepts /
rejects / deduplicates / conflicts, and `canonical_effect` shows whether
durable state actually changed. Two distinct surfaces implement this: a
**live decision trace** from runtime events and a **committed benchmark
summary** from frozen artifacts. They are never merged — a live shadow
proposal is not benchmark proof, and a benchmark classification is not a
live action.

## 2. Live Decision Trace

The "Extraction decision trace" section reads
`extraction_integration_evaluated` events via
`demo/extraction_diagnostics.extraction_trace`. It shows the latest
attempt as a signal table (proposal present, proposed kind, normalized
text, evidence offsets, grounding, lifecycle evaluation, duplicate /
conflict, adoption authorized, action generated, action applied,
canonical effect, final proposal source) and a bounded history expander.
When learned fields are present it also shows runner and parser status
and fallback usage. Absent fields render as distinct states
(`Not applicable`, `Not evaluated`, `None`, `Unavailable`), never as
misleading `False`.

## 3. Candidate-or-None Display

Abstention is first-class. `outcome_label` distinguishes: candidate
proposed; controller abstained (no candidate); grounding rejected;
integration re-validation rejected; adoption not authorized / mismatch;
learned runner unavailable; controller error (contained). A no-candidate
outcome is never treated as an error unless the event reports one, and
never rendered as a broken empty card.

## 4. Evidence Span Display

For committed case examples with locally committed source text, the
"Grounded extraction evaluation" section highlights the exact cited span
inside a bounded, escaped excerpt (`evidence_block`). Offsets are shown
as `[start, end)` zero-based, end-exclusive. The helper only ever slices
the provided source; it never reconstructs evidence from the normalized
candidate, and never displays a full unbounded message. All source text
is HTML-escaped before a single `<mark>` is placed around the verified
span, so markup-like or Unicode input cannot inject. The live trace
shows offsets and bounded normalized text (the integration event does
not carry the raw excerpt, so no highlight is fabricated there).

## 5. Grounding Stages

The integration event carries the overall grounding decision
(`grounding_status`) and primary `grounding_code`, which the trace shows
directly. Per-stage grounding results are not emitted on the integration
event, so the dashboard does not invent them — grounding is shown as its
overall decision plus code, clearly separated from lifecycle acceptance.

## 6. Lifecycle Evaluation

The trace shows `lifecycle_evaluation` (`eligible` / `rejected` /
`Not evaluated`), `lifecycle_rejection_reason`, and `duplicate_or_conflict`
as distinct signals. In shadow mode lifecycle is diagnostic-only; in
candidate mode it is evaluated non-mutating; in adopted mode an
authorized, admissible action is applied by the engine alone.

## 7. Canonical-Effect Semantics

`canonical_effect_label` renders `Yes — durable memory changed` only
when the event reports `canonical_effect: true`; otherwise
`No — durable state unchanged`, or `Unavailable` when the field is
absent. A valid, non-mutating proposal (shadow or candidate) always
shows canonical effect: no — grounding validity is proposal quality, not
lifecycle acceptance.

## 8. Learned Availability

The committed summary shows each optional learned system with
`executed: false` and its skip reason. Initial render constructs no
learned controller or local runner, imports no `llama_cpp`, constructs
no Qwen Cloud, reads no credentials, and scans for no model files. Clean
skip is shown as unavailability, never as a zero-quality score or a
failed adoption.

## 9. Fallback Attribution

`final_proposal_source` and `fallback_used` are surfaced so a
deterministic-fallback proposal is never credited to the learned
controller. The trace shows fallback usage and the final source
distinctly from the selected controller.

## 10. Benchmark Summary

`grounded_extraction_summary` loads
`benchmarks/results/committed/report-grounded-extraction/report_data.json`
and `adoption_gates.json` read-only. It shows proposal precision
(5/6), recall (5/13), F1, grounded-span validity (6/6), no-candidate
recall (23/24), durable creation for the canonical reference and the
benchmark-adopted grounded controller (11/13 each — no improvement),
duplicate active memories (2), and state corruption (0). Ratios are
shown with explicit numerators and denominators; unavailable metrics
stay distinct from zero.

## 11. Adoption-Gate Display

The gate-by-gate table from `adoption_gates.json` is shown with each
gate's status and threshold. The committed evidence records 12/15
passed. The dashboard states plainly that passing most gates is **not**
adoption approval and lists the decisive failed gates:
`creation_recall_or_absence_improvement`, `duplicate_active_memories`,
and `downstream_benefit`. The final classification is displayed as
**Shadow only**.

> Discrepancy note: the governing narrative for this work listed
> "defensible precision" among the failed gates. The committed
> `adoption_gates.json` — the source of truth per the benchmark contract
> — records `precision_defensible` as **pass** (durable false-positive
> delta of exactly 1, within the ≤1 threshold) and `downstream_benefit`
> as the third **fail** instead. The dashboard surfaces the committed
> artifact faithfully. The two decisive gates (no recall improvement,
> duplicate active memories) fail in both accounts, and the
> classification is shadow-only regardless.

## 12. Case Examples

Three committed lifecycle cases are shown, resolved to stable IDs:
`creation_002_durable_user_fact` (a durable fact the controller missed —
no proposal), `forgetting_003_forget_one_of_several` (a forget directive
the controller wrongly extracted "Prefers morning flights" from — a
grounded false positive, with the span highlighted), and
`updates_003_instruction_replacement` (a true positive that produces a
semantic-duplicate active memory under benchmark-only adoption). Each
card shows the expected candidate status, proposal, kind, grounding,
proposal score, lifecycle outcome, duplicate-active leak, and canonical
effect. Source text is bounded; no external copyrighted text is shown.

## 13. Artifact Loading

The loaders are read-only view models that load only approved committed
paths, tolerate missing/malformed files by returning an unavailable
state, preserve deterministic ordering, distinguish unavailable from
zero, perform no network access, run no benchmark, write no files,
mutate no state, and expose no personal paths. They do not import the
benchmark CLI or regenerate reports or digests.

## 14. Event Compatibility

`normalize_extraction_event` tolerates current integration events, old
events without extraction fields, partially populated events, and
unknown additive fields (ignored). Missing fields become `None`, shown
as distinct unavailable states, never as `False`. No migration is
required and unknown fields never invalidate the event stream.

## 15. Dashboard Safety

Initial render constructs no controller, runner, or provider beyond the
offline mock default; loads no model; imports no `llama_cpp`; constructs
no Qwen Cloud; touches no network; runs no benchmark; regenerates no
reports; mutates no memory; emits no controller proposal; writes no
files; and exposes no credentials or personal paths. Only an explicit
user interaction (selecting a non-mutating mode and sending a message)
causes the configured agent to process input.

## 16. Reset and Empty States

Empty states use the repository's caption convention:

- No extraction events: `No extraction decisions have been recorded.`
- Integration disabled: `Grounded extraction integration is disabled.`
- Benchmark unavailable: `Committed grounded-extraction evaluation is unavailable.`
- Learned unavailable: `... not executed — <reason>`.

Reset clears the live extraction trace (via the existing event-bus
clear) and never deletes committed benchmark artifacts; the committed
summary remains available after reset, and reset constructs no provider
and runs no benchmark.

## 17. Testing

`tests/test_extraction_diagnostics.py` covers the event view model,
evidence escaping/Unicode/bounds, the committed loader (null vs zero,
missing/malformed), classification display, and privacy.
`tests/test_dashboard_extraction_apptest.py` covers initial disabled
render with no heavy imports, the mode selector defaulting to disabled,
no controller construction on render, the committed summary (shadow-only,
failed gates, explicit ratios, learned unavailable, case examples), the
live shadow and candidate flows, shadow-equals-disabled non-mutation,
first-class abstention, and reset behavior.

## 18. Known Limitations

- The integration event does not carry the raw source excerpt or
  per-stage grounding results, so the live trace shows offsets and the
  overall grounding decision rather than a highlighted live span or
  per-stage breakdown.
- Case-example highlighting uses committed lifecycle source text; the
  external subset has no reconstructable source and is not shown.
- The duplicate-active gap is a semantic-equivalence limitation of the
  exact-text dedup, documented in `docs/extraction_integration.md`.

## 19. Current Controller Classification

The deterministic controller `experienceos_grounded_rules_v1` is
classified **shadow-only** by the committed benchmark evidence. The
learned and Qwen systems were **unavailable** in the committed benchmark.

## 20. Adoption Status

- Disabled remains the default.
- Shadow and candidate are non-mutating.
- Adopted mode requires an explicit authorization object and is never
  selectable from the dashboard.
- No controller is adopted.
- Deterministic grounded extraction is shadow-only; learned and Qwen
  were unavailable.
- Benchmark evidence showed no durable creation improvement over the
  canonical planner.
- Under benchmark-only adoption the deterministic path produced a
  forget-directive false positive and two semantic-duplicate active
  memories; state corruption remained zero.
- Dashboard visibility changes no runtime behavior.
