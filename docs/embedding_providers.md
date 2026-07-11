# Embedding Providers (Phase 11, Prompt 2)

The `experienceos/embeddings/` package is the provider-independent
embedding abstraction defined by `docs/phase11_contract.md` §12. It
exists so later Phase 11 prompts can request embeddings without
coupling ExperienceOS core logic to a particular model, library, or
service.

**Status: no retrieval integration exists yet.** Nothing in
`HybridRetrievalStrategy`, selection, context building, or the engine
consumes embeddings. Semantic candidate generation begins in Prompt 3;
score fusion begins in Prompt 4. No retrieval benchmark has been run
for this implementation, and no retrieval-improvement claim is made.

## Authority boundaries

Embedding providers are scoring utilities, not memory managers:

- they receive raw text only — never `ExperienceEntry` objects, a
  `MemoryStore`, an `EventBus`, or mutation callbacks;
- they cannot create, update, forget, supersede, retrieve, or select
  memories, and cannot decide lifecycle eligibility;
- lifecycle filtering remains a hard boundary ahead of any similarity
  computation (contract §10);
- no vector database is used or planned;
- diagnostics never contain absolute paths, environment values, or
  credentials.

## Contract surface (`experienceos/embeddings/base.py`)

- `EmbeddingProvider` (`typing.Protocol`): `provider_id`, `model_id`,
  `dimensions` (may be `None` until discoverable), `availability()`,
  `embed_query(text)`, `embed_memories(texts)`.
- `EmbeddingResult` (frozen): `vector` (tuple of finite floats),
  `dimensions`, `provider_id`, `model_id`, `deterministic`, optional
  `elapsed_ms` (wall-clock, non-deterministic, excluded from
  `to_metadata()` so serialized metadata stays digest-stable).
- `EmbeddingAvailability` (frozen): shallow readiness report —
  producing one never loads a model. Unavailability reasons are the
  stable constants `dependency_missing`, `model_not_configured`,
  `model_missing`, `load_failed`.
- Errors: `EmbeddingInputError` (non-string input),
  `EmbeddingDimensionError` (dimension drift, NaN/inf, empty vector),
  `EmbeddingUnavailableError` (carries the availability report).
- Utilities: `validate_vector` and `cosine_similarity` (strict
  dimension validation; zero vectors compare as 0.0). The similarity
  utility supports tests and future plumbing only — it performs no
  ranking, thresholding, or retrieval.
- `create_embedding_provider(mode)` (`factory.py`): modes
  `disabled` (default, returns `None`), `deterministic`, `local`.
  ExperienceOS never constructs a provider unless a caller explicitly
  asks; there are no global instances and no import-time environment
  reads.

## Deterministic provider (`deterministic`, `stable-feature-hash-v1`)

A dependency-free, offline test embedding provider for unit tests, CI,
plumbing validation, and deterministic fixtures. **It is a test double
for the interface, not a learned language embedding model**: it
captures token overlap (plus mild character-trigram overlap), not
meaning, and must never be cited as evidence of neural semantic
retrieval quality.

Frozen algorithm: casefold, tokenize with `[^\W_]+`; each token adds a
signed unit feature and (for tokens of length ≥ 4) character trigrams
at weight 0.25; features map into 512 dimensions via SHA-256 (never
Python's randomized `hash()`; byte 0-3 select the index, byte 4's low
bit the sign); non-zero vectors are L2-normalized; text with no tokens
embeds to the zero vector, which cosine-matches nothing. Vectors are
byte-equivalent across calls, processes, and machines; no truncation
is applied (cost is linear in input length).

Known limits: no synonym knowledge; stopword overlap and hash
collisions can produce nonzero similarity between unrelated texts.

## Optional local provider (`sentence-transformers-local`)

`experienceos/embeddings/local.py` wraps sentence-transformers behind
the optional extra:

```bash
pip install -e ".[embeddings-local]"
export EXPERIENCEOS_EMBEDDING_MODEL_PATH=/path/to/local/model-dir
```

Safety behavior (tested without the dependency installed):

- the library is imported lazily on the first embedding call — never
  at module, package, or root import, and never for `availability()`
  or factory inspection;
- **no automatic download**: the provider only ever passes an
  already-existing local directory to the library; a hub model name is
  never passed, so nothing can be fetched. A missing path reports
  `model_missing` instead of resolving anything remotely;
- construction mutates no global state; configuration precedence is
  constructor argument, then `EXPERIENCEOS_EMBEDDING_MODEL_PATH`, then
  unavailable;
- CPU-only (`device="cpu"`);
- diagnostics are path-free: `model_id` is the directory basename (or
  an explicit `model_label`, e.g. `all-MiniLM-L6-v2`), details
  reference the environment variable by name, and load failures report
  only the exception type name;
- `dimensions` is `None` until the first successful embed, then fixed
  and validated for every subsequent vector.

The candidate small models named by the contract (`all-MiniLM-L6-v2`,
`BAAI/bge-small-en-v1.5`) must be obtained manually and saved locally;
this provider is not part of any canonical retrieval configuration
yet.

Default installs, default tests, CI, demo validation, and all
benchmark validators require no embedding library, no model file, and
no network.
