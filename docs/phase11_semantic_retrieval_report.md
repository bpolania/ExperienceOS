# Phase 11 Semantic Retrieval Report

Generated from committed, digest-locked Phase 11 benchmark
artifacts (`benchmarks/results/committed/phase11-retrieval-ablation/`, `phase11-semantic-retrieval/`) by `benchmarks/reporting/report_phase11.py`. Regenerate with `./scripts/run_benchmarks.sh report-phase11`; verify with `validate-report-phase11`.

## Scope and provider disclosure

Four systems over one lifecycle-safe pipeline (the accepted Phase 9 final composition), differing only in retrieval configuration, on the frozen lifecycle scenarios (40 cases) and the pinned LongMemEval 50-case subset (project-specific, fixed subset, offline deterministic answer provider — **not an official LongMemEval score**). All committed evidence uses the **deterministic test embedding provider** (`deterministic` / `stable-feature-hash-v1`, 512 dims): token-overlap feature hashing that validates plumbing, reproducibility, and lifecycle safety. It is **not evidence of neural semantic quality**, and no learned-embedding quality conclusion is possible from this report. The optional local sentence-transformers provider was skipped cleanly (`dependency_missing`); no model was downloaded.

## Phase 9 reference lock

`experienceos_hybrid_full_v2_reference` reproduces the historical `experienceos_hybrid_full_v2` behaviorally: full aggregate metric equality on both benchmarks (lifecycle equal: True; external equal: True), excluding only the run-composition-relative derived metric `external_token_reduction_vs_full_history` (undefined in the Phase 11 matrix because `full_history` is deliberately not re-run; recorded as undefined, never fabricated). The historical committed artifacts were consumed read-only and remain byte-unchanged: candidate 31/50, selection 12/50, MRR 0.305, 5,527 context tokens.

## External retrieval quality (fixed 50-case subset)

| System | Candidate | Selection | MRR | Context tokens | Selected memories |
|---|---|---|---|---|---|
| Phase 9 reference | 31/50 | 12/50 | 0.305 | 5,527 | 51 |
| Embedding-only | 31/50 | 2/50 | 0.168 | 3,950 | 8 |
| Fused (full_fusion) | 31/50 | 13/50 | 0.293 | 5,448 | 48 |
| Fused + gate shadow | 31/50 | 13/50 | 0.293 | 5,448 | 48 |
| naive top-K (historical) | 50/50 | 42/50 | 0.658 | — | — |

Naive top-K retrieves raw history turns rather than distilled lifecycle-safe memories; its higher raw recall is disclosed, not matched.

## Lifecycle results (frozen 40 scenarios)

| System | Passed | Recall@K | Forgotten exclusion | Inactive contamination | Stale leakage |
|---|---|---|---|---|---|
| Phase 9 reference | 21/40 | 17/17 | 2/2 | 0/18 | 7/11 |
| Embedding-only | 15/40 | 2/17 | 2/2 | 0/2 | 7/7 |
| Fused (full_fusion) | 21/40 | 17/17 | 2/2 | 0/18 | 7/11 |
| Fused + gate shadow | 21/40 | 17/17 | 2/2 | 0/18 | 7/11 |

## Lifecycle safety

Inactive contamination, forgotten leakage, and superseded leakage in current mode are **zero for every system**; excluded records were never embedded, fused, or gate-evaluated (enforced by validators and unit tests). `gate_affected_selection` totals **0** across every case of every run. Stale leakage (active-but-outdated values, the documented Phase 9 supersession gap) remains 7/11 for the reference and fused systems and is unrelated to embeddings.

## Cache behavior (deterministic provider)

- Lifecycle (per-case fresh caches, warm reuse within a case): {"evictions": 0, "hits": 44, "invalidated": 0, "lookups": 104, "misses": 60, "stores": 60}
- External fused: {"evictions": 0, "hits": 135270, "invalidated": 0, "lookups": 136547, "misses": 1277, "stores": 1277}

Committed runs are cold-start per case by design (fresh strategy/cache per case keeps runs reproducible); hits are warm reuse across the turns within a case. Warm-cache decision identity (identical selections and scores on repeat retrievals) is unit-proven; latency is wall-clock, excluded from digests, and sub-millisecond per retrieval with this provider (see aggregate `latency` blocks).

## Gate-shadow behavior (fused + heuristic gate)

- External: {"gate_abstain": 27073, "gate_admit": 5028, "gate_affected_selection": 0, "gate_agreement": 4888, "gate_disagreement": 2187, "gate_evaluated": 34148, "gate_failures": 0, "gate_neutral": 27073, "gate_reject": 2047, "gate_selected_proposed_reject": 1752, "gate_skipped_proposed_admit": 435}
- Lifecycle: {"gate_abstain": 36, "gate_admit": 22, "gate_affected_selection": 0, "gate_agreement": 22, "gate_disagreement": 0, "gate_evaluated": 58, "gate_failures": 0, "gate_neutral": 36, "gate_reject": 0, "gate_selected_proposed_reject": 0, "gate_skipped_proposed_admit": 0}

Canonical equivalence with the fused system holds on both benchmarks (full metric equality); proposals are descriptive shadow evidence, never applied, and agreement with the selector is not a ground-truth quality metric.

## Interpretation

- **Embedding-only**: materially worse across the board — lifecycle Recall@K 2/17 vs 17/17, external selection 2/50 vs 12/50, MRR 0.168 vs 0.305. Interestingly its candidate rate matches the reference (31/50) — token-overlap similarity surfaces the same answer-bearing memories as candidates but ranks and selects them far worse without the lexical/structured machinery. This measures the deterministic provider, not embeddings in general.
- **Fused**: a genuinely mixed result. Lifecycle outcomes are identical to the reference (21/40, Recall@K 17/17). Externally it selects the answer session in one MORE case (13/50 vs 12/50) with slightly fewer context tokens (5,448 vs 5,527), but its MRR drops from 0.305 to 0.293 (−3.8% relative — a MATERIAL regression under the ratified threshold), and it adds no new candidates. Below-floor semantic contributions reorder some rankings for the worse under this provider. Mixed single-metric evidence tied to the test provider is inconclusive, not a verdict on learned embeddings.
- **Gate shadow**: proves the controller seam at benchmark scale with zero selection effect and zero failures.

## Adoption gates

Ratified materiality threshold: a drop of more than 1 case on a frozen numerator, or more than 2% relative on a continuous metric, is material.

| Adoption gate | Embedding-only | Fused | Fused+gate |
|---|---|---|---|
| 10_benefit_visible_in_report | FAIL | FAIL | FAIL |
| 1_candidate_or_mrr_improves | FAIL | FAIL | FAIL |
| 2_recall_at_k_no_material_regression | FAIL | PASS | PASS |
| 3_inactive_contamination_zero | PASS | PASS | PASS |
| 4_forgotten_leakage_zero | PASS | PASS | PASS |
| 5_superseded_leakage_zero_current_mode | PASS | PASS | PASS |
| 6_context_within_budget | PASS | PASS | PASS |
| 7_deterministic_fallback_available | PASS | PASS | PASS |
| 8_latency_acceptable_or_optional | PASS | PASS | PASS |
| 9_diagnostics_explain_ranking | PASS | PASS | PASS |

## Classification

- Embedding-only: **not_adopted** (broad material regression: Recall@K, selection, and MRR).
- Fused retrieval: **experimental** (safe and reproducible; mixed single-metric evidence — +1 selection, −3.8% MRR — under the deterministic test provider is inconclusive; adoption requires real-provider evidence).
- Fused + gate shadow: **experimental** (identical canonical behavior; shadow diagnostics only).

## Supported claims

- ExperienceOS benchmarks lexical, semantic, fused, and gate-shadow retrieval under one lifecycle-safe contract.
- The Phase 11 reference reproduces Phase 9 retrieval behavior exactly (full metric equality).
- Lifecycle leakage remained zero and context stayed within budget for every Phase 11 system.
- Cache reuse eliminated repeat embedding work within cases with zero decision drift.
- The gate shadow produced measurable proposal distributions without affecting selection (affected-selection = 0).
- The deterministic provider validated reproducible semantic-retrieval plumbing (double-run digest equality).

## Unsupported claims

- Any official LongMemEval score or improvement.
- Neural/learned semantic retrieval quality (no real embedding provider was exercised).
- Retrieval quality improvement OR harm from fusion (the deterministic-provider evidence is mixed — +1 selection, −3.8% MRR — and does not transfer to learned embeddings).
- MemoryGate usefulness or precision (distributions are descriptive only).
- Answer-quality, cost, or state-of-the-art claims.

## Recommended next step

Retrieval mechanics are proven safe but show no measurable quality gain without a learned provider; the largest documented gaps remain extraction coverage and supersession (stale leakage 7/11). Recommended: proceed to **Phase 12 grounded focused extraction**, keeping fused retrieval as an experimental, optional mode pending real-provider evidence.
