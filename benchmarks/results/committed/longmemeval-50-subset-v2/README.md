# LongMemEval 50-case stratified subset — offline-structural run

- Data: official LongMemEval data; dataset variant per provenance; official source
  revision 98d7416c24c778c2fee6e6f3006e7a073259d48f.
- Systems: full_history, naive_top_k, experienceos_rules, experienceos_hybrid_extract_v2, experienceos_hybrid_retrieval_v2, experienceos_extract_retrieval_v2, experienceos_coverage_v2, experienceos_temporal_v2, experienceos_local_v2, experienceos_hybrid_full_v2, identical session content,
  identical answer-provider configuration, identical budgets.
- Evaluation: deterministic structural evidence (official
  answer_session_ids retrieval oracle) plus clearly-labeled proxy
  answer checks. The official GPT-4o judge was NOT used — nothing
  here is an official LongMemEval score, leaderboard result, or full
  500-question benchmark run.
- This artifact is a offline-structural run: with the deterministic offline
  provider, answer-quality proxies reflect the echo provider equally
  across systems and are not live answer quality.
- Normalized result digest: `19b66cacb330e943b0460ccdb33e8cc6577fccb17621cb7a129f7420f5c7868f`
- Entirely separate from the custom lifecycle benchmark
  (benchmarks/results/committed/lifecycle-offline-v1); the two are
  never combined.
