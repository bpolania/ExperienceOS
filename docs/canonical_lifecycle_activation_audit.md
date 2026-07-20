# Canonical chat-path lifecycle activation audit

Traces the canonical chat execution path for ordinary creation, update
statements, and forget statements to locate exactly where update/forget
lifecycle intent is lost and to identify the missing activation seam.
Audit only — no code changed. Answers the central activation question: **why does
the canonical chat path still behave as create-only when deterministic
update, forget, transition-verification, authorization, and governed
application infrastructure already exist?**

## 1. Verified starting baseline

- branch `main`, local HEAD `d04ac6d`, upstream `origin/main` (`350f389`),
  ahead 2 / behind 0, 0 merges, clean tree, nothing pushed.
- Competitive evidence published and frozen (`origin/main` ==
  `350f389`); investigative artifacts present.
- Frozen hashes unchanged: viability manifest `9c7f3009…`, raw records
  `bb9c1362…`. Core `experienceos/` is 0-line diff vs the published
  baseline `6f893f9`. No tracked secrets.
- Full test suite: **2673 passed**. Demo validation: passed.
- Core lifecycle and transition infrastructure already implemented; no
  runtime correction applied.

## 2. The two lifecycle mechanisms that exist today

ExperienceOS contains **two** separate lifecycle-action generators:

1. **The default `MemoryPlanner`** (`experienceos/memory/planner.py`),
   wrapped by `RuleBasedMemoryPolicy` and used by every `agent.chat`
   turn. It *can* emit `SUPERSEDE` and `FORGET`, but only when its narrow,
   keyed matchers fire: preference supersession needs a recognized
   `preference_domain`, fact/instruction supersession needs a recognized
   `update_key`, and forgetting needs a content-word topic match.
2. **The transition integration machinery** — the deterministic update
   controller (`DeterministicUpdateController`, at ceiling on the frozen
   transition corpus), a forget controller, a transition verifier, exact
   `TransitionAuthorization`, and governed action replacement — all behind
   the `TransitionIntegrationCoordinator` seam
   (`experienceos/memory/transition_integration.py`). It is fully built
   and exercised by `tests/test_transition_integration.py` and
   `benchmarks/transition_benchmark/`.

Only mechanism 1 runs on the canonical chat path. Mechanism 2 is gated
behind a coordinator that the canonical composition never configures.

## 3. Canonical chat execution path (from `ExperienceEngine.run_interaction`)

```
user message
  → memory policy / planner            (RuleBasedMemoryPolicy → MemoryPlanner)   [always]
  → experience_manager.plan(...)       → valid_actions (the canonical plan)      [always]
  → extraction_coordinator.evaluate    (Qwen extraction, candidate mode)         [enabled, NON-MUTATING]
  → transition_coordinator._evaluate   (update/forget intelligence + verify +    [None → DISABLED, NOT RUN]
                                         authorization + action replacement)
  → _apply_memory_actions(valid_actions)  (sole mutation boundary)               [always]
  → persisted lifecycle state
```

Engine evidence: the transition seam runs **only** `if
self.transition_coordinator is not None and
self.transition_coordinator.enabled`
(`experience_engine.py:196–202`); "disabled does nothing … only an
authorized adopted action is merged." The canonical demo composition
builds the agent with `transition=None`
(`demo/support.py:116,136`; the Qwen system adapter passes only
`extraction=`), so `transition_coordinator` is `None`.
`TransitionIntegrationConfig.mode` defaults to `DISABLED`
(`transition_integration.py:265`).

## 4. Stage-by-stage trace — ordinary creation (works)

| Stage | Input | Output | Mode / controller | Update/forget runs | Transition proposal | Verify | Authorize | Canonical effect | Final action list | Persisted |
|---|---|---|---|---|---|---|---|---|---|---|
| planner/policy | new durable statement, active memories | one `CREATE` | rule_based `MemoryPlanner` | n/a (no conflict) | no | no | no | create | `[create]` | new memory ACTIVE |
| extraction (Qwen) | same message | candidate | candidate mode | n/a | no | no | no | none (non-mutating) | unchanged | unchanged |
| transition | — | — | **disabled** | no | no | no | no | none | unchanged | unchanged |
| apply | `[create]` | applied | engine | — | — | — | — | create | `[create]` | ACTIVE |

Ordinary creation is correct and must be preserved.

## 5. Stage-by-stage trace — update statement (intent lost)

Example: existing "Prefers tea in the morning." + "Actually, I prefer
coffee in the morning." (cases `updates_001` / `containment_002`).

| Stage | Input | Output | Mode / controller | Update/forget runs | Transition proposal | Verify | Authorize | Canonical effect | Final action list | Persisted |
|---|---|---|---|---|---|---|---|---|---|---|
| planner/policy | coffee statement, [tea active] | **`CREATE` only** | rule_based `MemoryPlanner` | supersede matcher runs but **misses** | no | no | no | create | `[create coffee]` | tea + coffee both ACTIVE |
| extraction (Qwen) | coffee statement | candidate | candidate mode | no | no | no | no | none | unchanged | unchanged |
| transition | — | — | **disabled (None)** | **no** | **no** | **no** | **no** | none | unchanged | unchanged |
| apply | `[create coffee]` | applied | engine | — | — | — | — | create | `[create coffee]` | **tea stays ACTIVE** |

**Where the intent is lost (two independent gaps):**
1. The default planner's supersede matcher does not recognize the
   conflict: verified directly — `preference_domain("Prefers tea in the
   morning.")` returns **`None`** (and the same for "coffee"), so
   `_find_conflict` finds no target and the planner emits a bare `CREATE`.
   The `memory_action_planned` event confirms `planned_actions:
   [{action: create}]`, `rejected_actions: []`.
2. The transition coordinator — which would route the statement to the
   capable `update_controller`, verify the supersession, apply exact
   authorization, and use action replacement to suppress the conflicting
   planner create — is **disabled** on the canonical path, so it never
   runs.

## 6. Stage-by-stage trace — forget statement (intent lost)

Example: existing "Send my daily status summary to the #eng-daily
channel." + "Forget the instruction about my daily status channel."
(case `forgetting_005`); and "…evening study preference…"/"I don't
care about it anymore" (`forgetting_002`).

| Stage | Input | Output | Mode / controller | Update/forget runs | Transition proposal | Verify | Authorize | Canonical effect | Final action list | Persisted |
|---|---|---|---|---|---|---|---|---|---|---|
| planner/policy | forget directive, [instruction active] | **no action** | rule_based `MemoryPlanner` | forget-topic matcher runs but **misses** | no | no | no | none | `[]` | target stays ACTIVE |
| extraction (Qwen) | forget directive | candidate/none | candidate mode | no | no | no | no | none | unchanged | unchanged |
| transition | — | — | **disabled (None)** | **no** | **no** | **no** | **no** | none | unchanged | unchanged |
| apply | `[]` | nothing | engine | — | — | — | — | none | `[]` | **target stays ACTIVE** |

**Where the intent is lost (two independent gaps):**
1. The default planner's `_plan_forgets` content-word topic match does not
   match the directive to the stored instruction, so **no forget action**
   is produced (verified directly; the frozen run shows no proposal on the
   forget turn).
2. The transition coordinator's `forget_controller` route is disabled on
   the canonical path.

## 7. Per genuine case — where the transition was lost

| Case | Intended | Planner outcome | Transition coordinator | Result |
|---|---|---|---|---|
| context_005 | SUPERSEDE (dark→light) | create-only (domain unrecognized) | disabled | dark stays ACTIVE |
| retrieval_008 | SUPERSEDE (Pixel 6→9) | create-only (update_key unrecognized) | disabled | Pixel 6 stays ACTIVE |
| containment_002 | SUPERSEDE (tea→coffee) | create-only (`preference_domain`=None) | disabled | tea stays ACTIVE |
| forgetting_005 | FORGET (#eng-daily) | no action (topic unmatched) | disabled | instruction stays ACTIVE |

(The five known evaluator false positives share the same create-only
state but did not produce a genuinely stale answer.)

## 8. The missing / bypassed seam

The engine already supports governed transition activation between the
canonical plan and the sole mutation boundary
(`experience_engine.py:189–245`), applying an authorized adopted
transition through the *same* lifecycle check and the *same*
`_apply_memory_actions` path (no second mutation path). The capable
update/forget intelligence, transition verifier, exact authorization, and
action replacement are all built and tested. **The one thing missing is
configuration:** the canonical composition (`demo.support.create_agent`
and `build_canonical_extraction_config`) never constructs a
`TransitionIntegrationConfig`, so `transition_coordinator` is `None` /
disabled, and the chat path falls back to the default `MemoryPlanner`
whose keyed matchers are too narrow for these update/forget statements.

Adopted mode additionally requires authorizations bound to exact verified
proposals (and replacement authorizations to reuse action replacement) —
the exact-authorization infrastructure that the seam already enforces.

## 9. Answer to the central activation question

The canonical chat path behaves as create-only for these cases because
the capable deterministic update/forget/transition/authorization/
replacement machinery lives behind the **transition integration
coordinator seam, which the canonical demo composition never configures**
(`transition=None` → `DISABLED`). The only generator that runs on the
chat path is the default `MemoryPlanner`, whose domain/update-key/topic
matchers do not recognize these update and forget statements, so
they fall through to plain `create`. This is an **integration/activation
gap on the canonical composition**, not a missing capability and not a
downstream leakage problem.

## Decision

`CANONICAL_CHAT_PATH_AUDIT_COMPLETE`

The missing seam is identified precisely: the transition integration
coordinator (adopted mode + supplied update/forget controllers + verifier
+ exact authorizations + replacement authorizations) is not wired into
the canonical chat composition. No implementation is performed in this
step; connecting that existing seam is the subject of the next step.
