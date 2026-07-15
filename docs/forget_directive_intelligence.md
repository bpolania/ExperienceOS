# Forget-Directive Intelligence

A bounded deterministic controller that separates real forget directives
from everything that merely looks like one, resolves exactly one safe
active target, and produces a verifiable forget transition.

> Given a source statement, its evidence, and the active memory state
> before it — is this a real forget directive, and if so which single
> active memory does it safely name?

Its goal is not to maximize the number of forgotten memories. It is to
recognize explicit forget intent, resolve one safe target, preserve
unrelated and differently scoped experience, and fail closed when the
request is unclear.

## 1. Authority boundary

- `ExperienceManager` remains lifecycle-policy authority.
- `ExperienceEngine._apply_memory_actions` remains the sole durable
  mutation boundary.
- The controller **proposes only**: no store, no durable event, no
  authorization, no application. `authorized` and `action_applied` are
  always `false`.
- **Bulk deletion is not supported** and is never approximated by
  splitting a broad request into single-target forgets.
- The controller **never constructs a created memory** for any source. A
  forget directive cannot become a positive assertion here structurally,
  not merely by rule.

A controller proposal, a verifier acceptance, and canonical-effect
eligibility are three different things. None is authorization.

## 2. Architecture: proposal adapter

`experienceos/memory/forget.py` already implements the layered forget
handling the transition contract names as authoritative:
`ForgetIntentDetector` (negation → question → hypothetical → quoted →
current-turn-only → bulk → positive patterns) and `ForgetTargetResolver`
(active-only scored resolution with explicit score and margin thresholds
that reject ambiguity rather than guessing, `MAX_TARGETS` bounded).

**That module is unchanged and reused.** Building a second forget parser
would fork the canonical semantics this work must stay consistent with,
and would leave two deterministic components disagreeing about what a
forget directive is.

What this module adds is the layer that did not exist:

- mapping the resolver's outcomes onto the frozen transition taxonomy;
- **refusing multi-target forgets** (the canonical resolver can return up
  to `MAX_TARGETS`; durable multi-target forgetting is out of scope, so a
  request resolving to several memories is refused, never split);
- bridging identity: the snapshot carries no `semantic_identity`
  metadata, so the identity layer's projection is passed to the resolver
  — which is what lets `"Forget my morning drink preference entirely."`
  resolve at all (lexical overlap alone scores below threshold);
- two safety guards the canonical detector does not cover (see §4);
- constructing `ProposedTransition` values and verifying every one.

The canonical planner, manager, engine, and store are untouched. Only one
component has forget authority, and it is not this one.

## 3. Controller identity

| Field | Value |
|---|---|
| controller id | `experienceos_forget_rules_v1` |
| version | `1` |
| canonical status | **not canonical, not adopted** |
| dependencies | standard library and existing modules only |
| statefulness | stateless — every call takes an explicit before-state |

The transition contract reserves no forget-specific system id (its
reserved ids are transition-scoped, and `experienceos_transition_rules_v1`
already names the update controller). A distinct behavior needs a
distinct id.

## 4. Classification ordering

Order is a safety property, not a style choice:

1. **hypothetical** — before questions, because the clearest hypothetical
   forget is phrased as a question ("If I asked you to forget X, what
   would happen?"); a question-first order would mislabel it. Both are
   non-mutating, so this ordering cannot widen anything.
2. **questions about memory, for every removal verb** — the canonical
   question guard only fires on *forget*-shaped questions, so
   `"Could you remove my airport preference?"` would otherwise reach the
   directive patterns and read as a real removal. **This controller adds
   that guard.** Polite question grammar is never permission to mutate.
3. **memory-inspection questions** ("Do you remember …?").
4. **the canonical detector's own ordering** — negation before
   affirmative, then hypothetical, quoted, current-turn-only, bulk. This
   already guarantees "Don't forget …" and "Can you forget …" can never
   become directives.
5. **replacement guard** — a removal that *supplies the new value*
   ("I no longer prefer aisle seats; I prefer window seats.") is a
   supersession. Update intelligence owns it; claiming it here would give
   one sentence two competing readings. **This controller adds that
   guard.**
6. **broad/bulk** → fail closed.
7. **direct affirmative directive** with a named target.
8. anything else with no forget bearing → not ours; abstain.

Note the detector runs **before** any wording gate: a real directive need
not contain the word "forget" (`"I don't care about my study schedule
preference anymore."`).

## 5. Intent taxonomy

Controller-internal, mapped onto the frozen transition taxonomy:
affirmative targeted / affirmative scoped, negative forget, forget
capability question, forget confirmation question, memory-inspection
question, hypothetical forget, broad forget, bulk forget, ambiguous
forget, no-target forget, inactive-target forget, quoted third-party
forget, current-turn-only, unrelated source, unsupported forget, positive
assertion containing forget wording.

| Directive | Frozen transition |
|---|---|
| affirmative, one safe target | `forget_existing` |
| forget/inspection question | `reject_question` |
| hypothetical | `reject_hypothetical` |
| ambiguous target | `reject_ambiguous` |
| broad / bulk / quoted | `reject_unsupported` |
| current-turn-only | `reject_temporary` |
| positive assertion with forget wording | `reject_forget_directive_as_creation` |
| negative forget | `duplicate_noop` / `semantic_duplicate_noop` / handoff |
| unrelated source | abstain |

## 6. Target description and resolution

The canonical `describe_target` supplies tokens, entities, attribute
hints, kind hint, and the historical qualifier; the identity layer
supplies subject/attribute/value/scope when the described text projects.
**Unknown stays unknown** — no field is filled in from an arbitrary
active memory, and scope is never borrowed.

Candidates are **active memories only**. Superseded and forgotten records
are inspected for audit diagnostics but can never be targets. Resolution
statuses: exact / semantic / scoped target, no active target, multiple
targets, inactive-only, ambiguous scope/kind/attribute, value-only
ambiguity, broad unsupported, description incomplete, unrelated only, no
target required, unsupported.

A forget is proposed only when exactly one active target resolves above
the canonical score threshold and beats the runner-up by the margin.
Ambiguity is refused, never ranked by recency. The snapshot has no
creation time, so a single constant timestamp makes the canonical
tie-break fall through to memory-id ascending: deterministic, with no
fabricated recency.

## 7. Negative forget

A negative forget asserts the memory; it never removes it. The assertion
is compared with active state and yields `duplicate_noop` /
`semantic_duplicate_noop`. If it names no active memory, the controller
**abstains with a handoff** — creating it is update intelligence's
authority, not this controller's.

## 8. Evaluation

```bash
./scripts/run_benchmarks.sh evaluate-forget-intelligence
./scripts/run_benchmarks.sh repeat-forget-intelligence
python -m pytest tests/test_forget_intelligence.py
```

Applicability is decided by the committed annotation, not by the
controller's own opinion: a record is forget-applicable when its scoring
categories name a forget concern *and* its statement carries forget
bearing, or its oracle is `forget_existing`. A forget *category* is not a
forget *source* — `forgetting_006` (a plain restatement) and
`forgetting_005` (a routing question) carry forget categories because the
scenario probes forget behavior, but say nothing about memory. They
belong to the abstention set.

Every other scorable record is checked for the opposite property: that
the controller **abstains** rather than claiming a source it does not
own.

### Measured results

| Metric | historical-scored | development-only |
|---|---|---|
| forget-applicable / records | 4 / 28 | 6 / 27 |
| directive classification | **4 / 4** | **6 / 6** |
| macro F1 | 1.0 | 1.0 |
| target accuracy | **4 / 4** | **1 / 1** |
| positive creations from directives | **0** (of 4) | **0** (of 2) |
| supersessions from directives | **0** | **0** |
| verifier accepted | 4 / 4 | 6 / 6 |
| abstained on non-forget sources | **24 / 24** | **21 / 21** |
| canonical-effect eligible | 0 | 0 |

Every zero-tolerance safety counter is 0 in both partitions. p95 latency
0.65 ms and 0.39 ms — inside the contract's 5 ms budget. Latency is
measured after a discarded warm-up, consistent with the update
controller.

## 9. Reference comparison

Anchor: `experienceos_hybrid_full_v2_reference`, reproduced by running
the real `SemanticMemoryPlanner` (which inherits the canonical
`_plan_forgets` layer) over the same before-state and statement.

| Forgot the oracle target | historical | development |
|---|---|---|
| `experienceos_forget_rules_v1` | 4 / 4 | 1 / 1 (of the cases requiring one) |
| `experienceos_hybrid_full_v2_reference` | 2 / 4 | 4 / 6 |

**This is not a claim of canonical improvement**, for three reasons:

1. the controller's identity lexicon and this corpus share domains;
2. the reference reproduced here is the **planner component standalone**,
   not the full composition, which contains further layers;
3. a shadow controller cannot demonstrate canonical improvement — only
   the adoption workstream can, against the contract's gates.

The earlier finding that the standalone reference planner forgets on a
forget *question* and on a *negative* forget reproduces here. Those
remain **development-only fixture findings**, not historical benchmark
evidence, and they characterize the planner component standalone — not
canonical production behavior.

## 10. Typed-evidence defect

`TransitionSourceEvidence.grounding_validation` lacks a type annotation,
so it is a class attribute rather than a constructible dataclass field:
passing it raises `TypeError`, and it never serializes. **Confirmed and
re-verified, deliberately not corrected.**

It does not block this controller, which decides from `evidence_mode` and
never constructs the field. The narrow correction was authorized only *if*
the defect blocked typed forget evidence; it does not, so frozen code
stays untouched. A regression test pins the current behavior so the
decision is visible rather than forgotten. A later prompt that needs to
attach a validator verdict to evidence will have to fix it.

## 11. Diagnostics

Structured `ForgetControllerDiagnostic(code, category, detail)` covering
classification, target resolution, and verifier status, plus the target
description, bounded candidate ids with scores, and per-stage latency.
Deterministic serialization; no secrets, keys, paths, benchmark contents,
unrelated memory text, or provider configuration.

## 12. Known limitations

- **Bounded directive vocabulary.** Supported forms only; anything else
  abstains or fails closed.
- **Sparse historical forget evidence.** 4 historical cases, all
  affirmative directives with an exact target. Questions, negative
  forget, broad forget, ambiguous targets, and inspection questions are
  **development-fixture only**.
- **Corpus fit.** The identity lexicon and the corpus share domains;
  results do not generalize beyond them.
- Attribute-only and value-only descriptions stay ambiguous whenever more
  than one active memory is compatible — safe, but it lowers recall.
- **No bulk forget support**, by design. Governed bulk forgetting remains
  a separate product capability.
- No canonical integration, no execution modes, no learned fallback.
- Reference comparability limits (planner component standalone).

## 13. Claims not supported

Open-domain forget understanding solved; bulk forgetting; autonomous
deletion; canonical adoption; production-grade target resolution; learned
forget reasoning; multilingual support; improved final answer quality;
safe broad deletion; general forget resolution outside supported
patterns.

## 14. Relationship to later work

Update intelligence detects forget language and hands off via
`forget_directive_detected`; this controller picks it up and resolves the
target. Neither emits the other's transition. Later integration modes
will decide whether a verified, eligible proposal is authorized and
applied — through `ExperienceManager` validation and the engine's
existing `valid_actions` + `_apply_memory_actions` path, which remains
the only way durable state changes. The binding definitions live in
`docs/transition_verification_contract.md`.
