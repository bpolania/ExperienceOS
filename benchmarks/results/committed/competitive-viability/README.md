# Competitive viability evidence

Committed, reproducible evidence for the competitive viability evaluation
(governed by `docs/competitive_viability_contract.md`, harness in
`experiments/competitive_viability/`).

## Contents

- `viability_manifest.json` — the frozen scored subset: all 40 frozen
  lifecycle scenarios in manifest order (a deterministic, complete,
  no-cherry-pick selection), with per-case evidence classification,
  categories, scoring method, references, required systems, and budget
  configuration. It carries **references only — no expected-answer
  content** — so it exposes no oracle to execution adapters. Rebuild with
  `experiments.competitive_viability.viability_subset.build_viability_manifest`;
  the case hash is stable.
- `execution_summary.json` — curated per-system execution completeness and
  fairness summary for the live run (counts and statuses only; **no raw
  answers, no provider payloads, no secrets**).
- `scoring_evidence.json` — curated final-answer scoring evidence: the
  frozen scoring configuration, the judge system prompt and rubric,
  method assignment, per-system answer-quality metrics (with numerators,
  denominators, and percentages), category-level accuracy, judge-usage
  and exclusion counts, bounded per-case structured verdicts, and
  artifact hashes. It carries **structured verdicts and hashes only — no
  raw answer text, no provider payloads, no secrets** — and **no
  competitive profile, ranking, or go/no-go decision** (that is later
  work). Deterministic scoring covers cases with response
  inclusion/exclusion criteria; a blinded Qwen judge scores abstention
  and no-response-criteria cases. Raw score records, blinded judge
  requests, and judge responses stay in the gitignored local scoring
  tree.

## What is not committed here

Raw live run artifacts (`records.jsonl` with full answers, per-run
`run_manifest.json`, errors) are non-deterministic and live in the
gitignored `benchmarks/results/local/competitive-viability/` tree. This
prompt records execution evidence only — **no scores, rankings, or
competitive conclusions**. Final-answer scoring and analysis are later
work.

## Coverage limitation

The LongMemEval 50-case subset is locally available but each case carries
419–608 conversation turns (24,558 total), making a live all-system run
structurally infeasible within a bounded evaluation. Multi-session
retrieval is covered at bounded scale by the lifecycle cross-session
cases; the existing committed `longmemeval-50-subset` offline-structural
evidence stands as prior reused-external evidence. Absent LongMemEval
live cases are a documented coverage limitation, not failures.
