# Benchmark Metric Behavior

How the evaluators implement the fixed
[contract](benchmark_contract.md) metric registry. Definitions
(numerators, denominators, zero-denominator rule, percentile
convention, leakage levels) are unchanged from the contract; this
documents evaluator mechanics.

## Ground rules

- Every value is built from **raw contribution records** (metric,
  numerator increment, denominator increment, evidence references).
  Aggregation sums increments per system and metric; per-case
  percentages are never averaged. F1 derives from *aggregate*
  precision and recall.
- **Undefined ≠ zero.** Zero-denominator or not-applicable
  contributions carry a reason, are excluded, and are counted in
  `undefined_count`. Stateless memory-token ratios and MRR without
  ranking are undefined, never 0% or infinity.
- **No composite score exists** (`aggregate.json` pins
  `composite_score: null`). Systems are never ranked by an
  unexplained number.
- The oracle is evaluated **after** execution; logical references
  resolve by match terms with explicit `unresolved`/`ambiguous`
  outcomes (recorded in `failures.json`) — never a silently chosen
  match.

## Group mechanics

- **Memory write**: precision counts *applied* creates matched
  one-to-one to expected creates by semantic value constraints;
  recall counts expected creates matched; kind correctness scores
  matched pairs only. Duplicate proposals = engine-rejected
  duplicates + extra active records in exact-state duplicate cases;
  acceptance counts only duplicates that reached active state.
  Non-durable rejection scores 1 when nothing was applied.
- **Update**: detection needs a supersede/forget *proposal*; target
  correctness scores *applied* supersedes against the expected target
  ref; supersession accuracy is a final-state check (old retired AND
  replacement active); old-value deactivation and conflicting-active
  are final-state checks. Append-only corrections score exactly as
  the baseline behaved (creates, conflict = 1) — never translated
  into supersession.
- **Forgetting**: detection (proposal), target (applied forget vs
  expected ref), exclusion (forgotten content absent from the final
  answer turn's rendered memory context), preservation (expected
  unrelated actives still resolved). **Resurrection** requires a
  forget that actually applied AND the ref back in active state with
  no forgotten record remaining — a restatement beside the
  still-forgotten record does not count; a never-applied forget is a
  detection failure, not resurrection.
- **Retrieval**: relevant set = oracle `selected` refs. Precision@K
  over selected; Recall@K over relevant refs (0-relevant cases score
  abstention instead); Hit@K any-relevant-selected; MRR = 1/rank of
  the first relevant candidate, 0 when relevant never surfaces,
  undefined without ranking. Inactive contamination and active
  utilization split the selected set against the oracle's inactive
  refs. Budget adherence: selected ≤ min(budget, K), every executed
  case.
- **Leakage**: four levels per the contract — candidate slots,
  selected slots, rendered context (binary per case; the primary
  metric), response assertion (scored only where the oracle carries
  forbidden constraints). Stored-but-never-surfaced inactive records
  never count. Stale and forgotten are tracked separately; per-level
  raw hits for both statuses ride in contribution evidence.
- **Response**: deterministic matching — casefold, collapse
  whitespace, substring phrase match; no hidden fuzz. Inclusion
  constraints map to current-fact accuracy (update cases),
  multi-session accuracy, instruction compliance (instruction-tagged),
  else preference compliance. `must_exclude` feeds the leakage
  contamination metrics. **Model-scored cases and abstention
  expectations defer offline** (recorded, excluded from numerators
  and denominators). Offline inclusion results reflect the
  deterministic echo provider equally across systems.
- **Context**: budget utilization, memory-token share,
  relevant-token share (chars of relevant selected / chars of all
  selected), compression ratio (only when compression ran; expected-
  but-absent compression is an undefined contribution preserving the
  engine's genuinely-shrinks guard). `answers_per_1k_memory_tokens`
  and `token_reduction_vs_full_history` are synthesized at
  aggregation — the latter only where the same-scenario full-history
  reference completed under the same accounting method, else
  undefined.
- **Operational**: fallback rate per planned turn; rejection
  containment; per-stage latency aggregated with the contract's
  nearest-rank p50/p95, `low_sample_warning` below 20 samples
  (computed, flagged, never hidden); provider request / local
  invocation / retry / fallback / rejection counts summed.
- **Local policy** (`experienceos_local` only): valid-proposal rate
  over *completed generations*; action-type and target correctness
  over local-sourced proposals; applied-action accuracy post-
  containment (fallback-sourced actions counted as applications,
  visibly labeled `fallback`, never as local-model correctness);
  explicit vs paraphrase accuracy split by scenario tags;
  state-corruption is a final-state invariant check where rejected
  proposals count as containment, not corruption. Scripted,
  unavailable, and real modes are never mixed into one number — the
  offline canonical artifact is scripted-plus-fallback mode.

## Report metric selection

The judge-facing report shows a curated subset of the registry, fixed
in `benchmarks/reporting/report_spec.json` (committed with the
generator, before findings were interpreted; it contains no result
values). Display-label caveats for four metrics whose constructions
need explanation (`stale_context_leakage_rate`,
`forgotten_exclusion_rate`, `local_state_corruption_rate`,
`answer_context_presence_rate`) are pinned in the spec and rendered
verbatim. The machine-readable appendix (`report_data.json`) carries
every displayed cell with raw numerators/denominators and source
digests.
