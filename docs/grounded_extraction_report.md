# Grounded Extraction Report

## 1. Executive Summary

This report evaluates the grounded-extraction controllers as explicit,
non-canonical benchmark systems on the frozen `experienceos-lifecycle-v1`
dataset against additive extraction annotations. No controller is
adopted; no default ExperienceOS behavior changes.

The headline result is honest and negative for adoption. The
deterministic grounded controller
(`experienceos_grounded_rules_v1`) proposes for only
5/13 (38.5%) of the annotated single-message creation probes —
it misses durable facts (e.g. "I am based in the Denver office.") and
several update-phrased preferences. The canonical reference already
creates 11/13 (84.6%) of
those durable memories through its existing planner, so adopting the
grounded controller adds **no** new durable creation
(11/13 (84.6%) under adoption, unchanged). Worse,
under benchmark-only adoption it introduces
2 semantic-duplicate active memories and
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
11/13 (84.6%).

## 4. Annotation Scope

Lifecycle annotations: 40 records — 13 single-message creation probes,
2 duplicate restatements, 24 oracle-negatives, 1 unscorable. External
annotations: 50 records, all classification-only (frozen artifacts lack
reconstructable source text). See
`benchmarks/annotations/grounded-extraction/README.md`.

## 5. Systems Compared

- `experienceos_hybrid_full_v2_reference` — reference, grounded extraction disabled.
- `experienceos_grounded_rules_v1` — deterministic grounded extraction (shadow,
  candidate, benchmark-only adopted; never a default mode, never
  adopted).
- `experienceos_grounded_learned_shadow_v1`,
  `experienceos_grounded_learned_candidate_v1`,
  `experienceos_grounded_qwen_ceiling_v1` — optional; clean skip.

## Comparison Table (all layers)

Explicit denominators throughout:

| system_id | scorable_cases | proposal_rate | valid_proposal_rate | creation_precision | creation_recall | durable_creation_recall | correct_kind_rate | grounded_span_validity | unsupported_claim_rate | no_candidate_recall | durable_false_positives | duplicate_active_memories | state_corruption | downstream_selection_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| experienceos_hybrid_full_v2_reference | 39 | n/a | n/a | n/a | n/a | 11/13 (84.6%) | n/a | n/a | n/a | n/a | 1 | 0 | 0 | 11/11 (100.0%) |
| experienceos_grounded_rules_v1 | 39 | 6/39 (15.4%) | 6/6 (100.0%) | 5/6 (83.3%) | 5/13 (38.5%) | 11/13 (84.6%) | 5/6 (83.3%) | 6/6 (100.0%) | 0/6 (0.0%) | 23/24 (95.8%) | 2 | 2 | 0 | 11/11 (100.0%) |


## 6. Proposal Metrics

Proposal rate 6/39 (15.4%); valid proposal rate
6/6 (100.0%); direct-valid proposal rate
6/6 (100.0%); candidate-absent cases
33 of 39.

## 7. Grounding Metrics

Grounded-span validity 6/6 (100.0%);
unsupported-claim rate 0/6 (0.0%). The
grounding ablation removed 0 of
6 raw proposals (none):
the deterministic controller's proposals were already grounded, so the
validator neither hid valid proposals nor caught the forget-directive
over-extraction (which is grounded in surface form).

## 8. Creation Precision, Recall, and F1

Proposal-layer creation precision 5/6 (83.3%), recall
5/13 (38.5%), F1 0.5263157894736842. The single precision
miss is `forgetting_003`: the controller extracts "Prefers morning
flights" from "Forget that I prefer morning flights." Correct-kind rate
5/6 (83.3%).

## 9. No-Candidate Behavior

No-candidate precision 23/31 (74.2%), recall
23/24 (95.8%). Abstention is strong except for the
one forget-directive false positive.

## 10. Lifecycle Evaluation

Candidate-mode eligibility: 3 of
6 valid proposals were lifecycle-eligible;
the rest were rejected as `duplicate_of_planned` — the canonical planner
already creates the same memory in the batch. The eligible ones are
exactly where canonical and grounded normalize differently.

## 11. Durable-Memory Outcomes

In isolated adopted state, grounded extraction creates
16 memories across
14 cases, but durable creation recall is
11/13 (84.6%) — identical to the reference.
Durable false positives rise from
1 (reference) to
2 (grounded).

## 12. Downstream Retrieval and Selection

Downstream selection rate 11/11 (100.0%)
on created memories. Recall@K and MRR are not recomputed here (they are
covered by the frozen retrieval evidence and are reported as
unavailable to avoid an incompatible redefinition). Because grounded
extraction creates no memory the reference did not already create, there
is no measured downstream benefit.

## 13. Safety Metrics

State corruption 0; inactive contamination
0; forgotten leakage 0;
superseded leakage 0; unauthorized application
0; direct mutation violations
0. Duplicate active memories
2 — the one non-zero safety signal, from
the semantic-dedup gap under adoption.

## 14. Latency and Availability

Total extraction latency (controller + grounding) is sub-millisecond
mean over 40 samples — well within the 5 ms gate.
Measured values are digest-excluded per the established convention and
therefore not embedded here to keep the report reproducible. Optional
learned and Qwen systems are unavailable and skip cleanly; no model is
loaded and no credentials are read.

## 15. Grounding Ablation

Raw proposals 6; validated 6;
removed by grounding 0
(none).

## 16. Lifecycle Ablation

{'grounded_valid_proposals': 6, 'lifecycle_eligible': 3, 'isolated_applied_created_memories': 16, 'cases_with_created_memory': 14, 'downstream_selected_cases': 16, 'duplicate_active_leaks': 2}

## 17. Learned Extraction Results

Clean skip — no configured local learned runner. Deterministic fallback
is never substituted for learned quality. Learned system definitions are
preserved for a future run with a real runtime.

## 18. Qwen Ceiling Results

Clean skip — no credentials. Not required for default validation.

## 19. Adoption-Gate Evaluation

| gate | threshold | measured | status |
| --- | --- | --- | --- |
| creation_recall_or_absence_improvement | durable creation recall improves by >=1 case vs reference | reference 11/13 vs grounded 11/13 | fail |
| precision_defensible | durable false positives regress by at most 1 vs reference | reference 1 vs grounded 2 | pass |
| grounded_span_validity | 100% of accepted proposals have valid exact spans | 6/6 | pass |
| unsupported_claim_rate | 0 among accepted; <=2% among raw proposals | 0/6 | pass |
| no_candidate_behavior_defensible | no-candidate recall regresses by at most 1 case vs reference (reference abstains on all negatives) | grounded no-candidate recall 23/24 | pass |
| inactive_contamination | 0 | 0 | pass |
| forgotten_leakage | 0 | 0 | pass |
| superseded_in_current_context_leakage | 0 | 0 | pass |
| state_corruption | 0 | 0 | pass |
| duplicate_active_memories | 0 (no semantic-duplicate active memories under adoption) | 2 | fail |
| downstream_benefit | external candidate/selection rate improves, or new durable memories become retrievable | grounded downstream selection 11/11; no new durable memories vs reference | fail |
| latency | deterministic extraction adds <= 5 ms mean per interaction | mean total extraction latency (digest-excluded) | pass |
| diagnostics_complete | every extraction decision carries full integration diagnostics | integration diagnostics present per case | pass |
| default_tests_offline_deterministic | default tests remain offline and deterministic | two-run digest equality holds; no network/model/credentials | pass |
| optional_runners_skip_cleanly | optional learned paths skip cleanly when unavailable | learned and Qwen systems recorded as clean skips | pass |

Passed 12/15; failed 3;
not measurable 0.

## 20. Controller Classification

| system | classification | reason |
| --- | --- | --- |
| experienceos_grounded_rules_v1 | shadow_only | Fails adoption gates: no durable creation-recall improvement over the canonical planner, and under adoption it adds a forget-directive false positive plus semantic-duplicate active memories. Safe and useful as observation, not as a durable writer. |
| experienceos_grounded_learned_shadow_v1 | unavailable | no configured local learned runner available |
| experienceos_grounded_learned_candidate_v1 | unavailable | no configured local learned runner available |
| experienceos_grounded_qwen_ceiling_v1 | unavailable | no optional learned runtime configured (no credentials for the Qwen ceiling) |

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
- Development fixtures (37) are smoke only.

## 24. Reproduction Commands

```bash
PYTHONPATH=. .venv/bin/python -m benchmarks.grounded_extraction.cli run \
  --output benchmarks/results/committed
PYTHONPATH=. .venv/bin/python -m benchmarks.grounded_extraction.cli validate \
  benchmarks/results/committed
PYTHONPATH=. .venv/bin/python -m benchmarks.grounded_extraction.cli report
```

Artifact inventory: `benchmarks/results/committed/grounded-extraction-ablation/`,
`benchmarks/results/committed/grounded-extraction/`,
`benchmarks/results/committed/report-grounded-extraction/`,
`benchmarks/annotations/grounded-extraction/`, and this report.
