# Canonical Action-List Seam Audit

Companion to `docs/action_replacement_contract.md`. This document
characterizes — with executable evidence — how the engine composes the
pre-application action list today, proves the add-not-replace defect,
and fixes the requirements the matching step must implement. It changes
no runtime behavior. Every claim below is backed by a test in
`tests/test_action_replacement_seam.py` unless a source line is cited
directly.

## 16.1 Decision

`ACTION_LIST_SEAM_AUDIT_COMPLETE`

The full action flow is mapped to exact symbols, the append seam is
confirmed, the defect is reproduced through the genuine adopted stack
and at the engine seam directly, digest feasibility is measured, and no
stop condition is triggered.

## 16.2 Baseline

Verified fresh: branch `main`; HEAD `740ff40` (single-parent descendant
of `a09fce0`); `origin/main` and direct remote `a09fce0`; ahead 1 /
behind 0; working tree clean. Full suite before this step 2,379 passed;
after adding the seam tests, 2,394 passed (2,379 + 15). Demo validation
passed. Frozen authorities: empty diff vs `a09fce0`.

## 16.3 Exact Runtime Flow

`ExperienceEngine.run_interaction` (`experienceos/engine/experience_engine.py:67`):

```
message
  -> memory_store.active_for_user            (:79)  pre-turn active snapshot
  -> context build + emit                    (:95-129)
  -> experience_manager.plan(PolicyContext)  (:131)  -> result.actions (MemoryAction[])
  -> retired_ids from result.actions         (:153-157)
  -> valid_actions = [a for a in result.actions if _reject_reason(a) is None]  (:158-167)
        # the planner create(new) is now in valid_actions
  -> if extraction enabled: _evaluate_extraction(... valid_actions)  (:179)
        # adopted+authorized extraction append  (:364)
  -> if transition enabled: _evaluate_transition(... valid_actions)  (:195)
        # adopted+ACTION_ADDED transition append (:450-451)  <-- SEAM
  -> emit MEMORY_ACTION_PLANNED / *_INTEGRATION_EVALUATED       (:211-239)
  -> _apply_memory_actions(valid_actions, ...)                  (:240 -> :483)  SOLE MUTATION
```

Per-stage record (input -> output; ordering; copy/mutate; provenance;
identity; before-state; authorization; can-mutate):

| Stage | Symbol | In -> Out | Mutates store? |
|---|---|---|---|
| Plan | `ExperienceManager.plan` (`policy/manager.py:90`) | `PolicyContext` -> `ExperienceManagerResult.actions` | no |
| Admit | `_reject_reason` (`experience_engine.py:260`) | action -> reason\|None | no |
| Extraction | `_evaluate_extraction` (`:309`) | evidence -> append or diagnostics | only via `valid_actions` append (`:364`) |
| Transition | `_evaluate_transition` (`:380`) | request -> append or diagnostics | only via `valid_actions` append (`:450-451`) |
| Apply | `_apply_memory_actions` (`:483`) | `valid_actions` -> store writes | **yes (sole boundary)** |

The transition coordinator (`transition_integration.py:691`) returns a
result and mutates nothing; it holds no store handle and exposes no
mutation method (test `test_real_coordinator_holds_no_store`).

## 16.4 Confirmed Append Seam

```python
# experienceos/engine/experience_engine.py:448-451
# Supersession is two linked actions; both enter the same
# canonical list together or neither does.
for action in result.generated_actions:
    valid_actions.append(action)      # THE SEAM
```

This is the only point where planner-derived and transition-derived
actions coexist in one list. It is an **append**, gated by adopted mode
+ `ACTION_ADDED` + every generated action passing
`_extraction_reject_reason` (`:425-436`). `valid_actions` is the same
list built at `:158` and applied undivided at `:240`. The extraction
path appends into the same list at `:364`.

Crucially, `_extraction_reject_reason` (`:286-307`) rejects a controller
create whose **exact normalized text** equals a planner create
(`duplicate_of_planned`). The surviving duplicate therefore must have
*different surface text*, matched only by semantic identity — proven by
`test_exact_text_duplicate_would_be_rejected_by_current_guard`. This is
the central reason exact-text dedup is insufficient and the replacement
matcher must use the established semantic-identity layer.

## 16.5 Failure Reproduction

**Genuine adopted stack** (`benchmarks.transition_benchmark.systems.run_case`,
no frozen artifact written):

- Case `updates_001_preference_replacement_cross_session`: adopted
  applied state has **1** semantic duplicate pair; reference **0**;
  candidate projection **0**; the old value is still superseded
  (`test_adopted_stack_reproduces_semantic_duplicate`).
- Across all **28** historical scored cases: adopted total **10**,
  reference **0** — equal to the committed
  `headline_metrics.json` (`adopted_duplicate_pairs=10`,
  `reference_duplicate_pairs=0`)
  (`test_adopted_duplicate_total_matches_committed_headline`).

**Engine seam directly** (controlled action list; real store, engine,
identity layer):

Action-list shape reaching the mutation boundary
(`test_transition_actions_append_planner_create_survives`):

```
create(preference, "I prefer window seats for work trips.")      # planner
create(preference, "I am based in the Denver office.")           # planner, unrelated
create(preference, "I prefer tea on weekends.")                  # planner, scoped
supersede(old.seat)                                              # transition (appended)
create(preference, "I now prefer window seats for work trips.")  # transition (appended)
```

Applied state (`test_applied_state_has_semantic_duplicate_pair`):

- `old.seat` retired (superseded);
- **two** active window-seat memories;
- `compare_memory_identity(...)` classifies them `SEMANTIC_DUPLICATE`.

Unrelated and scoped planner creates survive to the store untouched
(`test_unrelated_and_scoped_planner_actions_are_preserved`).

## 16.6 Candidate Projection vs Applied State

The candidate projection (`project_transition_state`, `systems.py:304`)
applies only the proposal's deactivations to the frozen before-state and
adds the proposal's created text — it never sees the planner's create,
so it shows a clean supersede + one create (0 duplicate pairs). The
applied engine path composes **both** the planner create and the
transition create into `valid_actions`, so it stores two. The divergence
is entirely at composition: the verifier accepted the correct proposal,
target resolution picked the correct old memory, and the projection is
clean — yet the applied state duplicates, because the planner create is
never removed.

## 16.7 Action Source Matrix

| Property | Planner action | Extraction action | Transition action |
|---|---|---|---|
| Construction site | `ExperienceManager._to_action` (`policy/manager.py:251`) via `MemoryPlanner.plan_memory_actions` (`planner.py:305`) | `_evaluate_extraction` translation (`experience_engine.py:337`) | coordinator translation -> `generated_actions` (`transition_integration.py`) |
| Type at seam | `MemoryAction` | `MemoryAction` | `MemoryAction` |
| Structural provenance | none | none | none |
| Grounding evidence | none on the action | on coordinator outcome, not the action | on `VerifiedActionSpec`/verification, not the `MemoryAction` |
| Semantic identity | not on the action | not on the action | computed upstream; not on the `MemoryAction` |
| Scope | only if placed in `metadata` | only if in `metadata` | only if in `metadata` |
| Stable ID | none (`test_memory_action_has_no_stable_identity`) | none | none |
| Digest | none | none | none |
| Before-state binding | none on the action | none on the action | on the coordinator request/authorization, not the action |
| Authorization binding | n/a | extraction authorization (separate) | 20-field `TransitionAuthorization` on the coordinator, not the action |
| List position | order of `result.actions` | appended after planner (`:364`) | appended after planner/extraction (`:450-451`) |

Answers to the classification questions: the engine **cannot** tell a
planner action from an extraction or transition action by inspecting the
`MemoryAction` — all three are the same thin, ID-less type, and once in
`valid_actions` they are indistinguishable. Provenance is known only
positionally and by which code path appended the action, never
structurally. Provenance is not encoded and is effectively lost at the
seam. Two separately constructed actions with the same normalized
content serialize identically (Group C).

## 16.8 Ordering Findings

Load-bearing:

- **Creates-before-supersedes at application.** `_apply_memory_actions`
  (`:483-544`) builds all creates first (recording `replaces` lineage),
  then applies supersedes/forgets. Lineage is keyed by the `replaces`
  field, **not** by list position — reversing the linked transition pair
  yields identical applied state
  (`test_application_order_is_creates_first_then_supersede`).
- **All-or-nothing admission of the linked supersede+create.** The seam
  appends both generated actions or neither (`:447-451`); the matcher
  and future rewrite must preserve this invariant.

Not load-bearing:

- Relative order among independent creates, and the position of the
  supersede relative to its paired create within `generated_actions`.

Requirement for the rewrite: when suppressing the matched planner
create, the linked transition `supersede + create` must still be
inserted as a unit, and lineage must remain expressed through `replaces`
(pointing at the surviving transition create).

## 16.9 Digest Findings

Three identities must stay distinct (Group C):

- **Semantic identity** — `IdentityProjector` + `compare_memory_identity`
  over subject/attribute/value/scope. The duplicate pair is a
  `SEMANTIC_DUPLICATE` with *different* normalized text.
- **Action-content identity** — a deterministic digest over normalized
  semantic fields (`action`, `kind`, normalized `text`, `memory_id`,
  `replaces`, and **scope**). Deterministic and key-order independent
  (`test_content_digest_is_deterministic_and_key_order_independent`). It
  is **not** semantic identity: the semantic-duplicate pair has
  *different* content digests
  (`test_content_digest_is_not_semantic_identity`).
- **Occurrence identity** — content digest + occurrence index +
  original action-list digest. Required because two identical creates
  share a content digest and are distinguishable only by position
  (`test_duplicate_creates_need_occurrence_identity`).

Collision risks measured:

- omitted field vs explicit `None` collide — null and absent are
  indistinguishable by content
  (`test_omitted_and_explicit_null_fields_collide`);
- two creates differing only by scope collide if scope is omitted, and
  separate when included — scope **must** be an input, or valid
  coexistence becomes invisible
  (`test_scope_collision_risk_when_scope_omitted`);
- normalization (`[a-z0-9]+` lowercased) conflates surface variants —
  correct for action-content identity, but it must never be read as
  semantic identity.

**Recommended digest input set for the matching step:** action-content
digest over `{action, kind, normalized_text, memory_id, replaces,
scope}`; occurrence identity as `{content_digest, occurrence_index,
action_list_digest}`; and semantic identity kept separate via the
existing identity layer. The matcher compares semantic identity to find
a candidate and uses occurrence identity to bind the exact planner
action to suppress. `list position` is safe to include **only** inside
occurrence identity bound to a specific action-list digest; it must not
enter semantic comparison. No mutable field (timestamps, UUIDs) may
enter any digest that later binds authorization.

## 16.10 Extraction Findings

Extraction actions are appended earlier, at `:364`, and are the same
ID-less `MemoryAction` type. Under the current architecture an
extraction-adopted create could in principle sit in `valid_actions`
before the transition append and be create-like. Therefore the matcher
**must not** treat every create-like action as a planner create: the
conflicting action to suppress is the one that represents the same
intended new-memory effect as the transition replacement, identified by
semantic + occurrence identity, not by "is a create". Unrelated and
scoped creates (whatever their source) are preserved today because the
append suppresses nothing. Whether extraction-originated creates should
ever be a replacement target is a **requirement the replacement-matching
step must decide explicitly**, not assume; the safe default is to match only the
canonical planner create and to leave extraction creates untouched
unless a case proves otherwise.

## 16.11 Before-State Findings

At the seam the engine already builds `build_before_state(memories,
user_id=...)` (`experience_engine.py:415`) from the pre-turn active
snapshot taken at `:79`, and the transition authorization already binds
a `before_state_digest` (`transition_integration.py` binding). The
before-state available is the active snapshot; superseded records are
included only when a temporal builder requests them (`:84-90`);
forgotten records are never passed. The state is captured once, before
planning, and application is single-threaded within the interaction, so
there is no concurrent mutation between verification and the append.

Requirements: the replacement plan must bind to the **same** before-state
digest the transition authorization already uses — it must not recompute
state during the rewrite (which would weaken authorization). The minimum
before-state binding for the rewrite is the pre-turn active snapshot
digest plus the target memory ids; superseded/forgotten coverage is only
needed if a case requires distinguishing a re-activation, which the
historical corpus does not currently exercise.

## 16.12 Authority Analysis

- **Plan:** the manager/planner and, for the rewrite, a pure
  replacement planner — proposal only.
- **Verify:** the transition verifier — `applied` invariantly false.
- **Authorize:** exact `TransitionAuthorization`, extended later to bind
  the replacement plan (contract §14).
- **Admit:** `ExperienceManager` and the engine's `_reject_reason` /
  `_extraction_reject_reason`.
- **Apply:** `ExperienceEngine._apply_memory_actions` — sole boundary.

No component other than the engine writes to the store; the coordinator
and any audit helper do not (`test_coordinator_does_not_mutate_the_store`).

## 16.13 Recommended Replacement-Planning Location

A **pure, deterministic action-replacement planner**, invoked at the
engine-owned seam, that:

- receives the immutable `valid_actions` (as a tuple), the verified
  transition proposal/verification, the generated actions, and the
  before-state;
- returns a replacement plan (which occurrence to suppress, what to
  insert, decision + diagnostics) and nothing else;
- holds no store and no engine reference and has no mutation method;
- is consulted by `_evaluate_transition` in place of the blind append,
  with the engine performing the actual list rewrite and the existing
  `_apply_memory_actions` performing the sole durable mutation.

This keeps controllers/verifiers proposal-only, keeps the coordinator
store-free, keeps the manager and engine authoritative, adds no second
mutation path, and lets exact authorization bind the whole plan. The
audit supports this recommendation; the plan is computed as a proposal
and applied only by the engine.

## 16.14 Replacement Matching Requirements (next step: replacement intent and conflict matching)

1. Compute a candidate only when the contract §9 conditions all hold
   (accepted verification, replacement-requiring type, create-like
   planner action, compatible grounding, equivalent memory effect by the
   identity layer, compatible scope, unique match, no unrelated or
   scoped suppression).
2. Match via **semantic identity** (existing layer) to find the
   candidate, and **occurrence identity** (content digest + index +
   action-list digest) to bind the exact planner action.
3. Use the recommended digest input set (§16.9); keep semantic, content,
   and occurrence identity distinct; include scope; exclude mutable
   fields.
4. Fail closed on every §10 condition, degrading to today's append /
   planner-only behavior.
5. Preserve unrelated, scoped, and fallback actions; suppress only the
   uniquely matched planner create.
6. Match only the canonical planner create by default; decide explicitly
   whether extraction creates are ever eligible.
7. Preserve the linked supersede+create as a unit and express lineage
   through `replaces`.
8. Bind the plan to the same before-state digest the transition
   authorization uses.
9. Emit diagnostics that explain every match and every rejection.
10. Implement as a pure planner (§16.13); no store, no engine reference,
    no mutation, proposal-only.

## 16.15 Stop-Condition Check

No stop condition (contract §17) is triggered. The conflicting planner
create is uniquely identifiable via occurrence identity; nothing
suppresses unrelated or scoped actions; the manager and engine
authorities are intact; no second mutation path exists; and no frozen
evidence was altered.

## 16.16 Non-Changes

No replacement behavior was implemented. No planner action is suppressed
in product code. No `ACTION_REPLACED` effect is emitted canonically. No
authorization was extended. Adopted-mode behavior, transition defaults,
and transition classification are unchanged. `MemoryAction` is
unchanged. The digest helpers live only in the test module and are
marked audit-only.
