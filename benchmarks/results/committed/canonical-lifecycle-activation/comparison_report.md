# Phase 17 vs Canonical Lifecycle Activation — Comparison Report

## 1. Decision

- Execution: **PHASE_20_LIFECYCLE_EVIDENCE_COMPLETE_LIVE_RERUN_UNAVAILABLE**
- Competitive: **LIVE_COMPETITIVE_RESULT_UNAVAILABLE**

The activated canonical lifecycle path is validated on the frozen subset
at the lifecycle, retrieval, and context level. The live competitive
final-answer campaign could not be rerun because Qwen Cloud was not
configured, so no new final-answer competitive metric is asserted.

## 2. Frozen contract and integrity

Frozen inputs live in `benchmarks/results/committed/competitive-viability/`
and are referenced read-only. Internal `manifest_hash` =
`9c7f3009…`; `stale_failure_evidence.raw_records_hash` = `bb9c1362…`.
Full hash table in `integrity_manifest.json`; preservation reproved after
the rerun.

## 3. Systems rerun

Only `canonical_experienceos_qwen`, run offline through the activated
canonical composition. The five comparison systems were **not** rerun:
the competitive comparison is a live-judge campaign, and no live provider
was available. Frozen Phase 17 baseline numbers are cited below by
reference, not recomputed.

## 4. Provider / model configuration

- Response provider: `MockProvider` (recorded); Qwen Cloud not configured.
- Extraction: canonical selection resolves to the deterministic controller
  offline (Qwen extraction only when configured).
- Lifecycle: deterministic update + forget controllers, `TransitionVerifier`,
  `BoundedRuntimeTransitionAuthority`, `planner_precedence=True`, exact
  transition + replacement authorization, ExperienceManager admission,
  ExperienceEngine application.
- Credentials present: **false** (boolean only).

## 5. Scope and selection

All 40 frozen cases were rerun. The deterministically-derived
lifecycle-affected subset uses the rule: `lifecycle_category ∈ {update,
forgetting}` OR `final_answer_category == current_vs_stale` OR
`case_id startswith "containment"`. Selected ids are in
`run_manifest.json`.

## 6. Four genuine stale-case results

All four are fixed at the lifecycle/retrieval/context level (full trace in
`four_genuine_case_audit.json`):

| Case | Obsolete memory | Phase 20 outcome |
|------|-----------------|------------------|
| `context_005_active_and_inactive_versions` | "Prefers dark mode…" | superseded; context shows only light |
| `retrieval_008_stale_would_mislead` | "Phone is a Pixel 6." | superseded; context shows only Pixel 9 |
| `containment_002_supersede_inactive_target` | "Prefers tea…" | superseded; context shows only coffee |
| `forgetting_005_forgotten_leakage_check` | "Send my daily status…#eng-daily" | forgotten; context shows no memory |

In frozen Phase 17 the obsolete memory in each of these remained active and
leaked into the rendered context.

## 7. Nine-case Phase 18 follow-up

`phase18_followup.json`. The four genuine failures →
`fixed_by_lifecycle_activation`. The five evaluator false positives →
`evaluator_false_positive_remains` (the frozen scoring-contract limitation
is unchanged and cannot be re-adjudicated without the live judge). Four of
those five now also show correct lifecycle supersede/forget; that is a
lifecycle improvement, not a re-scoring.

## 8. Lifecycle activity (Phase 17 → Phase 20)

| Metric | Phase 17 | Phase 20 |
|--------|----------|----------|
| Cases with any supersede or forget | 0 | 16 |
| Cases with a supersede | 0 | 11 |
| Cases with a forget | 0 | 6 |
| Deterministic constraints passed (applicable) | — | 38 / 38 |
| Skipped (not applicable) | 2 | 2 |

Phase 17 zero is from the frozen leakage classification
(`any_memory_superseded_or_forgotten = false`).

## 9. Frozen Phase 17 final-answer metrics (reference only)

Cited from `scoring_evidence.json`; not recomputed in Phase 20.

| System | Final-answer acc | Stale-use rate | Pref adherence | Unsupported |
|--------|------------------|----------------|----------------|-------------|
| canonical_experienceos_qwen | 27/38 = 71.05% | 9/18 = 50.0% | 14/15 = 93.33% | 7/38 = 18.42% |
| full_history | 30/38 = 78.95% | 5/17 = 29.41% | 16/17 = 94.12% | 5/38 = 13.16% |
| stateless | 30/38 = 78.95% | 1/16 = 6.25% | 10/15 = 66.67% | 1/38 = 2.63% |
| naive_top_k | 29/38 = 76.32% | 6/16 = 37.5% | 14/15 = 93.33% | 4/38 = 10.53% |
| append_only | 27/37 = 72.97% | 6/15 = 40.0% | 13/15 = 86.67% | 5/37 = 13.51% |
| deterministic_experienceos | 27/38 = 71.05% | 9/18 = 50.0% | 15/18 = 83.33% | 6/38 = 15.79% |

Prior gap: canonical 71.05% vs strongest baseline 78.95% = **7.90 points**;
stale used in 50% of applicable canonical answers.

## 10. Case-level improvements and regressions

- Improvements: 16 cases now correctly supersede/forget obsolete memory
  (0 before); the four genuine stale leakages are removed from context.
- Regressions: none observed. All 38 applicable cases pass the
  deterministic scenario constraints; the 2 skipped cases match Phase 17.
- Final-answer-level improvement/regression: not measurable offline.

## 11. Context economy

Canonical average context ≈ 58.05 tokens/case (sum 2206 over 38). The
frozen Phase 17 report’s ~87% reduction versus full history is referenced,
not recomputed (a live full-history rerun would be required to recompute
the exact ratio under identical conditions).

## 12. Safety and unsupported claims

Unchanged offline: no answer post-processing, no retrieval change that
hides state. Unsupported-claim and abstention rates are judge-scored and
therefore `UNAVAILABLE_LIVE_JUDGE` in Phase 20.

## 13. Competitive viability decision

**LIVE_COMPETITIVE_RESULT_UNAVAILABLE.** Canonical lifecycle activation is
validated; the competitive final-answer comparison is incomplete pending a
live Qwen campaign. The four genuine stale failures — the root cause behind
the 50% stale-use rate — are eliminated from context, which is the
necessary upstream condition for the final-answer stale-use rate to fall;
confirming that fall requires the live judge.

## 14. Supported claims

- Canonical deterministic updates now supersede obsolete memories.
- Canonical deterministic forgets now remove memories from active use.
- The four previously genuine stale-state failures are fixed at the
  lifecycle/retrieval/context level.
- Context remains small (≈58 tokens/case average).

## 15. Not-yet-supported claims

- Final-answer accuracy improved (needs live judge).
- Stale-answer rate decreased in scored answers (needs live judge).
- Canonical is within the frozen ~5-point comparability heuristic (needs
  live judge).
- All stale answers are eliminated; general semantic update/forget;
  production concurrency; provider-independent superiority.

## 16. Limitations

Offline, single response provider (Mock); no live judge; baselines cited
from frozen evidence, not rerun; the five evaluator false positives are not
re-adjudicated.

## 17. Reproduction

See `reproducibility.md`.

## 18. Artifact index

See `README.md`.
