# Governed Transition Integration

One bounded seam decides whether transition intelligence runs at all,
what its proposals may influence, and whether a verified proposal may
become a canonical lifecycle action.

> Is transition intelligence disabled? Should controllers run only for
> diagnostics? Should a proposal be fully verified without persistence?
> Should an existing planner action be checked without replacement? Is an
> adopted transition explicitly authorized for *this exact* proposal?

**Default: `disabled`.** Nothing is constructed, nothing runs, and
canonical behavior is unchanged.

## 1. Authority boundary

- `ExperienceManager` remains lifecycle-policy authority.
- `ExperienceEngine._apply_memory_actions` remains the **sole** durable
  mutation boundary.
- The coordinator orchestrates; it is not an authority. It has **no store
  field and no mutation method**, never calls create/supersede/forget or
  `_apply_memory_actions`, and cannot authorize itself.
- There is **no second mutation path**: an authorized action is appended
  to the same `valid_actions` list the engine already applies, after the
  same admission check every controller-derived action faces.

Four statements, never interchangeable:

| Statement | Meaning |
|---|---|
| controller proposal | a controller thinks this transition fits |
| verifier acceptance | the proposal is defensible |
| authorization | this exact proposal may influence canonical actions |
| `action_applied` | the engine's existing path actually applied it |

Only the last is an application, and only the engine sets it.

## 2. The seam

The coordinator receives a statement, validated evidence, a detached
before-state snapshot, and (for verify-only) the existing canonical
actions. It routes, verifies, authorizes, and translates — then returns
*data*. The engine keeps every existing check.

The engine hook sits exactly where the grounded-extraction hook sits:
after the canonical plan is validated, before the sole mutation
boundary. Both are optional and default to `None`.

## 3. Modes

| Mode | Controllers | Verifier | Authorization | Translation | Canonical actions |
|---|---|---|---|---|---|
| **disabled** (default) | no | no | no | no | unchanged |
| **shadow** | yes | yes | no | no | diagnostics only |
| **candidate** | yes | yes | no | yes (inert) | candidate only |
| **verify_only** | no | yes (on existing actions) | no | no | verified, unchanged |
| **adopted** | yes | yes | **exact** | yes | action added, then engine decides |

Disabled, shadow, candidate, and verify-only **cannot mutate**, by
construction: they never produce `generated_actions`, and the engine only
merges when the effective mode is adopted *and* the effect is
`action_added`.

Candidate differs from shadow by exercising the complete translation path
short of insertion. Verify-only inspects canonical planner actions and
**never** adds, removes, or rewrites one — it reports `verified`,
`rejected`, `unverifiable`, `ambiguous`, `unsupported`, or
`not_transition_relevant`. Enforcement would need separate authorization
and evidence, and is not built here.

## 4. Routing

Mutually exclusive, deterministic, one proposal per source:

1. update classification runs first;
2. its explicit `forget_directive_detected` handoff — and only that —
   routes to forget targeting;
3. otherwise the update result stands.

Both controllers never produce competing proposals; nothing is merged or
ranked by confidence; the coordinator never reinterprets controller
semantics. Affirmative forget therefore cannot reach create or update
adoption, and negative forget cannot become a forget.

## 5. Exact adoption authorization

Adopted mode requires a `TransitionAuthorization` bound to **the exact
verified proposal**. Every field must match; any difference fails closed
and names the mismatched field:

authorization version, mode, system id, controller id and version,
request id, source digest, evidence mode, evidence digest, before-state
digest, proposal id, proposal digest, transition type, target ids,
created-memory digest, verifier id and version, verification digest,
expected action type, expected action count.

There is **no wildcard** — every binding field is required, so an
authorization naming only a controller cannot exist. Authorization never
substitutes for verification: an unverified, ineligible, ambiguous, or
rejected proposal is refused *before* any authorization is consulted.
Historical-oracle and development-fixture evidence can never reach a
canonical effect, because they are never `canonical_effect_eligible`.

Adopted mode needs all ten of: proposal, accepted verification,
production-eligible evidence, valid grounding, complete before-state
coverage, canonical eligibility, exact authorization, successful
translation, lifecycle admission, and successful engine application.

## 6. Translation

A narrow translator maps a verified transition onto **existing**
lifecycle actions and returns data only:

| Transition | Existing actions |
|---|---|
| `create_new` | one `create` |
| `scoped_coexistence` | one `create`, no supersession |
| `supersede_existing` | `supersede` + replacement `create` carrying `replaces` |
| `forget_existing` | one `forget`, one active target, no create |
| duplicates, rejections, shadow | none |

Supersession uses the repository's own canonical representation — the
same pair the semantic planner emits, which the engine already links. No
new action type is invented, and translation fails closed whenever
existing vocabulary cannot represent a transition safely (inactive
target, missing replacement, a forget carrying a create).

## 7. Configuration

```python
from experienceos.memory.transition_integration import (
    TransitionIntegrationConfig, TransitionIntegrationMode,
)

agent = ExperienceOS(
    model=provider,
    transition=TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.SHADOW
    ),
)
```

`transition=None` (the default) constructs nothing. **There is no
environment-variable path**: adopted mode needs a structured config in
code *plus* an authorization bound to an exact verified proposal, so a
stray string can never enable a canonical effect. A bare string raises.

## 8. Diagnostics and annotations

Every result states configured mode, effective mode, system id, route,
controller id/version, whether the controller/verifier/authorization/
translation ran, canonical action effect, canonical effect status,
generated action types, fallback, failure stage and reason, and
`action_applied`. Nothing is inferred from a missing field.

Stable codes across the categories mode, routing, controller, verifier,
evidence, grounding, before-state, authorization, translation, lifecycle
admission, application, and fallback — e.g. `transition_disabled`,
`update_controller_selected`, `forget_controller_selected`,
`proposal_generated`, `verification_accepted`, `verification_rejected`,
`canonical_effect_ineligible`, `authorization_missing`,
`authorization_mismatch`, `authorization_accepted`,
`translation_succeeded`, `translation_failed`,
`canonical_actions_unchanged`, `candidate_action_not_inserted`,
`existing_action_verified`, `existing_action_rejected`,
`fallback_to_baseline`.

The `transition_integration_evaluated` event is additive and emitted only
when a coordinator is configured and enabled. Annotations are versioned
(`annotation_version`), deterministically serialized, and carry no keys,
secrets, paths, prompts, or unrelated memory text. Old events without
transition metadata remain readable.

## 9. Failure handling

Controller, verifier, authorization, and translation failures are
contained and produce bounded diagnostics: a component type, a failure
stage, and an exception *type name* — never a message, source text beyond
bounded diagnostics, or a path. Every failure preserves baseline
behavior; there is no silent fallback from an unsafe adopted transition
to an unverified controller action.

## 10. Measured infrastructure smoke

```bash
./scripts/run_benchmarks.sh smoke-transition-integration
python -m pytest tests/test_transition_integration.py
```

Ten bounded sources per mode:

| Mode | Proposals | Verifier | Generated actions | Applied |
|---|---|---|---|---|
| disabled | 0 | 0 | 0 | 0 |
| shadow | 10 | 10 | 0 | 0 |
| candidate | 10 | 10 | 0 | 0 |
| verify_only | 0 | — | 0 | 0 |
| adopted (isolated) | 4 mutating | 4 | 5 (`supersede` 1, `create` 3, `forget` 1) | 0 |

Authorization: 4 exact matches, 4 missing rejected, 4 single-field
mismatches rejected, 2 audit-only evidence modes refused. Controller
calls in disabled: **0**. Applications in disabled/shadow/candidate/
verify-only: **0**. p95 latency 0.38 ms.

**This is infrastructure evidence, not adoption evidence.** No adoption
gate is evaluated, no controller is canonical, and no benchmark
comparison is made here.

## 11. Known limitations

- Adopted mode is exercised only in isolated infrastructure paths and is
  never a default in the SDK, demo, dashboard, or tests.
- No benchmark adoption decision; the adoption gates are unevaluated.
- Authorization is in-memory and immutable — appropriate for this stage,
  not a production authorization service. `single_use` is represented but
  not enforced across processes.
- Verify-only diagnoses planner weaknesses without enforcing rejection.
- Optional annotations are stable data; full dashboard presentation is
  separate work.
- The typed `grounding_validation` field remains unfixed (see below).
- Bounded deterministic controller domains; no learned controller; no
  bulk forget.

## 12. Typed-evidence defect

`TransitionSourceEvidence.grounding_validation` is still a class
attribute rather than a constructible field. Integration **does not
require it**: authorization binds the evidence mode plus a digest of the
evidence record, which already covers grounding provenance exactly, so
the field would add nothing to the binding. It stays unchanged, and
frozen code stays untouched.

## 13. Claims not supported

Transition adoption gates passed; a canonical transition controller;
canonical lifecycle improvement; autonomous memory management;
production-grade authorization; learned-controller adoption; production
deployment; improved final answer quality; benchmark superiority; safe
broad forgetting.

## 14. Boundary to later work

Benchmarking and adoption classification are separate: the reference,
shadow, candidate, rules, and adopted-infrastructure systems can be
compared without redefining any integration semantics here. Full
dashboard presentation consumes the stable annotations this seam emits.
The binding definitions live in
`docs/transition_verification_contract.md`.
