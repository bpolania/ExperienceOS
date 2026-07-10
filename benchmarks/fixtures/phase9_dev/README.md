# Phase 9 development fixtures (DEVELOPMENT ONLY)

Fixtures under this root support Phase 9 implementation and unit/
integration testing. They are **never** final benchmark evidence, are
not part of any frozen evaluation set, and must not alter final
evaluation denominators. Final evidence uses the unchanged Phase 8
lifecycle dataset and LongMemEval subset under v2 system IDs (see
docs/phase9_experiment_contract.md).

Subdirectories:

- `semantic_identity/` — Prompt 2 semantic identity and conflict cases.
- `hybrid_extraction/` — Prompt 3 durability-gate positives/negatives
  and grounding adversaries. Development-only; not part of the frozen
  evaluation; never affects final denominators; must not be cited as
  final benchmark evidence.
- `hybrid_retrieval/` — Prompt 4 retrieval behavior classes (lexical
  mismatch, entity preservation, scoped preference, lifecycle
  filtering, budget pressure, stable ties). Development-only; not part
  of the frozen evaluation; never affects final denominators; must not
  be cited as final benchmark evidence.
- `coverage_selection/` — Prompt 5 coverage-aware selection classes
  (multi-attribute queries, multi-valued complements, redundancy,
  source diversity, conflicts, budget pressure). Development-only; not
  part of the frozen evaluation; never affects final denominators;
  must not be cited as final benchmark evidence.
