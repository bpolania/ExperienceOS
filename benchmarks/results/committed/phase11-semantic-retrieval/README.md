# LongMemEval 50-case stratified subset — offline-structural run

- Data: official LongMemEval data; dataset variant per provenance; official source
  revision 98d7416c24c778c2fee6e6f3006e7a073259d48f.
- Systems: experienceos_hybrid_full_v2_reference, experienceos_embedding_only_v1, experienceos_fused_retrieval_v1, experienceos_gate_shadow_v1, identical session content,
  identical answer-provider configuration, identical budgets.
- Evaluation: deterministic structural evidence (official
  answer_session_ids retrieval oracle) plus clearly-labeled proxy
  answer checks. The official GPT-4o judge was NOT used — nothing
  here is an official LongMemEval score, leaderboard result, or full
  500-question benchmark run.
- This artifact is a offline-structural run: with the deterministic offline
  provider, answer-quality proxies reflect the echo provider equally
  across systems and are not live answer quality.
- Normalized result digest: `5ff129ce4d638edaa3a49fda4f949f5337edf16ce4b5be216922b55b1d40390a`
- Entirely separate from the custom lifecycle benchmark
  (benchmarks/results/committed/lifecycle-offline-v1); the two are
  never combined.
