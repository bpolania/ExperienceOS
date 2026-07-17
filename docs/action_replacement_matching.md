# Replacement Intent and Conflict Matching

Companion to `docs/action_replacement_contract.md` and
`docs/action_replacement_seam_audit.md`. It documents the pure
deterministic decision engine in
`experienceos/memory/action_replacement/` that answers one question:

> If replacement were allowed, which planner action would be replaced?

It never answers "apply the replacement." No action list is rewritten,
no planner action is suppressed, no authorization is extended, and no
durable state is touched. Later work consumes the decision this engine
returns.

## Components

| Type | Role |
|---|---|
| `ActionReplacementPlanner` | Pure matcher; takes immutable inputs, returns one `ReplacementDecision` |
| `VerifiedTransition` | Immutable transition evidence the planner may consult |
| `ReplacementDecision` | Exactly one outcome + diagnostics |
| `ReplacementCandidate` | The fully-described replacement, when ready |
| `ReplacementMatch` | The bound planner action + its identity |
| `ReplacementDiagnostic` | Deterministic per-action / per-decision reasoning |
| `PlannerActionIdentity` / `OccurrenceIdentity` | The identity arithmetic |

## Three identities, kept separate

The seam audit proved that conflating identities is exactly how the
wrong action gets suppressed. The engine keeps three distinct notions:

- **Semantic identity** — subject / attribute / value / scope, from
  `experienceos/memory/identity.py`. Answers "same experience?" Computed
  by the projector, never here. Surfaced as the `semantic_key`
  (`target_key` + value + temporal).
- **Action-content identity** — `action_content_digest`, a SHA-256 over
  `{action, kind, normalized_text, memory_id, replaces, scope, version}`,
  serialized with sorted keys. Answers "same action?" Deterministic,
  key-order independent, and free of mutable fields (no ids, no
  timestamps) so it can later bind authorization without drift. It is
  **not** semantic identity: a semantic duplicate with different surface
  text has a *different* content digest.
- **Occurrence identity** — `{content_digest, occurrence_index,
  action_list_digest}`. Answers "which occurrence?" Two byte-identical
  creates in one list share a content digest and are separated only by
  index, bound to that specific list's digest.

Scope is included in the content digest because two creates that differ
only by scope are valid coexistence, not duplicates, and must not
collide. An omitted field and an explicit `None` serialize identically
— null and absent are deliberately indistinguishable.

## Digest construction

```
content_digest  = sha256(json({action, kind, normalized_text,
                               memory_id, replaces, scope, version},
                              sort_keys=True))
list_digest     = sha256("|".join(content_digest(a) for a in actions))
occurrence      = (content_digest, occurrence_index, list_digest)
```

`normalized_text` reuses the planner's `[a-z0-9]+` normalization, so the
content digest agrees with the canonical planner on "same text" while
tolerating punctuation and spacing. Mutable fields never participate.

## Matching algorithm

Given the canonical planner actions, a `VerifiedTransition`, and the
seam's before-state digest, in order:

1. **Verification.** If the transition was not accepted →
   `replacement_rejected_verification`. If its evidence is not grounded
   (`source_digest` empty) → `replacement_rejected_verification`.
2. **Replacement-requiring type.** A replacement is a supersession that
   emits a paired supersede + create. No generated actions →
   `no_replacement_needed`. A pure create (create-new) →
   `no_replacement_needed` (a distinct, non-replacement case; see
   Limitations). A supersede with no paired create →
   `replacement_rejected_unsupported`.
3. **Before-state binding.** If the transition's `before_state_digest`
   differs from the seam's → `replacement_rejected_before_state`. The
   plan must evaluate against the very state the transition was verified
   against; it never recomputes state.
4. **Project** the replacement create's semantic identity once.
5. **Extraction.** Any extraction-supplied create that semantically
   duplicates the replacement create is recorded as a diagnostic with
   `candidate_type = extraction`, `rejection_reason =
   extraction_not_supported`, and is **never** a match.
6. **Planner scan.** For each planner action, compute its occurrence
   identity and its relation to the replacement create:
   - `EXACT_DUPLICATE` / `SEMANTIC_DUPLICATE` on a create → a match
     candidate;
   - the same relation on a non-create → unsupported;
   - `SCOPED_COEXISTENCE` → a scope conflict (valid coexistence);
   - anything else → unrelated.
7. **Decide** exactly one outcome:
   - more than one match → `replacement_rejected_multiple_matches`
     (fail closed, never ranked);
   - exactly one match, but that create itself `replaces` a *different*
     target → `replacement_rejected_unrelated_action`;
   - exactly one match, clean → `replacement_ready` with a candidate
     bound by occurrence identity;
   - no match, with a scope-coexistence action present →
     `replacement_rejected_scope_conflict`;
   - no match, with an unsupported (non-create duplicate) action →
     `replacement_rejected_unsupported`;
   - no match otherwise → `replacement_rejected_no_match`.

An unexpected internal error becomes `replacement_rejected_internal`;
the planner never raises for an expected matching failure.

## Rejection algorithm (fail closed)

Every path that is not a clean, unique create match degrades to a
rejection, and every rejection leaves the planner action list exactly as
it was — this engine only *decides*. The decision vocabulary maps
one-to-one to the contract's §10 fail-closed conditions: no match,
multiple matches, scope conflict, unrelated suppression, before-state
mismatch, verification failure, unsupported type, and internal error.

## Planner-origin detection

`MemoryAction` carries no provenance and the seam audit proved it
disappears after append. The planner therefore does not guess origin
from content. Its `planner_actions` argument **is** the authoritative
canonical-planner set — the caller establishes origin structurally by
which list it passes (the engine knows the planner actions before any
extraction or transition append). Actions arriving through the
`extraction_actions` channel are never treated as planner actions. If a
caller cannot prove an action is planner-originated, it must not place
it in `planner_actions`; the matcher then fails closed with no match.

## Extraction decision

Extraction creates are **not** replacement candidates in this engine.
They are explicitly rejected with a diagnostic and never suppress a
planner action or block a planner match. Whether extraction creates
should ever be eligible is left to later work; this engine implements
the safe default only.

## Planner purity

The planner holds no `MemoryStore`, `ExperienceEngine`, or
`ExperienceManager` reference, exposes no mutation method, and performs
no authorization or persistence. Its only collaborator is the read-only
identity projector. All inputs and outputs are frozen dataclasses;
`plan()` does not mutate its arguments. These properties are asserted in
`tests/test_action_replacement_planner.py`.

## Future rewrite integration

A later step invokes this planner at the engine-owned action-list seam
(`experience_engine.py:450-451`), in place of the blind append. When the
decision is `replacement_ready`, the engine — the sole mutation boundary
— suppresses the uniquely matched planner create (by its occurrence
identity), inserts the transition supersede + create as a unit, and
binds the plan to an extended authorization. On any other decision the
engine keeps today's behavior. No matching logic belongs in that step;
it consumes this decision unchanged.

## Limitations (measured)

- **Create-new duplicates are out of scope.** Of the 10 historical
  applied duplicates, the supersession cases are replacement-type; the
  pure-create cases (planner create + transition create, no supersede)
  return `no_replacement_needed` here, because they are a redundant-create
  class, not a supersede-bearing replacement. Resolving them is a
  separate decision for later work.
- **Extraction coexistence.** If both a planner create and an extraction
  create name the same memory, suppressing only the planner create would
  leave the extraction duplicate. Extraction is default-disabled and
  absent from the historical corpus, so this is recorded, not handled.
