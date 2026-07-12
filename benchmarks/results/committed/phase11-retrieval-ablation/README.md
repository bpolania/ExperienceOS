# Benchmark raw artifact: phase11-retrieval-ablation

Produced by `python -m benchmarks.runner.cli run --profile full-offline`
in **deterministic-offline** mode (deterministic offline
provider; no network, no credentials, no real local model).

- Suite: experienceos-lifecycle-v1 · profile: full-offline
- Systems: experienceos_hybrid_full_v2_reference, experienceos_embedding_only_v1, experienceos_fused_retrieval_v1, experienceos_gate_shadow_v1
- Local-policy mode: scripted — the
  `experienceos_local` numbers are **scripted-plus-fallback offline
  results, NOT a real-GGUF score** (see provenance.json).
- Response-inclusion metrics reflect the deterministic echo provider
  applied equally to all systems; model-scored cases are deferred.
- Normalized result digest: `5fb0fb8825956933ceed0297f417c4844f61f800536ec2e6c474d5475f19cf15`

This artifact contains raw comparative evidence only: per-case
results, metric contributions with fixed numerators/denominators, and
aggregation. It is **not** a LongMemEval result, contains no LLM-judge
scores, and carries no final comparative interpretation — the
judge-facing report is produced separately.
