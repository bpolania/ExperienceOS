# Governed Action Replacement

Companion to the action-replacement contract, seam audit, matching, and
plan documents. It describes how the deterministic matcher and plan
builder are integrated into the engine so that, under exact
authorization, a verified transition **replaces** the conflicting
planner create instead of being appended beside it — closing the
add-not-replace defect while preserving every lifecycle and
authorization authority.

## 24.1 Runtime Integration

The matcher and plan builder are invoked inside
`ExperienceEngine._evaluate_transition`
(`experienceos/engine/experience_engine.py`), at the same seam the seam
audit identified. The engine captures the **admitted planner actions** as an
immutable snapshot *before* any extraction or transition append
(`admitted_planner_actions`), so planner origin is structural, never
inferred from the mixed list. The runtime sequence is:

1. canonical planner produces actions;
2. `ExperienceManager` admits them under existing rules;
3. the transition coordinator proposes and verifies (unchanged);
4. `build_replacement` runs the pure matcher on the admitted planner
   actions and the pure plan builder on its decision;
5. a `ReplacementAuthorization` must exactly match the plan binding;
6. only then does the engine suppress the matched planner create and
   insert the transition sequence in its place;
7. the rewritten list goes through the existing lifecycle admission and
   `_apply_memory_actions` — the sole durable mutation boundary;
8. diagnostics record the plan, authorization, rewrite, and fallback.

No new matching or projection logic lives in the engine — it consumes
the matcher decision and the replacement plan unchanged.

## 24.2 Mode Semantics

- **Disabled** — the coordinator is not invoked; nothing in the
  replacement path runs; canonical behavior is byte-for-byte unchanged.
- **Shadow** — the engine computes a non-mutating replacement projection
  (matcher + plan) for diagnostics; `valid_actions` is untouched; no
  planner action is suppressed and no transition action is applied.
- **Candidate** — same as shadow: a projected rewrite is recorded, never
  applied.
- **Verify-only** — no replacement projection or rewrite.
- **Adopted infrastructure** — replacement affects the canonical action
  list **only** when a `ReplacementAuthorization` exactly matches the
  plan. With no replacement authorization configured, adopted mode keeps
  the existing append behavior (backward compatible). A failed
  replacement never appends both — it falls back to the canonical planner
  list. Adopted is never the runtime default.

## 24.3 Authorization

Replacement is gated by a `ReplacementAuthorization`
(`action_replacement/authorization.py`) that binds the immutable
`ReplacementBinding` the plan produces: plan digest, before-state digest,
original action-list digest, matched occurrence, replaced-action digest,
preserved-occurrences aggregate digest, inserted action digests,
projected action-list digest, decision type, and verified-transition id.
Every field must match exactly; any difference fails closed. This reuses
the established exact-binding pattern — it authorizes *that exact plan*,
not a general right to replace.

## 24.4 Rewrite Rules

When the plan is ready and authorized, the engine consumes
`plan.projected_actions` directly — it does not rematch, reconstruct the
list, search for another occurrence, reorder preserved actions, or alter
inserted actions. It verifies the plan is ready and bound, the original
list digest matches the current planner list, the before-state digest
matches, and the authorization matches; then it rewrites
`valid_actions` to `plan.projected_actions + extraction_part`. After the
rewrite the matched planner create is absent, the transition sequence
appears exactly once, and preserved actions keep their order.

## 24.5 Planner Fallback

Any replacement prerequisite failure falls back to the **canonical
planner list** — the transition sequence is not appended and no planner
action is suppressed. Fallback fires for: no replacement needed (pure
create), no/multiple/scope/extraction match, plan rejection or
inconsistency, missing or mismatched authorization, and inserted-sequence
admission rejection. The fallback reason is recorded. The fallback is
never append-both.

## 24.6 Atomicity

The linked supersede + create are admitted as one unit against the
surviving actions (the matched create removed). If either is rejected by
the existing `_extraction_reject_reason` admission check, neither is
applied, the planner create is retained, and the outcome is recorded as
a fallback — never a partial replacement.

## 24.7 Manager and Engine Authority

`ExperienceManager` still admits the canonical planner actions;
`_reject_reason` / `_extraction_reject_reason` still gate every inserted
action; and `ExperienceEngine._apply_memory_actions` remains the sole
durable mutation boundary. The matcher, plan builder, authorization, and
coordinator hold no store and perform no mutation.

## 24.8 Diagnostics

The transition integration event carries a `replacement` sub-record:
attempted, applied, matcher decision, plan status, plan digest,
canonical effect, original and projected action-list digests,
authorization status and mismatch reason, fallback used and reason,
suppressed occurrence index, and final action count. It is additive and
safe for older consumers that ignore it. A successful replacement reports
`ACTION_REPLACED`; a failed one reports a rejection effect and never
`ACTION_ADDED`.

## 24.9 Unsupported Cases

- **Pure-create redundant duplicates** — a pure-create transition is not
  supersede-bearing, so `no_replacement_needed`; the existing append runs
  and roughly three historical duplicates remain this class. Not solved
  here; no generic semantic deduplication is introduced.
- **Extraction replacement** — extraction creates are never replacement
  candidates and are never suppressed.
- **Canonical default adoption** — the default mode remains disabled; no
  controller becomes canonical.
- **Fuzzy matching** — none; matching is deterministic and identity-based.

## 24.10 Applied-State Verification Boundary (next step)

The next step verifies deduplicated applied state across the historical
supersede-bearing failure patterns: run each through authorized
replacement, confirm the planner conflict is absent and the transition
create appears once, verify target deactivation and lineage, count
remaining pure-create duplicates separately, and record before,
projected, and applied states — all without altering frozen evidence or
making an adoption decision.
