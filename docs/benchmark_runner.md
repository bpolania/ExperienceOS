# Benchmark Runner and Artifacts (Phase 8, Prompt 5)

Deterministic six-system orchestration over the committed
[lifecycle dataset](lifecycle_benchmark_dataset.md), scoring against
the fixed [contract](benchmark_contract.md) metrics
([metric behavior](benchmark_metrics.md)) and writing validated raw
artifacts. **Raw comparative results now exist; the final judge-facing
interpretation has not been written yet.**

## Commands

```bash
./scripts/run_benchmarks.sh quick              # 6 systems x 14 scenarios
./scripts/run_benchmarks.sh full-offline       # 6 systems x 40 scenarios
./scripts/run_benchmarks.sh validate <dir>     # verify without rerunning
# equivalently:
PYTHONPATH=. python -m benchmarks.runner.cli run --profile full-offline \
    --output benchmarks/results/local/full [--overwrite]
PYTHONPATH=. python -m benchmarks.runner.cli validate <result-dir>
```

Both offline profiles need **no credentials, no network, no real
local model, no downloads**. Exit codes are nonzero only for
execution or artifact-integrity failures — a low benchmark score is a
result, never a runner failure. The quick profile also runs inside
`./scripts/validate_demo.sh` (temporary directory, cleaned up).

## Profiles

- **quick** — 14 committed scenarios (list in
  `benchmarks/runner/config.py`, fixed before any output was
  interpreted) covering creation, the non-durable boundary,
  correction, forgetting, leakage probes, retrieval distractors,
  budget pressure, compression, and containment — including known
  hard cases (`creation_006` paraphrase dedupe, `retrieval_003`
  lexical mismatch, `retrieval_004` wrong-domain padding,
  `context_003` compression guard).
- **full-offline** — all 40 scenarios in manifest order; the canonical
  result profile.
- **qwen / real-local** — configuration-only in this phase: resolving
  them for execution raises with an explanation; they are never part
  of default validation.
- **LongMemEval subset commands** (`longmemeval-fixture`,
  `longmemeval-prepare`, `longmemeval-structural`,
  `validate-external`) drive the separate external track — see
  [longmemeval_subset.md](longmemeval_subset.md).

## Execution semantics

Deterministic order: configured systems → committed scenario order →
ordered turns; recorded in `execution_manifest.json`. A fresh system
instance runs every case; state never crosses scenario, system, run,
or profile boundaries. `fail_fast` defaults to false: failures
produce evidence (`failures.json`, `execution_failed` outcomes) and
later cases continue. The oracle reaches evaluation only — never a
running system. Skips (the two `requires_local_model` cases per
system) and deferrals (model-scored and abstention response
evaluation) are explicit, reasoned, and counted.

## Artifact layout

```
<output-dir>/
  run_config.json             resolved configuration
  provenance.json             contract provenance (safe, commit-pinned)
  execution_manifest.json     ordered case-system runs and outcomes
  cases.jsonl                 {case, evaluation} per case-system run
  metric_contributions.jsonl  raw numerator/denominator increments
  aggregate.json              per-system sums, ratios, latency stats,
                              per-group rollups — no composite score
  failures.json               every failure/skip/deferral (explicit
                              empty lists)
  artifact_manifest.json      file hashes, record counts, normalized
                              result digest, schema version
  README.md                   what the artifact is and is not
```

Writing is atomic: a `.incomplete` staging directory is validated and
then promoted; existing output is never overwritten without
`--overwrite`; interrupted writes leave only the clearly-marked
incomplete directory, which canonical validation rejects.
Canonical evidence lives under `benchmarks/results/committed/`;
scratch runs under the gitignored `benchmarks/results/local/`.

## Validation

`validate` (or `python -m benchmarks.artifacts.validation <dir>`)
verifies: required files, JSON/JSONL parsing, per-file hashes, record
counts, execution-order consistency, scenario/system/metric identity
against the committed registries, dataset-manifest hash match,
aggregate recomputation from raw contributions, the normalized result
digest, and a safety scan (no secrets, no personal paths). It never
reruns systems.

## Structural determinism

Raw artifacts contain wall-clock latencies, timestamps, and runtime
memory UUIDs. The **normalized result digest** maps UUIDs to
first-seen placeholders and blanks timestamps/latencies — nothing
else. Actions, kinds, values, targets, rejection and fallback
reasons, candidate order, selection state, context text, responses,
constraint outcomes, numerators, denominators, statuses, and skip
reasons all stay verbatim, so behavioral changes change the digest
(tested). Repeated offline runs of the same profile reproduce the
same digest.

## Claims boundary

The artifacts contain measured comparative numbers; interpreting them
is later work. Nothing here is a LongMemEval result; no LLM judge was
used; `experienceos_local` offline numbers are **scripted-plus-
fallback mode, not a real-GGUF score** (provenance says so
explicitly); response-inclusion metrics reflect the deterministic
echo provider applied equally to every system.
