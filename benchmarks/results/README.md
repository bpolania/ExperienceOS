# Benchmark results

Two kinds of artifacts, with different rules:

- `committed/` — canonical, reviewable evidence artifacts: run
  provenance pinned to the generating commit, per-case JSONL, raw
  metric contributions, aggregation with raw numerators/denominators,
  file hashes, and a normalized result digest. Validate any directory
  with `./scripts/run_benchmarks.sh validate <dir>`. Everything here
  is deterministic-serialized and safe: no secrets, no personal
  paths, no model weights. Future live-provider or external-benchmark
  runs get their own clearly-labeled subdirectories — never mixed
  into offline lifecycle results.
- `local/` — gitignored scratch output for local runs (raw JSONL,
  reruns, experiments). Nothing here is evidence.

Fixtures under `benchmarks/fixtures/` validate schemas and are never
benchmark results.
