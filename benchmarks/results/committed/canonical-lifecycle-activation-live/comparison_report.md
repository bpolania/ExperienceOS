# Live Competitive Rerun — Phase 17 vs Phase 20

## Decision

- Execution: **PHASE_20_LIFECYCLE_EVIDENCE_RERUN_COMPLETE** (live).
- Competitive: **COMPETITIVE_VIABILITY_COMPARABLE_WITH_NOTES**.

Qwen Cloud credentials were configured (in `.env`), the approved provider
smoke passed, and the full campaign completed under the frozen Prompt 6
controls: 6 systems × 40 cases, one shared response model (`qwen-plus`),
frozen deterministic + blinded-judge scoring.

## Systems and scope

All six required systems rerun live in one campaign; every system
completed 38 applicable cases and skipped the same 2 not-applicable cases,
matching the frozen Phase 17 posture. No execution failures.

## Per-system final-answer accuracy (live)

| System | Phase 17 | Phase 20 live | Δ |
|--------|----------|---------------|---|
| canonical_experienceos_qwen | 71.05% | **78.95%** | +7.90 |
| stateless | 78.95% | 81.58% | +2.63 |
| naive_top_k | 76.32% | 76.32% | 0.00 |
| full_history | 78.95% | 73.68% | −5.27 |
| append_only | 72.97% | 73.68% | +0.71 |
| deterministic_experienceos | 71.05% | 71.05% | 0.00 |

Baseline movement (e.g. full_history down, stateless up) reflects
single-sample live variance; both Phase 17 and Phase 20 are single live
runs. The comparison within Phase 20 is internally aligned (same model,
same campaign).

## Competitive determination

Canonical 78.95% vs the strongest live baseline (stateless) 81.58%: a
**2.63-point gap, within the frozen ~5-point comparability heuristic**.
Canonical does not equal or exceed the single strongest baseline, so the
decision is `COMPARABLE_WITH_NOTES` rather than `DEMONSTRATED`. The prior
determination was `NOT_YET_DEMONSTRATED` (7.90-point gap).

## Stale-answer behavior

Canonical stale-information use fell from **50.0% (9/18) to 27.78%
(5/18)**. The four genuine Phase 18 stale failures are all now scored
correct with `uses_stale=False`:

| Case | Method | correct | uses_stale |
|------|--------|---------|-----------|
| context_005_active_and_inactive_versions | deterministic | True | False |
| retrieval_008_stale_would_mislead | deterministic | True | False |
| containment_002_supersede_inactive_target | blinded_judge | True | False |
| forgetting_005_forgotten_leakage_check | blinded_judge | True | False |

The residual 5 stale records are exactly the five Phase 18 evaluator false
positives, which remain flagged under the unchanged frozen scoring
contract (`evaluator_false_positive_remains`). This confirms they are
scoring-criteria artifacts, not lifecycle failures.

## Other canonical metrics (live)

Current-information accuracy 76.47% → 88.24%; unsupported-claim rate
18.42% → 13.16%; abstention 100%; preference adherence 93.33% → 88.89%
(within single-sample variance).

## Supported claims

- Canonical deterministic updates and forgets now change final answers:
  obsolete values are superseded/forgotten and no longer surface.
- The four genuine stale failures are fixed at the final-answer level.
- Canonical final-answer accuracy improved to 78.95% and stale use fell to
  27.78% in this live sample.
- Canonical is now within the frozen comparability heuristic.

## Not-supported / noted

- Not `DEMONSTRATED`: canonical does not exceed the strongest single
  baseline in this sample.
- Single live sample; no multi-run confidence interval; live outputs are
  stochastic and not byte-reproducible.
- The five evaluator false positives are a frozen-contract limitation, not
  re-adjudicated here.

## Reproduce

See `README.md`. A fresh run yields a new independent sample.
