# Action Replacement Plan Model

Companion to `docs/action_replacement_contract.md`,
`docs/action_replacement_seam_audit.md`, and
`docs/action_replacement_matching.md`. It documents the immutable,
deterministic plan model in `experienceos/memory/action_replacement/`
(`plan.py`, `projection.py`) that turns a matcher decision into an
explicit, authorization-ready description of a rewrite — **without
applying it**.

## 25.1 Purpose

The plan is a **pure projection**, not an applied rewrite. Given the
original canonical planner action list and a Prompt-3
`ReplacementDecision`, `ReplacementPlanBuilder` produces one immutable
`ActionReplacementPlan` describing exactly what the action list *would*
become if canonical replacement were later authorized: which occurrence
would be suppressed, what atomic sequence would be inserted, what would
be preserved, the projected list, and the digests binding all of it. It
mutates nothing, authorizes nothing, admits nothing, and applies nothing.

## 25.2 Inputs and Outputs

**Inputs** (all immutable): the original planner action list; the
`ReplacementDecision` (consumed unchanged); the seam's before-state
digest; a stable verified-transition identifier; optionally the
transition replacement sequence (defaults to the candidate's
supersede + create); and a projection context (`candidate` or `shadow`).

**Outputs**: `ActionReplacementPlan` (status, effect, digests,
occurrences, projected list, diagnostics, plan digest);
`ActionListProjection` / `ActionListRewriteResult` (the projection and
its accounting); `PlannedActionOccurrence` (per-action record);
`ReplacementBinding` (authorization-binding material);
`ReplacementPlanDiagnostic`.

## 25.3 Plan States

Ready / no-op / rejected, all as results — never exceptions:

| Status | Meaning |
|---|---|
| `no_replacement_needed` | Matcher decided nothing is to be replaced (e.g. pure create) |
| `replacement_plan_ready` | A projected rewrite is ready |
| `replacement_plan_rejected_matcher` | The matcher decision was itself a rejection |
| `replacement_plan_rejected_missing_candidate` | Ready decision without a candidate/match |
| `replacement_plan_rejected_occurrence_not_found` | Bound occurrence index absent |
| `replacement_plan_rejected_occurrence_ambiguous` | Match and candidate occurrences disagree |
| `replacement_plan_rejected_action_changed` | List or matched action changed since matching |
| `replacement_plan_rejected_before_state` | Before-state digest mismatch |
| `replacement_plan_rejected_invalid_sequence` | Transition sequence not a clean supersede + create |
| `replacement_plan_rejected_scope_preservation` | A scoped-compatible action would be suppressed (defensive) |
| `replacement_plan_rejected_unrelated_suppression` | Suppression accounting violated (defensive) |
| `replacement_plan_rejected_duplicate_insertion` | Inserted create already present |
| `replacement_plan_rejected_internal` | Unexpected internal error |

## 25.4 Occurrence Binding

The builder consumes the Prompt-3 occurrence identity and **never
rematches**. It locates the matched action by its `occurrence_index`,
then verifies: the recomputed action-list digest equals the bound one;
the matched action's content digest equals the candidate's; the action
is still create-like; the before-state digest matches; and the match and
candidate occurrences agree. Any drift rejects. `plan.py` and
`projection.py` import no identity projector — there is no semantic
comparison in the plan layer at all (asserted in tests).

## 25.5 Rewrite Projection

`project_rewrite` walks the original occurrences in order, and at the
matched occurrence inserts the transition sequence **in place of** the
matched create; all other actions keep their relative order. The
original list is never mutated; a new immutable projection is returned.

```
Original:                       Projected:
  planner_create(new_value)  ->   supersede(old_value)
  unrelated_action                create(new_value, replaces=old_value)
  scoped_action                   unrelated_action
                                  scoped_action
```

Insertion position is the matched occurrence's index. The linked
supersede + create enter as a unit; lineage is expressed through
`replaces`.

## 25.6 Count Invariants

For a ready plan:

```
suppressed_count == 1
preserved_count + suppressed_count == original_count
projected_count == original_count - 1 + inserted_count
```

Any mismatch rejects. Rejected and no-op plans suppress zero and expose
no projected list.

## 25.7 Plan Digest

`plan_digest` is a SHA-256 over a canonical, sorted, mutable-free
payload binding: schema version, matcher decision, verified-transition
id, before-state digest, original action-list digest, matched
occurrence, suppressed and preserved occurrences, inserted action
digests, projected action-list digest, canonical effect, and status. It
**excludes** timestamps, object ids, diagnostics, mutable metadata,
paths, exception text, and latency. It reproduces byte-for-byte across
runs (asserted).

## 25.8 Authorization Binding

`ReplacementBinding` is the minimum exact material a later step's
authorization may bind: plan digest, before-state digest, original
action-list digest, matched occurrence, replaced action digest, a
deterministic preserved-occurrences digest, inserted action digests,
projected action-list digest, decision type, and verified-transition id.
This prompt **issues and validates no authorization**; the binding is
immutable input only.

## 25.9 Purity and Authority

The builder holds no `MemoryStore`, `ExperienceEngine`, or
`ExperienceManager`; performs no persistence, mutation, authorization,
verification, matching, ranking, model, or network call; and returns
frozen dataclasses. It may validate the decision's internal consistency
and reject malformed matcher output, but it may never choose a different
planner action. It cannot mutate, authorize, admit, or apply.

## 25.10 Unsupported Cases

- **Pure-create redundant duplicates.** A pure-create transition (no
  supersede) is `no_replacement_needed`; roughly three of the ten
  historical applied duplicates are this class, and this model does not
  resolve them. The expected improvement is therefore material, not
  complete. No generic create deduplication is introduced.
- **Extraction replacement.** Extraction creates are never replacement
  candidates (matcher decision), and the plan never suppresses one.
- **Multiple matches / unsupported transition types.** Rejected upstream
  by the matcher and mirrored here as rejected plans.
- **Runtime rewriting.** Not performed; this is a projection only.

## 25.11 Governed Integration Boundary (next step)

A later step may consume this plan at the engine seam
(`experience_engine.py:450-451`) to perform the actual, authorized
rewrite — suppressing the matched planner create by its occurrence
identity, inserting the transition sequence, and binding the plan to an
extended authorization. That step **adds no new matching or projection
logic**: it consumes the `ActionReplacementPlan` and `ReplacementBinding`
unchanged, and the engine remains the sole durable mutation boundary.
