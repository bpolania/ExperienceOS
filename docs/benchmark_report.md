# ExperienceOS Benchmark Report (report-v1)

> Generated from committed raw artifacts by
> `./scripts/run_benchmarks.sh report` at commit
> `12b86992e9a6032b52002bd84d68a52e30510e08`. Do not edit manually — the
> validator detects edited numbers. No benchmark system was rerun; no
> network, provider, or model was used during generation.

## 1. Executive Summary

Six systems were compared on the custom 40-scenario lifecycle
benchmark and three on the LongMemEval 50-case stratified subset
(official data, structural offline run). Custom lifecycle benchmark: 40 committed scenarios, 6 systems, deterministic offline provider, approximated token accounting (ceil(chars/4)); ExperienceOS local runs scripted proposals plus rule fallback — not a real-GGUF result.

Strongest bounded findings (full conditions in section 12):

- Under the documented offline lifecycle configuration, duplicate memory proposals were accepted into active state in 0/2 eligible ExperienceOS local-policy cases, compared with 2/2 for append-only storage.
- Across the eligible custom retrieval expectations, ExperienceOS rules selected 15/17 expected memories into context, compared with 0/17 for the stateless baseline, which has no accumulated experience.
- ExperienceOS rules supplied 33.7% fewer approximated comparable context tokens than full-history prompting (1166/3461 token reduction across 38 eligible custom cases, same accounting method).
- In the scripted local-policy cases, final lifecycle state diverged from the oracle in 7/38 executed cases (the numerator counts unfulfilled aspirational memory expectations as well); every scripted invalid proposal (duplicate, inactive-target, nonexistent-target, malformed) was rejected or contained by the engine. This is the scripted-plus-fallback offline mode and does not measure real-GGUF proposal accuracy.
- In the LongMemEval 50-case stratified subset (structural offline run, official data, no official judge), ExperienceOS rules selected the official answer-bearing session in 14/50 cases — behind naive lexical retrieval at 42/50 — while supplying orders of magnitude fewer context tokens than full history. Sparse rule-based extraction on conversational data is a measured limitation.
- In the LongMemEval 50-case stratified subset, ExperienceOS rules supplied 99.8% fewer approximated context tokens than full-history prompting across 50 cases (same accounting method; structural run).

Visible limitations up front: the answer provider is a deterministic
offline echo (response-inclusion metrics are floor evidence applied
equally to every system); the dataset's update oracles are
deliberately aspirational, so ExperienceOS rules honestly fails
unkeyed-domain supersession; naive lexical retrieval beats
ExperienceOS retrieval on the external conversational subset; and the
local policy ran in scripted-plus-fallback mode, never a real GGUF.

## 2. What Was Measured

The custom lifecycle track measures whether an experience layer keeps
accumulated experience **current** (updates and supersession),
**relevant** (retrieval, selection, budget adherence), **bounded**
(context tokens, compression), and **safe** (four-level stale and
forgotten leakage, duplicate containment, invalid-proposal
containment). The external track measures long-history retrieval and
context cost on recognized official data. The two tracks are never
combined into one score, and no composite score exists anywhere in
the artifacts.

## 3. Systems Compared

| System | Description |
|---|---|
| Stateless | current request only; no accumulated experience |
| Full history | entire transcript replayed every turn; no lifecycle |
| Append-only | durable-looking statements stored forever; no updates or forgetting |
| Naive top-K | lexical + recency retrieval over an append-only store |
| ExperienceOS rules | the real engine with the deterministic rule policy |
| ExperienceOS local (scripted + fallback) | the real engine with the local-model policy driven by scripted proposals plus rule fallback — **not a real-GGUF run** |

## 4. Custom Lifecycle Benchmark

40 scenarios (creation 6, updates 8, forgetting 6, retrieval 8,
context 6, containment 6) across 13 domains, fixed hash-locked oracle
(manifest `0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb`), six systems, deterministic provider. 240
case-system runs: 228 executed, 12 skipped (2 requires-local-model
scenarios x 6 systems), 12 partial (deferred abstention/model-scored
response evaluation), 0 execution failures.

Case outcomes by system (navigation aid only — conclusions come from
the metric tables): 
- Stateless: failed=30, partial=2, passed=6, skipped=2
- Full history: failed=31, partial=2, passed=5, skipped=2
- Append-only: failed=25, partial=2, passed=11, skipped=2
- Naive top-K: failed=24, partial=2, passed=12, skipped=2
- ExperienceOS rules: failed=19, partial=2, passed=17, skipped=2
- ExperienceOS local (scripted + fallback): failed=22, partial=2, passed=14, skipped=2

## 5. Lifecycle Correctness Results

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `memory_creation_precision` | N/A (34 undefined, 0 eligible) | N/A (34 undefined, 0 eligible) | 11/15 (73.3%) | 11/15 (73.3%) | 10/11 (90.9%) | 10/11 (90.9%) |
| `memory_creation_recall` | 0/13 (0.0%) | 0/13 (0.0%) | 11/13 (84.6%) | 11/13 (84.6%) | 10/13 (76.9%) | 10/13 (76.9%) |
| `correct_memory_kind_rate` | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | 11/11 (100.0%) | 11/11 (100.0%) | 10/10 (100.0%) | 10/10 (100.0%) |
| `update_detection_accuracy` | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 2/7 (28.6%) | 2/7 (28.6%) |
| `supersession_accuracy` | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 2/7 (28.6%) | 2/7 (28.6%) |
| `old_value_deactivation_rate` | 8/8 (100.0%) | 8/8 (100.0%) | 0/8 (0.0%) | 0/8 (0.0%) | 3/8 (37.5%) | 3/8 (37.5%) |
| `conflicting_active_memory_rate` | 0/7 (0.0%) | 0/7 (0.0%) | 6/7 (85.7%) | 6/7 (85.7%) | 3/7 (42.9%) | 3/7 (42.9%) |
| `forget_detection_accuracy` | 0/4 (0.0%) | 0/4 (0.0%) | 0/4 (0.0%) | 0/4 (0.0%) | 2/4 (50.0%) | 2/4 (50.0%) |
| `correct_forget_target_rate` | N/A (4 undefined, 0 eligible) | N/A (4 undefined, 0 eligible) | N/A (4 undefined, 0 eligible) | N/A (4 undefined, 0 eligible) | 2/2 (100.0%) | 2/2 (100.0%) |
| `duplicate_acceptance_rate` | N/A (3 undefined, 0 eligible) | N/A (3 undefined, 0 eligible) | 2/2 (100.0%) | 2/2 (100.0%) | N/A (3 undefined, 0 eligible) | 0/2 (0.0%) |

Reading notes: `duplicate_acceptance_rate` is undefined where no
duplicate was ever proposed (rule dedupe prevents the proposal
itself); ExperienceOS supersession succeeds in keyed conflict domains
(seats, flight times, keyed facts) and honestly fails the dataset's
aspirational unkeyed-domain corrections — see the failure analysis.

## 6. Leakage Results

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `stale_candidate_leakage_rate` | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | 12/17 (70.6%) | 12/17 (70.6%) | 11/16 (68.8%) | 10/15 (66.7%) |
| `stale_selected_leakage_rate` | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | 12/17 (70.6%) | 12/17 (70.6%) | 11/16 (68.8%) | 10/15 (66.7%) |
| `stale_context_leakage_rate` | 0/11 (0.0%) | 11/11 (100.0%) | 11/11 (100.0%) | 11/11 (100.0%) | 10/11 (90.9%) | 9/11 (81.8%) |
| `stale_response_contamination_rate` | 1/9 (11.1%) | 1/9 (11.1%) | 1/9 (11.1%) | 1/9 (11.1%) | 1/9 (11.1%) | 1/9 (11.1%) |
| `forgotten_exclusion_rate` | 2/2 (100.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| `forgotten_response_contamination_rate` | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) |
| `memory_resurrection_rate` | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) |
| `unrelated_preservation_rate` | 0/3 (0.0%) | 0/3 (0.0%) | 2/3 (66.7%) | 2/3 (66.7%) | 3/3 (100.0%) | 3/3 (100.0%) |

The primary lifecycle safety measure is **rendered-context** leakage:
stored inactive history is not leakage, and candidate-level
contamination is less severe than content actually supplied to the
answer provider. Stateless rows are vacuously clean (no context at
all). `Stale content in rendered context (cases with an expected-superseded value)`;
`Forgotten-content exclusion (post-forget answers; the restatement scenario re-mentions the term legitimately and is counted against exclusion by construction)`.
Response contamination is scored only where the oracle carries a
deterministic forbidden constraint.

## 7. Retrieval and Downstream Use

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `recall_at_k` | 0/17 (0.0%) | 0/17 (0.0%) | 10/17 (58.8%) | 13/17 (76.5%) | 15/17 (88.2%) | 15/17 (88.2%) |
| `precision_at_k` | N/A (12 undefined, 0 eligible) | N/A (12 undefined, 0 eligible) | 10/20 (50.0%) | 13/20 (65.0%) | 15/20 (75.0%) | 15/20 (75.0%) |
| `hit_at_k` | N/A (12 undefined, 0 eligible) | N/A (12 undefined, 0 eligible) | 7/12 (58.3%) | 10/12 (83.3%) | 11/12 (91.7%) | 11/12 (91.7%) |
| `mean_reciprocal_rank` | N/A (12 undefined, 0 eligible) | N/A (12 undefined, 0 eligible) | 7.83333/12 (65.3%) | 10.6667/12 (88.9%) | 11/12 (91.7%) | 11/12 (91.7%) |
| `irrelevant_rejection_rate` | N/A (12 undefined, 0 eligible) | N/A (12 undefined, 0 eligible) | 5/15 (33.3%) | 8/15 (53.3%) | 8/13 (61.5%) | 8/13 (61.5%) |
| `inactive_contamination_rate` | N/A (12 undefined, 0 eligible) | N/A (12 undefined, 0 eligible) | 2/20 (10.0%) | 2/20 (10.0%) | 2/20 (10.0%) | 2/20 (10.0%) |
| `preference_compliance_rate` | 0/5 (0.0%) | 0/5 (0.0%) | 0/5 (0.0%) | 0/5 (0.0%) | 0/5 (0.0%) | 0/5 (0.0%) |
| `instruction_compliance_rate` | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) |
| `current_fact_accuracy` | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) |

Downstream response-inclusion metrics reflect the deterministic echo
provider applied equally to every system — they are configuration
floor evidence, not live answer quality.

## 8. Context Efficiency

Average approximated context per executed case (38 cases per system;
`ceil(chars/4)`; these are not provider-billed tokens and no cost
claim is made):

| System | Avg total context tokens | Avg memory tokens | Avg selected | Avg candidates |
|---|---|---|---|---|
| Stateless | 19.7 | 0.0 | 0.0 | 0.0 |
| Full history | 91.1 | 0.0 | 0.0 | 0.0 |
| Append-only | 32.2 | 12.9 | 1.26 | 1.58 |
| Naive top-K | 32.5 | 13.2 | 1.26 | 1.58 |
| ExperienceOS rules | 60.4 | 27.3 | 1.24 | 1.5 |
| ExperienceOS local (scripted + fallback) | 60.3 | 27.1 | 1.21 | 1.47 |

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `token_reduction_vs_full_history` | 2712/3461 (78.4%) | N/A (metric not applicable to this system) | 2238/3461 (64.7%) | 2226/3461 (64.3%) | 1166/3461 (33.7%) | 1171/3461 (33.8%) |
| `context_budget_utilization` | 0/133 (0.0%) | 0/133 (0.0%) | 48/133 (36.1%) | 48/133 (36.1%) | 47/133 (35.3%) | 46/133 (34.6%) |
| `compression_ratio` | N/A (1 undefined, 0 eligible) | N/A (1 undefined, 0 eligible) | N/A (1 undefined, 0 eligible) | N/A (1 undefined, 0 eligible) | N/A (1 undefined, 0 eligible) | N/A (1 undefined, 0 eligible) |
| `answers_per_1k_memory_tokens` | N/A (38 undefined, 0 eligible) | N/A (38 undefined, 0 eligible) | 6000/491 (1222.0%) | 7000/501 (1397.2%) | 12000/1036 (1158.3%) | 10000/1030 (970.9%) |
| `fallback_rate` | 0/104 (0.0%) | 0/104 (0.0%) | 0/104 (0.0%) | 0/104 (0.0%) | 0/104 (0.0%) | 97/104 (93.3%) |
| `rejection_containment_rate` | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | N/A (metric not applicable to this system) | 4/4 (100.0%) |

Conventions: stateless has zero structured memory tokens; full
history carries transcript context rather than structured memory, so
its comparable cost is total context; zero-token ratios stay
undefined; `answers_per_1k_memory_tokens` is undefined for zero-memory
systems rather than infinite.

## 9. Local Memory-Policy Containment

Scripted-plus-fallback offline mode (provenance:
`used_real_local_model: false`) — proposal quality, engine
validation, rejection, fallback, applied action, and final state are
separate layers:

| Metric | ExperienceOS local (scripted + fallback) |
|---|---|
| `local_valid_proposal_rate` | 7/8 (87.5%) |
| `local_correct_action_type_rate` | 0/1 (0.0%) |
| `local_correct_target_rate` | 0/2 (0.0%) |
| `duplicate_proposal_rate` | 2/20 (10.0%) |
| `fallback_rate` | 97/104 (93.3%) |
| `local_applied_action_accuracy` | 11/17 (64.7%) |
| `local_state_corruption_rate` | 7/38 (18.4%) |

Canonical containment patterns in the artifact: a valid scripted
create applied; the Phase 7 over-eager duplicate rejected
(`duplicate_of_active`); an inactive-target supersede and a
nonexistent-target forget rejected (`target_not_active`); malformed
output triggering the typed `invalid_output` fallback with the rules
producing the correct final state; unrelated memories preserved
throughout. `Final-state divergence from oracle (includes never-created aspirational memories, not only destroyed ones)`.
None of this measures real-GGUF proposal accuracy.

## 10. LongMemEval 50-case Stratified Subset

> **Scope.** 50 of 500 official questions; official `s_cleaned` data
> at revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`;
> deterministic metadata-based selection (10 per category:
> information extraction, multi-session reasoning, temporal
> reasoning, knowledge updates, abstention); subset manifest
> `a077cca377469ac3450ef5446e7d289bcbd42eb2c95beed677220f69fca73030`; structural offline
> run with labeled proxy answer metrics; **no official GPT-4o judge;
> not an official LongMemEval score; no leaderboard claim.**

| Metric | Full history | Naive top-K | ExperienceOS rules |
|---|---|---|---|
| `answer_session_candidate_rate` | N/A (50 undefined, 0 eligible) | 50/50 (100.0%) | 28/50 (56.0%) |
| `answer_session_selection_rate` | N/A (50 undefined, 0 eligible) | 42/50 (84.0%) | 14/50 (28.0%) |
| `answer_session_mrr` | N/A (50 undefined, 0 eligible) | 32.8795/50 (65.8%) | 9.28315/50 (18.6%) |
| `answer_context_presence_rate` | 42/42 (100.0%) | 24/42 (57.1%) | 0/42 (0.0%) |
| `external_token_reduction_vs_full_history` | N/A (metric not applicable to this system) | 6.17844e+06/6.30865e+06 (97.9%) | 6.29832e+06/6.30865e+06 (99.8%) |
| `normalized_exact_match_proxy` | 0/40 (0.0%) | 0/40 (0.0%) | 0/40 (0.0%) |
| `answer_entity_match_proxy` | 7/40 (17.5%) | 5/40 (12.5%) | 8/40 (20.0%) |
| `abstention_match_proxy` | N/A (10 undefined, 0 eligible) | N/A (10 undefined, 0 eligible) | N/A (10 undefined, 0 eligible) |

Retrieval metrics use the official `answer_session_ids` relevance
oracle (not proxies). Answer metrics marked `_proxy` are
deterministic checks against the offline echo provider — floor
evidence only. `Verbatim evidence-turn content present in supplied context (exact substring; normalized ExperienceOS memory text cannot match verbatim by construction)`.
Abstention answer evaluation is deferred (30 case-evaluations across
the three systems).

Average supplied context (50 cases per system, approximated):

- Full history: 126173.0 total tokens, 126123.8 history/memory tokens, 0.0 selected items on average
- Naive top-K: 2604.2 total tokens, 2555.1 history/memory tokens, 6.0 selected items on average
- ExperienceOS rules: 206.6 total tokens, 163.2 history/memory tokens, 6.0 selected items on average

Category tables (metrics eligible per category; temporal cases keep
session dates in the source representation, though ExperienceOS
memory text may lose structured date context; knowledge-update cases
carry no custom-style lifecycle oracle, so no lifecycle accuracy is
derived; abstention shows execution and deferral only — no invented
accuracy):

### information-extraction

| Metric | Full history | Naive top-K | ExperienceOS rules |
|---|---|---|---|
| `answer_session_candidate_rate` | N/A (10 undefined, 0 eligible) | 10/10 (100.0%) | 4/10 (40.0%) |
| `answer_session_selection_rate` | N/A (10 undefined, 0 eligible) | 9/10 (90.0%) | 2/10 (20.0%) |
| `answer_session_mrr` | N/A (10 undefined, 0 eligible) | 7.27/10 (72.7%) | 1.62662/10 (16.3%) |
| `answer_context_presence_rate` | 10/10 (100.0%) | 7/10 (70.0%) | 0/10 (0.0%) |

### multi-session-reasoning

| Metric | Full history | Naive top-K | ExperienceOS rules |
|---|---|---|---|
| `answer_session_candidate_rate` | N/A (10 undefined, 0 eligible) | 10/10 (100.0%) | 7/10 (70.0%) |
| `answer_session_selection_rate` | N/A (10 undefined, 0 eligible) | 8/10 (80.0%) | 4/10 (40.0%) |
| `answer_session_mrr` | N/A (10 undefined, 0 eligible) | 6.22331/10 (62.2%) | 1.9345/10 (19.3%) |
| `answer_context_presence_rate` | 10/10 (100.0%) | 3/10 (30.0%) | 0/10 (0.0%) |

### temporal-reasoning

| Metric | Full history | Naive top-K | ExperienceOS rules |
|---|---|---|---|
| `answer_session_candidate_rate` | N/A (10 undefined, 0 eligible) | 10/10 (100.0%) | 5/10 (50.0%) |
| `answer_session_selection_rate` | N/A (10 undefined, 0 eligible) | 8/10 (80.0%) | 3/10 (30.0%) |
| `answer_session_mrr` | N/A (10 undefined, 0 eligible) | 6.0396/10 (60.4%) | 3.1125/10 (31.1%) |
| `answer_context_presence_rate` | 10/10 (100.0%) | 5/10 (50.0%) | 0/10 (0.0%) |

### knowledge-updates

| Metric | Full history | Naive top-K | ExperienceOS rules |
|---|---|---|---|
| `answer_session_candidate_rate` | N/A (10 undefined, 0 eligible) | 10/10 (100.0%) | 6/10 (60.0%) |
| `answer_session_selection_rate` | N/A (10 undefined, 0 eligible) | 9/10 (90.0%) | 3/10 (30.0%) |
| `answer_session_mrr` | N/A (10 undefined, 0 eligible) | 8.19298/10 (81.9%) | 1.75758/10 (17.6%) |
| `answer_context_presence_rate` | 10/10 (100.0%) | 8/10 (80.0%) | 0/10 (0.0%) |

### abstention

| Metric | Full history | Naive top-K | ExperienceOS rules |
|---|---|---|---|
| `answer_session_candidate_rate` | N/A (10 undefined, 0 eligible) | 10/10 (100.0%) | 6/10 (60.0%) |
| `answer_session_selection_rate` | N/A (10 undefined, 0 eligible) | 8/10 (80.0%) | 2/10 (20.0%) |
| `answer_session_mrr` | N/A (10 undefined, 0 eligible) | 5.15357/10 (51.5%) | 0.851954/10 (8.5%) |
| `answer_context_presence_rate` | 2/2 (100.0%) | 1/2 (50.0%) | 0/2 (0.0%) |

## 11. Failure Analysis

Examples are selected by fixed deterministic rules (first matching
case in canonical execution order per rule — never by favorable
performance):

| Track | Rule | Case | System | Outcome | Unmet metrics | Note |
|---|---|---|---|---|---|---|
| lifecycle | first failed case per system | `creation_001_explicit_scoped_preference` | stateless | failed | memory_creation_recall 0/1; context_budget_utilization 0/4; memory_token_share 0/18 | first evaluation failure in canonical execution order |
| lifecycle | first failed case per system | `creation_001_explicit_scoped_preference` | full_history | failed | memory_creation_recall 0/1; context_budget_utilization 0/4; memory_token_share 0/18 | first evaluation failure in canonical execution order |
| lifecycle | first failed case per system | `creation_005_exact_duplicate_restatement` | append_only | failed | memory_creation_precision 0/1; context_budget_utilization 1/4; memory_token_share 6/18 | first evaluation failure in canonical execution order |
| lifecycle | first failed case per system | `creation_005_exact_duplicate_restatement` | naive_top_k | failed | memory_creation_precision 0/1; context_budget_utilization 1/4; memory_token_share 6/18 | first evaluation failure in canonical execution order |
| lifecycle | first failed case per system | `updates_001_preference_replacement_cross_session` | experienceos_rules | failed | update_detection_accuracy 0/1; supersession_accuracy 0/1; old_value_deactivation_rate 0/1 | first evaluation failure in canonical execution order |
| lifecycle | first failed case per system | `updates_001_preference_replacement_cross_session` | experienceos_local | failed | update_detection_accuracy 0/1; supersession_accuracy 0/1; old_value_deactivation_rate 0/1 | first evaluation failure in canonical execution order |
| lifecycle | first experienceos_local containment case | `containment_001_duplicate_create_contained` | experienceos_local | passed | duplicate_acceptance_rate 0/1; inactive_contamination_rate 0/1; context_budget_utilization 1/4 | invalid scripted proposal rejected by the engine; final state preserved |
| lifecycle | first deferred evaluation | `forgetting_005_forgotten_leakage_check` | stateless | partial | memory_resurrection_rate 0/1; forgotten_response_contamination_rate 0/1; context_budget_utilization 0/4 | abstention verification requires provider-backed evaluation; deferred in deterministic offline mode |
| external | first missed answer-bearing session per retrieval system | `1faac195` | naive_top_k | completed | answer_session_selection_rate 0/1 | the official evidence session never entered the selected context |
| external | first missed answer-bearing session per retrieval system | `001be529` | experienceos_rules | completed | answer_session_selection_rate 0/1 | the official evidence session never entered the selected context |
| external | full-history context advantage | `001be529` | experienceos_rules | completed | answer_context_presence_rate 0/1 | full history retained verbatim evidence at ~126 vs full-history-scale token cost; sparse rule extraction plus normalized memory text kept verbatim evidence out |
| external | first abstention case | `031748ae_abs` | full_history | completed | — | abstention answer evaluation deferred: requires a live labeled run |

Mixed outcomes are explicit: full history and naive retrieval each
beat ExperienceOS rules on cases the rules pass over (lexical
overlap, verbatim retention); append-only recall exceeds ExperienceOS
recall on creation because it stores raw statements the normalizing
planner skips; ExperienceOS wins are concentrated in lifecycle
correctness, duplicate containment, inactive-memory exclusion in
keyed domains, and context economy.

## 12. What the Evidence Supports

- Under the documented offline lifecycle configuration, duplicate memory proposals were accepted into active state in 0/2 eligible ExperienceOS local-policy cases, compared with 2/2 for append-only storage.
  - condition: duplicate_acceptance_rate denominator > 0 and numerator == 0 for experienceos_local
- Across the eligible custom retrieval expectations, ExperienceOS rules selected 15/17 expected memories into context, compared with 0/17 for the stateless baseline, which has no accumulated experience.
  - condition: recall_at_k denominators > 0 for both systems
- ExperienceOS rules supplied 33.7% fewer approximated comparable context tokens than full-history prompting (1166/3461 token reduction across 38 eligible custom cases, same accounting method).
  - condition: full-history reference exists with matching accounting
- In the scripted local-policy cases, final lifecycle state diverged from the oracle in 7/38 executed cases (the numerator counts unfulfilled aspirational memory expectations as well); every scripted invalid proposal (duplicate, inactive-target, nonexistent-target, malformed) was rejected or contained by the engine. This is the scripted-plus-fallback offline mode and does not measure real-GGUF proposal accuracy.
  - condition: state-corruption denominator > 0; real_model_used false and disclosed
- In the LongMemEval 50-case stratified subset (structural offline run, official data, no official judge), ExperienceOS rules selected the official answer-bearing session in 14/50 cases — behind naive lexical retrieval at 42/50 — while supplying orders of magnitude fewer context tokens than full history. Sparse rule-based extraction on conversational data is a measured limitation.
  - condition: external selection denominators > 0; subset and proxy scope stated
- In the LongMemEval 50-case stratified subset, ExperienceOS rules supplied 99.8% fewer approximated context tokens than full-history prompting across 50 cases (same accounting method; structural run).
  - condition: external full-history reference exists

## 13. What the Evidence Does Not Support

Withheld claims (conditions failed, honestly):

- `stale-exclusion`: stale rendered-context leakage is 10/11 for ExperienceOS rules — the dataset's aspirational unkeyed-domain update oracles are honestly failed, so no exclusion claim is emitted
- `forgotten-exclusion`: forgotten-content exclusion is 0/2 on the eligible post-forget answers (one case is a missed paraphrased forget; the other is the restatement scenario where the term legitimately reappears) — no blanket exclusion claim is emitted

Never claimed, regardless of results: any official LongMemEval score
or leaderboard placement; superiority beyond the measured scenarios;
live Qwen answer quality (the provider was a deterministic echo);
real-GGUF local-policy accuracy; provider cost or pricing outcomes;
production-scale behavior; any combined lifecycle-plus-external
score.

## 14. Limitations

- Deterministic echo provider: response-inclusion metrics are floor
  evidence, identical in kind for every system.
- No official LongMemEval judge; external answer metrics are labeled
  proxies; abstention evaluation deferred.
- No real-GGUF benchmark run; local mode is scripted-plus-fallback.
- 40 custom scenarios and a 50-case external subset bound
  generalization.
- Token accounting is a documented approximation, not billed tokens.
- Rule-based extraction misses paraphrases and conversational
  phrasing; assistant turns are not ingested; session-date structure
  can be lost in memory text.
- Latency was measured on one machine and is not comparable across
  hardware.

## 15. Reproduction

```bash
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1
./scripts/run_benchmarks.sh report                 # regenerate report + CSVs
./scripts/run_benchmarks.sh validate-report benchmarks/results/committed/report-v1
./scripts/run_benchmarks.sh quick                  # offline benchmark smoke
./scripts/run_benchmarks.sh full-offline           # full 240-run benchmark
./scripts/run_benchmarks.sh longmemeval-fixture    # external offline smoke
# with official data present under benchmarks/data/external/longmemeval/:
./scripts/run_benchmarks.sh longmemeval-structural benchmarks/data/external/longmemeval/longmemeval_s_cleaned.json
```

## 16. Provenance

- Report version: report-v1; generating commit `12b86992e9a6032b52002bd84d68a52e30510e08` (clean tree: True).
- Lifecycle artifact: `benchmarks/results/committed/lifecycle-offline-v1`, digest `8b0e245d914a43bc578923111e8ff40e70d9c8aa487664c00125fc52fa319b33`, generated at commit `d96c76cf6af68db3e02be23006c53f53188600e0`, dataset manifest `0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb`.
- External artifact: `benchmarks/results/committed/longmemeval-50-subset-v1`, digest `2b3e2000647b8d3ca85e0539ce3ac518afb32e4eb343c96a20538607d428ea03`, generated at commit `7a79729452dc8d5a9fbc2fde2c8be1d7e2276331`, subset manifest `a077cca377469ac3450ef5446e7d289bcbd42eb2c95beed677220f69fca73030`.
- Flags: network=False, provider invoked=False, model invoked=False, systems rerun=False; local mode: scripted-plus-fallback offline; external evaluation: structural + labeled proxies (no official GPT-4o judge).

## 17. Appendix

Machine-readable data: `benchmarks/results/committed/report-v1/report_data.json`
(every table above, with raw numerators/denominators). CSV exports in
the same directory. Category-level lifecycle tables:

### creation

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `memory_creation_precision` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 3/5 (60.0%) | 3/5 (60.0%) | 3/3 (100.0%) | 3/3 (100.0%) |
| `memory_creation_recall` | 0/3 (0.0%) | 0/3 (0.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) |
| `correct_memory_kind_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) |
| `non_durable_rejection_rate` | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 (100.0%) |
| `duplicate_acceptance_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 2/2 (100.0%) | 2/2 (100.0%) | N/A (no eligible cases in group) | N/A (no eligible cases in group) |

### updates

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `update_detection_accuracy` | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 2/7 (28.6%) | 2/7 (28.6%) |
| `correct_update_target_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 2/2 (100.0%) | 2/2 (100.0%) |
| `supersession_accuracy` | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 0/7 (0.0%) | 2/7 (28.6%) | 2/7 (28.6%) |
| `old_value_deactivation_rate` | 8/8 (100.0%) | 8/8 (100.0%) | 0/8 (0.0%) | 0/8 (0.0%) | 3/8 (37.5%) | 3/8 (37.5%) |
| `conflicting_active_memory_rate` | 0/7 (0.0%) | 0/7 (0.0%) | 6/7 (85.7%) | 6/7 (85.7%) | 3/7 (42.9%) | 3/7 (42.9%) |
| `stale_context_leakage_rate` | 0/7 (0.0%) | 7/7 (100.0%) | 7/7 (100.0%) | 7/7 (100.0%) | 6/7 (85.7%) | 6/7 (85.7%) |

### forgetting

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `forget_detection_accuracy` | 0/4 (0.0%) | 0/4 (0.0%) | 0/4 (0.0%) | 0/4 (0.0%) | 2/4 (50.0%) | 2/4 (50.0%) |
| `correct_forget_target_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 2/2 (100.0%) | 2/2 (100.0%) |
| `forgotten_exclusion_rate` | 2/2 (100.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |
| `memory_resurrection_rate` | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) | 0/6 (0.0%) |
| `unrelated_preservation_rate` | 0/3 (0.0%) | 0/3 (0.0%) | 2/3 (66.7%) | 2/3 (66.7%) | 3/3 (100.0%) | 3/3 (100.0%) |

### retrieval

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `precision_at_k` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 3/8 (37.5%) | 5/8 (62.5%) | 6/8 (75.0%) | 6/8 (75.0%) |
| `recall_at_k` | 0/7 (0.0%) | 0/7 (0.0%) | 3/7 (42.9%) | 5/7 (71.4%) | 6/7 (85.7%) | 6/7 (85.7%) |
| `hit_at_k` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 2/5 (40.0%) | 4/5 (80.0%) | 4/5 (80.0%) | 4/5 (80.0%) |
| `mean_reciprocal_rank` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 2.83333/5 (56.7%) | 4.5/5 (90.0%) | 4.5/5 (90.0%) | 4.5/5 (90.0%) |
| `irrelevant_rejection_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 1/6 (16.7%) | 3/6 (50.0%) | 3/5 (60.0%) | 3/5 (60.0%) |
| `inactive_contamination_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 1/8 (12.5%) | 1/8 (12.5%) | 1/8 (12.5%) | 1/8 (12.5%) |

### context

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `context_budget_utilization` | 0/15 (0.0%) | 0/15 (0.0%) | 11/15 (73.3%) | 11/15 (73.3%) | 11/15 (73.3%) | 11/15 (73.3%) |
| `compression_ratio` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) |
| `selection_budget_adherence` | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) | 6/6 (100.0%) |

### containment

| Metric | Stateless | Full history | Append-only | Naive top-K | ExperienceOS rules | ExperienceOS local (scripted + fallback) |
|---|---|---|---|---|---|---|
| `duplicate_proposal_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 0/1 (0.0%) | 0/1 (0.0%) | 0/1 (0.0%) | 2/5 (40.0%) |
| `fallback_rate` | 0/8 (0.0%) | 0/8 (0.0%) | 0/8 (0.0%) | 0/8 (0.0%) | 0/8 (0.0%) | 1/8 (12.5%) |
| `rejection_containment_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 4/4 (100.0%) |
| `local_state_corruption_rate` | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | N/A (no eligible cases in group) | 0/4 (0.0%) |


Denominator notes: undefined cells state their exclusion reason inline; skipped and deferred counts appear in section 4; per-metric undefined counts are preserved in report_data.json and the source aggregates.
