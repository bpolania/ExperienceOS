# Transition Verification Closure

Closure record for the transition intelligence work: what was built,
what it was measured against, what was decided, and what deliberately
remains undone.

## Executive summary

ExperienceOS can now decide, deterministically and with evidence,
whether a new statement **replaces** an existing memory, **coexists**
with it, or **removes** it — and it can verify that decision before
anything durable happens.

On 28 historical scored cases the transition path classified **28/28**
transitions correctly and resolved **11/11** update targets with **0
wrong**, where the canonical reference resolves none. It lost **0**
scoped and **0** unrelated memories, guessed **0** ambiguous targets
into a mutation, and cut stale active-memory leakage from **6 pairs to
1**. Exact authorization rejected **20/20** bound-field mismatches.

**18 of 20 adoption gates passed, 1 failed, 1 is inconclusive. All 9
blocking safety gates passed.** The path is nonetheless **candidate-only**
— classified **`TRANSITION_PATH_CANDIDATE_ONLY`** — and **no transition
controller is canonical**. Under isolated benchmark-only adoption, semantic-duplicate
active pairs rise **0 → 10**: the integration *adds* its replacement
create alongside the canonical planner's create instead of replacing it,
so both persist. Gate 1 fails on exactly that, and a failed quality gate
blocks adoption even when every safety gate passes.

The decision is the deliverable. The system evaluated its own
intelligence, found the proposals sound and the applied outcome wrong,
and refused to let it touch durable memory.

## Objective

Give ExperienceOS the ability to reason about *transitions* in durable
experience — supersession, scoped coexistence, and removal — without
weakening the single mutation boundary or the lifecycle authority, and
to prove with committed evidence whether that ability deserves adoption.

Explicit non-goals: open-domain understanding, learned reasoning,
autonomous memory management, and adoption-by-default.

## What was built

| Component | Module | Role |
|---|---|---|
| Semantic memory identity | `experienceos/memory/identity.py` | Projects a statement into subject / attribute / value / scope; compares against existing memories. Structural, not a similarity score |
| Proposal & verification model | `experienceos/memory/transition_verification.py` | A verifier that checks a proposal against before-state and cited evidence and **never applies it** (`action_applied` invariantly false) |
| Update intelligence | `experienceos/memory/update_intelligence.py` | `experienceos_transition_rules_v1` — proposes supersession or abstains; hands forget directives off rather than answering them with a new memory |
| Forget intelligence | `experienceos/memory/forget_intelligence.py` | `experienceos_forget_rules_v1` — a proposal adapter over the canonical forget path; questions and hypotheticals never become directives |
| Governed integration | `experienceos/memory/transition_integration.py` | Five modes; exact 20-field authorization; routes only through the existing engine boundary |
| Benchmark & gates | `benchmarks/transition_benchmark/` | Five systems, 20 gates, ablations, digest-locked artifacts |
| Diagnostics | `demo/transition_diagnostics.py` | Single read-only source for every benchmark number the dashboard shows |

## Architecture and authority

The authority boundaries were not moved:

- `ExperienceEngine._apply_memory_actions` remains the **sole** durable
  mutation boundary. The benchmark measured 0 second mutation paths and
  0 direct mutation violations.
- `ExperienceManager` remains the lifecycle-policy authority.
- Controllers **propose only**. The verifier produces a
  `VerifiedActionSpec`, deliberately *not* a `MemoryAction`, so a
  verification result cannot be mistaken for something applicable.
- The integration coordinator holds no store and has no mutation method.

Integration modes: `disabled` (**default**), `shadow`, `candidate`,
`verify_only`, `adopted`. Only `adopted` can reach durable state, and
only with an authorization bound to 20 exact fields of one specific
verified proposal. Any mismatch fails closed and names the field. There
is no wildcard, and a bare environment-variable string cannot authorize
canonical effects.

## Results (28 historical scored cases)

| Metric | Reference (applied) | Candidate projection | Isolated applied |
|---|---:|---:|---:|
| Transition classification | 0/28 | **28/28** | **28/28** |
| Update targets resolved | 0/11 | **11/11** (0 wrong) | **11/11** (0 wrong) |
| Stale active pairs | 6 | 0 | **1** |
| Semantic duplicate pairs | **0** | 0 | **10** |
| Scoped memories lost | 0 | 0 | 0 |
| Unrelated memories lost | 0 | 0 | 0 |
| Forget targets | — | 4/4 | 4/4 |

The reference system scores 0/28 on classification because it performs
no transition classification at all — it is the full canonical
composition, not a transition controller. That is a description of
scope, not a defect.

Partitions are kept separate and never merged into one headline: **28
historical scored**, **27 development fixtures**, 2 unresolved
(diagnostic only), 11 excluded.

## Adoption gates

**18 passed · 1 failed · 1 inconclusive · 0 unavailable.**
**Blocking gates: 9 (4, 5, 8, 9, 10, 11, 12, 19, 20) — all passed.**

- **Gate 1 — FAIL.** Semantic duplicate active-memory count must
  decrease materially. It rose: 0 → 10.
- **Gate 6 — INCONCLUSIVE.** Forget-directive creation false positives
  must decrease. Both systems already produce 0, so no reduction can be
  demonstrated. Absence of regression is not measured improvement, and
  it is not rounded up to a pass.

Every blocking gate concerns safety — scoped coexistence, unrelated
preservation, state corruption, forgotten and superseded exclusion,
lineage, fail-closed ambiguity, exact authorization, and the
single-mutation-path invariant. All nine pass. **Passing every safety
gate is not adoption.** Gate 1 is a quality gate, it failed, and it is
decisive.

## The decisive finding

The transition intelligence proposes correctly. Applying it does not
work yet.

In adopted mode the verified replacement `create` is **appended**
alongside the canonical planner's own `create` for the same statement.
Both survive, and the pair is a semantic duplicate. The projection —
what the proposal *would* do on its own — is clean; the applied outcome
is not, because two correct components each independently create.

The fix is action-*replacement* integration semantics. It was
deliberately **not** attempted during closure: changing integration
behavior after the evidence is committed would invalidate the artifacts
the decision rests on. It is the first thing to do next.

## Safety

Measured, all zero: state corruption, forgotten leakage, superseded
leakage, lineage errors, scoped memories lost, unrelated memories lost,
ambiguous targets guessed, direct mutation violations, second mutation
paths, unauthorized applications, model calls, network calls.

Authorization: 20 bound fields, 20/20 mismatches rejected, exact match
accepted, 0 unauthorized applications.

## Ablation contributions

Ten configurations were measured, including `no_identity_layer`,
`no_scope_awareness`, `exact_text_duplicate_only`,
`proposal_without_verifier`, `verifier_with_oracle_proposals` (an upper
bound on verifier correctness, not a system claim),
`no_exact_authorization` (deliberately mismatched), and
`reference_planner_component` (component-only, reported separately so it
is never confused with the full canonical composition).

## Limitations

Reported as committed, not softened:

- small historical corpus (28 scored cases);
- sparse semantic-duplicate evidence (**1** scored case) — the failed
  Gate 1 rests on a thin historical base and the fixture evidence around
  it;
- sparse forget evidence (4 affirmative directives, all exact-target);
- question, negative-forget, hypothetical, broad-forget, and
  ambiguous-target coverage exists **only** in development fixtures;
- bounded deterministic controller vocabulary, sharing domains with the
  corpus — accuracy does not generalize beyond them;
- no relevance judgements in the corpus, so Recall@K and MRR are
  **unavailable** rather than synthesized;
- no learned controller, no multilingual evaluation, no bulk forget;
- adopted infrastructure is tested only in isolated benchmark runs;
- in-memory authorization; no production authorization service;
- no production deployment evidence, and no measured answer-quality
  improvement;
- the typed `grounding_validation` field in
  `transition_verification.py` remains unfixed — it is declared without
  a type annotation, so it is a class attribute rather than a
  constructible dataclass field. Known, recorded, and left alone.

## Not claimed

Open-domain transition intelligence, production-grade update or forget
understanding, autonomous memory management, learned transition
reasoning, multilingual generalization, **canonical adoption**, improved
final answer quality, broad forget support, complete duplicate
elimination, complete update-target resolution, or that semantic
duplicate prevention improves the applied lifecycle outcome.

## Artifacts and digests

| Family | Content digest |
|---|---|
| `benchmarks/results/committed/transition-verification/` | `d7c2946117e64f1c3dbea12982b8a38b4a7be77fc4ade3bb6769736924882ce3` |
| `benchmarks/results/committed/transition-ablation/` | `ed5338c29db08f2f7beea33441e0af7a38ef2a035848dd87cc77a672d632e25a` |
| `benchmarks/results/committed/report-transition-verification/` | `5dd83d40dd5ac4546b016fcd7d7fa3a0a74777c5dfbcfefc53127186e8fd0b69` |

All three bind `contract_commit 938cbd0`, `corpus_commit dba85ec`, and
`code_commit 56672f6`. The contract and the annotated corpus were
committed **before** any result. `latency.json` is excluded from
`file_digests` and declared under `nondeterministic_files`, so timing
noise cannot perturb a digest while the committed files stay
byte-identical across runs.

## Validation evidence

```bash
./scripts/run_benchmarks.sh validate-transition-verification   # all three families
./scripts/run_benchmarks.sh repeat-transition-benchmark        # determinism
./scripts/validate_demo.sh                                     # full offline demo path
python -m pytest                                               # full suite
```

Everything above is offline: no credentials, no network, no model
download, no Qwen call.

## Commit chain

Nine commits, linear, single-parent, no merges and no amendments:

1. `938cbd0` Define transition verification and update intelligence contract
2. `dba85ec` Add transition verification annotations
3. `8a3d948` Add semantic memory identity
4. `c967e23` Add transition proposal verification
5. `d3b8f0c` Add deterministic update intelligence
6. `95281af` Add forget directive intelligence
7. `56672f6` Add governed transition integration
8. `ef0f8c8` Add transition benchmark evidence
9. `b2362a0` Add transition dashboard visibility

Contract first, corpus second, results last.

## Recommended next work (not started)

1. **Action-replacement integration semantics** — make the transition's
   verified create *replace* the canonical planner's create rather than
   be appended beside it. This is the direct cause of Gate 1's failure
   and the single blocker to re-evaluating adoption.
2. Re-run the benchmark afterward and let the gates decide again. Do not
   adopt on the strength of a fix that has not been measured.
3. Fix the typed `grounding_validation` field.
4. Broaden historical semantic-duplicate and forget evidence; 1 scored
   duplicate case is too thin to carry an adoption decision either way.
5. Add relevance judgements so Recall@K and MRR become measurable
   instead of unavailable.
