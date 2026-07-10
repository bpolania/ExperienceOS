# ExperienceOS Benchmark Contract (Phase 8)

This document locks the measurement rules for the Phase 8 benchmark
**before any result exists**. Later prompts implement scenarios,
baselines, runners, and reports against this contract; they may not
change a metric's definition, denominator, or comparison rule after
observing results. Machine-readable counterparts live in
`benchmarks/contract/` (schemas, metric registry, hashing).

## 1. Core question

Under the same model, same dataset, same context budget, and same
scoring rules, does ExperienceOS preserve current experience, exclude
stale or forgotten experience, and supply more relevant context than
stateless, full-history, append-only, and naive-retrieval baselines?

ExperienceOS is the experience layer for LLM-powered agents: it
decides what to remember, update, forget, retrieve, rank, compress,
and place inside a bounded context window. The benchmark measures
whether that accumulated experience stays **current, relevant, safe,
and context-efficient**. It is provider-independent: Qwen Cloud is
the primary hackathon inference provider, but no benchmark interface
couples to Qwen-specific request or response shapes.

## 2. Systems compared

All systems implement `benchmarks.contract.system.BenchmarkSystem`
and run the identical scenario manifest:

| system_id | Description |
|---|---|
| `stateless` | No memory; each turn sees only the current message |
| `full_history` | Entire prior transcript prepended every turn |
| `append_only` | Every user statement stored forever; all injected |
| `naive_top_k` | Keyword top-K over an append-only store; no lifecycle |
| `experienceos_rules` | ExperienceOS with RuleBasedMemoryPolicy |
| `experienceos_local` | ExperienceOS with LocalModelMemoryPolicy (real GGUF) |

Adapters are observers around public interfaces (`ExperienceOS`,
`ExperienceOS.wrap`, `ExperienceOS.with_sqlite_memory`, providers,
`agent.events`, the memory store). The production engine contains no
benchmark branches.

## 3. Case contract

Cases are declarative JSON validated by
`benchmarks.contract.case.case_from_dict` (schema version `1`).
A case carries: identity (`scenario_id`, `title`, `category`,
`description`, `tags`, `notes`), configuration (`seed`,
`context_budget`, `selection_k`, `requires_provider`,
`requires_local_model`, `evaluation_mode`,
`evaluator_requirements`), ordered multi-session setup `turns`, one
`current_message`, and an `expected` oracle covering: expected memory
actions (create/supersede/forget/**none**) with kind and semantic
value constraints, expected rejection reasons and fallback, expected
final active/superseded/forgotten state, expected retrieval
candidates / selected / skipped sets, and response constraints
(required concepts, forbidden concepts, expected abstention).

**Logical memory references.** Real memory IDs are assigned at
runtime, so oracles reference memories by `logical_id` plus
`match_terms` (all terms must match, case-insensitive); a stable
`memory_id` may be pinned when one exists. Every reference must be
resolvable (terms or ID) or the case fails validation.

**Fixtures are not results.** The files under
`benchmarks/fixtures/contract/` exist to validate the schema.

## 4. Evidence layers (never conflated)

Every per-case result (`benchmarks.contract.result.CaseResult`)
separates:

1. **Proposal** — what the policy proposed (any source: rules, local
   model, fallback).
2. **Containment** — what engine validation rejected, with the reason
   (`target_not_active`, `duplicate_of_active`, ...).
3. **Applied action** — what actually mutated lifecycle state.
4. **Final state** — active/superseded/forgotten snapshots.
5. **Retrieval** — candidates with deterministic ranks, selected,
   skipped.
6. **Context** — the messages actually supplied, plus token
   accounting.
7. **Response and evaluation** — deterministic constraint results and
   optional labeled judge results.
8. **Operations** — latency records, provider request counts,
   local-model invocation counts, retry count.

Two invariants follow: a **rejected proposal is never state
corruption** (containment is success evidence), and a **clean final
state never erases** the record that an invalid action was proposed.
Partial failures keep all earlier evidence (`status: "partial"` with
a `failure_reason`); skipped cases state their `skip_reason`. Failed,
rejected, skipped, and fallback cases are always reported — never
silently excluded.

## 5. Context accounting

Recorded per case in `ContextAccounting` with an explicit `method`:

Precedence (highest first):
1. `provider_reported` — provider-returned token usage, when
   available and comparable across the compared systems.
2. `tokenizer` — a repository-configured tokenizer utility (none
   exists today; this slot is reserved).
3. `approximation` — the deterministic documented fallback:
   `tokens = ceil(characters / 4)` computed over the exact context
   strings. Character counts are always recorded alongside tokens as
   the method-independent floor.

**One method per compared run.** All systems inside one comparison
use the same method; a report may only mix methods if it explicitly
separates them. Stateless systems supply zero memory tokens: ratios
over that denominator are *undefined*, never infinity (see §7).

## 6. Metric registry

Every metric is a named numerator/denominator pair committed in
`benchmarks/contract/metrics.py` (`METRIC_DEFINITIONS`). Reports must
show raw numerators and denominators next to every ratio. There is no
composite score. Groups:

- **Memory-write quality** — creation precision / recall / F1,
  correct-kind rate, duplicate proposal rate, duplicate acceptance
  rate, non-durable rejection rate. A *predicted creation* is an
  **applied** create; a rejected duplicate proposal counts against
  `duplicate_proposal_rate` (proposal-level) but not against
  creation precision (applied-level). Multiple proposals in one case
  are each counted once at proposal level; matching between expected
  and applied creations is one-to-one by semantic value constraints.
- **Update quality** — update detection, correct target, supersession
  accuracy, new-value accuracy, old-value deactivation, conflicting
  active memories.
- **Forgetting quality** — forget detection, correct target,
  forgotten exclusion, forgotten response contamination, memory
  resurrection, unrelated preservation.
- **Retrieval/selection** — Precision@K, Recall@K, Hit@K, MRR,
  relevant selection, irrelevant rejection, active utilization,
  inactive contamination, budget adherence.
- **Response quality** — preference compliance, instruction
  compliance, current-fact accuracy, correct abstention,
  multi-session accuracy, experience-use rate.
- **Context efficiency** — budget utilization, memory-token share,
  relevant-token share, compression ratio, answers per 1k memory
  tokens, token reduction vs full history.
- **Operational** — latency stages with p50/p95, request counts,
  fallback rate, rejection containment rate.
- **Local-model policy** — valid proposal rate, correct action-type,
  correct target, applied-action accuracy, state-corruption rate
  (must be 0), explicit-wording vs paraphrased-wording accuracy,
  decision latency, tokens per decision.

**Retrieval definitions.** The *candidate set* is everything the
system's retrieval stage considered for this turn, ranked by the
system's own deterministic order (rank 1 = best; ties broken by the
system's stable tie-break, which is part of measured behavior). The
*selected set* is what entered context (≤ K / budget); the *skipped
set* is candidates − selected. The *relevant set* is the oracle's
`selected` expectation. With fewer than K candidates, K is
effectively the candidate count. **Zero-relevant cases**: Recall@K,
Hit@K, and MRR are undefined for that case (excluded, exclusion
counted); such cases are scored by `correct_abstention_rate` instead.

## 7. Zero denominators and percentiles

Suite-wide convention: a metric with denominator 0 is **undefined**
(`None`) for that case or aggregate — never 0.0, never 1.0, never
infinity. Undefined cases are excluded from that metric's aggregate
and the exclusion count is reported. Percentiles use the
deterministic nearest-rank convention
(`sorted(x)[ceil(q/100·n)−1]`); percentiles over fewer than 20
samples must carry a small-sample warning.

## 8. Lifecycle leakage — four levels

Leakage is defined separately at each pipeline stage; the **primary
lifecycle leakage metric is level 3**, context actually supplied:

1. **Candidate contamination** — inactive (superseded or forgotten)
   memories appearing in the retrieval candidate set.
2. **Selected contamination** — inactive memories in the selected
   set.
3. **Context contamination** — inactive memory content present in
   the context strings actually supplied to the answer provider.
4. **Response contamination** — the answer asserting a superseded
   (*stale contamination*) or forgotten (*forgotten contamination*)
   value, checked by deterministic forbidden-concept constraints.

**Resurrection** is a forgotten memory *record* returning to active
status. It is **not** resurrection when the user later makes a
genuinely new durable statement with the same value and the engine
creates a new, separately auditable memory — the forgotten record
must stay forgotten and the new record must have its own identity and
lineage.

## 9. Fair-comparison rules

Locked identical across compared systems in one run: scenario
messages, ordering, manifest (verified by `manifest_hash`), response
provider and model version, temperature, max output tokens, retry
policy, context budget, selection K (or an explicitly equivalent
token budget), seed, evaluator and scoring rules, machine (for
latency), and number of runs (unless clearly disclosed).

Prohibited: post-result scenario removal; manual correction; hidden
retries or fallbacks; different context budgets or response models;
comparing deterministic mock answers to stochastic live answers as if
memory were the only variable; reporting a subset as an official
score; combining custom and external results into one unexplained
number; per-baseline undisclosed prompt engineering; silently
omitting failures or skips.

## 10. Execution modes

| Mode | Provider | Policy | Needs network / creds / GGUF |
|---|---|---|---|
| quick offline | Mock (deterministic) | rules | no / no / no |
| full offline lifecycle | Mock (deterministic) | rules | no / no / no |
| Qwen Cloud | Qwen Cloud | rules | yes / yes / no |
| local-model policy | Mock or Qwen | local GGUF | maybe / maybe / yes |
| LongMemEval subset | configured | configured | yes (dataset) |
| report regeneration | none (reads raw results) | — | no / no / no |

The **default command is the offline mode**: fixed seed,
deterministic scenario order, RuleBasedMemoryPolicy, deterministic
provider, stable artifacts, zero credentials, zero downloads.
Stochastic (live-provider) runs are labeled as such in provenance
(`used_real_provider`, temperature, model), preserved as separate raw
artifacts, and never merged into deterministic aggregates. Retries
are counted per case (`retry_count`) and disclosed; a retried case is
never presented as first-attempt. Multiple stochastic runs may later
be aggregated only across runs with identical provenance
configuration, reported with run count and per-run spread — never
mixed into deterministic results.

## 11. Run provenance

Every run emits `RunProvenance`: repository commit, tree cleanliness,
suite/manifest versions, manifest hash, timestamp, full system
configuration, platform and Python version, which real/mock/fallback
modes were used, evaluator identity, and executed/passed/failed/
skipped/partial counts. Never recorded: API keys, environment dumps,
personal home-directory paths, full model paths (basename only, via
`safe_model_name`), unrelated machine identifiers.
`assert_provenance_safe` rejects violations at emission time.

## 12. External benchmark boundary — LongMemEval

Verified against the official repository
(`github.com/xiaowu0162/LongMemEval`; paper: *LongMemEval:
Benchmarking Chat Assistants on Long-Term Interactive Memory*, ICLR
2025, arXiv:2410.10813):

- **License**: MIT (repository and dataset distribution as published).
- **Categories**: information extraction, multi-session reasoning,
  temporal reasoning, knowledge updates, abstention; question types
  include `single-session-user`, `single-session-assistant`,
  `single-session-preference`, `temporal-reasoning`,
  `knowledge-update`, `multi-session`.
- **Format**: JSON instances (500 total) with `question_id`,
  `question_type`, `question`, `answer`, `question_date`,
  `haystack_session_ids`, `haystack_dates`, `haystack_sessions`,
  `answer_session_ids`. Distributions: `longmemeval_s.json` (~115k
  tokens), `longmemeval_m.json` (~500 sessions), and an oracle
  variant. Hosted on HuggingFace (`xiaowu0162/longmemeval-cleaned`).
- **Official evaluation**: GPT-4o judge via the repo's
  `evaluate_qa.py`.

**Phase 8 boundary**: a committed manifest of ~50 `question_id`
references (IDs only — no copied haystack data in the repo), selected
by a deterministic procedure: sort official question IDs
lexicographically within each category, then take every ⌈N/10⌉-th ID
until 10 per category are drawn from the five categories above
(50 total). Dataset files download on demand into the gitignored
`benchmarks/data/external/`; ordinary tests never download. Offline
tests use tiny synthetic fixtures in the official format, clearly
labeled synthetic. Because the run uses a subset and (for the
hackathon) a Qwen judge rather than the official GPT-4o judge, any
result **must** be labeled **"LongMemEval 50-case stratified
subset"** and is not an official LongMemEval score. An official score
would require the full 500-question set, the official GPT-4o judge,
and the official evaluation scripts. Prompt 6 must re-verify: exact
dataset file checksums, the cleaned-distribution license text, and
judge-prompt compatibility.

## 13. Supported and unsupported claims

Successful results **may** support:

- ExperienceOS outperformed the named baselines on the reported
  lifecycle metrics under the documented configuration.
- ExperienceOS prevented stale or forgotten memories from entering
  context in the benchmark.
- ExperienceOS used fewer memory-context tokens than full-history
  prompting for the measured scenarios.
- ExperienceOS improved later-session constraint compliance compared
  with the stateless baseline.
- Invalid or duplicate local-model proposals were contained by the
  engine.

The following claims are **rejected** regardless of results:

- "state of the art" / "world's best memory system"
- superiority over all vector databases
- guaranteed cost reduction
- universal generalization beyond the measured scenarios
- production scalability
- an official LongMemEval leaderboard result from a custom subset
- local-model superiority over deterministic rules in all cases

## 14. Validation commands (contract level)

```
PYTHONPATH=. .venv/bin/python -m pytest tests/test_benchmark_contract.py
.venv/bin/python -m compileall experienceos demo benchmarks
PYTHON=.venv/bin/python ./scripts/validate_demo.sh
```

Contract changes bump the relevant `*_SCHEMA_VERSION` and must state
why the change does not retroactively alter already-published
results.
