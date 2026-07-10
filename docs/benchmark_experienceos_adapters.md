# ExperienceOS Benchmark Adapters (Phase 8, Prompt 4)

The `experienceos_rules` and `experienceos_local` systems behind the
same `BenchmarkSystem` interface as the four
[baselines](benchmark_baselines.md), producing the same evidence
shape from the [benchmark contract](benchmark_contract.md) over the
committed [lifecycle dataset](lifecycle_benchmark_dataset.md).
Canonical comparative results now exist under
`benchmarks/results/committed/`; see
[benchmark_report.md](benchmark_report.md).

## Evidence flow

```
User turn
→ Memory policy proposal            (rule_based | local_model | fallback)
→ ExperienceManager validation      (confidence gate, contradiction rules,
                                     whole-batch typed fallback)
→ Engine lifecycle validation       (target_not_active, duplicate_of_active)
→ rejection OR applied action       (create / supersede / forget)
→ memory store state                (active / superseded / forgotten)
→ retrieval candidates              (active memories only)
→ context selection + compression   (budget-bounded, explained)
→ provider context                  (exact messages captured)
→ response
```

Every stage lands in its own evidence field, so **proposal quality,
engine containment, applied actions, and final state stay separate**:

- *Correct proposal applied* → proposal + applied action + state.
- *Invalid proposal rejected* → proposal + rejection reason + empty
  applied actions + clean state (containment, never corruption).
- *Fallback success* → fallback record with typed reason; the applied
  action's `decision_source` is `fallback`, never presented as
  local-model correctness.
- *Semantically wrong but valid proposal* → applied action recorded;
  the oracle comparison (Prompt 5) surfaces the wrong outcome.
- *No usable proposal* → fallback or empty evidence; state preserved.
- *Duplicate proposal* → visible proposal + `duplicate_of_active`
  rejection + single active record.

## How the adapters attach

Public seams only: `ExperienceOS(model=…, memory_policy=…,
context_builder=…)`, `chat`, `memories_for_user(status=…)`, and the
public event stream. No private store access, no monkey-patching, no
benchmark flags in the production package — the Prompt 1 audit's
conclusion (events already expose proposals, confidence, decision
source, fallback provenance, rejections, selection records,
compression, and context messages) held: **zero production changes
were required**.

Each `initialize` builds a fresh scenario-isolated agent: in-memory
store, `MockProvider` (or an injected provider through the same
seam), compression enabled, scenario-scoped user ID, and the shared
budget interpretation (memory budget = min(context_budget,
selection_k)) — identical to the baselines. An event cursor scopes
each turn's evidence to exactly the events that turn produced.

## Rule-based adapter (`experienceos_rules`)

The SDK default path: deterministic `RuleBasedMemoryPolicy` through
the real `ExperienceManager`, engine, store, context builder, and
compressor. The adapter only translates events; no lifecycle decision
is recreated in benchmark code.

## Local-model adapter (`experienceos_local`)

Always the real `LocalModelMemoryPolicy`, real manager validation,
and the real typed fallback path. Three modes:

- **scripted** (default, offline): scenarios declared with the
  `scripted_local_proposals` evaluator requirement get a
  `ScriptedLocalRunner` that replays declarative per-turn proposal
  payloads through the production policy parser; all other scenarios
  run with an unavailable runner, so every turn exercises the real
  whole-batch fallback to rules (`decision_source: fallback`).
- **unavailable**: forces the no-runner path everywhere; local
  invocation count stays 0.
- **real**: constructs the production `LlamaCppLocalModelRunner` from
  the repository's environment configuration. Never part of default
  tests or `validate_demo.sh`; no downloads, no filesystem searches;
  when unconfigured it degrades to the fallback path with
  `real_model_used: false`. Provenance records the **safe model
  basename only**.

Invocation convention (tested): `local_model_invocation_count` counts
*completed structured generations* — scripted generations count and
are marked `scripted` in diagnostics; the unavailable runner raises
before generating, so its count is 0.

## Scripted containment fixtures

Declarative per-turn proposal scripts keyed strictly by scenario ID
(`benchmarks/adapters/scripted_policy.py`), covering: over-eager
duplicate create on a planning request (`containment_001`), supersede
targeting a retired record (`containment_002` — its paired
replacement create deliberately duplicates the active value, so the
engine rejects both halves), forget targeting a nonexistent ID
(`containment_003`), and malformed structured output driving the real
`invalid_output` fallback (`containment_004`). Target resolution uses
the same ID channel a real model uses — parsing the prompt's ACTIVE
MEMORIES block — plus a remembered-ID mechanism for deliberately
targeting retired records.

Fixtures define **only what the "model" proposes** — never expected
final state, never which action should be accepted. The engine
decides validation, rejection, fallback, and state. A registry test
pins fixtures exactly to the four `scripted_local_proposals`
scenarios so unrelated scenarios can never consume one. This is the
documented narrow oracle-firewall exception: the fixture stands in
for external model output, not expected results.

## Memory-state, selection, and compression evidence

`final_state()` queries all three statuses through
`memories_for_user`; the harness splits them into
`final_active/final_superseded/final_forgotten`. Candidates translate
from production selection records (rank, score, reason, selected
flag); skipped = unselected. In the deterministic ExperienceOS path,
inactive memories are excluded at the candidate level, and the
primary leakage evidence is the exact provider context (captured and
test-verified against the provider's actual input). Compression is
context-time-only evidence: summary count and saved characters in the
accounting, compressed text visible in context, source memories still
stored and auditable, and no stored memory created from a summary.

## Context accounting and latency

Same `approximation` method as the baselines (`ceil(chars/4)`, with
character floors): total context = built context messages + current
message; memory context = built context minus the leading static
system instruction. Latency: end-to-end from a monotonic clock around
`chat()`, plus retrieval / memory-decision / response stages derived
from event timestamps (documented approximations; Prompt 5 does the
aggregation).

## Oracle firewall

Adapters receive user messages, budgets, seed, requirement flags, and
the scenario ID (fixture lookup only). Expected fields never reach
lifecycle decisions; logical-reference annotation (which also covers
superseded and forgotten records) runs post-execution into
diagnostics. Tested by stripping the oracle and comparing normalized
evidence.

## Honest weaknesses preserved (not patched)

Unkeyed-domain fact supersession (`retrieval_008`: Pixel 6 stays
active beside Pixel 9 under the rules policy), the
genuinely-shrinks compression guard declining `context_003`'s three
short preferences, paraphrase dedupe, lexical-mismatch retrieval, and
the two real-local hard cases (`containment_005/006`, skipped without
a configured model). These are measurement targets, locked in by
tests that assert *current* production behavior.

## Commands

```bash
PYTHONPATH=. python -m pytest tests/test_benchmark_adapters.py
PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_rules --all
PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_local --scripted
PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_local --all
# optional, explicitly configured real model only (never default):
PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_local --real-local
```
