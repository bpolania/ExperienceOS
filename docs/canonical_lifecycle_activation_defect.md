# Canonical lifecycle activation defect classification

Proves precisely why the canonical chat path remains create-only for the
four genuine stale-answer failures, and whether a minimal, bounded
activation of the existing governed transition machinery is possible.
Classification only — no runtime behavior changed.

## 1. Decision

- **`CANONICAL_ACTIVATION_DEFECT_IDENTIFIED`** — the defect is precisely
  classified with repository evidence.
- Implementation readiness: **`MINIMAL_CANONICAL_ACTIVATION_BLOCKED`**.

The capable deterministic update/forget/verify/replacement machinery is
fully built, correct on all four genuine cases, and already reachable
from the engine seam. But **exact authorization cannot be satisfied for a
general runtime chat path with a bounded configuration change**: adopted
mode requires an authorization bound to the *exact runtime proposal*, the
coordinator cannot authorize itself, and an unconditional runtime
auto-authorizer is the wildcard authority the phase forbids. This trips
an activation stop condition. A negative result is acceptable.

## 2. Verified starting state

branch `main`; HEAD `dbd9a80`; parent `d04ac6d`; upstream `origin/main`;
direct remote `main` `350f389`; ahead 2 / behind 0; 0 merges; clean tree;
0 staged, 0 untracked non-ignored. the audit commit `dbd9a80`
present with `docs/canonical_lifecycle_activation_audit.md`. Phase 17
published (`origin/main` == `350f389`) and frozen; Phase 18 artifacts
present. Core `experienceos/` 0-line diff vs the published baseline
`6f893f9`. Frozen hashes unchanged (`9c7f3009…`, `bb9c1362…`). No tracked
secrets. `dbd9a80` is the actual HEAD.

## 3. Prior audit revalidation

| # | Prior-audit conclusion | Evidence | Result |
|---|---|---|---|
| 1 | Default `MemoryPlanner` runs every chat turn | `experience_engine.py:54` `self.memory_planner or MemoryPlanner()` | CONFIRMED |
| 2 | Wrapped by `RuleBasedMemoryPolicy` | `experience_engine.py:56` | CONFIRMED |
| 3 | Planner can emit SUPERSEDE/FORGET | `planner.py` SUPERSEDE (328), `_plan_forgets` (407) | CONFIRMED |
| 4 | Keyed update matcher misses the genuine updates | pure call: `preference_domain("Prefers tea in the morning.")` = `None` → bare create | CONFIRMED |
| 5 | Forget-topic matcher misses the genuine forgets | pure call: no forget action produced | CONFIRMED |
| 6 | Coordinator invoked only when configured | `experience_engine.py:196–201` `if transition_coordinator is not None and enabled` | CONFIRMED |
| 7 | Invocation after planning, before mutation | seam at `experience_engine.py:189–245`, before `_apply_memory_actions(245)` | CONFIRMED |
| 8 | `TransitionIntegrationConfig.mode` defaults DISABLED | `transition_integration.py:265` | CONFIRMED |
| 9 | Canonical demo passes `transition=None` | `demo/support.py:116,136` | CONFIRMED |
| 10 | Canonical Qwen composition uses no transition | `qwen_system.py` passes only `extraction=` (test-pinned) | CONFIRMED |
| 11 | No alternate root enables the coordinator | grep: no non-None `transition=` in demo/experiments/benchmarks/examples | CONFIRMED |
| 12 | No env var / flag / factory enables it later | `sdk.py:139` "There is no environment-variable path" | CONFIRMED |
| 13 | Machinery not already active in another layer | coordinator holds no store, no mutation; engine is sole boundary | CONFIRMED |

No prior-audit conclusion is disproved.

## 4. Defect taxonomy classification

| Classification | Result | Evidence |
|---|---|---|
| update controller not invoked | **CONTRIBUTING** | coordinator disabled → `DeterministicUpdateController` never routed |
| forget controller not invoked | **CONTRIBUTING** | coordinator disabled → `DeterministicForgetController` never routed |
| transition mode disabled | **CONTRIBUTING** | config default `DISABLED`; canonical roots pass `transition=None` |
| transition proposal discarded | NOT_PRESENT | no proposal is generated at all (coordinator never runs) |
| verification not reached | CONTRIBUTING (consequence) | verifier not reached because coordinator disabled |
| authorization unavailable | **PRIMARY (deep blocker)** | exact per-proposal authorization cannot be pre-configured for a runtime path (§10) |
| adopted effect not enabled | **PRIMARY** | adopted is the only mutating mode; never selected on any canonical root |
| action replacement not invoked | CONTRIBUTING (consequence) | replacement runs only in adopted supersede-bearing + replacement-auth path |
| canonical planner output bypasses transition integration | NOT_PRESENT | engine DOES route through the seam when configured; the seam is simply disabled |
| extracted proposal shape insufficient | NOT_PRESENT | inputs are sufficient (§8) |
| controller selection misconfiguration | NOT_PRESENT | controllers are correct and identified (§7) |
| demo composition seam misconfiguration | **PRIMARY** | no canonical composition constructs a coordinator; the only builder refuses adopted |
| unsupported mode combination | NOT_PRESENT | adopted supports both update and forget |
| another precisely evidenced cause | **PRIMARY** | exact-authorization model deliberately withholds autonomous adoption (§10, §16) |

Exact facts: the object not constructed is a `TransitionIntegrationCoordinator`
in adopted mode; the argument set to `None` is `transition` on
`create_agent`/`ExperienceOS(...)` (and the Qwen system adapter omits it);
the default mode is `TransitionIntegrationMode.DISABLED`; the engine
branch taken is the early return (transition seam skipped because
`transition_coordinator is None`); the stronger path skipped is
`update_controller`/`forget_controller` → verifier → authorization →
governed replacement; the fallback behavior is planner-only (`create` for
updates, no action for forgets); the resulting final action list is
`[create]` (updates) or `[]` (forgets).

## 5. Canonical composition analysis

| Composition Root | Transition Arg | Config Mode | Update Ctrl | Forget Ctrl | Verifier | Authorization | Replacement Auth | Effective Result |
|---|---|---|---|---|---|---|---|---|
| `demo.support.create_agent` | `None` (default) | — | — | — | — | — | — | coordinator=None (disabled) |
| `demo/app.py rebuild_agent` | `build_transition_config(mode)`; default `disabled`→`None` | disabled/shadow/candidate/verify_only | none | none | none | none | none | non-mutating at most; adopted **refused** |
| `experiments/…/qwen_system.py` (canonical answer run) | absent (only `extraction=`) | — | — | — | — | — | — | coordinator=None (disabled) |
| `experienceos/sdk.py ExperienceOS` | `None` (default) | — | — | — | — | — | — | coordinator=None (disabled) |
| benchmark `transition_benchmark/systems.py` | ADOPTED **with per-record authorization** | adopted | real | real | real | real (per record) | (not always) | mutating — but **not canonical**; authorization built per known record |

The defect is **more than one** of the row categories: `transition=None`
on every canonical root, and (where a builder exists) adopted mode is
refused and no controllers/authorizations are supplied. Changing only
canonical composition **cannot** make the engine branch reachable for a
general runtime path, because of §10.

## 6. Transition mode analysis

| Mode | Controllers run | Proposal | Verify | Authorize | Observes only | Replaces actions | Durable mutation | Suitable for canonical effect |
|---|---|---|---|---|---|---|---|---|
| disabled | no | no | no | no | — | no | no | no (preserves planner-only) |
| shadow | yes | yes | yes | no | yes (diagnostics only) | no | no | no (never alters action list) |
| candidate | yes | yes | yes | no | yes (translation, no insert) | no | no | no |
| verify_only | no (inspects planner actions) | no | yes (on existing) | no | yes | no | no | no (never injects transitions) |
| **adopted** | yes | yes | yes | **yes** | no | yes (with replacement auth) | **yes** | **yes — the only mutating mode** |

`DISABLED` preserves current planner-only behavior. Shadow/candidate/
verify-only never change the canonical action list, so they cannot fix
create-only. **Adopted is the minimal existing effect mode** and supports
both update and forget; it preserves planner fallback when no safe
transition exists (§12). Classification: **`EXISTING_ADOPTED_MODE_SUFFICIENT`**
as the mode — but gated by authorization (§10). No new mode required.

## 7. Controller selection

Update: **`DeterministicUpdateController`** (`update_intelligence.py:309`,
id `experienceos_transition_rules_v1`). Deterministic ("No providers, no
model, no network"); the implementation scored at ceiling on the frozen
transition corpus; **not** the experimental Qwen update controller. Input
`propose(statement, evidence, before_state)`; output `UpdateProposalResult`
with a `ProposedTransition` (`supersede_existing` → superseded_ids +
replacement create with lineage; `scoped_coexistence`; `create_new`);
forget directives abstain with `FORGET_HANDOFF`; abstains on incomplete
identity; scope preserved via identity projection.

Forget: **`DeterministicForgetController`** (`forget_intelligence.py:346`,
id `experienceos_forget_rules_v1`). Deterministic; identity-projection
matching; negative-forget never removes (asserts/hands off); questions map
to frozen rejections; ambiguous/multi-target → `reject_ambiguous`; a safe
single active target → `forgotten_ids=(target,)`.

**Classification: `CANONICAL_DETERMINISTIC_CONTROLLERS_IDENTIFIED`.**
Verified by pure call: both controllers produce the correct supersede/
forget with the correct target for all four genuine cases.

## 8. Input and proposal sufficiency

The engine already builds the full request from canonical inputs
(`experience_engine.py:_evaluate_transition`): `statement=message`,
`evidence` (grounded-valid), `before_state=build_before_state(memories,
user_id)` (the active-memory snapshot), `request_id`, `user_id`,
`existing_actions=valid_actions` (planner actions). Per genuine case:

| Case | Inputs available at runtime | Controller result (pure call) | Classification |
|---|---|---|---|
| updates_001 / containment_002 (tea→coffee) | message + active [tea] + planner create | `supersede_existing` target food.morning_drink | `SUFFICIENT_USING_EXISTING_CANONICAL_INPUTS` |
| context_005 (dark→light) | message + active [dark] + planner create | `supersede_existing` target editor.color_mode | `SUFFICIENT_USING_EXISTING_CANONICAL_INPUTS` |
| retrieval_008 (Pixel 6→9) | message + active [Pixel 6] + planner create | `supersede_existing` target device.phone | `SUFFICIENT_USING_EXISTING_CANONICAL_INPUTS` |
| forgetting_005 (forget #eng-daily) | turn-1 directive + active [instruction] | `forget_existing` target work.daily_status_channel | `SUFFICIENT_USING_EXISTING_CANONICAL_INPUTS` |

No extraction change is required; no synthetic fields; the frozen expected
answers/annotations are not used as runtime input.

## 9. Transition verification

The verifier is **`TransitionVerifier`** (`transition_verification.py:699`,
id `transition_rules-1`), deterministic and non-mutating, lazily built by
the coordinator. It receives the controller's `ProposedTransition` and the
`before_state`; enforces structure, evidence usability, source durability,
target activeness/uniqueness, identity-relation match, lifecycle,
projected after-state preservation of unrelated actives, and lineage
(update: `(target, created:0)`; forget: precondition `target_active`).
Verification occurs **before** authorization and **before** action
replacement and manager admission; a transition effect cannot occur if
verification fails (adopted `_authorize` returns `proposal_not_verified` /
`canonical_effect_ineligible`). On rejection: `AUTHORIZATION_DENIED`,
`fallback_used=True`, no generated actions → planner actions preserved. No
partial lifecycle effect. Both update and forget are covered. For the four
genuine cases the verifier would **accept** (the controllers already
produce structurally valid, target-active, lineage-correct proposals).

## 10. Exact authorization (the binding blocker)

Authorization is **`TransitionAuthorization`** (`transition_integration.py:173`),
a frozen, deterministic, immutable permission for **one exact verified
proposal**. Its `binding()` includes `request_id`, `source_digest`,
`before_state_digest`, `proposal_id`, `proposal_digest`, `created_digest`,
`verifier_id/version`, `verification_digest`, `transition_type`,
`target_ids`; `scope="single_proposal"`, `single_use=True`. `_authorize`
(`:976`) matches by **exact field equality** against `expected_binding`
(the runtime request+proposal+verification); any mismatch fails closed;
no candidates → `authorization_missing` → no adopted effect. The factory
`build_authorization(coordinator, request, proposal, verification,
translation)` (`:1211`) builds the binding from the **actual runtime
proposal**.

Answers:
1. Does canonical composition already have the info to issue exact
   authorization? **No** — the required digests (`before_state_digest`
   depends on the runtime memories' random UUIDs; `proposal_digest`,
   `verification_digest`) exist only *after* the coordinator runs at
   runtime, per turn.
2. Existing factory? Yes (`build_authorization`) — but it needs the
   runtime proposal, and the two existing full-adopted assemblies
   (`systems._run_adopted`, the real-case test) call it **per known
   record** in test/benchmark context, not for arbitrary runtime input.
3. Deterministic? Yes. 4. Bound to the plan? Yes, exactly.
5. Replacement separately authorized? Yes (`ReplacementAuthorization` via
   `authorization_from_plan`, also runtime-bound).
6/7. Can update+forget be authorized without broad changes / would it need
   global or wildcard authority? **A general runtime path would require an
   unconditional auto-authorizer** that issues an authorization for every
   verified transition — functionally global authority, and the design
   states the coordinator "cannot authorize itself." 8. Any bypass needed?
   Yes, which is forbidden.

**Classification: `AUTHORIZATION_REQUIRES_BROAD_CHANGE`.** A static
config-time authorization cannot match runtime proposals; the only way to
authorize arbitrary runtime transitions is a new standing/auto adoption
authority, which is the wildcard authority the phase forbids.

## 11. Governed action replacement

`build_replacement(...)` (`action_replacement/integration.py:27`) consumes
the planner CREATE, matches the exact create by **occurrence identity** +
semantic-duplicate relation, and either replaces (suppress-then-insert) or
fails closed to planner-only. Multiple matches → `REJECTED_MULTIPLE_MATCHES`;
unrelated target → `REJECTED_UNRELATED_ACTION`; scope-coexistence preserved;
unrelated actions preserved; lineage preserved; **never appends both
creates** (`experience_engine.py:595–596`). Reachable only in adopted +
supersede-bearing + a matching `replacement_authorizations`
(`experience_engine.py:465`). Update cases require replacement (to suppress
the conflicting planner create); forget cases do not (no planner create;
final list is just `[forget]`).

**Classification: `GOVERNED_ACTION_REPLACEMENT_REUSABLE`** (with the same
per-proposal replacement-authorization gate as §10).

## 12. Planner fallback

Every non-adopted-success coordinator path returns `generated_actions=()`
and leaves `valid_actions` untouched: controller abstains, no proposal,
verifier rejects, authorization missing/denied, translation fails, or
controller raises (bounded failure). Ordinary create, semantic duplicate,
ambiguous update/forget, negative forget, question, unsupported statement,
verifier rejection, authorization rejection, and disabled/offline mode all
preserve planner behavior (tests: `test_missing_authorization_fails_closed`,
`test_controller_exception_is_contained_and_falls_back_to_baseline`,
`test_non_adopted_modes_never_generate_actions`).

**Classification: `PLANNER_FALLBACK_PRESERVED`.**

## 13. Single mutation boundary

The coordinator holds **no store** and has **no mutation method**; it
produces/rewrites an action list as data only (module + class docstrings).
`ExperienceManager` remains authoritative for admission; `ExperienceEngine`
remains the sole durable mutation boundary (`_apply_memory_actions`); the
adopted action passes the SAME admission check and the SAME application
path; MemoryStore semantics unchanged; retrieval still depends only on
persisted lifecycle state.

**Classification: `SINGLE_MUTATION_BOUNDARY_PRESERVED_WITH_EXISTING_SEAM`.**

## 14. Four genuine Phase 18 cases

| Case | Type | Planner result | Controller result | Verifier | Authorization available | Replacement needed | Adopted supports effect | Exact defect |
|---|---|---|---|---|---|---|---|---|
| updates_001 / containment_002 | update | create-only (`preference_domain`=None) | `supersede_existing` food.morning_drink | accept | **not for runtime** | yes | yes | coordinator disabled + runtime auth unavailable |
| context_005 | update | create-only | `supersede_existing` editor.color_mode | accept | **not for runtime** | yes | yes | same |
| retrieval_008 | update | create-only (`update_key` unrecognized) | `supersede_existing` device.phone | accept | **not for runtime** | yes | yes | same |
| forgetting_005 | forget | no action (topic unmatched) | `forget_existing` work.daily_status_channel | accept | **not for runtime** | no | yes | coordinator disabled + runtime auth unavailable |

Loss sequence (all four): planner matcher misses target → planner emits
`create` or no lifecycle action → canonical composition supplies no
transition coordinator → engine skips the transition seam → controller,
verifier, authorization, replacement never reached → planner action list
reaches the manager unchanged → obsolete memory remains ACTIVE. Update and
forget share the **same activation defect**; they differ only in whether
governed replacement is needed. The deeper, shared blocker is exact
runtime authorization.

## 15. Primary cause

**`DEMO_AND_CANONICAL_COMPOSITION_DO_NOT_CONFIGURE_TRANSITION_INTEGRATION`**,
and — decisively — the **exact-authorization model deliberately withholds
autonomous runtime adoption**: adopted mode is the only mutating mode and
requires an authorization bound to the exact runtime proposal, which a
bounded composition change cannot supply for a general path.

## 16. Contributing conditions

- `TRANSITION_MODE_DEFAULTS_TO_DISABLED` (safety-preserving default).
- `DEFAULT_PLANNER_MATCHERS_ARE_TOO_NARROW_FOR_THE_GENUINE_CASES`
  (explains why planner-only fails).
- `UPDATE_CONTROLLER_NOT_INVOKED`, `FORGET_CONTROLLER_NOT_INVOKED`,
  `VERIFICATION_NOT_REACHED`, `ACTION_REPLACEMENT_NOT_REACHED` — all
  consequences of the disabled coordinator, not independent defects.

## 17. Non-defects

The controllers, verifier, exact authorization, action replacement,
manager admission, and engine mutation boundary are **not defective** —
they are correct and simply not reached. The disabled default is a
deliberate safety design, not a bug. Verifier/authorization/replacement
are not defective merely because they are unreached.

## 18. Stop-condition assessment

| Stop condition | Status |
|---|---|
| canonical path already invokes the required infrastructure | NOT_TRIGGERED |
| failure lies in unsupported intelligence | NOT_TRIGGERED (intelligence is correct on all four cases) |
| activation requires transition-intelligence redesign | NOT_TRIGGERED |
| activation requires Qwen update intelligence | NOT_TRIGGERED |
| **exact authorization cannot be satisfied without broad changes** | **TRIGGERED** |
| action replacement cannot be reused safely | NOT_TRIGGERED (reusable) |
| forget requires broad multi-target support | NOT_TRIGGERED (single-target suffices) |
| scoped memories would regress | NOT_TRIGGERED (verifier/replacement preserve scope) |
| unrelated memories would regress | NOT_TRIGGERED |
| ordinary creation would regress | NOT_TRIGGERED (planner fallback preserved) |
| state-corruption risk cannot be bounded | NOT_TRIGGERED |
| frozen corpus modification required | NOT_TRIGGERED |
| second mutation path required | NOT_TRIGGERED (single boundary preserved) |

One TRIGGERED condition (exact authorization) blocks minimal activation.

## 19. Minimal activation change boundary (not authorized here)

If — and only if — the maintainers authorize introducing a standing adoption
authority (a policy decision that supplies the runtime authorization the
exact-authorization model deliberately withholds), the narrowest boundary
would be: the canonical composition factory (`demo/support.py`), the Qwen
system adapter, a transition-coordinator construction helper reusing the
existing components, and focused tests — reusing:
`TransitionIntegrationConfig` (adopted) → existing
`DeterministicUpdateController` → existing `DeterministicForgetController`
→ existing `TransitionVerifier` → per-proposal `TransitionAuthorization`
(via `build_authorization`) → per-plan `ReplacementAuthorization` (via
`authorization_from_plan`) → existing `TransitionIntegrationCoordinator` →
existing `ExperienceEngine` transition seam. Any activation step must **not** change
controller algorithms, verifier rules, authorization semantics,
replacement semantics, manager/engine mutation behavior, store semantics,
extraction schema, retrieval, context building, benchmark data, or scoring.
**However, because supplying runtime authorization for arbitrary
statements is functionally the wildcard authority the phase forbids, this
boundary is not currently unblocked.**

## 20. Implementation readiness

**`MINIMAL_CANONICAL_ACTIVATION_BLOCKED`.** All components except
authorization are ready for reuse. The single blocker is exact runtime
authorization, which cannot be satisfied by a bounded config-only change
and whose only resolution (a standing/auto adoption authority) is the
forbidden wildcard authority. The minimal activation step should not
proceed as a bounded config change under the current constraints.

## 21. Commands and evidence

- `preference_domain("Prefers tea in the morning.")` → `None` (pure call).
- `DeterministicUpdateController.propose(...)` → `supersede_existing` with
  correct target for tea→coffee, dark→light, Pixel 6→9 (pure calls).
- `DeterministicForgetController.propose(...)` → `forget_existing` with
  correct target for the #eng-daily forget directive (pure call).
- `create_agent(MockProvider()).transition_coordinator is None` (test).
- `build_transition_config("adopted")` raises (test).
- `TransitionIntegrationConfig().mode == DISABLED`, enabled False (test).
- `TransitionAuthorization` binds `request_id/before_state_digest/
  proposal_digest/verification_digest`, `scope=single_proposal`,
  `single_use=True` (test).
- Compile, full suite, demo validation, and targeted suites: §Validation.

## 22. Limitations

The runtime-authorization conclusion is an architectural/design judgment:
the exact-authorization model *technically* permits per-proposal
authorization, but issuing it unconditionally at runtime is the wildcard
adoption the phase forbids; whether to introduce a standing adoption
authority is a governance policy decision, not a bounded integration fix. The
controller-correctness evidence uses reconstructed before-states matching
the frozen cases; runtime UUIDs differ but the transition types/targets
are deterministic and stable.
