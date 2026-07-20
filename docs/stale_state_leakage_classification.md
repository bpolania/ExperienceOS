# Stale-state leakage source classification

Root-cause classification of the nine canonical stale-answer failures,
tracing each through the governed answer path in the required order to
determine **why each obsolete value remained available to the response
model**. Analysis only — no correction implemented; no change to
extraction, validation, governance, lifecycle, retrieval, context
construction, prompts, generation, scoring, or benchmark artifacts.

Machine-readable companion:
`benchmarks/results/committed/competitive-viability/stale_leakage_classification.json`
(sha256 `034bd8e588336ed7…`). The failure-inventory evidence:
`…/stale_failure_evidence.json` (sha256 `209a64dc72e65e87…`).

## 1. Verified starting state

- branch `main`, local HEAD `7563fce`, upstream `origin/main`
  (`350f389`), ahead 1 / behind 0, 0 merges, clean tree, nothing pushed.
- The failure-inventory commit `7563fce` is an ancestor of HEAD; its artifacts
  (`docs/stale_state_failure_analysis.md`, `stale_failure_evidence.json`)
  are present.
- Frozen artifacts verified unchanged by hash: viability manifest
  `9c7f3009…`, raw records `bb9c1362…`. Core `experienceos/` is 0-line
  diff vs the published baseline `6f893f9`. No frozen artifact,
  benchmark case, scoring rule, answer prompt, or judge prompt changed;
  no implementation correction has been introduced.

## 2. Methodology

Each case was traced in the required order — user statement → extraction
proposal → grounded validation → authorized actions → transition
application → persisted state → eligibility → retrieval → ranking →
selection → rendered memory context → conversation history → final prompt
→ final answer → evaluator verdict — using the frozen execution records
(`records.jsonl`), the scenario oracle, and the frozen score records. The
governed memory path is deterministic and independent of the response
model, so a single **offline reconstruction** (`MockProvider`, no
network) reproduced the frozen memory state exactly (identical
active/superseded/forgotten sets; only random UUIDs differ) and exposed
the planner decision via the `memory_action_planned` event. The primary
question answered first, per case, is: **did the governed lifecycle ever
contain the correct current state?** An active obsolete memory correctly
surfaced by retrieval is treated as retrieval *correctly exposing* an
upstream state failure, not a retrieval error.

## 3. Intended lifecycle outcome (per case)

| Case | Intended op | Prior state | Statement that should affect memory | Expected current | Obsolete | Expected final states |
|---|---|---|---|---|---|---|
| updates_001 | SUPERSEDE | tea active | "Actually, I prefer coffee" | coffee | tea | coffee active, tea superseded |
| updates_003 | SUPERSEDE | eng-daily active | "…#eng-standup instead" | eng-standup | eng-daily | standup active, daily superseded |
| updates_008 | SUPERSEDE | daily→standup | "…goes to #team-updates now" | team-updates | eng-standup/daily | team-updates active, prior superseded |
| context_005 | SUPERSEDE | dark active | "Switch that — light mode now" | light | dark | light active, dark superseded |
| context_006 | NO_MEMORY_CHANGE | peanut-dislike active | (query only) | peanut-dislike | (none) | peanut-dislike active |
| retrieval_008 | SUPERSEDE | Pixel 6 active | "I upgraded — Pixel 9 now" | Pixel 9 | Pixel 6 | Pixel 9 active, Pixel 6 superseded |
| containment_002 | SUPERSEDE | tea active | "Actually, I prefer coffee" | coffee | tea | coffee active, tea superseded |
| forgetting_002 | FORGET | evening active | "I don't care about my study preference anymore" | (none) | evening | evening forgotten |
| forgetting_005 | FORGET | eng-daily active | "Forget the instruction about my daily status channel" | (none) | eng-daily | eng-daily forgotten |

## 4. Extraction trace

For every SUPERSEDE case, the mutating memory path (the SDK default
rule-based memory policy, `decision_source: rule_based`) planned a plain
**`create`** for the new value with `target_memory_id=None` and
`replaces=None` — no supersede intent and no target. For both FORGET
cases the forget directive produced **no memory action at all** (no
proposal, no applied action). The Qwen extraction overlay ran in
candidate mode (non-mutating) and did not affect the store. Evidence:
per-turn `proposals`/`applied_actions` in `records.jsonl` and the
`memory_action_planned` event.

## 5. Validation trace

Grounded validation is **not reached for the lifecycle intent**: there
was never a supersede or forget proposal to validate. The created
memories were admitted; validation neither introduced nor removed a
replace/forget intent. No `VALIDATION_INTENT_LOSS` is observed.

## 6. Governance matching and action trace

Governance admitted exactly what the policy planned: `create` (updates)
or nothing (forgets). No supersede was matched or admitted; no forget was
applied; `rejected_actions` is empty. The transition intelligence that
performs supersession/forgetting (the deterministic transition
controller evaluated in the update benchmark) is **not on the default
chat path** exercised by the canonical demo composition. There is no
evidence of a wrong-target match — rather, no matching/replacement was
ever attempted.

## 7. Transition application trace

No supersede or forget transition was authorized, so none was applied.
`final_superseded = []` and `final_forgotten = []` in **all nine** cases.
Update cases created the new value as a **separate active memory**
beside the obsolete one. This is not a `TRANSITION_APPLICATION_ERROR`
(no correct action was authorized-but-unapplied); it is upstream of
transition application.

## 8. Persisted-state analysis

In every case the obsolete memory remained **active**. Consequently the
answer to *"did the governed lifecycle ever contain the correct current
state?"* is **PARTIALLY** for the SUPERSEDE cases (the current value is
active, but the obsolete value is also active), **NO** for the FORGET
cases (the value was never taken out of active state and there is no
replacement), and **YES** for `context_006` (no obsolete exists — its
active preference is correct).

## 9. Retrieval and context analysis

Because the obsolete memories were **active**, they were correctly
retrieval-eligible, correctly retrieved, and correctly selected —
retrieval, ranking, selection, and rendering all behaved **correctly
against the persisted state**. No `ELIGIBILITY_ERROR`, `RETRIEVAL_ERROR`,
`SELECTION_ERROR`, or `CONTEXT_RENDERING_ERROR` is present. In three
genuine cases (`context_005`, `retrieval_008`, `containment_002`) both
the current and the obsolete value were active and rendered together with
**no metadata distinguishing which is obsolete**. The obsolete value did
not enter through raw conversation history (ExperienceOS supplies
retrieved memory plus the current message, not prior turns).

## 10. Case-level classification matrix

| Case | Intended | Extractor | Governance | Persisted | Correct state ever | Obsolete eligible | Stale selected | Stale in rendered mem | Stale in history | Answer used stale | Verdict | Primary root cause | Downstream | Five-way | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| updates_001 | SUPERSEDE | create-only | create | tea active | PARTIALLY | yes | yes | yes | no | **no** (neg.) | stale=true | **EVALUATOR_ERROR** | none | EVALUATOR_FALSE_POSITIVE | high |
| updates_003 | SUPERSEDE | create-only | create | daily active | PARTIALLY | yes | yes | yes | no | **no** (contrast) | stale=true | **EVALUATOR_ERROR** | none | EVALUATOR_FALSE_POSITIVE | high |
| updates_008 | SUPERSEDE | create-only | create | prior active | PARTIALLY | yes | yes | yes | no | **no** (contrast) | stale=true | **EVALUATOR_ERROR** | none | EVALUATOR_FALSE_POSITIVE | high |
| context_005 | SUPERSEDE | create-only | create | dark active | PARTIALLY | yes | yes | yes | no | **yes** | stale=true | **EXTRACTION_INTENT_ERROR** | none | CURRENT_AND_STALE_BOTH_PRESENT | high |
| context_006 | NO_CHANGE | create | create | (current) | YES | n/a | no | no | no | **no** (peanut-free) | stale=true | **EVALUATOR_ERROR** | none | EVALUATOR_FALSE_POSITIVE | high |
| retrieval_008 | SUPERSEDE | create-only | create | Pixel 6 active | PARTIALLY | yes | yes | yes | no | **yes** | stale=true | **EXTRACTION_INTENT_ERROR** | none | CURRENT_AND_STALE_BOTH_PRESENT | high |
| containment_002 | SUPERSEDE | create-only | create | tea active | PARTIALLY | yes | yes | yes | no | **yes** | stale=true | **EXTRACTION_INTENT_ERROR** | none | CURRENT_AND_STALE_BOTH_PRESENT | high |
| forgetting_002 | FORGET | none | none | evening active | NO | yes | yes | yes | no | **no** (confirms forget) | stale=true | **EVALUATOR_ERROR** | none | EVALUATOR_FALSE_POSITIVE | medium |
| forgetting_005 | FORGET | none | none | eng-daily active | NO | yes | yes | yes | no | **yes** | stale=true | **EXTRACTION_INTENT_ERROR** | none | STALE_IN_SELECTED_MEMORY_CONTEXT | high |

Every classification traces to `records.jsonl` (per-turn actions), the
`memory_action_planned` reconstruction, and the captured answer in
`stale_failure_evidence.json`.

## 11. Five-way context exposure results

- `EVALUATOR_FALSE_POSITIVE` (5): updates_001, updates_003, updates_008,
  context_006, forgetting_002.
- `CURRENT_AND_STALE_BOTH_PRESENT` (3): context_005, retrieval_008,
  containment_002.
- `STALE_IN_SELECTED_MEMORY_CONTEXT` (1): forgetting_005.
- No case exposed the stale value only through raw history, and none had
  the stale value absent from all context.

## 12. Cross-case cause ranking

1. **EXTRACTION_INTENT_ERROR — create-only default policy / forget not
   extracted (4 genuine stale answers; underlies all 9's dirty state).**
   The single dominant upstream cause: the default chat-path memory
   policy only ever `create`s; it never supersedes or forgets, so every
   obsolete value stays active. High confidence. One bounded correction
   *could* address all of these — but it is **upstream** (extraction /
   transition intelligence / lifecycle governance), which the current
   scope forbids.
2. **EVALUATOR_ERROR — deterministic/judge over-flagging (5 cases).** The
   deterministic `must_exclude` substring scorer false-positives on
   negation ("not tea"), contrast ("instead of #eng-daily"), and correct
   avoidance ("peanut-free"); one judge case over-flags a forget
   confirmation. High confidence (4 deterministic), medium (1 judge). A
   correction here is an **allowed** class (evaluator correction) but
   fixes *measurement*, not stale suppression, and must not touch the frozen
   competitive outputs.
3. No downstream (retrieval/selection/rendering/history/prompt) or
   model-reintroduction cause is present in any case.

Ranked by affected cases, confidence, and single-fix leverage: the one
cause that produces every dirty state is upstream and out of scope; the
one cause that is in scope (evaluator) does not suppress stale answers.

## 13. Stop-condition evaluation

| Stop condition | Status | Evidence |
|---|---|---|
| stale absent from all context but model reintroduces unpredictably | NOT_TRIGGERED | stale values were present and active in the store/context |
| only viable correction requires broad retrieval redesign | NOT_TRIGGERED | retrieval behaved correctly against persisted state |
| suppressing stale answers would also suppress current information | **TRIGGERED** | obsolete and current are both ACTIVE, same kind/subject (e.g. context_005 has 3 active preferences) |
| no downstream system can know which ACTIVE memory is obsolete | **TRIGGERED** | 3 genuine cases render current+stale both active with no distinguishing metadata |
| correction would require case-specific prompt tuning | **TRIGGERED** | no general authority signal distinguishes two governed active memories |
| correction would require modifying frozen evidence | NOT_TRIGGERED | not required by this analysis |
| correction would require reopening extraction or lifecycle governance | **TRIGGERED** | the real fix (supersede/forget) is lifecycle governance, forbidden in the current scope |
| no single bounded cause explains a meaningful share | NOT_TRIGGERED | one upstream cause explains all nine dirty states |

**Key question — can an allowed downstream correction
distinguish obsolete ACTIVE memories from valid ACTIVE memories using
existing general metadata and rules? NO.** Both obsolete and valid
memories carry identical `active` lifecycle status; the only signal that
would separate them (`superseded`/`forgotten`) was never set because the
chat-path policy never ran supersession or forgetting.

## 14. Scope compatibility assessment

The dominant cause is **upstream lifecycle-state generation**, not
downstream leakage. It is classified accurately (not disguised as a
retrieval or context bug). The allowed downstream correction
classes — earlier lifecycle filtering, context rendering correction,
history isolation, prompt authority clarification, bounded generation-side
validation, evaluator correction — **cannot reliably suppress the four
genuine stale answers** without reopening forbidden upstream architecture:
there is no downstream signal that an active memory is obsolete. History
isolation and prompt-authority clarification do not apply (the stale value
came from governed memory, not raw history, and there is no
memory-vs-history authority conflict). Evaluator correction is allowed and
would remove the five false positives, but it corrects measurement rather
than suppressing stale answers, and cannot touch the frozen competitive outputs.

## 15. Candidate correction boundaries (no implementation, no selection)

Recorded, not chosen:

- **(Out of scope, upstream)** wire supersession/forget transition
  intelligence into the default chat-path memory policy so obsolete
  values leave active state — the only reliable fix, but it reopens
  extraction / transition intelligence / lifecycle governance.
- **(Allowed, measurement-only)** make the deterministic answer scorer
  negation/contrast/avoidance-aware (going forward, not retroactively on
  frozen evidence) — removes the five evaluator false positives but
  suppresses no genuine stale answer.
- **(Allowed but ineffective here)** context-rendering or
  prompt-authority changes — no authority conflict exists to resolve when
  both values are governed active memories.

## 16. Unresolved evidence

None material. `forgetting_002`'s evaluator classification is
medium-confidence (a judge over-flag of a forget confirmation that
mentions the value); its upstream state (forget never applied) is
unambiguous. Exact provider token usage was not recorded in the original
run (approximation tokens only); this does not affect classification.

## Decisions

`STALE_LEAKAGE_SOURCE_IDENTIFIED`

`PHASE_18_STOP_CONDITION_TRIGGERED`

The dominant cause of every dirty state — and of all four genuine stale
answers — is upstream lifecycle-state generation (a create-only default
memory policy that never supersedes or forgets on the chat path).
Obsolete and valid memories are indistinguishably ACTIVE, so no allowed
downstream correction can reliably suppress stale answers
without reopening forbidden extraction / transition / lifecycle
governance. The remaining five failures are evaluator false positives —
a real measurement finding, but not a stale-suppression opportunity.
