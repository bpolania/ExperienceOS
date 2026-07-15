# Transition Verification Report

**Adoption classification: `TRANSITION_PATH_CANDIDATE_ONLY`**

every blocking safety gate passes, but one or more quality gates fail: gate 1 (Semantic duplicate active-memory count decreases materially). Candidate mode remains non-mutating, so the path may keep running for diagnostics and candidate translation without affecting canonical state.

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
| `experienceos_transition_adopted_v1` | full composition | adopted (isolated) | 14 |
| `experienceos_transition_learned_shadow_v1` | unavailable | — | — |
| `experienceos_transition_qwen_ceiling_v1` | unavailable | — | — |

Both optional systems report unavailable with a reason and receive no
synthetic score.

## 3. Historical-scored results (28 cases)

| Metric | Reference | Candidate | Adopted (isolated) |
|---|---|---|---|
| transition classification | 0/28 | 28/28 | 28/28 |
| update targets resolved | 0/11 | 11/11 | 11/11 |
| wrong targets | 11 | 0 | 0 |
| **stale active pairs** | **6** | 6 | **1** |
| **duplicate pairs** | **0** | 0 | **10** |
| targets deactivated | 5/11 | 5/11 | 10/11 |
| preservation | 28/28 | 28/28 | 28/28 |

The reference resolves no transition targets because the canonical planner
has no transition taxonomy — that is an availability difference, not eleven
wrong guesses.

## 4. The decisive finding

The transition path **identifies the right target** (11/11) and, when applied,
**removes stale current values** (stale pairs 6 → 1).

But applying it **creates duplicates**: duplicate pairs rise
**0 → 10**.

The cause is measured, not inferred. Adopted mode *adds* its verified
`supersede` + replacement `create` alongside the canonical planner's own
`create` for the same statement. Both creates persist, and they are
semantic duplicates of each other. The candidate's **projected** state
reaches 0 duplicate pairs — but a projection is not what
adoption applies.

Gate 1 therefore fails, and the path is classified **candidate only**.
Resolving this needs an `action_replaced` effect that substitutes the
planner's equivalent create, which is integration work and not a
benchmarking change.

## 5. Development fixtures (27 cases)

Reported separately and never merged into the historical headline. Several
categories — questions, negative forget, hypothetical, broad forget, and
ambiguous targets — exist **only** as fixtures, so findings there are
engineering evidence, not historical evidence.

## 6. Adoption gates

| # | Gate | Threshold | Reference | Candidate/Adopted | Decision |
|---|---|---|---|---|---|
| 1 | Semantic duplicate active-memory count decreases materially | strictly fewer than reference; 0 for the strongest claim | 0 | 10 | **fail** |
| 2 | Supersession accuracy improves materially OR stale active-memory leakage decreases materially | >=1 case or >=2% relative on one, with no regression in the other | stale=6, supersessions=5/11 | stale=1, supersessions=10/11 | **pass** |
| 3 | Update-target accuracy is defensible | regresses by at most 1 case vs reference; every wrong target reviewed | 0/11 | 11/11 | **pass** |
| 4 | Scoped coexistence is preserved | 0 scoped memories wrongly deactivated/merged/replaced | 0 | 0 | **pass** (blocking) |
| 5 | Unrelated-memory preservation remains intact | 0 unrelated memories changed | 0 | 0 | **pass** (blocking) |
| 6 | Forget-directive creation false positives decrease | strictly lower than reference and 0 for adoption | 0 | 0 | **inconclusive** |
| 7 | Correct forget behavior does not regress | detection, correct-target, and no-op accuracies do not regress | targets=4/4, preserved=4 | targets=4/4, preserved=4 | **pass** |
| 8 | State corruption remains 0 | 0 | 0 | 0 | **pass** (blocking) |
| 9 | Forgotten memories remain excluded | 0 | 0 | 0 | **pass** (blocking) |
| 10 | Superseded current-mode memories remain excluded | 0 | 0 | 0 | **pass** (blocking) |
| 11 | Supersession lineage is preserved | 0 | 0 | 0 | **pass** (blocking) |
| 12 | Ambiguous transitions fail closed | ambiguous rejection does not regress; no ambiguous target guessed | 0 | 0 | **pass** (blocking) |
| 13 | Downstream retrieval and selection do not materially regress | within materiality (>1 case or >2% relative) | 1.0 rate | 1.0 rate | **pass** |
| 14 | Context token use does not materially regress | within materiality (>1 case or >2% relative) | 17 tokens | 17 tokens | **pass** |
| 15 | Latency remains acceptable for the demo | <= 5 ms mean added per interaction over the reference | measured; see latency.json | measured; see latency.json | **pass** |
| 16 | Diagnostics explain every transition decision | before/after fields and a decision reason present per case | n/a | 28/28 | **pass** |
| 17 | Default tests remain offline and deterministic | fixed | n/a | deterministic | **pass** |
| 18 | Optional learned paths skip cleanly when unavailable | fixed | n/a | 2 optional systems reported unavailable | **pass** |
| 19 | Authorization matches the exact controller, mode, source, transition type, and verified proposal | mismatch fails closed | n/a | 20/20 mismatches rejected | **pass** (blocking) |
| 20 | No second durable mutation path exists | adopted actions flow through valid_actions + _apply_memory_actions | 0 | 0 | **pass** (blocking) |

**18 passed, 1 failed, 1 inconclusive, 0 unavailable.**
Every blocking safety gate passes.

### Failed and inconclusive gates

**Gate 1 (fail).** Reference leaves 0 semantic-duplicate active pair(s); the adopted path leaves 10. The adopted path is not strictly fewer, so the gate fails. The candidate's projected state would reach 0, but a projection is not what adoption applies: adopted mode adds its replacement create alongside the canonical planner's create, so both persist and form a duplicate. Scoped memories lost: 0.

**Gate 6 (inconclusive).** Reference creates 0 positive memories from forget directives; adopted creates 0. Adoption requires strictly lower and 0. Both are already 0 on this corpus, so there is no reduction to demonstrate — the gate cannot be passed on evidence of improvement and is recorded inconclusive rather than passed by intuition.

## 7. Ablation contributions

| Ablation | Disabled component | Classification correct | Safety failures | Runtime eligible |
|---|---|---|---|---|
| full_transition_stack | nothing | 55 | 0 | false |
| exact_text_duplicate_only | semantic value canonicalization | 52 | 0 | false |
| no_scope_awareness | scope comparison | 52 | 0 | false |
| no_identity_layer | semantic memory identity | 26 | 0 | false |
| proposal_without_verifier | transition verifier | — | 0 | false |
| verifier_with_oracle_proposals | controller proposal generation | — | 0 | false |
| update_only | forget controller | 48 | 0 | false |
| forget_only | update controller | — | 0 | false |
| no_exact_authorization | exact authorization | — | 0 | false |
| reference_planner_component | manager, engine, and application | — | 0 | false |

Identity is the largest single contributor. Every ablation is
benchmark-only, non-mutating, and cannot reach adopted action insertion.

## 8. Safety

Every zero-tolerance metric, reported whether or not it passed:

- ambiguous_targets_guessed: **0**
- direct_mutation_violations: **0**
- forgotten_leakage: **0**
- lineage_errors: **0**
- model_calls: **0**
- network_calls: **0**
- scoped_memories_lost: **0**
- second_mutation_paths: **0**
- state_corruption: **0**
- superseded_leakage: **0**
- unauthorized_applications: **0**
- unrelated_memories_lost: **0**

## 9. Downstream retrieval and context

Recall@K and MRR are **unavailable**: the transition corpus carries no
relevance judgements, so those metrics have no defensible denominator here
and were not synthesized. What the corpus supports was measured:
selection rate 1.0 → 1.0,
context tokens 17 → 17,
inactive memories retrieved 0 → 0.

## 10. Claims

### Supported

- **deterministic transition proposal exists and is verified** — 28/28 transition classifications correct; every proposal verified (historical)
- **safe update-target resolution improves on supported cases** — 11/11 targets resolved with 0 wrong; the reference resolves no transition targets (historical)
- **stale active-memory leakage decreases materially** — stale active pairs 6 → 1 (historical)
- **scoped and unrelated memories remain preserved** — 0 scoped and 0 unrelated memories lost (historical)
- **ambiguous targets fail closed** — 0 ambiguous cases guessed into a mutation (historical+fixture)
- **exact authorization gates adopted effects** — 20/20 bound-field mismatches fail closed (infrastructure)
- **the transition path is CPU-feasible and offline** — well under the 5 ms mean ceiling; measured values in latency.json, which is excluded from content digests (historical+fixture)

### Not supported

- open-domain transition intelligence solved
- production-grade update understanding
- production-grade forget understanding
- autonomous memory management
- learned transition reasoning
- multilingual generalization
- canonical adoption
- improved final answer quality
- broad forget support
- complete duplicate elimination
- complete update-target resolution
- semantic duplicate prevention improves the applied lifecycle outcome — measured and refuted: adopted mode adds its replacement create alongside the canonical planner's create, so duplicate pairs rise from 0 to 10; gate 1 fails

## 11. Limitations

- small historical transition corpus (28 scored cases)
- sparse historical semantic-duplicate evidence (1 scored case)
- sparse historical forget evidence (4 affirmative directives, all exact-target)
- question, negative-forget, hypothetical, broad-forget, and ambiguous-target coverage exists only in development fixtures
- bounded deterministic controller vocabulary
- the controller lexicon and the corpus share domains, so accuracy does not generalize beyond them
- the reference is the full canonical composition on this corpus; a component-only view is reported separately as an ablation
- the transition corpus carries no relevance judgements, so Recall@K and MRR are unavailable rather than synthesized
- no learned controller and no multilingual evaluation
- no bulk forget support
- adopted infrastructure is tested only in isolated benchmark runs
- in-memory authorization; no production authorization service
- no production deployment evidence
- no measured answer-quality improvement
- the typed grounding_validation field remains unfixed

## 12. What this does not mean

- No transition controller is canonical.
- The default mode remains `disabled`.
- Candidate-only means the path may keep running for diagnostics and
  candidate translation; it may **not** affect canonical state.
- Isolated adopted-infrastructure applications are evidence that the
  governed path works, not evidence of canonical adoption.

Regenerate: `./scripts/run_benchmarks.sh transition-benchmark` then
`./scripts/run_benchmarks.sh transition-report`.
