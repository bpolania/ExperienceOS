# Canonical Lifecycle Transitions

Current status: **active in canonical composition**. The canonical chat
path supersedes and forgets obsolete experience instead of only creating.

Runtime path per user turn:

```
user turn
 → grounded extraction (Qwen when configured; deterministic offline)
 → memory planner
 → deterministic update / forget controller
 → transition verifier
 → bounded runtime authority (exact receipt)
 → exact transition authorization check
 → planner precedence  OR  governed action replacement (+ exact replacement check)
 → ExperienceManager admission
 → ExperienceEngine persistence (sole mutation boundary)
 → lifecycle-aware retrieval (excludes superseded / forgotten)
 → context selection (budgeted)
 → model response
```

## Create

Ordinary memory creation. No runtime lifecycle receipt is required; the
new active memory is available in future sessions.

```
"I prefer aisle seats."  → one active preference; no supersede, no forget
```

## Update

1. one active obsolete memory is selected by the deterministic controller;
2. a supersede proposal is produced and verified;
3. an exact runtime receipt is issued and validated;
4. where the planner emitted a conflicting create, a governed replacement
   replaces it (its own exact receipt validated) rather than appending;
5. the old memory becomes **superseded**, the new one **active**, lineage
   preserved;
6. retrieval and context exclude the superseded memory.

```
"I prefer tea in the morning."
"Actually, I prefer coffee in the morning."
 → tea superseded, coffee active; retrieval/context surface only coffee
```

## Forget

1. one active target is resolved by the deterministic forget controller;
2. the forget proposal is verified;
3. an exact runtime receipt is issued and validated;
4. the target becomes **forgotten**; no replacement memory is created;
5. retrieval and context exclude the forgotten state.

```
"Send my daily status summary to the #eng-daily channel."
"Forget the instruction about my daily status channel."
 → instruction forgotten; nothing leaks into later context
```

## Planner precedence

When the canonical planner already emits the *same well-formed target
transition* (a keyed domain it handles natively), the coordinator
**defers** to it:

- avoids a double supersede or double forget;
- keeps the planner's normalized create text authoritative;
- a **malformed** planner lifecycle batch (e.g. a supersede whose create
  replaces a different memory) does **not** suppress a correct verified
  transition;
- the policy is opt-in and set only in the canonical composition
  (`planner_precedence=True`);
- with precedence off, the raw append/governed-replacement mechanism is
  unchanged, so the frozen action-replacement benchmark still reproduces
  (10 → 4 duplicate reduction).

```
Planner-handled seat update:
"I prefer aisle seats." / "I prefer window seats now."
 → planner supersedes aisle → coordinator defers → window active,
   aisle superseded, normalized text, single supersede.

Transition-handled update (planner is create-only here):
"I prefer tea in the morning." / "Actually, I prefer coffee in the morning."
 → planner creates coffee only → transition supersedes tea, governed
   replacement swaps in the create → coffee active, tea superseded.

Forget:
"...#eng-daily channel." / "Forget the instruction about my daily status channel."
 → deterministic forget controller resolves one target → forgotten.
```

## Cross-session behavior

Lifecycle state is durable (in-memory or SQLite). Reconstructing the agent
against the same store preserves active / superseded / forgotten state, and
retrieval continues to exclude obsolete and forgotten memory.

## Evidence and tests

- `tests/test_canonical_lifecycle_transitions.py` — end-to-end create /
  update / forget / persistence.
- `tests/test_planner_precedence.py` — exact-match and malformed-batch cases.
- `benchmarks/results/committed/canonical-lifecycle-activation/` — offline
  deterministic lifecycle/retrieval/context proof over the frozen subset.
- `benchmarks/results/committed/canonical-lifecycle-activation-live/` — live
  six-system competitive rerun.

## Limitations

Bounded update/forget classes only; no general semantic update or forget;
the raw create text of a transition-inserted memory is accepted as-is when
retrieval and answers remain correct.
