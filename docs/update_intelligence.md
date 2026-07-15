# Deterministic Update Intelligence

A bounded deterministic controller that turns supported update language
and active memory state into explicit, verifiable transition proposals.

> Given a source statement, its evidence, and the memory state before it
> — which lifecycle transition should ExperienceOS *propose*?

Its purpose is not to maximize mutation rate. It is to propose a safe,
explainable transition when the evidence supports one, and to abstain or
reject when it does not.

## 1. Authority boundary

- `ExperienceManager` remains lifecycle-policy authority.
- `ExperienceEngine._apply_memory_actions` remains the sole durable
  mutation boundary.
- The controller **proposes only**: it holds no store, emits no durable
  event, authorizes nothing, and applies nothing.
- Every actionable proposal is submitted to the transition verifier.
  `action_applied` is always `false`.

Three statements that are not interchangeable: a controller proposal, a
verifier acceptance, and canonical-effect eligibility. None of them is
authorization, and none of them is application.

## 2. Relationship to the canonical planner

**Option C — shared identity foundation, proposal-only.**

`SemanticMemoryPlanner` is **unchanged** and remains the only
deterministic component with real lifecycle effect. This controller is
not wired into any runtime path, so two deterministic components can
never issue contradictory lifecycle decisions: only one has authority,
and it is not this one. Both consume the same semantic identity layer,
so identity semantics are shared rather than forked.

## 3. Controller identity

| Field | Value |
|---|---|
| controller id | `experienceos_transition_rules_v1` (reserved by the contract) |
| version | `1` |
| canonical status | **not canonical, not adopted** — a reserved id implies neither |
| dependencies | standard library only; no provider, model, embedding, or network |
| statefulness | stateless — every call takes an explicit before-state |

## 4. Architecture

1. **source classification** — bounded intent patterns plus the identity
   layer's markers;
2. **candidate identity projection** — `project_text` from the identity
   layer, consumed and never reimplemented;
3. **target resolution** — `resolve_identity` against the active
   snapshot, plus explicit old-value validation;
4. **proposal construction and verification** — a `ProposedTransition`
   submitted to `TransitionVerifier`.

## 5. Intent taxonomy

Controller-internal, and mapped onto the frozen transition taxonomy
rather than replacing it: durable assertion, direct replacement,
instead-of replacement, switched-from-to, no-longer-now, used-to-now,
correction, exact/semantic restatement, scoped addition, unrelated
addition, temporary exception, historical-only, hypothetical, question,
forget directive, negative forget, valueless update request, task
request, ambiguous, unsupported.

Classification order matters, most decisive first:

1. non-durable markers (question → hypothetical → temporary);
2. forget language — **negative first**, because "Don't forget that I
   prefer X" asserts X rather than removing it;
3. historical-only (a historical marker with no current clause);
4. task request (a one-off ask, not a durable assertion);
5. valueless update request ("Update my airport." names a topic but no
   new value);
6. explicit replacement forms;
7. durable assertion (identity projected a current value, or a
   standing-scope cue makes an imperative durable);
8. otherwise transient conversational state.

## 6. Supported patterns

| Pattern | Example | Extracted |
|---|---|---|
| direct replacement | "I now prefer window seats." | new value |
| instead-of | "Use SFO instead of SJC for work flights." | new + explicit old |
| switched-from-to | "I switched from Chrome to Firefox." | old + new |
| no-longer-now | "I no longer prefer aisle seats; I prefer window seats." | old + new |
| used-to-now | "I used to prefer aisle seats, but now I prefer window seats." | historical old + current new |
| correction | "Actually, make it window." / "Correction: use SFO." | new value only |
| scoped addition | "For long international flights, I prefer window seats." | new + scope |
| restatement | "I prefer aisle seats for short work trips." | duplicate |

The replaced clause is **never** projected as the asserted value. Where
an old value is explicit, it must match the resolved target or the
proposal is rejected — the source would otherwise be naming a different
memory than the one it claims to replace.

## 7. Target resolution

Candidates start from **active memories only**; superseded and forgotten
memories are never canonical targets. Selection is by identity, never by
text similarity or recency.

Statuses: no target required, exact target, semantic target, conflict
target, scoped coexistence, no matching target, multiple targets,
inactive-only match, old-value mismatch, identity ambiguous, unrelated
only, unsupported.

Supersession requires exactly one active target with the same subject
and attribute, a compatible scope, a conflicting current value, current
durable intent, and a matching explicit old value where one is supplied.
Multiple plausible targets **fail closed** as `reject_ambiguous` — never
ranked by recency and never guessed.

A valueless update request cannot update anything; whether it is
`reject_ambiguous` or `reject_unsupported` depends on how many active
memories its topic could name.

## 8. Forget boundary

Formal forget-directive targeting is a **separate concern and is not
implemented here**. This controller detects forget language only to keep
it out of update intelligence:

- affirmative forget → bounded handoff (`forget_directive_detected`),
  abstains, and **never creates a positive memory**;
- negative forget → treated as an assertion of the memory; produces no
  forget and no duplicate creation;
- forget question → `reject_question`;
- the controller emits **no forget proposal for any source** and
  resolves no forget targets.

## 9. Evaluation

```bash
./scripts/run_benchmarks.sh evaluate-update-intelligence
./scripts/run_benchmarks.sh repeat-update-intelligence
python -m pytest tests/test_update_intelligence.py
```

The controller sees only the statement, its evidence, and the
before-state — nothing derived from the expected transition (test
enforced). This measures **proposal intelligence**, unlike the
verifier's oracle-derived evaluation.

Two scoring conventions, both explicit:

- **Forget cases are scored on the forget boundary**, not on transition
  classification, because forget targeting is out of scope. What is
  measured is that they create nothing positive.
- **`duplicate_noop` without the `exact_duplicate` category accepts
  either duplicate form**, exactly as the identity and verification
  layers already treat it. Strict label-equality accuracy is reported
  alongside so the convention hides nothing.

Latency is measured after a discarded warm-up call: the first call in a
process pays ~1.9 ms of one-time regex compilation that has nothing to
do with per-case work.

### Measured results

| Metric | historical-scored | development-only |
|---|---|---|
| applicable / records | 24 / 28 | 24 / 27 |
| transition accuracy | **24 / 24** | **24 / 24** |
| strict label equality | 24 / 24 | 23 / 24 |
| macro F1 | 1.0 | 1.0 |
| target accuracy | 7 / 7 | 10 / 10 |
| supersession | 7 / 7 | 10 / 10 |
| duplicates | 2 / 2 | 3 / 3 |
| scoped coexistence | 1 / 1 | 2 / 2 |
| verifier accepted | 24 / 24 | 24 / 24 |
| forget boundary: positive creations | 0 / 4 | 0 / 3 |
| abstentions (applicable) | 0 | 0 |

Every zero-tolerance safety counter is 0 in both partitions. p95 latency
0.45 ms and 0.87 ms — inside the contract's 5 ms budget.

The single strict-equality miss is `negative_forget-01`, labelled
`duplicate_noop` while the controller emits the more specific
`semantic_duplicate_noop`. The lifecycle effect is identical.

## 10. Reference comparison

Anchor: `experienceos_hybrid_full_v2_reference`, reproduced by running
the real `SemanticMemoryPlanner` over the same before-state and
statement. Comparison is on **lifecycle effect** — (created count,
superseded ids, forgotten ids) — because the planner has no transition
taxonomy, and forcing its actions into one would measure translation
rather than behavior.

| Lifecycle effect matches the oracle | historical | development |
|---|---|---|
| `experienceos_transition_rules_v1` | 24 / 24 | 24 / 24 |
| `experienceos_hybrid_full_v2_reference` | 16 / 24 | 11 / 24 |

**This is not a claim of canonical improvement.** Read it with three
limits:

1. The controller's bounded lexicon was built from exactly these
   domains, and it is evaluated on exactly them. The reference is a
   general-purpose planner that was not tuned to this corpus. The gap
   measures fit to this corpus, not general superiority.
2. The reference reproduced here is the **planner component evaluated
   standalone**, not the full composition, which contains further
   layers.
3. The controller is shadow-only. A shadow controller cannot demonstrate
   canonical improvement; only the adoption workstream can, against the
   contract's gates.

Characterized honestly, the reference's misses are mostly **missed
supersessions**: it creates the new value without deactivating the old
one, leaving two current values for one identity. Two development
fixtures also record the planner acting on forget language it should
not: it forgets in response to `"Can you forget my seat preference?"` (a
question) and `"Don't forget that I prefer aisle seats."` (a negative
forget). Those are two authored fixtures, not historical evidence, and
they characterize the planner component standalone.

## 11. Diagnostics

Structured `UpdateControllerDiagnostic(code, category, detail)` covering
intent, matched pattern, target resolution, and verifier status, plus
the identity projection, target keys, bounded candidate list, and
per-stage latency. Deterministic serialization; no secrets, keys, paths,
benchmark contents, unrelated memory text, or provider configuration.

## 12. Known limitations

- **Bounded language patterns.** Supported forms only; anything else
  abstains or rejects. Not open-domain update intelligence.
- **Corpus fit.** The lexicon and the evaluation share domains; results
  do not generalize beyond them.
- **Sparse evidence.** One historical semantic-duplicate case; several
  categories exist only as development fixtures.
- **Correction depends on context.** An elliptical correction ("back to
  aisle") has no identity key of its own and resolves only when exactly
  one active memory matches its value domain.
- **Reference comparability.** The planner component standalone, on a
  corpus it was not built for.
- **No canonical integration**, no execution modes, no learned fallback,
  and no formal forget targeting.
- Small, uneven corpus: 24 + 24 applicable cases.

## 13. Claims not supported

Open-domain update intelligence solved; autonomous memory management;
canonical adoption; production-grade natural-language parsing; learned
update reasoning; multilingual support; complete forget intelligence;
improved final answer quality; general target resolution outside
supported patterns.

## 14. Relationship to later work

Formal forget-directive separation and target safety build on the
handoff this controller emits. Later integration modes will decide
whether a verified, eligible proposal is authorized and applied —
through `ExperienceManager` validation and the engine's existing
`valid_actions` + `_apply_memory_actions` path, which remains the only
way durable state changes. The binding definitions live in
`docs/transition_verification_contract.md`.
