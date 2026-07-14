# Transition Verification and Update Intelligence Contract

**Status: contract — this document governs the transition-verification
initiative before any implementation begins. Where this contract and a
later workstream disagree, the safety boundaries here win.**

This is the binding measurement and governance contract for transition
verification and update intelligence: the verified starting baseline,
the transition task and its authority boundaries, the semantic memory
identity model, supersession / scoped-coexistence / forget-directive
rules, before- and after-state requirements, frozen metric definitions,
predeclared adoption gates and stop conditions, artifact boundaries, and
validation obligations. Everything in "Current" statements was verified
against the live repository at commit `d764afc` on 2026-07-14;
everything in "Planned" statements is design intent, not yet
implemented.

Naming note (repository policy). The repository `CLAUDE.md` content
policy is authoritative and forbids project-stage vocabulary (phase,
prompt, milestone, roadmap, sequencing) in new committed filenames,
directory names, document titles, headings, identifiers, and system
IDs. This contract therefore uses **feature-based** names throughout
(`transition_verification`, `transition-verification`,
`experienceos_transition_*`), following the precedent already
established for the grounded-extraction work
(`docs/grounded_extraction_report.md`,
`benchmarks/results/committed/grounded-extraction/`). Existing committed
names that already contain stage vocabulary
(`report-phase11/`, `docs/phase11_contract.md`, …) are frozen history:
they are referenced but never renamed. Concept and metric names below
are stable; only surface identifiers follow repository conventions.

---

## 1. Objective

This is the measurement and implementation contract for explicit
**before-to-after memory transition verification**. The central
question is: *given existing active experience and a newly grounded
statement, what before-to-after memory transition is justified?*

The initiative seeks to improve or characterize:

- duplicate handling;
- semantic-duplicate prevention;
- update-target resolution;
- supersession correctness;
- stale active-memory handling;
- scoped coexistence;
- unrelated-memory preservation;
- forget-directive separation;
- lifecycle lineage;
- transition diagnostics.

Durable **creation** improvement is not the primary objective. The
grounded-extraction evidence
(`docs/grounded_extraction_report.md`) already showed that creation
gains alone do not solve update correctness: exact-text duplicate
handling allowed two semantic-duplicate active memories, update-phrased
preferences were missed, and a forget directive was misread as a
positive preference assertion. This initiative targets that
transition/update boundary, not raw creation recall.

This initiative does **not** authorize an autonomous memory manager. No
transition controller becomes canonical in this initiative unless the
predeclared gates in §13 pass with explicit authorization.

---

## 2. Baseline Evidence

Verified fresh at the start of this workstream (not copied from a
transfer report):

| Item | Verified value |
|---|---|
| Branch | `main` |
| Starting commit (HEAD) | `d764afc788c3cbe298df6a61a4c83c8464023c0a` |
| `origin/main` (local ref and direct remote) | `d764afc788c3cbe298df6a61a4c83c8464023c0a` |
| Ahead / behind | 0 / 0 |
| Working tree | clean |
| Tests | 1,768 passed (measured) |
| Demo validation | passed (`scripts/validate_demo.sh`) |
| Grounded-extraction artifact validators | 3/3 passed |
| Historical artifact + retrieval validators | 11/11 passed |
| Repository hygiene | no tracked secrets, model files, caches, or personal paths (only `.env.example` placeholder) |

Inherited canonical decisions, verified intact against committed
artifacts and code:

- deterministic extractor `experienceos_grounded_rules_v1` →
  `shadow_only`;
- `experienceos_grounded_learned_shadow_v1`,
  `experienceos_grounded_learned_candidate_v1`,
  `experienceos_grounded_qwen_ceiling_v1` → `unavailable`;
- default extraction integration mode → `disabled`
  (`ExtractionIntegrationConfig.effect_mode` default;
  `ExperienceOS(extraction=None)`);
- adopted extraction mode is infrastructure capability, not adopted
  production behavior — no extraction controller is canonical;
- `ExperienceManager` remains lifecycle-policy authority;
  `ExperienceEngine._apply_memory_actions` remains the sole
  durable-mutation boundary;
- historical evidence frozen and reproducible (regenerated
  grounded-extraction digests match committed exactly).

Baseline variance: none. The prompt narrative referenced a
`report-phase12` directory; the actual Phase 12 evidence is committed
under feature-named directories (`grounded-extraction`,
`grounded-extraction-ablation`, `report-grounded-extraction`), which is
the correct, policy-compliant location. This is a naming observation,
not a variance in evidence.

These are the verified starting conditions, not measured transition
results. No transition result exists yet.

---

## 3. Transition Task Boundary

Input to a transition verification (planned; bounded by existing
controller conventions):

- a source statement (bounded user text);
- grounded source evidence when applicable
  (`ProposedMemoryCandidate` + `EvidenceSpan`, already validated by the
  grounded-candidate validator);
- the current active memories for the user
  (`MemoryStore.active_for_user`);
- relevant inactive lineage where needed (superseded records only, via
  the existing `wants_inactive_candidates` interface — forgotten
  records are never surfaced);
- memory kind (`preference` / `fact` / `instruction`), scope,
  qualifiers, and provenance.

Output: exactly one justified transition classification, or an
abstention. The classification vocabulary (concepts frozen; surface
strings mapped to repository conventions where noted):

| Contract concept | Meaning | Repository mapping |
|---|---|---|
| `create_new` | a new durable memory with no active lifecycle identity match | `MemoryAction(action="create")` |
| `duplicate_noop` | exact duplicate of an active memory; no new memory | rejected as `duplicate_of_active` / `duplicate_of_planned` |
| `semantic_duplicate_noop` | same durable meaning, different wording; no new memory | new: semantic-identity no-op |
| `supersede_existing` | replace an active current value for the same identity | `MemoryAction(action="supersede")` + replacement `create` with `replaces` |
| `scoped_coexistence` | different supported scope; both memories stay active | `create_new` with no supersession |
| `forget_existing` | affirmative forget directive targeting an active memory | `MemoryAction(action="forget")` |
| `reject_forget_directive_as_creation` | a forget clause must never become a positive create | no create emitted from the forget span |
| `reject_unsupported` | value/scope not supported by grounded evidence | abstain / reject |
| `reject_ambiguous` | target or meaning ambiguous | fail closed / shadow-only |
| `reject_temporary` | bounded/one-time choice without durable intent | abstain / reject |
| `reject_question` | interrogative, not an assertion | abstain / reject |
| `reject_hypothetical` | conditional/imagined statement | abstain / reject |
| `reject_unrelated` | candidate shares no lifecycle identity with a target | no supersession/deactivation |
| `shadow_only` | verification recorded, no canonical effect | diagnostics only |

These map onto the existing interface-only controller vocabularies,
which the initiative extends rather than replaces:

- `experienceos/controllers/transition.py`:
  `TRANSITION_RECOMMENDATIONS = ("approve", "reject", "abstain")`,
  `TRANSITION_TYPES = ("create", "supersede", "forget")`;
- `experienceos/controllers/update.py`:
  `UPDATE_RELATIONSHIPS = ("no_relation", "duplicate", "reinforce",
  "supersede", "correct", "merge_candidate", "abstain")`;
- `experienceos/controllers/forget.py`:
  `("no_forget_intent", "forget_candidate", "ambiguous", "abstain")`.

Concept and scoring boundaries in this contract are stable; surface
names may be normalized to these controller vocabularies during
implementation.

---

## 4. Authority Boundary (non-negotiable)

- Transition verifiers **propose or validate only**; verification is a
  **non-mutating** operation.
- Transition controllers do not mutate `MemoryStore` directly.
- Transition controllers do not call durable create, update,
  supersede, or forget methods directly (`store.add`,
  `store.supersede`, `store.forget` are engine-only).
- Transition controllers do not bypass `ExperienceManager`
  (lifecycle-policy authority: proposal validation, contradiction
  resolution, confidence gating, whole-batch fallback).
- Transition controllers do not bypass `ExperienceEngine`
  (`_reject_reason` admission + `_apply_memory_actions` — the sole
  mutation boundary).
- Transition controllers do not bypass grounding validation
  (`grounded_candidate_validator` v1).
- Transition controllers do not bypass lifecycle validation
  (`target_not_active`, `duplicate_of_active`, `duplicate_of_planned`).
- Transition controllers do not bypass adoption authorization (an
  explicit `AdoptionAuthorization`-style object; never synthesized in
  the UI or by evidence).
- Transition controllers do not bypass context budgets.
- Ambiguous transitions **fail closed** (reject or shadow-only).
- Forgotten memories cannot be reactivated by a transition controller
  (`MemoryStore` has no un-forget path; only `supersede`/`forget` flip
  status).
- Superseded memories remain available for **audit lineage** (kept as
  visible history, never re-injected into context).
- `ExperienceManager` remains lifecycle-policy authority.
- `ExperienceEngine` remains the sole durable-mutation authority.
- No second durable mutation path is created. An authorized adopted
  transition action is merged into the same `valid_actions` list the
  engine already validates and applies — mirroring the
  extraction-integration seam.

---

## 5. Reserved System IDs

Reserved (feature-based; a reserved ID implies neither implementation
nor adoption). None of these is registered in
`benchmarks/contract/system.py` yet; the transition benchmark will
define its own registry, as the grounded-extraction benchmark did.

| System ID | Meaning |
|---|---|
| `experienceos_hybrid_full_v2_reference` | canonical reference (reused unchanged — the comparison anchor for before/after state) |
| `experienceos_transition_shadow_v1` | transition verification, shadow-only — diagnostics, no canonical effect |
| `experienceos_transition_candidate_v1` | proposed transitions evaluated for lifecycle eligibility, no persistence |
| `experienceos_transition_rules_v1` | deterministic transition intelligence (the adoption candidate) |
| `experienceos_transition_adopted_v1` | may exist only if the §13 gates pass and authorization is explicit |
| `experienceos_transition_learned_shadow_v1` | optional learned verifier, shadow-only, non-canonical unless separately proven |
| `experienceos_transition_qwen_ceiling_v1` | optional live-Qwen ceiling, credential-gated, non-canonical unless separately proven |

A changed behavior requires a new ID; a historical ID is never reused
for different behavior.

---

## 6. Artifact Boundaries

Reserved feature-based paths for future work (Planned):

- `benchmarks/annotations/transition-verification/` — additive
  transition annotations keyed to stable frozen case IDs (never mixed
  with development fixtures);
- `benchmarks/results/committed/transition-verification/` — the
  external/downstream evidence directory;
- `benchmarks/results/committed/transition-ablation/` — the lifecycle
  transition runs and ablations;
- `benchmarks/results/committed/report-transition-verification/` —
  digest-locked report data, comparison tables, adoption-gate
  evaluation;
- `docs/transition_verification_report.md` — the human-readable report.

Those directories should eventually contain (following the established
grounded-extraction artifact conventions): per-case JSONL; aggregate
JSON; **before-state snapshots** and **after-state summaries**;
transition diagnostics; a comparison CSV or Markdown; adoption-gate
evaluation JSON; a human-readable report; and per-file sha256 manifests
plus a latency-excluded `normalized_result_digest` with overwrite
protection, exactly as `benchmarks/grounded_extraction/artifacts.py`
already does.

**This contract creates only this document.** No annotation, result,
report, manifest, placeholder, or code artifact is created here; those
belong to later workstreams.

---

## 7. Semantic Memory Identity

A memory identity is a structured comparison over:

- subject (whose/what the memory is about);
- attribute (which property);
- value (the asserted content);
- scope (the supported context: e.g. short work trips vs long
  international flights, work vs personal, one workflow domain vs
  another);
- qualifiers (modality, frequency, conditions);
- temporal validity (current vs historical; bounded vs durable);
- provenance (`user_asserted` and the confirmable set only);
- kind (`preference` / `fact` / `instruction`);
- source evidence (the grounded span);
- normalized text (`_normalized_text`: lowercased alphanumeric tokens).

Existing update selection is **key/domain-driven, not similarity-based**
(`preference_domain` over seat/flight_time/hotel terms; `update_key`
yields stable keys like `fact:home_airport`, `fact:work_location`,
`instruction:response_style`). Semantic identity generalizes this;
lexical similarity alone is never sufficient (§9).

Categories:

- **Exact duplicate** — same normalized durable meaning and compatible
  metadata as an existing active memory. (Currently rejected as
  `duplicate_of_active` / `duplicate_of_planned`.)
- **Semantic duplicate** — different wording, but same subject,
  attribute, value, scope, temporal validity, and durable intent as an
  existing active memory. (Currently **not** detected — the gap this
  initiative measures.)
- **Compatible scoped coexistence** — shared general subject/attribute
  but meaningfully different supported scope/qualifiers/context; both
  remain active without contradiction.
- **Incompatible current-state update** — a newly supported current
  durable value conflicts with an existing active current value for the
  same subject, attribute, and compatible scope.
- **Unrelated memory** — no shared lifecycle identity with the
  potential target; must not supersede or deactivate it.
- **Temporary exception** — a bounded one-time or temporary choice;
  must not overwrite a durable preference unless durable intent is
  explicit.
- **Historical statement** — describes a prior state; must not replace
  a current active memory unless the source explicitly establishes a
  new current state.

Ambiguous identity comparisons **fail closed** or remain shadow-only.

---

## 8. Supersession Contract

Valid supersession requires all of:

- the old target exists;
- the old target is `active`;
- the target matches the relevant semantic identity;
- the new value conflicts with the current value within a compatible
  scope;
- the source supports current durable replacement;
- unrelated and compatible scoped memories remain unchanged;
- the old memory is marked `superseded`, not deleted
  (`store.supersede`, which records `superseded_by`, `superseded_at`,
  `superseded_reason` in metadata);
- the replacement memory retains audit lineage to the superseded
  memory (`replaces` + `update_reason` metadata, `superseded_by` link);
- the new memory is independently grounded or derived from validated
  grounded evidence.

Invalid supersession (must be rejected or shadow-only): inactive
targets; unrelated targets; scope mismatch; historical-only statements;
temporary exceptions; questions; hypotheticals; unsupported values;
unsupported inferred scope; ambiguous target selection.

---

## 9. Scoped-Coexistence Contract

Scoped coexistence is **correct** when memories differ by supported
durable scope, e.g. short work trips vs long international trips; work vs
personal context; one tool/workflow domain vs another; current
preference vs an accurately represented historical record.

Lexical similarity alone is insufficient to supersede a memory. Scoped
coexistence **fails** when a valid scoped memory is incorrectly
deactivated, merged, or replaced. A reduced duplicate count achieved by
destroying a legitimately distinct scoped memory is a regression, not an
improvement (§12).

---

## 10. Forget-Directive Contract

Distinguish:

- **affirmative forget directive** ("Forget that I prefer X");
- **negative forget directive** ("Don't forget X");
- **forget question** ("Should I forget X?");
- **memory-inspection question** ("What do you remember about X?");
- **hypothetical forget** ("If I forgot X…");
- **broad or bulk forget request** ("Delete everything");
- **ambiguous forget target**.

Requirements (consistent with the existing layered forget handling —
rule `_FORGET_PATTERNS`, the temporal `forget_resolver`,
`ForgetIntentDetector`/`ForgetTargetResolver` in `memory/forget.py`, and
the `ForgetIntentController`):

- affirmative forget directives are **blocked from positive creation**
  (the forget span is stripped so it never doubles as a create);
- negative forget directives produce **no** forget mutation;
- questions remain non-mutating;
- hypothetical forgets remain non-mutating;
- forget proposals target only `active` memories;
- ambiguous target resolution rejects or remains shadow-only;
- unsupported broad deletion fails closed under existing product policy
  (bounded `MAX_TARGETS`, minimum score/margin);
- forgotten memories remain excluded from active retrieval and context.

---

## 11. Before-State and After-State Contract

Minimum **before-state** snapshot (per case): active memory IDs; kinds;
normalized values; scopes and qualifiers; temporal status; provenance
where relevant; and related superseded/forgotten lineage where required
for verification.

**After-state** expectation: which memories remain active; which become
superseded; which become forgotten; which are created; which remain
unchanged; the resulting semantic-duplicate count; lineage
relationships; and the canonical-effect status.

Verification compares the expected transition against **both** the
before-state and the after-state — a transition is correct only if the
resulting active set, lineage, and duplicate count all match the oracle,
not merely the single emitted action.

---

## 12. Metric Definitions

Conventions (inherited from `docs/grounded_extraction_contract.md` §14
and the `benchmarks/grounded_extraction/scoring.py` implementation):
every ratio ships as numerator/denominator plus rate; zero denominators
are **undefined** (never 0% or 100%); unscorable/abstained cases are
excluded from scored denominators and counted separately; latency is
wall-clock `time.perf_counter()`, reported count/mean/median/p95 (p95
only when n ≥ 20) and always excluded from artifact digests. Duplicates
and development fixtures never enter the scored transition denominators
silently.

Universal interpretation rules (frozen):

- a rejected bad transition is **not** state corruption;
- a correct shadow transition is **not** a canonical improvement;
- a reduced duplicate count achieved by losing scoped memories is
  **not** an improvement;
- additional supersessions are **not** an improvement when targets are
  wrong;
- development-only fixtures must never be mixed silently with
  benchmark-scored cases;
- unavailable optional systems are reported as `unavailable`, never
  assigned synthetic scores.

For every metric: `gate` = adoption gate (§13); `nonreg` =
non-regression gate; `diag` = diagnostic; `ext` = optional external.

### 12.1 Proposal and verification quality

- **transition proposal rate** = interactions with a positive
  transition proposal / evaluated interactions. `diag`.
- **valid transition proposal rate** = proposals passing the full
  validation pipeline (structural + grounding + lifecycle-admission
  shape) / positive proposals. Higher better. `diag`.
- **transition precision** = correct transitions (right type, right
  target, right after-state) / positive transition proposals. Higher
  better. `gate` (via §13.3).
- **transition recall** = oracle-positive transition interactions with
  an acceptable proposal / oracle-positive transition interactions.
  Higher better. `gate` (via §13.2).
- **transition F1** = harmonic mean of precision and recall; undefined
  when either denominator is zero. `diag`.
- **fallback rate** = learned attempts requiring deterministic fallback
  (dependency unavailable, malformed output, timeout, validation
  failure, controller error) / learned attempts; configured shadow-only
  or intentionally-disabled paths are recorded as modes, not fallbacks.
  Lower better. `diag`.
- **shadow/adoption effect** = per-system canonical-effect count;
  shadow and candidate must be 0. `nonreg`.
- **latency** = per-stage and total transition-verification overhead vs
  the reference, digest-excluded. `gate` (§13.15).

### 12.2 Duplicate handling

- **duplicate-noop accuracy** = exact-duplicate cases correctly
  producing no new memory / exact-duplicate oracle cases. Higher
  better. `nonreg`.
- **semantic-duplicate prevention** = semantic-duplicate oracle cases
  correctly producing no new active memory / semantic-duplicate oracle
  cases. Higher better. `gate` (§13.1).
- **semantic duplicate active-memory count** = number of active memory
  pairs sharing one semantic identity, after the transition, across the
  scored set. Lower better; the primary §13.1 gate metric.

### 12.3 Update and supersession

- **supersession accuracy** = correct supersessions (right target,
  valid per §8) / proposed supersessions. Higher better. `gate`
  (§13.2/§13.3).
- **update-target accuracy** = correct target selections / update
  interactions with a target. Higher better. `gate` (§13.3).
- **old-value deactivation** = incompatible current-state updates where
  the old value became `superseded` / such oracle cases. Higher better.
  `nonreg`.
- **current-value preservation** = interactions where the correct
  current value remains active / such oracle cases. Higher better.
  `nonreg`.
- **stale active-memory leakage** = active memories that should have
  been superseded but remain active / superseding-oracle cases. Lower
  better. `gate` (§13.2).
- **lineage correctness** = superseded memories carrying correct
  `superseded_by`/`replaces` lineage / supersessions. Higher better.
  `gate` (§13.11).

### 12.4 Preservation

- **scoped-coexistence preservation** = scoped-coexistence oracle cases
  where both memories remain correctly active / such cases. Higher
  better. `gate` (§13.4).
- **unrelated-memory preservation** = unrelated memories left unchanged
  / unrelated-target oracle cases. Higher better. `gate` (§13.5).
- **before-state coverage** = cases whose required before-state
  snapshot was fully captured / scored cases. Higher better. `diag`.
- **after-state correctness** = cases whose full after-state (active
  set + lineage + duplicate count) matches the oracle / scored cases.
  Higher better. `gate` (§13, composite).

### 12.5 Forget behavior

- **forget-directive detection** = forget-directive oracle cases
  correctly identified as forget intent / forget-directive cases.
  Higher better. `nonreg`.
- **forget-directive creation-false-positive rate** = forget-directive
  cases that wrongly produced a positive create / forget-directive
  cases. Lower better; must reach 0 for adoption. `gate` (§13.6).
- **correct forget target** = correct active targets / affirmative
  forget cases with a target. Higher better. `gate` (§13.7).
- **ambiguous forget rejection** = ambiguous forget cases correctly
  rejected/shadowed / ambiguous forget cases. Higher better. `nonreg`.
- **forgotten exclusion** = forgotten memories absent from active
  retrieval/context / checks. Must be 100%. `gate` (§13.9).
- **negative-forget no-op accuracy** = "don't forget" cases producing
  no forget mutation / negative-forget cases. Higher better. `nonreg`.
- **forget-question no-op accuracy** = forget/inspection questions
  producing no mutation / such cases. Higher better. `nonreg`.

### 12.6 Rejection and safety (all must hold for any safe system)

- **unsupported transition rejection** = unsupported-value cases
  correctly rejected / unsupported cases. Higher better. `nonreg`.
- **ambiguous transition rejection** = ambiguous cases correctly failing
  closed / ambiguous cases. Higher better. `gate` (§13.12).
- **state corruption** = invalid persisted lifecycle outcomes. Must be
  0. `gate` (§13.8).
- **inactive contamination** = inactive memories injected into context.
  Must be 0. `gate` (§13.9/§13.10).
- **forgotten-memory leakage** = forgotten memories re-injected or
  reactivated. Must be 0. `gate` (§13.9).
- **superseded-memory leakage** = superseded current-mode memories
  re-injected. Must be 0. `gate` (§13.10).
- **unauthorized application** = adopted actions applied without a
  matching authorization. Must be 0. `gate` (§13.19).
- **direct mutation violations** = mutations outside
  `_apply_memory_actions`. Must be 0. `gate` (§13.20).

### 12.7 Downstream effects (existing definitions, unchanged)

- **durable creation recall / precision** — reported for context;
  creation improvement is not the objective. `diag`.
- **downstream candidate rate**, **downstream selection rate**,
  **Recall@K**, **MRR**, **context tokens** — using the existing
  canonical retrieval definitions (never redefined incompatibly).
  `nonreg` (§13.13/§13.14).

---

## 13. Adoption Gates

A transition path may affect canonical behavior only when **all**
applicable gates pass on the frozen transition benchmark vs
`experienceos_hybrid_full_v2_reference`. Materiality rule (reused from
the retrieval/extraction contracts): a change of more than 1 case on a
frozen numerator, or more than 2% relative on a continuous metric, is
material; given small frozen denominators, every gate decision also
requires transparent paired case-level review in the report.

1. **Semantic duplicate active-memory count decreases materially** —
   fewer semantic-duplicate active pairs than the reference (target:
   the two reference semantic duplicates → 0), with no scoped memory
   lost. Threshold: strictly fewer, and 0 required for the strongest
   claim.
2. **Supersession accuracy improves materially OR stale active-memory
   leakage decreases materially** — at least one, by ≥1 case or ≥2%
   relative, with no regression in the other.
3. **Update-target accuracy is defensible** — regresses by at most 1
   case vs the reference; every wrong target reviewed case-by-case.
4. **Scoped coexistence is preserved** — scoped-coexistence
   preservation does not regress (0 scoped memories wrongly
   deactivated/merged/replaced).
5. **Unrelated-memory preservation remains intact** — 0 unrelated
   memories changed.
6. **Forget-directive creation false positives decrease** — the
   forget-directive creation-false-positive count is strictly lower
   than the reference and reaches 0 for adoption.
7. **Correct forget behavior does not regress** — forget-directive
   detection, correct-target, and no-op accuracies do not regress.
8. **State corruption remains 0.**
9. **Forgotten memories remain excluded** — forgotten leakage 0,
   forgotten exclusion 100%.
10. **Superseded current-mode memories remain excluded** — superseded
    leakage 0.
11. **Supersession lineage is preserved** — lineage correctness 100%
    for emitted supersessions.
12. **Ambiguous transitions fail closed** — ambiguous rejection does
    not regress; no ambiguous target is guessed into a mutation.
13. **Downstream retrieval and selection do not materially regress** —
    selection rate and Recall@K/MRR within materiality vs the reference.
14. **Context token use does not materially regress** — within
    materiality vs the reference.
15. **Latency remains acceptable for the demo** — deterministic
    transition verification adds ≤ 5 ms mean per interaction over the
    reference (same generous ceiling as the extraction contract),
    measured and digest-excluded.
16. **Diagnostics explain every transition decision** — the §11
    before/after fields and a decision reason are present per case.
17. **Default tests remain offline and deterministic.**
18. **Optional learned paths skip cleanly when unavailable.**
19. **Authorization matches the exact controller, mode, source,
    transition type, and verified proposal** — an
    `AdoptionAuthorization`-style object gates adopted mode; a mismatch
    fails closed.
20. **No second durable mutation path exists** — adopted actions flow
    through the engine's existing `valid_actions` + `_apply_memory_actions`.

Deferred numeric thresholds and the decision procedure. Where a numeric
threshold cannot yet be justified because the reference values are not
yet measured (gates 1, 2, 3, 6, 13, 14), the deferred procedure that the
final adoption-decision workstream must follow is: (a) measure the
reference value on the committed transition benchmark first; (b) apply
the materiality rule (>1 case or >2% relative) against that measured
reference; (c) record the exact numerator/denominator for both systems;
(d) write an explicit human-readable justification per gate — a gate is
never silently passed. Gates 4, 5, 8, 9, 10, 11, 15, 17, 18, 19, 20 have
fixed thresholds (0 or 100% or ≤5 ms) that do not require reference
measurement.

Learned transition verification may become canonical only if it beats
`experienceos_transition_rules_v1` on the predeclared quality metrics
(semantic-duplicate prevention, supersession accuracy, update-target
accuracy, forget separation) **without** weakening any safety or
preservation gate. Otherwise it remains shadow-only, candidate-only, or
deferred. Deterministic fallback remains permanently available.

---

## 14. Stop Conditions

The transition adoption path remains `disabled`, candidate-only, or
shadow-only if it: incorrectly supersedes scoped memories; loses
unrelated memories; increases state corruption; increases forgotten
leakage; increases inactive contamination; increases stale leakage;
treats forget directives as creation; treats questions as mutations;
treats temporary exceptions as durable updates; creates semantic
duplicates; cannot explain decisions; requires heavy dependencies for
default tests; requires model downloads for default tests; destabilizes
the dashboard; bypasses manager or engine authority; cannot be
reproduced deterministically; weakens lineage; or guesses ambiguous
targets.

A failed adoption experiment still yields a successful outcome when it
produces honest evidence, keeps canonical behavior safe, strengthens the
deterministic path or the contract, and adopts no unsafe path.

---

## 15. Validation Contract

Required offline validation (every transition workstream and closure):

```bash
python -m compileall experienceos demo benchmarks
python -m pytest
PYTHON=.venv/bin/python ./scripts/validate_demo.sh
```

Plus the inherited historical-preservation and retrieval-evidence
validators (the eleven `scripts/run_benchmarks.sh` commands recorded in
`docs/grounded_extraction_contract.md` §19) and the three
grounded-extraction validators — all must continue to pass unchanged.

Future transition-verification validation obligations: a transition
benchmark smoke; the full or documented transition benchmark subset;
report regeneration via its established command only; artifact digest
verification for every new committed directory; two-run deterministic
digest equality; dashboard AppTest/smoke when dashboard code changes;
optional learned-controller smoke with clean-skip behavior; optional
Qwen ceiling smoke with clean credential-gated skip behavior; repository
hygiene verification; and historical artifact integrity verification.
The optional-local-model and optional-live-Qwen classes must never be
required for default tests.

---

## 16. Closure Requirements

The final transition closure/transfer report (returned through the
governing workflow, not committed) must contain, in order:

1. Decision
2. Executive Summary
3. Starting Baseline
4. Final Repository State
5. Commit Inventory
6. Architecture Changes Delivered
7. Semantic Memory Identity
8. Transition Proposal and Verification
9. Update and Supersession Intelligence
10. Forget-Directive Separation
11. Integration Modes and Adoption Controls
12. Dashboard and Diagnostics
13. Benchmark Results
14. Transition Improvements
15. Duplicate and Semantic-Duplicate Results
16. Supersession and Update Results
17. Forget Results
18. Retrieval and Downstream Effects
19. Regressions or Trade-Offs
20. Latency and CPU Feasibility
21. Lifecycle Safety Verification
22. Supported Claims
23. Claims Not Supported
24. Remaining Limitations
25. Recommended Next Workstream
26. Final Transfer Statement

---

## 17. Known Contract Limitations

- Reference values for the transition benchmark are not yet measured;
  the materiality thresholds in gates 1–3, 6, 13, 14 are defined as a
  decision procedure (§13) rather than fixed numbers until then.
- Semantic identity comparison is defined structurally here but not yet
  implemented; the initiative must decide it deterministically (no
  learned embeddings in default tests).
- The frozen lifecycle scenarios carry supersession/duplicate oracles
  but not full semantic-scope oracles; additive annotations (§6) must
  supply them without editing frozen records.
- The external subset remains classification-only for extraction-style
  scoring; transition scoring is primarily on the lifecycle dataset.

---

## 18. Acceptance

This contract is the stable, auditable standard for deciding whether
grounded experience should create, replace, preserve, forget, or reject
memory state without weakening lifecycle safety. It creates only this
document; it changes no runtime behavior, no default, no oracle, and no
controller classification. No transition controller is canonical. The
default extraction integration mode remains `disabled`. Later
transition workstreams are governed by the boundaries, metrics, gates,
and stop conditions defined here and may not redefine success after
seeing results.
