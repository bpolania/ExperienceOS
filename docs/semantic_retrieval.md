# Semantic Retrieval (Phase 11, Prompt 3)

Lifecycle-safe semantic candidate scoring and generation over the
Prompt 2 embedding abstraction. This is plumbing plus a clearly
separated experimental mode — **not** the canonical retrieval
configuration: full lexical+semantic score fusion is Prompt 4, and no
benchmark evidence exists yet (Prompt 7). No retrieval-improvement
claim is made here.

## Lifecycle-first order (binding)

`HybridRetrievalStrategy.retrieve` (`experienceos/context/retrieval.py`)
keeps its Phase 9 shape: user scoping happens at the store, lifecycle
eligibility is decided in step 1 (active only; superseded admitted
solely by the audited temporal policy under explicit historical
intents; forgotten never), and **semantic scoring runs strictly after
that filter** — only admitted entries are ever canonicalized, embedded,
cached, or scored. Excluded records are never sent to a provider and
carry `semantic: {"considered": false}` in semantic modes. Embedding
similarity can rank eligible memories; it cannot make an ineligible
memory eligible, and there is no second admission path.

## Modes (`semantic_mode`, fixed per strategy instance)

Prompt 4 added a fourth mode, **`fused`**, which combines normalized
lexical/structured/semantic/temporal evidence under fixed versioned
profiles — see `docs/retrieval_score_fusion.md`. The three Prompt 3
modes below remain available and unchanged; semantic scores are now
consumable by fused retrieval through the same single
`SemanticCandidateGenerator` invocation. No canonical adoption
decision has been made for any semantic or fused mode.

- **`disabled`** (default): byte-identical Phase 9 behavior. No
  provider constructed or invoked, no cache activity, empty
  `result.semantic`, `candidate.semantic is None`. Regression-tested
  against the plain strategy for identical candidates, order, scores,
  reasons, and rendered context.
- **`score_only`**: the Prompt 4 seam. Semantic scores are computed
  and attached as diagnostics (`candidate.semantic`,
  `component_scores` untouched); lexical ranking and selection are
  provably unchanged.
- **`semantic_only`**: embedding similarity generates candidates from
  the admitted pool — the mode that can find a memory whose *text*
  lexically mismatches the query (via canonicalized identity fields).
  Experimental, not canonical; benchmarked in Prompt 7.

Mode selection is explicit, deterministic, and never derived from
query content.

## Semantic component

`SemanticCandidateGenerator` (`experienceos/context/semantic.py`)
takes an `EmbeddingProvider` and owns a bounded `EmbeddingCache`. It
receives only already-admitted entries, holds no store/engine/bus/
callback, mutates nothing, and returns vector-free
`SemanticScore`/`SemanticScoringOutcome` records (raw cosine, score,
rank, cache status, floor flag, bounded latency).

## Cache

`EmbeddingCache` (`experienceos/embeddings/cache.py`): process-local,
LRU, default bound 4096 entries, owned per generator instance (no
global singleton), explicit `clear()`. Canonical key:
`(provider_id, model_id, dimensions, sha256(canonical text))` — text,
provider, model, or dimension changes miss by construction. The
optional provider's late dimension discovery (dimensions `None` before
first embed) makes first lookups misses; entries are stored under the
dimensions the provider actually returned. `get` re-validates stored
vectors and drops incompatible entries (`invalidated` counter). Query
embeddings are not cached (one embed per retrieval call; no bounded
reuse case yet). Nothing is persisted: no vector database, no SQLite
table, no schema migration, no vectors in memory metadata.

## Canonical memory text

`memory_embedding_text(entry)`: memory text + semantic-identity
attribute/value/scope (underscores spaced, `global` omitted) + sorted
tags, newline-joined. Lifecycle status, user IDs, timestamps, internal
IDs, and diagnostics are excluded — they are not memory meaning. The
cache digest is computed over exactly this string.

## Scores, floor, ranking

Semantic score = `max(0, cosine)` in [0, 1]; raw cosine kept in
diagnostics. Relevance floor default **0.30** (candidates must score
strictly above it), chosen from deterministic-provider measurements:
unrelated short texts reach ~0.25 via shared stopwords and signed-hash
collisions, while two-plus shared meaningful tokens score 0.45–0.60.
The floor is fixed configuration — never query- or benchmark-derived —
and is *not* claimed optimal (weak single-token matches on long
queries fall below it); Prompt 7 evaluates it. A zero-vector query
(no tokens) yields zero scores and no candidates — recorded, never
fabricated. No zero-score padding toward K: fewer qualifying memories
mean fewer candidates.

Semantic-only ranking tuple: `(-semantic_score, -(phrase+entity)=0,
-kind_priority, -confidence, -created_at, memory.id)` — the shared
deterministic step-4 sort with non-relevance refiners only; lexical
scores are never mixed in (that is fusion, Prompt 4). Candidate
limits, downstream selection (K), and the context-token budget apply
unchanged.

## Fallback

Provider unavailable or failing (typed `EmbeddingProviderError` only):
retrieval falls back deterministically to the unchanged lexical path,
recording `fallback_used` and the sanitized, path-free reason in
`result.semantic`. `semantic_strict=True` raises the typed error
instead (no silent degradation); the default favors safe fallback.
Programming errors are never swallowed.

## Diagnostics (additive, vector-free)

Per candidate (`RetrievalCandidate.semantic`): considered flag, score,
raw cosine, semantic rank, floor, cache status, provider/model IDs,
dimensions — or `{"considered": false}` for lifecycle-excluded records.
Per retrieval (`RetrievalResult.semantic`): mode, provider
availability/IDs, dimensions, floor, eligible/scored/candidate counts,
query-zero flag, `{"elapsed_ms": …}` timing blocks (wall-clock,
non-deterministic, named for the existing digest-normalization
convention), cache counters, fallback state. `summary()` gains a
`semantic_retrieval` block only when configured. Old payloads remain
valid; disabled mode adds nothing. Dashboard visibility is Prompt 8.

## Measured status (Prompt 7)

Benchmarked in `docs/phase11_semantic_retrieval_report.md`:
`semantic_only` (as `experienceos_embedding_only_v1`) is classified
**not_adopted** under the deterministic test provider (lifecycle
Recall@K 2/17, external selection 2/50 vs 12/50) — a result about the
test provider's token-overlap embeddings, not learned embeddings.
Lifecycle safety stayed zero-leakage in every mode.

## Limitations

Deterministic-provider scores measure token overlap, not meaning —
they validate plumbing, not semantic quality. No fusion, no MemoryGate,
no adoption decision, no benchmark evidence yet. The cache is
process-local (rebuilt per process). The optional local provider was
not exercised on this machine (`dependency_missing`); no model was
downloaded.
