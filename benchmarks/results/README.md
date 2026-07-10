# Benchmark results

Two kinds of artifacts, with different rules:

- `committed/` — small, reviewable evidence artifacts that later
  prompts explicitly promote: run provenance, aggregate metric tables
  with raw numerators/denominators, and the manifest hash they were
  produced from. Everything here is deterministic-serialized
  (key-sorted JSON) and safe: no secrets, no personal paths, no model
  weights.
- `local/` — gitignored scratch output for local runs (raw JSONL,
  reruns, experiments). Nothing here is evidence.

Fixtures under `benchmarks/fixtures/` validate schemas and are never
benchmark results.
