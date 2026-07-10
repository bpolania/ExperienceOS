# Phase 9: Coverage-Aware Context Selection

Prompt 5 of the [Phase 9 experiment contract](phase9_experiment_contract.md).
Implemented in `experienceos/context/selection.py` behind an optional
`selection_strategy` seam on Prompt 4's `HybridRetrievalStrategy` —
when unset (every v1 and Prompt 4 configuration), final selection is
the unchanged deterministic top-K loop, and there is still exactly one
context-assembly path through the existing `ContextBuilder`.
Exercised through `experienceos_coverage_v2` (ablation E) and a
development-only extraction+retrieval+coverage composition.

## What it does

Coverage selection operates on Prompt 4's lifecycle-filtered, scored
ACTIVE candidate pool — it is the final selection layer, not a new
retrieval engine. It never creates, updates, or mutates memories,
never receives benchmark oracle data, and never restores
zero-relevance padding: retrieval relevance remains the foundation of
utility, and the strongest direct match normally stays first.

## Query and candidate facets (version 1)

`extract_query_facets` derives a deterministic facet set from the
query and the transparent alias registry only: `token:`, `entity:`,
`attribute:` (alias-class canonical names), and `domain:` facets, plus
two cues — `multi_facet` (conjunctions, "what do you know", ≥2
attributes or entities) and `multi_valued` ("which languages…").
A single-request query legitimately has few facets. Candidate facets
are grounded in the matched query evidence and the candidate's own
structured metadata: matched tokens/entities, semantic attribute,
`value:attr=value`, non-global scope, matched domains, memory kind.

## Redundancy and complements

Deterministic signals against the already-selected set: same semantic
slot and value (paraphrase), near-duplicate text (token Jaccard ≥
0.8), identical matched-evidence sets. Multi-valued same-attribute
values ("Speaks Spanish" + "Speaks Portuguese") are complementary and
earn a complement bonus instead. Same-session memories with different
attributes are never automatically redundant. Redundant candidates are
penalized, not banned — a strong enough base score can still admit
one, and it is counted (`selected_redundant`).

## Iterative utility (weights version 1)

MMR-style, per step: `base_relevance` (Prompt 4 final score, weight
1.0) + `facet_gain` 0.6/new query facet + `attribute_gain` 0.8 (first
coverage of an attribute) + `value_complement` 0.7 (new multi-valued
value) + `entity_gain` 0.5 + bounded `source_diversity` 0.4 (only for
multi-facet queries when a new session adds new query facets and is
not redundant or conflicting) + `instruction_gain` 0.3 +
`confidence_gain` 0.1 + small `token_efficiency` 0.15/(1+tokens/20) −
`redundancy_penalty` 1.2/signal (capped) − `conflict_penalty` 2.0.
Selection stops at K, at the token budget, or when no remaining
candidate has positive utility — unused K is allowed and counted;
nothing is padded.

## Conflict visibility

Same-slot different-value active candidates (single/unknown
cardinality; multi-valued exempt) are unresolved conflicts: they earn
no diversity bonus, are penalized, and when kept out of context they
are explicitly marked `conflict_contained` — the warning survives
whether or not the conflicting record is selected. Which value wins
follows the pre-existing deterministic recency tie-break; nothing is
silently designated true, and Prompt 2 composition remains the proper
lifecycle fix. On the frozen lifecycle dataset this containment
REDUCED stale rendered-context leakage (10/11 → 8/11) and inactive
contamination (2/20 → 0/18) relative to Prompt 4 selection.

## Determinism, K, and budgets

Tie-break order: utility ↓, new-facet count ↓, base score ↓,
phrase+entity ↓, kind priority, confidence ↓, token estimate ↑,
Prompt 4 retrieval rank ↑ (unique, creation-ordered — never runtime
UUIDs). Latency stays out of digest-sensitive diagnostics. K and token
budget semantics are unchanged and enforced in the same place as
Prompt 4; rerun digests match exactly.

## Diagnostics

Every selected candidate records step, utility, new facets, redundancy
penalty, source-diversity/instruction/confidence/token contributions,
conflict warning, and a human-readable reason
(`RetrievalResult.coverage.steps`); skipped candidates carry reasons
(`not_selected_by_coverage`, `not_top_k`, `token_budget`,
`conflict_contained`, upstream `zero_relevance`/lifecycle reasons).
Prompt 4 component scores and exclusion reasons are preserved
untouched; benchmark and dashboard channels read their original keys.

## Configuration

`experienceos_coverage_v2`: v1 rules extraction and lifecycle, Prompt
4 hybrid retrieval, Prompt 5 coverage selection; unchanged K, budget,
provider, dataset, metrics; no Prompt 2 supersession, no Prompt 3
extraction, no Prompt 6/7 behavior — all recorded in provenance. The
development composition (`coverage_selection=True` on the ablation D
adapter, system-ID `dev_extract_retrieval_coverage`) is never a
contract system and never `experienceos_hybrid_full_v2`.

## Known limitations and the Prompt 6 boundary

Coverage helps when candidate pools exceed K or contain redundancy;
after Prompt 4's zero-relevance exclusion, the external subset rarely
crowds K=6, so external selection/MRR were unchanged there (tokens
slightly lower) — the measured wins are lifecycle-side (leakage,
contamination, conflict visibility). Facet extraction is lexical and
registry-based, not semantic. Temporal/historical evidence handling,
validity intervals, and assistant-derived provenance belong to Prompt
6. Development results are not final Phase 9 evidence (Prompt 8 owns
committed v2 artifacts).
