# Transition Verification

Deterministic verification of proposed memory lifecycle transitions.
This layer answers one question and applies no answer:

> Given a source statement, its evidence, the memory state before it, and
> a proposed before-to-after transition — is that transition structurally
> valid, grounded, identity-consistent, lifecycle-legal, correctly
> targeted, scope-safe, preservation-safe, and lineage-safe?

The deliverable is a **verified description of an intended effect**, not
a mutation.

## 1. Authority boundary

- `ExperienceManager` remains lifecycle-policy authority.
- `ExperienceEngine._apply_memory_actions` remains the sole durable
  mutation boundary.
- The verifier holds no store, emits no durable event, authorizes
  nothing, and applies nothing.

Three statements that are **not** interchangeable:

| Claim | Meaning |
|---|---|
| `status == accepted` | the proposal is a defensible description |
| `canonical_effect_eligible` | *structurally* eligible for later consideration |
| `action_applied` | immutably `false` — nothing here applies anything |

A verification result is not an authorization token and is not proof
that an action ran.

## 2. Naming

`experienceos/controllers/transition.py` already defines
`TransitionEvidence` and `TransitionProposal` for a different layer — a
controller's approve/reject/abstain *recommendation*. To avoid two
representations wearing one name, the before-to-after models in
`experienceos/memory/transition_verification.py` are
**`TransitionSourceEvidence`** and **`ProposedTransition`**.

Reused rather than forked: `MemorySnapshot`, `ProposedMemoryCandidate`,
`EvidenceSpan`, `LIFECYCLE_STATUSES`, `MEMORY_KINDS`, and the identity
relations from `experienceos/memory/identity.py`.

## 3. Models

| Model | Role |
|---|---|
| `TransitionSourceEvidence` | bounded source support and evidence mode |
| `BeforeStateSnapshot` | detached lifecycle state + projected identities |
| `CreatedMemorySpec` | a memory that would be created (`created:0`) |
| `AfterStateExpectation` | the result a proposal claims |
| `ProposedTransition` | the proposal itself |
| `TransitionCandidate` | raw proposer output, pre-normalization |
| `TransitionVerificationResult` | explained outcome |
| `TransitionDiagnostic` | one structured reason |
| `VerifiedActionSpec` | inert action description |
| `ProjectedAfterState` | inert projection, diagnostic only |

## 4. Evidence model

`evidence_mode` distinguishes `grounded_valid`, `grounded_invalid`,
`ungrounded`, `historical_oracle`, `development_fixture`, `unavailable`,
and `unsupported`. Mode comes from the **caller**, never from the
proposal: a proposal cannot upgrade its own trust.

- **`historical_oracle`** — a frozen benchmark case predating grounded
  extraction. Usable for audit-only verification. **Never authorizes
  production adoption.**
- **`development_fixture`** — explicitly synthetic. Never presented as
  production grounding.

Unavailable historical grounding is *not* treated as invalid; it is
treated as non-production. Only `grounded_valid` can ever reach
canonical eligibility.

## 5. Before-state snapshot

Built once from read-only primitives and detached: mutating the caller's
collection afterwards cannot reach the snapshot (test-enforced). Carries
lifecycle state, kind, text, projected identity, target keys, a
deterministic content digest, and a `coverage_complete` flag.

The verifier accepts a **preconstructed** snapshot and never queries a
store. That keeps verification deterministic, testable, and independent
of persistence.

**Partial-snapshot safety.** If coverage is incomplete, preservation
cannot be proven: the result is `shadow_only`, canonical eligibility is
refused, and the diagnostic says why.

## 6. Verification order

1. **structure** → `structurally_invalid` / `unsupported`
2. **evidence** → grounding required/invalid
3. **source durability** → temporary / historical / hypothetical /
   question can never justify a durable effect
4. **targets** → exists, active, unique, not unrelated, scope-compatible
5. **identity relation** → the relation the transition type requires
6. **lifecycle legality** → no reactivation, no double supersession
7. **unsupported changes** → every created value and scope must appear
   in the evidence
8. **after-state projection** → compared against the proposal's claim
9. **preservation** → unrelated, scoped, and promised memories
10. **lineage** → predecessor valid, active, related, preserved
11. **eligibility**

Source durability is checked before targets because it is a property of
the *statement*, not of anything it names. Target checks precede
relation-matching so a mis-targeted proposal reports the target defect
rather than a generic mismatch.

## 7. Identity verification

Semantic identity is **consumed, not reimplemented** (test-enforced):

| Transition type | Required relation |
|---|---|
| `duplicate_noop` | exact **or** semantic duplicate |
| `semantic_duplicate_noop` | semantic or exact duplicate |
| `supersede_existing` | current-state conflict |
| `scoped_coexistence` | scoped coexistence |

`duplicate_noop` accepts either duplicate form because the transition
type asserts only "this duplicates existing experience, so do nothing" —
exactness is carried by the frozen scoring category, not the type.

Ambiguous comparisons fail closed. A forget directive is not a durable
assertion, so its identity projection cannot gate an explicitly supplied
target; identity only guards against a confidently unrelated one.

## 8. Preservation semantics

The frozen corpus distinguishes two claims, and so does the verifier:

- **`preserved`** — the record survives. Compatible with being
  superseded or forgotten, because ExperienceOS never hard-deletes.
  `forget_directive-01` lists the same id as both forgotten and
  preserved.
- **`unchanged`** — the stronger claim: still active and untouched. Only
  this contradicts a deactivation.

Unrelated active memories and compatibly scoped memories must survive a
supersession, creation, or forget of something else. Temporary,
historical, hypothetical, question-like, unsupported, and ambiguous
proposals must preserve the existing current value.

## 9. After-state projection

Computed inertly from the snapshot and the proposal — no store, no
production mutation method. Projects active/superseded/forgotten sets,
created local refs, lineage edges, semantic-duplicate count, and stale
active count. A mismatch against the proposal's expectation rejects. The
projection is **diagnostic only** and is never a durable state object.

## 10. Lineage

A supersession requires exactly one predecessor that exists, is active,
is identity-related, is preserved as superseded, and is not the created
memory itself. No-ops and rejections must claim no lineage. Forgetting
preserves audit identity without becoming a supersession.

## 11. Inert action specification

`VerifiedActionSpec` is deliberately **not** a `MemoryAction`. The engine
cannot consume this type, so a verification result can never be mistaken
for something applicable. Translating a spec into a canonical action is
a later, explicit integration step this layer does not build. Every spec
carries `applied=False`.

## 12. Diagnostics

Structured `TransitionDiagnostic(code, category, severity, field_ref,
memory_id, detail)` with stable codes from `TransitionRejectionReason`.
Deterministic serialization; bounded detail; no secrets, keys,
filesystem paths, benchmark file contents, model prompts, or unrelated
memories.

## 13. Evaluation

```bash
./scripts/run_benchmarks.sh evaluate-transition-verification
./scripts/run_benchmarks.sh repeat-transition-verification
python -m pytest tests/test_transition_verification_model.py
```

Proposals are **oracle-derived**: built directly from the committed
expected transitions. Adversarial proposals are deterministic
single-defect corruptions of those, so each rejection is attributable to
one cause. Historical-scored and development-only partitions are
reported separately; unresolved and excluded records are never scored.

### Measured results

| Partition | Correct (oracle-derived) | Adversarial rejected |
|---|---|---|
| historical-scored | **28 / 28** accepted | **54 / 54** |
| development-only | **27 / 27** accepted | **67 / 67** |

Every per-check pass rate is 28/28 and 27/27. No corpus proposal is
canonical-eligible (55/55), because neither partition carries production
grounding. Verification p95 latency ≤ 0.24 ms, inside the contract's
5 ms budget.

No committed result artifacts are produced. The contract reserves
`benchmarks/results/committed/transition-verification/` for the later
transition benchmark that measures controllers; publishing an
oracle-derived verifier evaluation under that name would pre-empt it.

## 14. Known limitations

- **Oracle-derived proposals.** Acceptance measures the verifier, not a
  controller's ability to produce these transitions. No transition
  precision or recall is claimed or measurable here.
- **No proposal generation.** This layer verifies proposals; it does not
  produce them from natural language.
- **Bounded identity support.** Inherits the identity layer's bounded
  lexicon; unsupported phrasing fails closed.
- **No production grounding in the corpus.** Historical cases predate
  grounded extraction and fixtures are synthetic, so canonical
  eligibility is exercised only in unit tests.
- **Grounding support checks are term-level.** Created values are
  verified against the source statement by required terms, not by full
  semantic entailment.
- **No canonical integration.** No shadow, candidate, verify-only, or
  adopted mode exists yet.
- **Corpus size.** 28 historical-scored and 27 development-only records.

## 15. Claims not supported

Natural-language update intelligence solved; controller proposal
precision or recall; autonomous memory management; canonical transition
adoption; production-grade transition verification; complete open-domain
target resolution; learned transition reasoning; improved final answers.

## 16. Relationship to later work

Later update intelligence will *generate* proposals; this layer decides
whether they are defensible. Later integration modes will decide whether
a verified, eligible proposal is authorized and applied — through
`ExperienceManager` validation and the engine's existing `valid_actions`
+ `_apply_memory_actions` path, which remains the only way durable state
changes. The binding definitions live in
`docs/transition_verification_contract.md`.
