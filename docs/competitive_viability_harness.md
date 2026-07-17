# Competitive viability comparison harness

A thin, removable layer (`experiments/competitive_viability/`) over the
existing benchmark infrastructure. It registers the evaluation's logical
systems, normalizes existing cases, drives every system through the
existing execution drivers, and records one comparable per-(case, system)
record plus a run manifest. It produces **execution evidence only** — no
competitive metrics, rankings, or conclusions. Scoring and analysis are
later work. Governed by `docs/competitive_viability_contract.md`.

## Adapter contract

Every system implements the existing `BenchmarkSystem` protocol
(`initialize` → `process_turn` → `final_state` → `close`) and is driven
by the existing drivers — `run_adapter_case` for ExperienceOS systems,
`run_case` for baselines. The Phase-level registry (`systems.py`) maps
seven logical ids to implementations:

| logical id | implementation | family |
|---|---|---|
| `canonical_experienceos_qwen` | `CanonicalQwenSystem` (demo composition) | experienceos |
| `deterministic_experienceos` | `ExperienceOSRulesAdapter` | experienceos |
| `stateless` / `full_history` / `naive_top_k` / `append_only` | existing baselines | baseline |
| `mem0_style_lightweight` | registered, `not_implemented` (unavailable) | unimplemented |

`build_system(id, provider)` constructs a system or returns `None` for an
unavailable one; `run_system_case(id, scenario, provider, run_id)` drives
one system over one scenario and returns a `CaseResult`, or `None` if the
system is unavailable. Capabilities are declared honestly per system, so
a baseline is never forced to emulate lifecycle features it lacks
(stateless has no memory state; append-only has no supersession).

The canonical adapter invokes the actual demo composition
(`build_canonical_extraction_config`, the same selection the demo uses:
Qwen extraction when configured → grounded validation → deterministic
governance → lifecycle → retrieval → context builder → Qwen response via
`agent.chat`). One documented deviation from `demo.support.create_agent`:
the agent honors the benchmark's per-case memory budget instead of the
demo's fixed budget, so every system runs under the same budget.

### One response model, two message contracts

Baselines call `provider.complete(list[str])`; the SDK path calls
`provider.complete(list[dict])`. `UnifiedResponseProvider` adapts one
underlying model (a `MockProvider` offline, a `QwenCloudProvider` live) to
both — changing message *shape*, never *content*. The ExperienceOS path
receives the raw provider (it is dict-native and the canonical extraction
selection detects a configured Qwen provider by type); baselines receive
the wrapped provider. The same model answers every system.

## Comparison record schema

One `ComparisonRecord` per (case, system), separating execution evidence
from memory/retrieval/context/final-answer evidence and from later
scoring. Key fields: `schema_version`, `run_id`, `system_id`, `case_id`,
`dataset_id`, `evidence_classification`, `execution_mode`,
`response_model`, `judge_model` (null here), `status`,
`unscorable_reason`, `capabilities`, `case_metadata` (no oracle),
`execution` (the existing `CaseResult` payload: turns with proposals /
applied / rejected actions, retrieved+selected candidates, context
messages, response, latencies; final active/superseded/forgotten;
context accounting), `context_tokens`, `full_history_tokens`,
`execution_error`, `evaluator_error`, and a `scoring` block
(`deterministic` / `rule_based` / `judge`, all null in this stage).

Statuses: `completed`, `failed`, `unavailable`, `unscorable`,
`not_applicable`. A system execution failure is `failed` with its error
preserved — never a low-quality answer. A registered-but-unavailable
system is `unavailable` with `execution: null` — never dropped and never
replaced by another system.

## Manifest schema

`RunManifest` records what was requested and what ran: `run_id`,
`timestamp`, `git_commit`, `schema_version`, `execution_profile`,
`execution_mode` (offline/live), `ordering_policy`,
`token_counting_method`, `response_model_config` (name/model/temperature/
timeout — **never credentials**), requested / available / unavailable
systems, requested cases, `incomplete_cases`, full `execution_order`,
`artifact_paths`, `environment_capability`, and the
`DEVELOPMENT_ONLY_NOT_COMPETITIVE_EVIDENCE` marker.

## Artifact locations

Live and smoke runs are non-deterministic and land in the gitignored
local tree `benchmarks/results/local/competitive-viability*/`
(`run_manifest.json`, `records.jsonl`, `execution_summary.json`,
`errors.json`). Only deterministic fixtures, schemas, code, tests, and
curated non-secret evidence are committed. Secrets, `.env`, raw provider
payloads, and locally supplied LongMemEval content are never committed;
record/manifest writing refuses any payload carrying a secret-bearing key.

## How later prompts run systems

```python
from experiments.competitive_viability.cases import load_cases
from experiments.competitive_viability.systems import REGISTERED_SYSTEM_IDS
from experiments.competitive_viability.harness import execute

execute(list(REGISTERED_SYSTEM_IDS), load_cases([...]), provider,
        run_id="...", execution_mode="live",
        out_dir="benchmarks/results/local/competitive-viability/...")
```

Offline non-Qwen systems run with a `MockProvider`; the canonical Qwen
system runs live with a configured `QwenCloudProvider`. A later prompt
finalizes the ~40–60 case viability subset and adds the scoring layer
(the `scoring` block and `judge_model` are the seams for it).

## Development smoke vs scored evidence

The smoke fixture (`smoke_cases()`: durable fact, update/correction,
forgetting, insufficient-evidence abstention) validates mechanics only.
Every smoke artifact carries `DEVELOPMENT_ONLY_NOT_COMPETITIVE_EVIDENCE`.
No competitive ranking is computed or published at this stage.

## Representing unavailable and unscorable cases

An unavailable system is recorded once per case with
`status: unavailable` and an `unscorable_reason`. A case a system cannot
score is marked `unscorable`/`not_applicable` with a reason, and excluded
from later scored numerators and denominators rather than counted as a
wrong answer.
