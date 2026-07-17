# Canonical Action Replacement Contract

**Status: contract complete — this document governs all subsequent
canonical action-replacement work.** No implementation is authorized by
this document; it fixes scope, authority, metrics, gates, artifact
boundaries, and stop conditions so that later work cannot silently
redefine them. Where this contract and any later working note disagree,
the safety boundaries here win.

Everything in "Verified" sections was checked against the live
repository at commit `a09fce0` on 2026-07-16. Everything in "Planned"
sections is design intent, not yet implemented.

Naming note (repository policy). Per `CLAUDE.md`, all NEW committed
content — files, directories, system IDs, headings, identifiers,
decision tokens — uses feature-based names (`action-replacement`,
`deduplicated-transition`, …) and never development-stage vocabulary.
Existing committed names that already contain stage vocabulary (e.g.
`report-transition-verification/`, `docs/phase11_contract.md`,
`benchmarks/results/committed/phase11-semantic-retrieval/`) are frozen
history and are cross-referenced unchanged. Where an internal working
specification suggested stage-based names for new artifacts or decision
tokens, this contract substitutes the feature-based equivalent and
records the mapping; the feature-based name is the binding one.

---

## 1. Purpose

The committed transition-verification evidence
(`benchmarks/results/committed/report-transition-verification/`,
`docs/transition_verification_closure.md`) established that transition
proposals, target resolution, verification, and exact authorization can
all be correct while the **applied** action list is still wrong. On 28
historical scored cases the transition path classified 28/28 transitions
correctly and resolved 11/11 update targets with 0 wrong, yet under
isolated benchmark-only adoption semantic-duplicate active pairs rose
**0 → 10**. Adoption-gate 1 (`Semantic duplicate active-memory count
decreases materially`) failed on exactly that, and a failed quality gate
blocks adoption even though all nine blocking safety gates passed. The
path is therefore classified `TRANSITION_PATH_CANDIDATE_ONLY` with no
canonical controller.

The measured cause is add-not-replace composition:

- the canonical planner emits a `create` for the new memory;
- the transition path emits a verified `supersede(old)` **plus** another
  `create(new)` for the same replacement;
- the transition-derived actions are **appended** to the canonical
  action list instead of **replacing** the conflicting planner `create`;
- both `create`s persist;
- a semantic-duplicate active pair appears.

This work is a **narrow correction** to that defect. It does not build
new transition intelligence, does not redesign identity, taxonomy,
target resolution, forget classification, or the verifier, and does not
adopt the transition path by documentation. It introduces **governed
canonical action-replacement semantics at the action-list seam**: when —
and only when — a verified transition replacement uniquely and safely
matches a planner `create`, the planner `create` is suppressed and the
transition `supersede + create` take its place, so the replacement
`create` appears in the canonical action list exactly once. Every other
case falls back to today's behavior.

---

## 2. Verified Starting Baseline (2026-07-16)

Facts verified fresh in this audit (distinct from inherited evidence in
§3):

| Fact | Value |
|---|---|
| Branch | `main` |
| Local `HEAD` | `a09fce0406c02909a09f29022072f18fa64ae386` |
| Remote-tracking `origin/main` | `a09fce0` |
| Direct remote head (`git ls-remote origin refs/heads/main`) | `a09fce0` |
| Ancestry: `a09fce0` is ancestor of `HEAD` | yes |
| Ahead / behind vs `origin/main` | `0 / 0` |
| Working tree | clean |
| Full suite (`.venv/bin/python -m pytest`) | 2371 passed |
| Demo validation (`PYTHON=.venv/bin/python ./scripts/validate_demo.sh`) | passed; result digest `4f9a20b442c4e39688653bfa7e6962667909678409f7874ae29225ccb2e681b6` |
| Frozen-authority diff vs `a09fce0` | empty |

Baseline drift: none. Local, remote-tracking, and direct remote heads
agree at the accepted baseline; no unexplained commits exist beyond it.
The Python interpreter used throughout is `.venv/bin/python` (3.14.3),
because the environment `python3` lacks `pytest`; this substitution is
recorded wherever a command is given.

---

## 3. Inherited Evidence (measured previously; not re-verified here)

Treat the following as inherited measured results, each mapped to its
committed source. This document does not restate them as newly verified.

| Inherited result | Source of truth |
|---|---|
| Transition classification 28/28 | `report-transition-verification/headline_metrics.json` |
| Update targets 11/11, wrong targets 0 | `report-transition-verification/headline_metrics.json` |
| Forget targets 4/4 | `report-transition-verification/report_data.json` |
| Scoped lost 0, unrelated lost 0 | `report-transition-verification/report_data.json` |
| Stale active pairs 6 → 1 | `report-transition-verification/headline_metrics.json` |
| Reference duplicate pairs 0; isolated applied 10 | `report-transition-verification/headline_metrics.json` |
| Adversarial proposals rejected 121/121 | `benchmarks/results/committed/transition-verification/` |
| Verifier mutations 0; exact authorization tested | `benchmarks/results/committed/transition-verification/` |
| 20 adoption gates: 18 pass / 1 fail / 1 inconclusive | `report-transition-verification/gate_summary.json` |
| 9 blocking gates (4,5,8,9,10,11,12,19,20), all pass | `report-transition-verification/gate_summary.json` |
| Gate 1 FAIL (duplicate pairs); Gate 6 INCONCLUSIVE | `report-transition-verification/gate_summary.json` |
| Classification `TRANSITION_PATH_CANDIDATE_ONLY`; default disabled; no canonical controller | `gate_summary.json`, `docs/transition_verification_closure.md` |

If any repository evidence is later found to differ from this table, the
discrepancy is reported and the committed artifact — not this table —
is authoritative. Historical artifacts are not edited to match.

---

## 4. Settled Architecture (not reopened)

Not redesigned by this work: semantic memory identity, transition
taxonomy, target resolution, forget classification, verifier structure,
the authorization semantics already established, dashboard architecture,
and the frozen transition corpus. Retained authorities: `ExperienceManager`
holds lifecycle admission; `ExperienceEngine` remains the sole durable
mutation boundary; controllers propose only; verifiers verify only;
transition infrastructure is candidate-only and no controller is
canonical at the start of this work; default integration mode is
`disabled`. A later step may **extend** authorization binding to
replacement-plan data; this contract defines that requirement (§13) but
does not implement it.

---

## 5. Verified Action-Composition Seam (from code at `a09fce0`)

The single action list where canonical planner actions and
transition-derived actions first coexist is `valid_actions` inside the
engine. The merge is an **append**, and it happens in the engine, not in
the integration coordinator.

**Canonical planner action type.** `MemoryAction`,
`experienceos/memory/planner.py:288-299`, a frozen dataclass. Fields:
`action`, `kind`, `text`, `memory_id`, `replaces`, `reason`, `request`,
`metadata`. It carries **no** `id`, digest, `source_digest`, grounding,
`scope`, or `proposal_id`; those live on transition-side types. This
thinness is a fact the matcher (§7) must accommodate.

**Planner / manager production.** `MemoryPlanner.plan_memory_actions`,
`experienceos/memory/planner.py:305-383`, builds `list[MemoryAction]`;
the admission authority is `ExperienceManager.plan`,
`experienceos/policy/manager.py:90-112`, returning
`ExperienceManagerResult` (`manager.py:36-50`) with `.actions` and
parallel `.decisions`.

**Transition verifier output.** `VerifiedActionSpec`,
`experienceos/memory/transition_verification.py:493-511`, a frozen
dataclass **deliberately not** a `MemoryAction` (so a verification
result cannot be mistaken for something applicable). Fields: `action`,
`kind`, `text`, `target_id`, `replaces`, `local_ref`, `preconditions`,
`metadata`, `applied=False`. `verify` is at `transition_verification.py:708`.

**Integration coordinator — proposes only.**
`TransitionIntegrationCoordinator.evaluate`,
`experienceos/memory/transition_integration.py:691`; adopted branch
`:843-903`. It applies nothing: it returns a `TransitionIntegrationResult`
carrying `generated_actions` with `canonical_action_effect =
CanonicalActionEffect.ACTION_ADDED` and the explicit comment that the
engine decides admission and application. The five modes are
`TransitionIntegrationMode` at `transition_integration.py:48-55`
(`DISABLED` default, `SHADOW`, `CANDIDATE`, `VERIFY_ONLY`, `ADOPTED`).
The 20-field authorization is `TransitionAuthorization.binding()`,
`transition_integration.py:208-231`; there is no env-var authorization
path (`sdk.py:139`).

**The seam (add-not-replace).**
`ExperienceEngine._evaluate_transition`,
`experienceos/engine/experience_engine.py:425-456`. When mode is
`ADOPTED`, effect is `ACTION_ADDED`, `generated_actions` is non-empty,
and every generated action passes `_extraction_reject_reason`, the
engine executes:

```python
# experienceos/engine/experience_engine.py:450-452
for action in result.generated_actions:
    valid_actions.append(action)          # the add-not-replace seam
payload["canonical_action_effect"] = CanonicalActionEffect.APPLIED
```

`valid_actions` is the planner-derived admitted list created at
`experience_engine.py:158`, filtered per action by `_reject_reason`
(`:260-284`) / `_extraction_reject_reason` (`:286-307`), and passed
undivided to the sole mutation boundary
`ExperienceEngine._apply_memory_actions`
(`experience_engine.py:483`) at `experience_engine.py:240`. The grounded
extraction path appends into the same list at `experience_engine.py:364`.

**Call path.**

1. `ExperienceEngine.run_interaction` (`experience_engine.py:67`).
2. `ExperienceManager.plan(...)` → `result.actions` (manager-facing) —
   `experience_engine.py:131`.
3. Lifecycle filter → `valid_actions` (engine-facing admitted list) —
   `experience_engine.py:158-167`. **The planner `create(new)` is here.**
4. Extraction seam may append — `experience_engine.py:364`.
5. Transition seam: coordinator returns `generated_actions`
   (`supersede(old)`, `create(new)`); engine appends them —
   `experience_engine.py:450-451`. **Both `create`s now coexist.**
6. `_apply_memory_actions(valid_actions, …)` — the sole durable mutation
   — `experience_engine.py:240` → `:483`.

The candidate seam this work may change is the transition-append step
(5): before appending, a replacement plan may suppress the uniquely
matched planner `create(new)` from `valid_actions`, so that after the
append the replacement `create` appears exactly once. **Confirmed** by
code inspection: the append at `:451` is the merge point, the coordinator
mutates nothing, and `CanonicalActionEffect` already declares
`ACTION_REPLACED` and `ACTION_SUPPRESSED` (`transition_integration.py`)
though neither is exercised on the add path today. **To be characterized
in the seam-audit step** (§21): exact ordering guarantees within
`valid_actions`, how the planner `create` is identified without a stable
action id, and whether the plan is best computed in the coordinator
(propose) with the engine performing the list rewrite (apply).

---

## 6. Task Boundary

**May change:** replacement-intent matching between a verified transition
replacement and a planner `create`; explicit replacement planning;
governed rewrite of the canonical action list at the seam of §5;
replacement-specific authorization binding (§13); replacement
diagnostics; a deduplicated applied-state benchmark evaluation; and the
minimum dashboard visibility needed to explain a rewrite.

**May not redesign:** semantic identity; transition taxonomy; target
resolution; forget classification; the transition verifier architecture;
`ExperienceManager` authority; `ExperienceEngine` authority; durable
storage architecture; frozen benchmark corpora; and unrelated planner
behavior. No second mutation path may be introduced.

---

## 7. Authority Boundary (non-negotiable)

- Controllers **propose**.
- Verifiers **verify** (`VerifiedActionSpec.applied` is invariantly
  false).
- Replacement planners **plan** a rewrite; they produce a
  proposal/plan, never a durable effect.
- Authorization **permits one exact proposal and one exact rewrite**.
- `ExperienceManager` admits or rejects lifecycle actions.
- `ExperienceEngine._apply_memory_actions` remains the **sole** durable
  mutation boundary; the rewrite composes the list it consumes but does
  not itself mutate `MemoryStore`.
- Replacement components hold no store and expose no mutation method.
- Diagnostics produce **no** durable effect.
- Dashboard code cannot trigger a replacement merely by rendering.

---

## 8. Replacement Candidate — minimum information

A replacement candidate must carry at least:

- verified transition proposal id;
- transition type;
- source-statement or grounding digest;
- before-state digest;
- target memory id(s);
- replacement-created-memory digest;
- candidate planner-action digest;
- semantic-identity comparison (planner create vs replacement create);
- scope comparison;
- conflict reason;
- deterministic decision;
- diagnostics.

Fields the current architecture cannot yet supply are marked as
**introduced later**: `MemoryAction` (§5) carries no id, digest, or
proposal id, so a planner-action digest and a stable identity for the
matched action must be **computed at the seam** (a deterministic digest
over the planner action's semantic fields), not read from an existing
attribute. No new fuzzy inference layer is added; identity and scope
comparisons reuse the established semantic-identity projection.

---

## 9. Planner-Action Conflict — definition

A planner `create` conflicts with a verified transition replacement
**only when all** of the following hold, so that the two would otherwise
coexist as a semantic duplicate:

1. transition verification **accepted** the proposal;
2. the transition type is one that **requires replacement** (a
   supersession that emits a paired `supersede(old) + create(new)`);
3. the planner action is **create-like** (a `create`, not a supersede
   or forget);
4. grounding / source evidence is **compatible** (same triggering
   statement, by digest where available);
5. the replacement create and the planner create denote the **equivalent
   memory effect** — same projected semantic identity (subject /
   attribute / value / scope), compared by the established identity
   layer, not by a similarity score;
6. identity and scope are **compatible** (a scoped create never conflicts
   with a general one — that is valid coexistence, not a duplicate);
7. the match is **unique** — exactly one planner create matches;
8. no unrelated planner effect would be suppressed with it;
9. no valid scoped-coexistence create would be suppressed.

Exact comparisons: transition type, action kind, target ids, and any
digest-based evidence match must be **exact**. Semantic equivalence of
the two creates uses the **already-established** identity projection.
The phrase "sufficiently similar" is not admissible anywhere in the
matcher.

---

## 10. Replacement Rejection — fail closed

Replacement must fail closed (leave the planner action in place, append
nothing that would duplicate, or abstain entirely) when any of:

- no planner action matches;
- more than one planner action matches (ambiguous);
- required evidence is incomplete;
- source evidence materially differs;
- scope differs;
- the planner action carries unrelated effects that cannot be separated;
- the action cannot be suppressed independently;
- the rewrite would remove valid coexistence;
- transition verification failed;
- authorization is missing;
- authorization mismatches any bound field;
- before-state coverage is insufficient;
- the rewrite cannot be explained deterministically.

Fail-closed always degrades to the current, measured behavior. It never
degrades to a stronger effect.

---

## 11. Action Preservation — required

The rewrite must preserve:

- every unrelated canonical planner action;
- every valid scoped planner action;
- the planner fallback when transition processing abstains;
- the planner fallback when transition verification rejects;
- the planner fallback when replacement matching fails;
- the planner fallback when authorization is unavailable or invalid;
- action ordering where it is semantically relevant (the linked
  `supersede + create` remain all-or-nothing, as the current seam already
  guarantees at `experience_engine.py:448-451`);
- the manager's and engine's ability to reject.

Only the **uniquely matched** conflicting planner `create` may be
suppressed. Nothing else is ever removed.

---

## 12. Decision and Effect Vocabulary (planned)

Replacement decisions (names may follow repository conventions; the
semantic distinctions are fixed):

- `no_replacement_needed`
- `replacement_ready`
- `replacement_rejected_no_match`
- `replacement_rejected_ambiguous_match`
- `replacement_rejected_scope_conflict`
- `replacement_rejected_unrelated_suppression`
- `replacement_rejected_unauthorized`
- `replacement_rejected_verification_failed`
- `replacement_rejected_unsupported_transition`

Canonical-effect states. These extend the existing
`CanonicalActionEffect` enum (`transition_integration.py`), which
**already declares** `ACTION_ADDED`, `ACTION_REPLACED`, and
`ACTION_SUPPRESSED`; the replacement work exercises the latter two,
which are presently defined but unused on the add path:

- `action_none` → existing `UNCHANGED`;
- `action_added` → existing `ACTION_ADDED` (fallback, no conflict);
- `action_replaced` → existing `ACTION_REPLACED` (planner create
  suppressed, transition pair inserted);
- `action_replacement_rejected` → a rejected rewrite that falls back to
  add or to planner-only;
- `action_replacement_shadow` → shadow-mode rewrite, observed only;
- `action_replacement_candidate` → candidate-mode rewrite, computed but
  not applied.

Exact enum member names are a later decision; the six semantic states
above are binding.

---

## 13. Mode Semantics

At the start of this work:

- **disabled** — default; nothing in the replacement path runs.
- **shadow** — matcher and planner run and are recorded; the canonical
  action list is untouched; no durable effect.
- **candidate** — the full replacement plan is computed, including an
  inert rewrite; nothing is inserted or suppressed durably.
- **verify_only** — verification and matching run; the canonical action
  list is **not** rewritten.
- **adopted** — the only mode that can rewrite and apply, and only with
  an exact authorization (§14). Not offered by the dashboard; not
  reachable from a mode string alone.

No replacement becomes canonical by documentation. Candidate and shadow
outputs cannot mutate durable state. Verify-only cannot rewrite the list.
Adopted requires exact authorization. Transition adoption remains
unauthorized until the benchmark gates (§16) pass.

---

## 14. Authorization-Binding Requirements (planned)

The adopted rewrite must be capable of binding, in addition to the
existing 20-field transition authorization:

- verified proposal digest;
- replacement-plan digest;
- replaced-action digest;
- original action-list digest;
- rewritten action-list digest;
- preserved action digests;
- removed action digests;
- inserted action digests;
- replacement decision type;
- before-state digest;
- target memory id(s).

A later step decides the **minimal exact field set** consistent with the
current `TransitionAuthorization.binding()` architecture
(`transition_integration.py:208-231`) and adds a mismatch test for
**every** newly bound field. Any mismatch fails closed and names the
field. This contract does not implement the extension.

---

## 15. Metric Definitions

Conventions (reused from the transition and grounded-extraction
contracts): every ratio ships as numerator/denominator plus rate; zero
denominators are undefined, never 0% or 100%; non-applicable and
unscorable cases are excluded from denominators and counted separately;
latency is wall-clock `time.perf_counter()`, warm process, reported as
count/mean/median/p95 (p95 only when n ≥ 20) and always excluded from
artifact digests. Metrics already defined by the transition contract are
referenced and preserved unchanged; nothing here redefines a historical
metric in a way that would change a committed result.

**Replacement mechanics.**
- *replacement proposal rate* = interactions with a replacement proposal
  / evaluated interactions.
- *replacement candidate count* = candidates formed (§8), total.
- *replacement match rate* = candidates with ≥1 matching planner create
  / candidates.
- *unique replacement match rate* = candidates with exactly one match /
  candidates.
- *ambiguous replacement count* = candidates with >1 match.
- *missing replacement count* = replacement-requiring proposals with 0
  match.
- *incorrect replacement count* = rewrites whose match was wrong under
  oracle review.
- *`action_replaced` count* / *`action_added` count* /
  *`action_suppressed` count* = interactions ending in each canonical
  effect.

**Preservation.**
- *unrelated action preservation* = unrelated planner actions surviving
  / unrelated planner actions present (target 1.0).
- *scoped action preservation* = valid scoped creates surviving / valid
  scoped creates present (target 1.0).
- *planner fallback preservation* = fallbacks where the planner action
  survived intact / fallback cases (target 1.0).
- *action ordering preservation* = interactions whose required ordering
  held / interactions with an order requirement (target 1.0).

**Applied-state quality** (definitions inherited from the transition
contract; computed on the deduplicated applied path).
- *duplicate pairs*; *semantic duplicate active-memory count*; *stale
  active pairs*; *target deactivation*; *old-value deactivation*;
  *current-value preservation*; *wrong targets*; *scoped memories lost*;
  *unrelated memories lost*; *lineage correctness*.

**Governance and safety.**
- *manager rejection count*; *engine rejection count*; *unauthorized
  replacement rejection*; *authorization mismatch rejection*; *state
  corruption*; *inactive contamination*; *forgotten leakage*;
  *superseded current-mode leakage*; *forget-as-creation false
  positives*; *direct store mutation count* (must be 0); *second
  mutation path count* (must be 0).

**Downstream.** *downstream selection*; *context tokens*; *latency* —
each as defined by the transition contract, materiality by the same
rule.

Materiality rule (reused): on a frozen numerator, a change of more than
1 case is material; on a continuous metric, more than 2% relative is
material; given small frozen denominators, every gate decision also
requires paired case-level review in the report.

---

## 16. Adoption Gates

The transition contract defines a **20-gate** framework (numbered 1–20,
9 blocking: 4, 5, 8, 9, 10, 11, 12, 19, 20). This work does **not**
renumber or replace it. The following acceptance conditions map onto
that framework; conditions with no existing gate are **additional
acceptance conditions** for the deduplicated path, not renumbered gates.

Mapped to existing gates (must hold on the frozen scored evidence vs
`experienceos_hybrid_full_v2_reference`):

1. **Gate 1 no longer fails** — semantic duplicate active-memory count
   decreases materially (this is the whole point).
2. Semantic duplicate active-memory count does not regress vs reference
   (Gate 1 family).
3. Duplicate pairs materially improve vs the isolated applied transition
   path measured previously (0 → 10 must become materially better).
4. Stale-pair improvement remains materially better than reference
   (Gate 2).
5. Target accuracy remains 11/11 or better (Gate 3).
6. Wrong targets remain 0 (Gate 3 family).
7. Scoped memories lost remains 0 (**Gate 4, blocking**).
8. Unrelated memories lost remains 0 (**Gate 5, blocking**).
9. Lineage remains correct (**Gate 11, blocking**).
10. Forget-as-creation does not regress (Gate 7; Gate 6 evidence
    inconclusive — see rule below).
11. Unauthorized replacement applications remain 0 (**Gate 19,
    blocking**).
12. Missing authorization rejects (**Gate 19 family, blocking**).
13. Authorization mismatches reject (**Gate 19 family, blocking**).
14. No direct store mutation occurs (**Gate 20 family, blocking**).
15. No second mutation path is introduced (**Gate 20, blocking**).
16. Manager and engine remain authoritative (**Gates 8/20 family,
    blocking**).
17. Downstream selection does not materially regress (Gate 13).
18. Context tokens do not materially regress (Gate 14).
19. Latency remains acceptable (Gate 15).
20. Diagnostics explain every replacement or rejection (Gate 16).
21. Historical evidence remains frozen (Gate 17 family).
22. Default tests remain offline and deterministic (Gate 17).

Additional acceptance conditions specific to the rewrite (new, not
renumbered): unique-match discipline (no ambiguous rewrite is ever
applied), unrelated-suppression count 0, scoped-suppression count 0, and
every newly bound authorization field (§14) has a mismatch-rejection
test.

**Gate 6 rule.** Gate 6 is currently `inconclusive` because both systems
already produce 0 forget-directive creations, so no reduction can be
demonstrated. It is **not blocking**, and absence of regression is not
rounded up to a pass. Adoption is **not** declared while any applicable
**blocking** gate is inconclusive; a non-blocking inconclusive gate does
not by itself block adoption but is reported honestly as inconclusive.

Adoption is authorized only when Gate 1 passes, no blocking gate
regresses, and no additional acceptance condition fails. Passing every
safety gate is not adoption.

---

## 17. Stop Conditions

The path remains candidate-only or disabled if any of: a conflicting
planner action cannot be identified uniquely; replacement suppresses an
unrelated action; replacement suppresses valid scoped coexistence;
duplicate active memories remain materially worse than reference;
stale-pair improvement disappears; wrong targets appear; state
corruption appears; forgotten leakage appears; inactive contamination
appears; manager authority is bypassed; engine authority is bypassed; a
second durable mutation path appears; authorization becomes weaker;
diagnostics cannot explain the rewrite; benchmark evidence must be
changed to make the system pass; or the implementation destabilizes the
demo or dashboard.

---

## 18. Immutable Evidence

The following are frozen. Later steps create **new** artifacts and never
overwrite, rename, reformat, or re-digest these paths. Their diff must
remain empty.

Historical authorities:

- `benchmarks/results/committed/lifecycle-offline-v1/`
- `benchmarks/results/committed/lifecycle-v2-ablation/`
- `benchmarks/results/committed/longmemeval-50-subset-v1/`
- `benchmarks/results/committed/longmemeval-50-subset-v2/`
- `benchmarks/results/committed/phase11-retrieval-ablation/`
- `benchmarks/results/committed/phase11-semantic-retrieval/`
- `benchmarks/results/committed/grounded-extraction/`
- `benchmarks/results/committed/grounded-extraction-ablation/`
- `benchmarks/results/committed/report-v1/`, `report-v2/`,
  `report-phase11/`, `report-grounded-extraction/`

Transition authorities:

- `docs/transition_verification_contract.md`
- `benchmarks/annotations/transition-verification/` (corpus,
  annotations, oracle, manifest, schema)
- `benchmarks/results/committed/transition-verification/`
- `benchmarks/results/committed/transition-ablation/`
- `benchmarks/results/committed/report-transition-verification/`
- `benchmarks/transition_benchmark/` (as committed at `a09fce0`)

Digests (must not change):

| Family | Content digest |
|---|---|
| `transition-verification/` | `d7c2946117e64f1c3dbea12982b8a38b4a7be77fc4ade3bb6769736924882ce3` |
| `transition-ablation/` | `ed5338c29db08f2f7beea33441e0af7a38ef2a035848dd87cc77a672d632e25a` |
| `report-transition-verification/` | `5dd83d40dd5ac4546b016fcd7d7fa3a0a74777c5dfbcfefc53127186e8fd0b69` |

All three bind `contract_commit 938cbd0`, `corpus_commit dba85ec`, and
`code_commit 56672f6`. Historical system IDs are never reused (§19).

---

## 19. Reserved System IDs

Confirmed existing (reused as references, unchanged):

- `experienceos_hybrid_full_v2_reference` — canonical full composition,
  transition disabled. **Exists** in
  `transition-verification/systems.json`.
- `experienceos_transition_candidate_v1` — the existing candidate
  baseline; the action-replacement work references it as
  `experienceos_transition_candidate_v1_reference` (a reference alias
  for the pre-rewrite candidate). The alias is **not yet present** and
  is reserved here.

Reserved for this work (verified collision-free against the committed
`systems.json`, which contains only `experienceos_hybrid_full_v2_reference`,
`experienceos_transition_shadow_v1`, `experienceos_transition_candidate_v1`,
`experienceos_transition_rules_v1`, `experienceos_transition_adopted_v1`,
`experienceos_transition_learned_shadow_v1`,
`experienceos_transition_qwen_ceiling_v1`):

- `experienceos_action_replacement_shadow_v1`
- `experienceos_action_replacement_candidate_v1`
- `experienceos_action_replacement_verify_only_v1`
- `experienceos_action_replacement_adopted_v1` — **only if** adoption
  gates pass; no adopted result artifact is created before adoption is
  authorized.
- `experienceos_action_replacement_ablation_no_replacement_v1`
- `experienceos_action_replacement_ablation_replace_all_v1` — a clearly
  unsafe, non-adoptable negative control only.

None of the reserved ids collide with any existing tracked id.

---

## 20. Artifact Boundaries

Reserved output directories (feature-named per the §0 naming policy, in
place of any stage-named equivalent a working spec may suggest):

- `benchmarks/results/committed/action-replacement/`
- `benchmarks/results/committed/deduplicated-transition/`
- `benchmarks/results/committed/report-action-replacement/`

These are **not populated** by this contract step. Following existing
benchmark policy in the transition and grounded-extraction families,
future raw outputs are **committed** as digest-locked artifacts with a
manifest binding `contract_commit` / `corpus_commit` / `code_commit`,
with `latency.json` excluded from `file_digests` and declared
nondeterministic; determinism is proved by a repeat command. A `README`,
`.gitkeep`, or manifest may be added only when the corresponding
evidence is generated, not before.

---

## 21. Open Questions for the Seam Audit

Reserved for the next step; each must be characterized before any
rewrite:

1. Exact ordering guarantees within `valid_actions`
   (`experience_engine.py:158-451`) and which orderings are
   semantically load-bearing.
2. How to identify the matched planner `create` without a stable action
   id — the deterministic digest over its semantic fields (§8), and its
   collision behavior.
3. Whether the replacement plan is computed in the coordinator
   (`transition_integration.py`) as a proposal with the engine
   performing the list rewrite, or wholly at the engine seam — subject
   to the authority boundary (§7).
4. Whether extraction-appended actions (`experience_engine.py:364`) can
   ever be the conflicting create, or only planner-produced creates.
5. The precise before-state coverage needed to prove a rewrite
   deterministic.
6. Which of the §14 authorization fields are minimal-and-exact given the
   current `binding()` shape.
7. How `_extraction_reject_reason` / `_reject_reason` interact with a
   suppressed planner create (the suppressed create must not be
   re-admitted elsewhere).

Characterization tests for these belong to the seam-audit step, not this
one.

---

## 22. Validation Commands (for later steps)

Grounded in actual repository commands (interpreter `.venv/bin/python`
where `python3` lacks `pytest`):

```bash
# core
python -m compileall experienceos demo benchmarks
python -m pytest
PYTHON=.venv/bin/python ./scripts/validate_demo.sh

# historical / artifact validators (existing targets)
./scripts/run_benchmarks.sh validate <result-dir>
./scripts/run_benchmarks.sh validate-report
./scripts/run_benchmarks.sh validate-v2
./scripts/run_benchmarks.sh validate-external-v2
./scripts/run_benchmarks.sh validate-phase11
./scripts/run_benchmarks.sh validate-external-phase11
./scripts/run_benchmarks.sh validate-report-phase11
./scripts/run_benchmarks.sh validate-grounded-extraction
./scripts/run_benchmarks.sh validate-transition-verification   # all three transition families
./scripts/run_benchmarks.sh repeat-transition-benchmark        # determinism

# benchmark smoke / report / dashboard
./scripts/run_benchmarks.sh smoke-transition-benchmark
./scripts/run_benchmarks.sh transition-report
# dashboard AppTest lives under tests/ (Streamlit AppTest), run via pytest
```

A dedicated aggregate validation target for the new
action-replacement and deduplicated-transition families does **not** yet
exist; the step that produces those artifacts adds one, modeled on the
existing `validate-transition-verification` aggregate target
(`scripts/run_benchmarks.sh:174-181`).

---

## 23. Work Sequence and Deliverables

| Step | Deliverable |
|---|---|
| 1. Baseline audit and this contract | `docs/action_replacement_contract.md` (this document) + contract-integrity tests |
| 2. Action-list seam audit | Characterization tests answering §21; no behavior change |
| 3. Replacement intent and conflict matching | Deterministic matcher (§9) + rejection rules (§10), proposal-only |
| 4. Replacement plan model | Typed replacement-candidate / plan model (§8, §12) |
| 5. Governed integration at the seam | Rewrite at the §5 seam behind modes (§13); adopted gated by authorization (§14) |
| 6. Deduplicated applied-state verification | Applied-state evaluation proving duplicate pairs materially improve |
| 7. Benchmarking and gate re-evaluation | New artifacts under §20; gate re-run per §16 |
| 8. Dashboard and diagnostics visibility | Read-only rewrite explanation in the dashboard |
| 9. Freeze, documentation, closure | Closure record + controlled publication |

---

## 24. Closure Requirements

The final closure report uses feature-based decision tokens (per §0, in
place of any stage-named tokens):

- `ACTION_REPLACEMENT_COMPLETE_AND_PUBLISHED`
- `ACTION_REPLACEMENT_COMPLETE_WITH_NOTES`
- `ACTION_REPLACEMENT_BLOCKED`
- `ACTION_REPLACEMENT_FAILED`

Transition classification tokens are the established ones, unchanged:

- `TRANSITION_PATH_ADOPTED`
- `TRANSITION_PATH_CANDIDATE_ONLY`
- `TRANSITION_PATH_DISABLED`
- `TRANSITION_PATH_BLOCKED`

This contract step itself concludes with `ACTION_REPLACEMENT_CONTRACT_COMPLETE`
(or a bounded blocked/failed equivalent if the baseline or evidence
cannot be trusted).

---

## 25. Known Contract Limitations

- The seam is confirmed by code inspection but not yet exercised by a
  characterization test; §21 questions remain open by design.
- Historical semantic-duplicate evidence is thin (1 scored case); a
  material improvement must be demonstrated on that base plus fixtures,
  and the report must review every duplicate case by hand.
- `MemoryAction` carries no provenance, so matching depends on a digest
  computed at the seam; the digest's determinism and collision behavior
  are a §21 obligation.
- The typed `grounding_validation` field in `transition_verification.py`
  remains an untyped class attribute; it is inherited as a known defect
  and is **not** in this work's scope.

---

## 26. Acceptance Decision

`ACTION_REPLACEMENT_CONTRACT_COMPLETE`. The baseline was verified fresh,
frozen authorities are unchanged, the action-composition seam is located
precisely, and the scope, authority, metrics, gates, stop conditions,
system IDs, and artifact boundaries are fixed. No replacement behavior
was implemented; no runtime behavior changed; no frozen evidence was
touched; authorization was not weakened; the manager and engine
authorities were not bypassed; no second mutation path was introduced;
and transition adoption was not authorized. The seam audit may proceed.
