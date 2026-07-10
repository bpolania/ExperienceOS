# Benchmark raw artifact: lifecycle-v2-ablation

Produced by `python -m benchmarks.runner.cli run --profile full-offline`
in **deterministic-offline** mode (deterministic offline
provider; no network, no credentials, no real local model).

- Suite: experienceos-lifecycle-v1 · profile: full-offline
- Systems: experienceos_rules, experienceos_slots_v2, experienceos_hybrid_extract_v2, experienceos_hybrid_retrieval_v2, experienceos_extract_retrieval_v2, experienceos_coverage_v2, experienceos_temporal_v2, experienceos_local_v2, experienceos_hybrid_full_v2
- Local-policy mode: scripted — the
  `experienceos_local` numbers are **scripted-plus-fallback offline
  results, NOT a real-GGUF score** (see provenance.json).
- Response-inclusion metrics reflect the deterministic echo provider
  applied equally to all systems; model-scored cases are deferred.
- Normalized result digest: `ee437bb3e9fde909f343112e40aaa6ecf63155a07a81ad67e017e310fbefb547`

This artifact contains raw comparative evidence only: per-case
results, metric contributions with fixed numerators/denominators, and
aggregation. It is **not** a LongMemEval result, contains no LLM-judge
scores, and carries no final comparative interpretation — the
judge-facing report is produced separately.
