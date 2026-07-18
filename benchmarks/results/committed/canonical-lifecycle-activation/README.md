# Canonical Lifecycle Activation — Evidence Family

Additive follow-up evidence produced after the canonical chat path was
changed to run the activated deterministic lifecycle transitions
(deterministic update and forget controllers, the shared verifier, the
bounded runtime transition authority, and planner precedence). It reruns
the complete frozen competitive-viability subset through the **activated**
canonical composition and records what changed.

This family is **additive**. It does not modify any frozen Phase 17 or
Phase 18 evidence; it references those files read-only by path and hash
(`integrity_manifest.json`).

## Live-provider status

Qwen Cloud was **not configured** in the environment that produced this
family, so the live competitive final-answer campaign could not be rerun.
The lifecycle, retrieval, and context path is provider-independent — it is
driven by the deterministic controllers and the bounded authority, not by
the language model — so it is reproduced here in full with the recorded
(Mock) response provider. Final-answer/judge dimensions are recorded as
`UNAVAILABLE_LIVE_JUDGE` and the competitive decision is
`LIVE_COMPETITIVE_RESULT_UNAVAILABLE`.

## What this family shows

- The four genuine Phase 18 stale-answer failures are fixed at the
  lifecycle/retrieval/context level: the obsolete memory is now superseded
  or forgotten and excluded from the rendered context.
- Across the 40-case subset, 16 cases now supersede or forget an obsolete
  memory; the frozen Phase 18 leakage classification recorded that **zero**
  memories were superseded or forgotten under the create-only path
  (`any_memory_superseded_or_forgotten = false`).
- All 38 applicable cases pass the deterministic scenario constraints
  (lifecycle + retrieval + context); the 2 not-applicable cases skip, as
  in Phase 17.

## What this family does NOT claim

- It does not recompute final-answer accuracy, stale-answer rate, or any
  judge-scored competitive metric — those require the live Qwen judge.
- It does not re-adjudicate the five Phase 18 evaluator false positives;
  that is a frozen scoring-contract matter and remains unchanged.
- It makes no production-concurrency or provider-independent-superiority
  claim.

## Files

| File | Contents |
|------|----------|
| `integrity_manifest.json` | Hashes (sha256 + git blob) of every frozen input, before/after preservation |
| `run_manifest.json` | Run id, system, offline mode, affected-selection rule, affected ids |
| `execution_summary.json` | Status distribution, provider-failure record, competitive status |
| `complete_case_results.jsonl` | All 40 canonical cases: lifecycle/retrieval/context, deterministic |
| `affected_case_results.jsonl` | The deterministically-selected lifecycle-affected subset |
| `scoring_results.jsonl` | Deterministic scenario status per case (final-answer = unavailable) |
| `aggregate_metrics.json` | Lifecycle activity, deterministic pass counts, context economy |
| `phase18_followup.json` | Nine-case Phase 18 follow-up classification |
| `four_genuine_case_audit.json` | Sixteen-question deep trace of the four genuine cases |
| `comparison_report.md` | Judge-readable Phase 17 vs Phase 20 comparison |
| `reproducibility.md` | Exact commands, environment, determinism notes |
| `generate_evidence.py` | Deterministic generator for the whole family |

## Reproduce

```bash
python benchmarks/results/committed/canonical-lifecycle-activation/generate_evidence.py
```
