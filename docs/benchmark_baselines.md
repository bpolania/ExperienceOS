# Benchmark Baselines (Phase 8, Prompt 3)

Four comparison systems implemented behind the common
`BenchmarkSystem` interface from the
[benchmark contract](benchmark_contract.md), runnable offline against
the committed [lifecycle dataset](lifecycle_benchmark_dataset.md).
Each is a reasonable, documented implementation of its named
strategy — not a strawman — and none borrows ExperienceOS lifecycle
logic. **No comparative accuracy or leakage result has been generated
yet**; everything here describes behavior, not measurement.

## Why these four

| Baseline | Question it answers |
|---|---|
| `stateless` | What happens with no accumulated experience at all? |
| `full_history` | Does replaying the whole transcript preserve quality, and at what context cost? |
| `append_only` | What happens when durable statements are stored but never deactivated? |
| `naive_top_k` | How far does lexical + recency retrieval go without lifecycle state? |

## Capability comparison (behavior only — no measured numbers)

| System | Persists prior experience | Stores structured memory | Updates old memory | Forgets memory | Retrieves top K | Filters stale state | Compresses context | Default offline |
|---|---|---|---|---|---|---|---|---|
| stateless | no | no | no | no | no | n/a | no | yes |
| full_history | yes (transcript) | no | no | no | no | no | no | yes |
| append_only | yes | yes | no | no | recency cap only | no | no | yes |
| naive_top_k | yes | yes | no | no | yes | no | no | yes |
| experienceos_* (Prompt 4) | yes | yes | yes | yes | yes | yes | yes | rules: yes |

## Shared machinery (`benchmarks/baselines/common.py`)

- **Deterministic provider boundary.** `DeterministicEchoProvider`
  is stateless and derives its reply purely from the supplied context
  messages (it names the current request and summarizes context
  size). It never sees oracle expectations; baseline correctness —
  and baseline failure — emerges from the context each baseline
  assembled. Live providers plug into the same one-method seam later.
- **Oracle firewall.** Baseline decision methods receive only turn
  messages, their own state, and the case's budgets. Expected-oracle
  fields never reach them; `annotate_logical_references` runs after
  execution and writes only into result diagnostics (tested: evidence
  is byte-identical with the oracle stripped).
- **Durability heuristic** (append-only and naive top-K): a small
  fixed pattern list ("I prefer", "I (now) prefer", "I like",
  "I don't like/dislike/avoid", "I am based in", "My … is",
  "From now on", "Always", "Remember that", "I go to the",
  "I upgraded"). Messages containing forget-command language
  ("forget …", "don't care about …") are commands, not durable
  statements — they are neither stored nor acted upon. Kind estimate:
  instruction for "always/from now on/never", fact for
  "my … is / based in / upgraded / go to the", else preference.
- **Context accounting**: the contract's `approximation` method
  (`ceil(chars/4)`) over the exact context strings, with character
  counts always recorded. Memory-context vs total-context split per
  the contract.
- **Timing**: per-turn `memory_decision`, `retrieval`,
  `context_assembly`, `response`, `end_to_end` latency records.
- **Harness** (`run_case`): drives initialize → ordered turns →
  current message → final snapshot, emits a contract-valid
  `CaseResult`, converts execution exceptions to `partial` results
  that keep all earlier evidence, and skips `requires_local_model`
  cases with an explicit reason. Pass/fail here is execution
  integrity only, never scenario correctness.

## Baseline semantics

### `stateless`

Keeps nothing. Context = system instructions + current message.
Emits empty proposals/actions/candidates, a zero-entry final
snapshot, and zero memory-context tokens. Known limitation (by
definition): any prior-session preference, fact, or instruction is
unavailable.

### `full_history`

Appends every user and assistant turn to an ordered transcript and
supplies the complete prior transcript before each current message
(added exactly once). No extraction, filtering, truncation, or
compression — the fair-comparison contract imposes no history budget
on this strategy because its context growth is the measurement.
Corrected, contradicted, and "forgotten" text stays in context
forever. **Token convention**: the transcript counts toward total
context tokens; memory-context tokens are 0 (no structured memory) —
this is the full-history side of the contract's
`token_reduction_vs_full_history` metric.

### `append_only`

Stores each durable-looking message verbatim as an always-active
record. Never updates, supersedes, forgets, or deduplicates:
corrections and paraphrased or exact duplicates accumulate side by
side (documented policy: **no duplicate guard**). Forget requests
alter nothing. Context strategy, fixed before any result:
**most-recent-first within the memory budget** (min of
context_budget and selection_k — the same pair every system gets);
all records appear as candidates with the overflow visibly skipped.
Known limitations: contradictions stay co-active; stale values remain
selectable; recency capping can evict older relevant records.

### `naive_top_k`

Same storage heuristic as append-only; retrieval over all stored
records with a fixed transparent score:

```
score = 1.0 * |content_words(query) ∩ content_words(record)|
      + 0.5 * (created_turn / max_created_turn)
```

No domain tags (no deterministic derivation exists that wouldn't
borrow production code — documented limitation), zero-overlap falls
back to recency, ties break by insertion-order record ID. Selects the
top min(K, budget) records; every candidate exposes its score
components in the evidence. Known limitations: wrong-domain lexical
matches can rank and be selected; zero-overlap safety memories can
lose to newer chatter; stale and "forgotten" values remain eligible
forever.

## Scenario-feature handling

- **Scripted proposal fixtures** (`scripted_local_proposals`
  containment cases): baselines have no memory-policy proposal
  engine, so the channel is recorded as
  `diagnostics.scripted_proposals = "not_applicable_to_baseline"`
  and the turns execute normally. The Prompt 4 ExperienceOS adapters
  consume those fixtures.
- **`requires_local_model` cases** (2): skipped with an explicit
  reason in default offline paths; no model is ever invoked.
- **`requires_provider` case** (1): executes offline structurally;
  the diagnostics note that response-quality evaluation is deferred
  to provider-backed runs.

## Honest weaknesses preserved

Stateless missing prior preferences, full history retaining corrected
and forgotten text, append-only holding contradictions and
duplicates, naive retrieval taking lexical traps and padding budgets
— these are benchmark observations, not defects, and are locked in by
tests so they cannot be silently "fixed" after results appear.

## Commands

```bash
PYTHONPATH=. python -m pytest tests/test_benchmark_baselines.py
PYTHONPATH=. python -m benchmarks.baselines.smoke          # representative subset
PYTHONPATH=. python -m benchmarks.baselines.smoke --all    # all 40 × 4 systems
PYTHONPATH=. python -m benchmarks.baselines.smoke --system naive_top_k --scenario retrieval_003
```

The smoke command runs offline, uses the deterministic provider,
validates every emitted result, creates no artifacts, and reports
execution integrity only.
