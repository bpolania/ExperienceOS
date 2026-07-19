# Canonical Lifecycle Activation — Claims Matrix

Every value below traces to committed machine-readable evidence under
`benchmarks/results/committed/`. Live figures are one stochastic sample
from the six-system `qwen-plus` campaign
(`canonical-lifecycle-activation-live/`).

## Supported

| Claim | Evidence |
|-------|----------|
| Persistent memory across sessions | `test_canonical_lifecycle_transitions.py` (SQLite reconstruction) |
| Memory creation | canonical create path |
| Deterministic bounded updates | `update_intelligence.py`; live update cases |
| Deterministic bounded forgetting | `forget_intelligence.py`; live forget cases |
| Lifecycle-aware retrieval (excludes superseded/forgotten) | offline family; live context |
| Context selection within a budget | `context_accounting` in both families |
| Lineage preserved | superseded rows resolve to replacement |
| Exact runtime transition authorization | `transition_authority.py`; adversarial suite |
| Exact replacement authorization | `action_replacement/authorization.py` |
| ExperienceManager admission preserved | engine admission before application |
| Engine-only durable mutation | `_apply_memory_actions` sole boundary; spies |
| Dashboard lifecycle visibility | `transition_diagnostics.py`; dashboard tests |
| Four genuine stale failures fixed at final-answer level | live: 4/4 `correct`, `uses_stale=False` |
| Canonical final-answer accuracy 71.05% → 78.95% | frozen vs live `aggregate_by_system.json` |

## Supported with notes

| Claim | Note |
|-------|------|
| Competitive comparability | canonical 78.95% is 2.63 pts below strongest live baseline (stateless 81.58%), within the frozen ~5-point heuristic; one stochastic sample; **not superior** |
| Stale-answer improvement | 9/18 → 5/18; the four genuine failures fixed, the five residual flags are the known Phase 18 evaluator false positives under the unchanged frozen contract |
| Context economy | canonical 58.05 vs full-history 454.45 avg tokens/case = 87.23% reduction, from the live Phase 20 campaign |

## Not supported

- Competitive superiority / definitive competitive dominance.
- State-of-the-art memory performance.
- All stale answers eliminated.
- General semantic update understanding.
- General semantic forgetting.
- Production concurrency safety.
- Durable single-use receipt consumption (no consumed-receipt registry).
- Enterprise authorization guarantees.
- Provider-independent competitive superiority.

## Current status labels

- `CANONICAL_DETERMINISTIC_LIFECYCLE_TRANSITIONS_ACTIVATED`
- `RUNTIME_TRANSITION_AUTHORITY_FAIL_CLOSED_VALIDATED`
- `PHASE_20_LIFECYCLE_EVIDENCE_RERUN_COMPLETE`
- `LIVE_COMPETITIVE_CAMPAIGN_COMPLETE`
- `COMPETITIVE_VIABILITY_COMPARABLE_WITH_NOTES`
