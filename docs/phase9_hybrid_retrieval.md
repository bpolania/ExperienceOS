# Phase 9: Lifecycle-Aware Hybrid Retrieval

Prompt 4 of the [Phase 9 experiment contract](phase9_experiment_contract.md).
Implemented in `experienceos/context/retrieval.py` (query
normalization, candidate generation, scoring, lifecycle filtering)
behind an optional `retrieval_strategy` seam on the existing
`ContextBuilder` — when unset (every v1 configuration), context
selection is byte-identical to Phase 8, and there is exactly one
context assembly path. Exercised through
`experienceos_hybrid_retrieval_v2` (ablation C: rules extraction +
hybrid retrieval) and `experienceos_extract_retrieval_v2` (ablation D:
Prompt 3 extraction + hybrid retrieval).

## Strategy interface

`RetrievalStrategy.retrieve(RetrievalRequest) -> RetrievalResult` —
provider-independent, versioned (`retrieval_strategy_version = 1`).
Requests carry the query, the candidate memories, K, the session, and
an optional token budget — never benchmark expected answers,
answer-session oracles, scenario IDs, or inactive records presented as
truth. Results carry selected memories, every candidate with component
scores and exclusion reasons, counts, K/budget compliance, and
warnings. **Retrieval selects existing memories only** — it never
creates, updates, supersedes, forgets, or rewrites provenance.

## Lexical candidate generation

Deterministic normalization: Unicode NFKC, case folding, punctuation
and possessive removal, safe plural folding only (never `-ss/-us/-is`,
so Celsius/status stay intact), stopword removal, and safe prefix
matching (a ≥5-character token matches its inflections: "commit" ↔
"committing"; "book" never matches "bookshelf"). Distinct values stay
distinct: Pixel 6 vs Pixel 9, Monday vs Thursday, aisle vs window,
Celsius vs Fahrenheit, Acme vs Globex. Multi-word entities and model
numbers are preserved as phrases. A small transparent alias registry
(employer↔work/company, phone↔mobile/device, residence↔live/city,
seat↔aisle/window, school↔attends/goes, language↔speaks,
send↔route/channel, weather↔forecast, drink↔coffee/tea,
food↔meal/recipe/snack) expands query tokens only; no alias was
derived from benchmark answers. Lexical relevance is a BM25-style
summed IDF over the bounded in-process active-memory corpus — no
search service, no index, no embeddings (deferred: structured identity
plus lexical signals met the lifecycle targets without adding model
weights or a network dependency; an embedding seam remains a candidate
for later prompts).

## Structured semantic signals

Prompt 2 identity metadata contributes attribute (expanded-query
match), value (query-token match), and scope compatibility scores;
Prompt 3 extraction/identity confidence contributes a small refinement
term. Existing tags/domains contribute a domain score. Kind priority
(instruction > fact > preference) and confidence refine ranking but
**never create relevance on their own** — zero-signal memories are
excluded, never selected to fill K.

## Scoring and determinism

Explicit versioned weights (`SCORING_WEIGHTS`, lexical-scoring version
1): lexical 1.0, phrase 1.5, entity 2.0, attribute 1.2, value 1.5,
scope 0.8, domain 0.6, kind 0.15, confidence 0.1 — tuned only on
phase9_dev fixtures, never on frozen scenario IDs, with no per-case
exceptions. Tie-breaking: final score ↓, phrase+entity score ↓, kind
priority ↓, confidence ↓, recency ↓, memory ID ↑. Unranked candidates
(inactive, zero-relevance) keep deterministic append order. Repeated
runs produce identical rankings and identical normalized artifact
digests; measured latency is kept out of digested diagnostics.

## Lifecycle filtering

Non-negotiable, enforced before ranking: forgotten and superseded
records are excluded with audited reasons (`inactive_forgotten`,
`inactive_superseded`), never ranked, never compressed, never
rendered. Current queries use active memories only. No historical
retrieval mode exists in the repository, so none was added —
`historical_mode` requests are answered with active-only results plus
a warning (Prompt 6 owns temporal semantics). Unresolved active
conflicts (extraction-only configurations can hold two same-slot
values) are counted in diagnostics (`unresolved_conflict_pairs`,
multi-valued slots exempt) and reported — never silently resolved by
recency.

## K and token budgets

K is the existing memory budget, unchanged; candidate generation may
score every active memory, but the final selection never exceeds K
and is never padded. The optional token budget deterministically skips
ranked memories that do not fit (`token_budget` reason); canonical
benchmark configurations leave it unset, preserving Phase 8 semantics
exactly. Counts recorded per retrieval: active, inactive-filtered,
lexical candidates, zero-relevance exclusions, selected,
skipped-not-top-K, skipped-for-budget, K/budget compliance.

## Provenance and diagnostics

Retrieval reads and never rewrites semantic identity, extraction
provenance (source_ref, evidence, versions), and lifecycle linkage;
benchmark evidence keeps source-session attribution for answer-session
scoring. Selection records gain `component_scores` and
`exclusion_reason` fields (empty on the v1 path); existing
selected/skipped dashboard panels keep working unchanged.

## Ablation configuration

Both v2 systems keep the v1 provider, dataset, K, token budget, answer
generation, and metric definitions. `experienceos_hybrid_retrieval_v2`
keeps v1 rules extraction and lifecycle (its stored memories equal the
rules system's); `experienceos_extract_retrieval_v2` composes Prompt 3
hybrid extraction (extraction-only lifecycle — no Prompt 2 generalized
supersession) with hybrid retrieval. Neither enables Prompt 5 coverage
selection, Prompt 6 temporal logic, or Prompt 7 policy changes; full
provenance is recorded per run. `experienceos_rules`,
`experienceos_slots_v2`, and `experienceos_hybrid_extract_v2` are
untouched.

## Known limitations and the Prompt 5 boundary

Lexical retrieval is a candidate-recall mechanism, not semantic
understanding: memories whose wording shares nothing with the query
("total number of siblings" vs a stored networking preference) remain
unreachable without embeddings, and dropping v1's zero-relevance
padding removes the accidental answer-session credit that padding used
to earn on the external subset — selection counts fall there while
MRR, Recall@K, and context cost all improve. Coverage-aware and
diversity-aware final composition (multi-facet questions, redundancy
penalties) is deliberately deferred to Prompt 5. Development results
under `benchmarks/results/local/` are not final Phase 9 evidence
(Prompt 8 owns committed v2 artifacts).
