# Benchmark raw artifact: lifecycle-offline-v1

Produced by `python -m benchmarks.runner.cli run --profile full-offline`
in **deterministic-offline** mode (deterministic offline
provider; no network, no credentials, no real local model).

- Suite: experienceos-lifecycle-v1 · profile: full-offline
- Systems: stateless, full_history, append_only, naive_top_k, experienceos_rules, experienceos_local
- Local-policy mode: scripted — the
  `experienceos_local` numbers are **scripted-plus-fallback offline
  results, NOT a real-GGUF score** (see provenance.json).
- Response-inclusion metrics reflect the deterministic echo provider
  applied equally to all systems; model-scored cases are deferred.
- Normalized result digest: `8b0e245d914a43bc578923111e8ff40e70d9c8aa487664c00125fc52fa319b33`

This artifact contains raw comparative evidence only: per-case
results, metric contributions with fixed numerators/denominators, and
aggregation. It is **not** a LongMemEval result, contains no LLM-judge
scores, and carries no final comparative interpretation — the
judge-facing report is produced separately.
