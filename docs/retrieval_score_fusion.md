# Retrieval Score Fusion (Phase 11, Prompt 4)

Deterministic, inspectable fusion of the existing retrieval signals in
`experienceos/context/fusion.py`, consumed by `HybridRetrievalStrategy`
in the new `fused` semantic mode. This is the mechanism only: **no
benchmark has evaluated any fused profile, and no adoption claim is
made** — Prompt 7 measures it, and every profile may end up classified
experimental.

## Component inventory and classification (audited)

| Component | Raw source | Range | Class |
|---|---|---|---|
| `lexical` | `component_scores["lexical_score"]` (summed IDF) | unbounded ≥ 0 (observed 1.8–5.4) | primary relevance |
| `structured` | SCORING_WEIGHTS-weighted sum of `phrase/entity/attribute/value/scope/domain` raw scores (`fusion.structured_aggregate`) | small ≥ 0 (strong ≈ 3.5) | primary relevance |
| `semantic` | Prompt 3 semantic score | [0, 1] | primary relevance |
| `temporal` | `TemporalRetrievalPolicy.score` bonus — includes `trust_score`, the only implemented provenance signal (no separate provenance component exists; none was invented) | [0, ≈0.85] | compatibility |
| kind priority, confidence, recency, stable ID | existing refiners | — | rank refiners (never fused, never create relevance) |
| user scope, lifecycle status, historical admission | store scoping + step-1 filter + temporal policy | — | hard eligibility (never a weight) |

## Normalization `bounded_ratio-1`

Per-candidate, monotonic, deterministic — never per-query min-max, so
identical raw evidence always normalizes identically:

- `lexical`: `x / (x + 3.0)` — 3.0 ≈ observed matched-sum midpoint
  (1.8 → 0.37, 5.4 → 0.64); asymptotic bound means an unbounded raw
  value can never exceed its weight.
- `structured`: `x / (x + 2.0)` (entity+phrase pair ≈ 3.5 → 0.64).
- `semantic`: identity (already [0, 1]; out-of-range rejected).
- `temporal`: `min(x, 1.0)` (bounded ≈ 0.85 by construction).

Missing evidence contributes exactly 0.0 — never fabricated. NaN,
infinity, negatives, and unknown components raise `FusionConfigError`.

## Profiles (all version `1`, frozen, serializable, validated)

| Profile | Weights | Purpose |
|---|---|---|
| `lexical_reference` | — (bypass) | routes through the unchanged Phase 9 lexical path; fusion math never runs, the provider is never inspected. The zero-semantic reference. |
| `embedding_only` | semantic 1.0 | delegates to the Prompt 3 `semantic_only` implementation (no duplication); lexical never mixed in. |
| `lexical_semantic` | lexical 0.55, semantic 0.45 | token-vs-embedding ablation. |
| `structured_semantic` | structured 0.55, semantic 0.45 | the whole lexical token aggregate is excluded (not just exact matches); structured-identity-vs-embedding ablation. |
| `full_fusion` (default) | lexical 0.35, structured 0.25, semantic 0.30, temporal 0.10 | candidate recommended configuration. |

Weight rationale: lexical+structured hold the majority (0.60) so exact
matches stay competitive; semantic 0.30 can lift lexically missed
candidates; temporal 0.10 refines. Chosen from the range audit, signal
precision, and exact-match preservation on unit fixtures — never from
LongMemEval labels, frozen scenarios, or Phase 9 per-case misses.
These are architectural starting values, not learned truth.

## Fused candidate pool

Union over the **already lifecycle-admitted** entries only:

- enters with positive lexical/structured relevance (the existing
  `relevance > 0` gate), OR
- enters with a semantic score strictly above the relevance floor
  (0.30), OR both.

Semantic-floor rule: a lexically relevant memory keeps its below-floor
semantic score as a fusion contribution (it refines an already
relevant candidate); a memory with no lexical relevance needs an
above-floor score (collision noise cannot introduce irrelevant
memories). Kind, confidence, recency, temporal bonus, and IDs never
create eligibility. Zero-evidence memories are excluded as
`no_fused_evidence`; nothing is padded toward K. Each candidate is
classified `lexical_only` / `semantic_only` / `lexical_and_semantic`.

## Formula and ranking

`fused_score = Σ weight(c) × normalized(c)` over
lexical/structured/semantic/temporal — reconstructable from the
per-candidate `contributions` dict (tested equality). Ranking tuple
(the shared deterministic sort): `(-fused_score, -(phrase+entity raw),
-kind_priority, -confidence, -created_at, memory.id)`. Candidate
limit applies after fused ranking; the existing selection layer (K or
coverage) and the context-token budget are unchanged downstream.

## Fallback

If a fused profile needs semantic evidence and the provider is
unavailable or fails (typed embedding errors only): retrieval uses the
**exact lexical reference path**, recording `fallback_used`,
the sanitized reason, and `fallback_path: "lexical_reference"`. No
partial union survives; no semantic score is fabricated.
`semantic_strict=True` raises instead. With `lexical_reference`
selected the provider is never inspected at all (proven with a
provider that raises on any access, including `availability()`).

## Diagnostics

Per candidate (`RetrievalCandidate.fusion`): profile ID/version,
normalization ID, raw, normalized, weights, contributions, fused
score, evidence source, lexical rank (pre-fusion, existing tuple),
semantic rank, fused rank, rank delta. Raw `component_scores` are
never overwritten. Per retrieval
(`RetrievalResult.semantic["fusion"]`): profile metadata, eligible/
lexical/semantic/overlap/lexical-only/semantic-only/union/post-limit
counts, promoted-by-semantic, demoted-after-fusion. No vectors, no
paths, no secrets; old events and consumers remain valid (all fields
additive, `None`/absent outside fused mode).

## Limits and lifecycle authority

Fusion runs strictly after the step-1 lifecycle filter; excluded
records get no semantic evidence, no fusion breakdown, and never reach
the provider (spy-tested with maximum-evidence forgotten/superseded
fixtures). No profile — including an adversarial all-max-weight
profile — can admit an inactive record. `candidate_limit`, selection
K, and token budgets are enforced unchanged. The fusion layer holds no
store, bus, engine, or mutation handle and persists nothing.

## Gate shadow observation (Prompt 5)

The shadow MemoryGate (`docs/memory_gate.md`) observes retrieval
results strictly after selection and budget enforcement are final: it
reads fusion breakdowns as evidence and attaches additive diagnostics,
but cannot alter fusion scores, the candidate union, ranking, or
selection in any configuration.

## Measured status (Prompt 7)

Benchmarked in `docs/phase11_semantic_retrieval_report.md`:
`experienceos_fused_retrieval_v1` (this module's `full_fusion`
profile) is classified **experimental** — external selection improved
by one case (13/50 vs 12/50) with fewer context tokens (5,448 vs
5,527), but MRR regressed materially (0.293 vs 0.305, −3.8%) under the
deterministic test provider; lifecycle outcomes were identical to the
Phase 9 reference and all safety gates passed. Mixed single-metric
evidence tied to the test provider is inconclusive for learned
embeddings.

## Limitations

Deterministic-provider fixtures demonstrate the mechanism (a
semantic-evidence candidate can enter and reorder ranking) via token
overlap, not meaning. Weights and the semantic floor are uncalibrated
for learned providers. No retrieval-quality, MRR, Recall@K, or
LongMemEval claim is supported by this prompt.
