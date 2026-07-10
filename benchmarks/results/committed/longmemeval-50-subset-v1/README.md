# LongMemEval 50-case stratified subset — structural-offline run

- Data: official LongMemEval data; dataset variant per provenance; official source
  revision 98d7416c24c778c2fee6e6f3006e7a073259d48f.
- Systems: full_history, naive_top_k, experienceos_rules, identical session content,
  identical answer-provider configuration, identical budgets.
- Evaluation: deterministic structural evidence (official
  answer_session_ids retrieval oracle) plus clearly-labeled proxy
  answer checks. The official GPT-4o judge was NOT used — nothing
  here is an official LongMemEval score, leaderboard result, or full
  500-question benchmark run.
- This artifact is a structural-offline run: with the deterministic offline
  provider, answer-quality proxies reflect the echo provider equally
  across systems and are not live answer quality.
- Normalized result digest: `2b3e2000647b8d3ca85e0539ce3ac518afb32e4eb343c96a20538607d428ea03`
- Entirely separate from the custom lifecycle benchmark
  (benchmarks/results/committed/lifecycle-offline-v1); the two are
  never combined.
