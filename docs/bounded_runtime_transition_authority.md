# Bounded Runtime Transition Authority

Current status: **active in canonical composition**
(`CANONICAL_DETERMINISTIC_LIFECYCLE_TRANSITIONS_ACTIVATED`,
`RUNTIME_TRANSITION_AUTHORITY_FAIL_CLOSED_VALIDATED`).

Implementation: `experienceos/memory/transition_authority.py`.

## 1. Purpose

The adopted transition path needs a `TransitionAuthorization` bound to the
exact runtime request, before-state, proposal, verification, and
translation — material a static configuration cannot precompute. This
authority issues that one exact receipt, and only for a single verified,
canonical-effect-eligible, single active-target supersede or forget
produced by an allowlisted deterministic controller.

## 2. Non-goals

It is not a general adoption policy or an enterprise authorization
platform. It issues **data** (a receipt); it never mutates memory, applies
actions, owns a store, or relaxes any downstream check.

## 3. Eligible controllers

Only the two canonical deterministic controllers, pinned by
`(controller_id, version)`:

- `experienceos_transition_rules_v1` (deterministic update controller);
- `experienceos_forget_rules_v1` (deterministic forget controller).

The experimental Qwen update controller (`qwen_update-1`) and the grounded
Qwen shadow controller are never allowlisted.

## 4. Eligible transition types

`supersede_existing` and `forget_existing`. Ordinary creation is not a
transition and needs no receipt; every other type is denied.

## 5. Eligibility sequence (fail-closed at each step)

1. mode is `adopted`;
2. a proposal exists with a non-empty allowlisted controller id;
3. the transition type is supported;
4. `(controller_id, version)` is allowlisted for the route;
5. verification exists, accepted, canonical-effect-eligible, from an
   allowlisted verifier, and references this proposal and type;
6. `proposal.before_state_digest == request.before_state.digest()`;
7. translation succeeded;
8. exactly one active target (no zero, no multiple, no supersede+forget);
9. the action shape matches the type (supersede: one supersede + one
   create whose `replaces` is the target; forget: one forget, no create);
10. the target is present and active in the before-state;
11. the receipt is built via the existing `build_authorization` binding.

Any failure returns a stable denial reason and no receipt.

## 6. Transition receipt binding

The receipt binds every field of `TransitionAuthorization.binding()`:
authorization version, mode, system id, controller id/version, request id,
source digest, evidence mode/digest, before-state digest, proposal
id/digest, transition type, target ids, created digest, verifier
id/version, verification digest, and expected action type/count. The
existing exact `_authorize` consumer re-derives the expected binding and
rejects on any single mismatch. `scope` and `single_use` are declarative
and deliberately outside the binding, so tampering them cannot broaden the
authority — the binding still pins one exact proposal.

## 7. Replacement receipt binding

For a supersede, a governed action replacement plan is authorized
separately by an exact `ReplacementAuthorization` bound to the plan digest,
before-state digest, original/projected action-list digests, matched
occurrence, replaced-action digest, inserted-action digests, and verified
transition id. The engine treats receipt issuance as only an additional
candidate; the exact consumer still decides.

## 8. Planner-precedence behavior

When the canonical planner already performs the same well-formed target
transition, the coordinator defers (no duplicate batch). See
[canonical_lifecycle_transitions.md](canonical_lifecycle_transitions.md).

## 9. Manager and engine boundaries

Every authorized action still passes ExperienceManager admission and is
applied only by ExperienceEngine — the sole durable mutation boundary. The
authority, coordinator, and verifier hold no store.

## 10. Fail-closed denial categories

Mode-not-adopted, proposal/controller missing, controller/version not
allowlisted, transition-type-unsupported, verification
missing/rejected/ineligible, verifier-not-allowlisted,
verification-proposal or before-state mismatch, translation
missing/failed/mismatch, target missing/multiple/conflict/not-active/
not-in-before-state, wrong action type/count, supersede-lineage-missing,
supersede-has-forget-effect, forget-has-supersede-effect,
forget-creates-memory, binding-construction-failed, malformed-input.

## 11. Exception containment

Any unexpected error is contained as `malformed_input` carrying only the
exception type name — never raw source text, memory content, or secrets.
Exceptions from any seam leave the chat turn intact with no mutation.

## 12. Replay and single-use semantics

The receipt declares `scope="single_proposal"` and `single_use=True` as
intent. There is **no durable consumed-receipt registry**. A stale receipt
cannot re-authorize a changed world because any lifecycle change moves the
before-state digest and the exact consumer rejects; a re-sent update finds
the target already superseded/forgotten and the transition does not
re-fire. No transactional concurrency guarantee is claimed.

## 13. Canonical composition

`demo.support.build_canonical_transition_config()` assembles the adopted
config (both deterministic controllers, the shared verifier, the bounded
authority, `planner_precedence=True`, no static authorizations). The demo
`create_agent`, the dashboard, and the competitive Qwen adapter use it.

## 14. Experimental-controller exclusion

The Qwen update intelligence remains experimental and is never in the
canonical transition composition; the canonical update controller id is
always `experienceos_transition_rules_v1`.

## 15. Evidence and tests

- `tests/test_transition_authority.py` — per-reason denial matrix.
- `tests/test_runtime_transition_authority_adversarial.py` — end-to-end
  state, spies, exception containment, replay, composition isolation.
- `tests/test_planner_precedence.py`, `tests/test_runtime_transition_integration.py`,
  `tests/test_canonical_transition_activation.py`.

## 16. Known limitations

Deterministic controllers cover bounded update/forget classes (no general
semantic update or forget). Single-use is intent, not durable
consumption. Hackathon validation, not production certification.
