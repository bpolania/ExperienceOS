# ExperienceOS Lifecycle Benchmark Dataset

**Dataset**: `experienceos-lifecycle` · **Version**: `experienceos-lifecycle-v1`
· **Scenarios**: 40 · **Manifest**: `benchmarks/scenarios/lifecycle_manifest.json`

The committed dataset that Phase 8's comparative benchmark executes.
Every scenario is a declarative JSON file conforming to the Prompt 1
case contract ([benchmark_contract.md](benchmark_contract.md));
every oracle is fixed here, **before any comparative result exists**.
No benchmark results exist yet, and nothing in this dataset is a
result.

## Purpose

Measure whether accumulated experience stays **current, relevant,
bounded, auditable, and safe from stale or forgotten leakage** — and
do it with cases that can also show where stateless systems lack
experience, full-history prompting wastes context, append-only stores
retain contradictions, naive retrieval selects stale or irrelevant
content, and where ExperienceOS itself may still miss (paraphrase
dedupe, lexical-mismatch retrieval, unkeyed-domain supersession).

## Distribution

- **Groups** (directories under `benchmarks/scenarios/lifecycle/`):
  creation 6 · updates 8 · forgetting 6 · retrieval 8 · context 6 ·
  containment 6.
- **Modes**: 39 deterministic, 1 model-scored (`retrieval_007`);
  1 provider-required; 2 local-model-required (`containment_005/006`).
  The default dataset loads and validates fully offline.
- **Domains** (via `domain:` tags): travel (8), food (7),
  work/work-communication (6), software-development (4), study (3),
  and one or two each of family-scheduling, writing, devices,
  shopping, fitness, home, small-talk, general. Travel is 20% of the
  dataset — under the one-third cap.

## File format and manifest

One scenario per JSON file, filename = `scenario_id` + `.json`.
Canonical order is **group order (creation → updates → forgetting →
retrieval → context → containment), then scenario_id** — recorded in
the manifest; filesystem enumeration never defines benchmark order.
The manifest records per scenario: id, path, group, contract
category, tags, optional-mode flags, evaluation mode, seed (distinct,
fixed, 201–240), context budget, selection K, and a per-file
`content_hash` (SHA-256 of the canonical case payload). The overall
`manifest_hash` uses the Prompt 1 `manifest_hash` helper over the
ordered payloads, so any content or order change is detectable.

## Oracle semantics

- **Logical memory references** name semantic slots
  (`travel.seat.short_work_trip`, `work.daily_status_channel.v2`),
  never runtime IDs. Runners resolve them via `match_terms`.
  Supersession chains use distinct logical IDs per version; a
  restatement after forgetting uses a new logical ID so the forgotten
  record and the new record stay distinguishable.
- **Empty oracle lists are unasserted.** `final_state_exact: true`
  makes the active/superseded/forgotten lists exhaustive — used for
  "nothing may persist" and "exactly one memory for this slot".
- **Semantic value constraints** (`must_include_all/any`,
  `must_exclude`) match memory values and responses by concept, never
  by exact generated prose.
- **Response constraints** are evaluated against whatever response a
  system produces; inclusion constraints are meaningful in
  provider-backed runs (a deterministic mock echo cannot satisfy
  them), while lifecycle and context oracles are checked in every
  mode. `requires_provider` marks only cases that are meaningless
  without a live response (abstention judging).
- **Proposal vs final state**: containment cases assert an expected
  rejection reason AND a clean exact final state — a rejected
  proposal is containment evidence, never state corruption
  (`containment_001`–`003`). The fallback case (`containment_004`)
  asserts `fallback_expected` plus the correct rules-produced final
  state.
- **Ambiguity is explicit.** Where multiple outcomes are legitimate
  (`containment_005` one-sentence supersession, `containment_006`
  vague forget), the oracle asserts only the invariants that must
  hold (unrelated memories survive; no corruption) and the notes list
  the acceptable outcomes. Selection-order ties are never asserted;
  set membership is.

## Durable vs non-durable boundary

Durable: stable preferences, standing instructions ("From now on…",
"Always…"), long-lived facts, and their corrections. Non-durable:
weather, mood, one-time tasks, transient plans ("tonight's dinner"),
and planning requests themselves. `creation_004`, `updates_007`, and
`retrieval_006` make the boundary inspectable; each scenario's notes
say why its statements should or should not persist.

## Honest hard cases (by design)

The dataset is not a demo script. Cases expected to stress
ExperienceOS itself include: `creation_006` (paraphrase dedupe),
`retrieval_003` (safety memory with zero lexical overlap, one slot),
`retrieval_004` (budget padding selects a wrong-domain memory),
`updates_001/003/004/008` (supersession outside the rule planner's
keyed domains — the oracle encodes defensible correct behavior, not
current engine behavior), and both local-model containment cases.
Oracles were fixed with these known: they will produce failed cases
for some systems, including ExperienceOS configurations, and those
failures are reported, never excluded.

## Phase 7 findings encoded

`creation_001` (verified explicit create), `updates_004` ("I now
prefer" planner fix), `updates_005` ("instead of" clause hygiene),
`forgetting_001` (verified explicit forget), `containment_001`
(over-eager duplicate proposal on a planning request, scripted
deterministic twin), `containment_005` (one-sentence supersession
limit, real GGUF), `containment_006` (vague-reference forget safety,
real GGUF).

## Validating the dataset

```bash
PYTHONPATH=. python -m benchmarks.scenarios.validate
PYTHONPATH=. python -m pytest tests/test_benchmark_dataset.py
```

The validator checks manifest structure and canonical order,
per-file and overall hashes, group allocation, category placement,
oracle consistency (kinds, targets, leakage constraints, abstention
contradictions, optional-mode flags, budget bounds), and content
hygiene (no secrets, no personal paths). Current manifest hash:
`0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb`.

## What this dataset does not prove

Loading and validating the dataset proves internal consistency only.
It proves nothing about any system's quality until later prompts run
the comparative benchmark under the fair-comparison rules of the
benchmark contract — and even then, results support only the claims
listed in that contract.

## Scenario index

| Scenario ID | Title | Category | Domain | Mode |
|---|---|---|---|---|
| `creation_001_explicit_scoped_preference` | Explicit scoped travel preference is remembered | creation | travel | deterministic |
| `creation_002_durable_user_fact` | Durable work-location fact is remembered | creation | work | deterministic |
| `creation_003_durable_instruction` | Standing communication instruction is remembered | creation | work-communication | deterministic |
| `creation_004_non_durable_statement` | Transient small talk must not persist | creation | small-talk | deterministic |
| `creation_005_exact_duplicate_restatement` | Exact duplicate restatement does not duplicate memory | creation | food | deterministic |
| `creation_006_paraphrased_duplicate` | Paraphrased duplicate must not create a second memory | creation | food | deterministic |
| `updates_001_preference_replacement_cross_session` | Changed drink preference replaces the old one across sessions | update | food | deterministic |
| `updates_002_fact_correction` | Corrected work location supersedes the old fact | update | work | deterministic |
| `updates_003_instruction_replacement` | Replaced channel instruction retires the old instruction | update | work-communication | deterministic |
| `updates_004_now_prefer_wording` | 'I now prefer' wording performs the update | update | study | deterministic |
| `updates_005_instead_of_wording` | 'Instead of' wording updates and keeps memory text clean | update | travel | deterministic |
| `updates_006_scoped_preferences_coexist` | Differently scoped preferences must both stay active | update | travel | deterministic |
| `updates_007_correction_with_distractors` | Correction embedded in distractor chatter | update | family-scheduling | deterministic |
| `updates_008_repeated_correction_chain` | Repeated correction of the same logical field | update | work-communication | deterministic |
| `forgetting_001_exact_forget` | Exact forget request retires the memory | forgetting | food | deterministic |
| `forgetting_002_paraphrased_forget` | Paraphrased forget request retires the memory | forgetting | study | deterministic |
| `forgetting_003_forget_one_of_several` | Forgetting one memory preserves its neighbors | forgetting | travel | deterministic |
| `forgetting_004_forget_after_supersession` | Forget after supersession retires the active successor only | forgetting | food | deterministic |
| `forgetting_005_forgotten_leakage_check` | Forgotten instruction must not shape the later answer | forgetting | work-communication | deterministic |
| `forgetting_006_restatement_not_resurrection` | Explicit restatement creates a new memory, not a resurrection | forgetting | food | deterministic |
| `retrieval_001_one_relevant_among_many` | One relevant instruction among unrelated memories | retrieval | software-development | deterministic |
| `retrieval_002_multiple_relevant` | Multiple relevant travel memories are all selected | retrieval | travel | deterministic |
| `retrieval_003_lexical_mismatch` | Safety-relevant memory with no lexical overlap | retrieval | food | deterministic |
| `retrieval_004_wrong_domain_similar_wording` | Similar wording from the wrong domain is skipped | distractor | home | deterministic |
| `retrieval_005_old_relevant_vs_recent_irrelevant` | Old relevant memory beats recent irrelevant memory | retrieval | study | deterministic |
| `retrieval_006_no_memory_needed` | Self-contained request needs no memory | retrieval | general | deterministic |
| `retrieval_007_correct_abstention` | Unknown preference requires abstention | abstention | shopping | model-scored |
| `retrieval_008_stale_would_mislead` | Stale superseded fact would produce a wrong answer | retrieval | devices | deterministic |
| `context_001_budget_exceeded` | More candidates than budget forces real selection | context_budget | software-development | deterministic |
| `context_002_cross_domain_relevance` | Relevant experience spans two domains | selection | work | deterministic |
| `context_003_redundant_compression` | Related travel memories compress into one summary | compression | travel | deterministic |
| `context_004_instruction_priority` | Standing instruction outranks preferences under a tight budget | context_budget | writing | deterministic |
| `context_005_active_and_inactive_versions` | Only the active version of an updated preference reaches context | selection | software-development | deterministic |
| `context_006_minimal_context_sufficient` | Tiny selected context answers correctly despite long history | context_budget | food | deterministic |
| `containment_001_duplicate_create_contained` | Over-eager duplicate create on a planning request is contained | rejection | travel | deterministic |
| `containment_002_supersede_inactive_target` | Supersede targeting an already-superseded memory is rejected | rejection | food | deterministic |
| `containment_003_forget_nonexistent_target` | Forget targeting a nonexistent memory is rejected | rejection | software-development | deterministic |
| `containment_004_malformed_proposal_fallback` | Malformed policy output falls back to rules and still succeeds | fallback | writing | deterministic |
| `containment_005_one_sentence_supersession_local` | Real local model attempts a one-sentence supersession | rejection | travel | local-model |
| `containment_006_vague_forget_safe` | Vague forget reference must not corrupt unrelated memories | rejection | fitness | local-model |
