# Phase 11 Contract — Semantic Retrieval and Specialized Controller Foundation

**Decision: PHASE_11_CONTRACT_COMPLETE**

This document is the binding implementation contract for ExperienceOS
Phase 11. It records the verified starting baseline, the inspected
current architecture, the planned seams, the metric and adoption-gate
definitions, and the safety invariants that Prompts 2 through 9 must
uphold. Where this contract and a later prompt disagree, the safety
invariants in this contract win.

Everything in "Current" sections below was verified against the live
repository at commit `340cab0` on 2026-07-11. Everything in "Planned"
sections is design intent, not yet implemented.

---

## 1. Decision and objective

- **Prompt 1 decision:** `PHASE_11_CONTRACT_COMPLETE`.
- **Phase 11 objective:** add an optional, replaceable semantic
  retrieval capability (embedding provider, semantic scoring, bounded
  cache, deterministic score fusion) plus the first specialized
  learned-controller seam (a shadow-only MemoryGate), without weakening
  any lifecycle guarantee, determinism property, or offline default.
- **Why semantic retrieval:** the committed Phase 9 evidence shows the
  lexical hybrid retriever's residual failures are semantic, not
  mechanical. On the frozen LongMemEval 50-case subset the final
  system (`experienceos_hybrid_full_v2`) leaves 19 cases with no
  answer-bearing candidate at all and 19 further cases where a
  candidate exists but is not selected
  (`benchmarks/results/committed/report-v2/failure_summary_v2.json`);
  lifecycle stale leakage remains 7/11. Lexical expansion (alias
  classes, prefix matching) has been pushed about as far as it goes.
- **Phase 9 weakness targeted:** answer-bearing candidate rate 31/50
  and MRR 0.305 versus the naive top-K raw-turn reference at 50/50 and
  0.658 — the gap is dominated by paraphrase and vocabulary mismatch
  between queries and distilled memories.
- **Adoption is conditional.** Semantic retrieval becomes a
  recommended configuration only if the adoption gates in §17 pass. If
  they fail, it ships as a documented optional mode (or is dropped)
  and `experienceos_hybrid_full_v2` remains the recommended system.
  Embeddings are a hypothesis to test, not an assumed improvement.
- **Architecture doctrine (binding, from Phase 10):** do not make one
  generic local LLM responsible for every memory decision. Phase 11
  builds a deterministic experience kernel supported by specialized,
  replaceable learned controllers that propose, score, gate, and
  compress experience without owning durable state. The real
  Qwen2.5-0.5B local model remains a failure-containment and
  proposal-interface proof (0/15 and 0/8 directly valid proposals,
  fully contained), not a reliable autonomous memory manager, and must
  never be described as one.

## 2. Verified starting baseline (2026-07-11)

| Item | Verified value |
|---|---|
| Branch | `main` |
| Local HEAD | `340cab0e31ee51edac1d50bf35e7db7e2c3c6cce` ("Close and document Phase 9") |
| `origin/main` | `340cab0e31ee51edac1d50bf35e7db7e2c3c6cce` |
| Ahead/behind | 0 / 0 |
| Working tree | clean (no staged, unstaged, or untracked files) |
| Expected baseline ancestry | baseline commit **is** HEAD (`git merge-base --is-ancestor` passed) |
| Full test suite | `PYTHONPATH=. .venv/bin/python -m pytest` → **1043 passed**, 0 skipped, exit 0 |
| Demo validation | `PYTHON=.venv/bin/python ./scripts/validate_demo.sh` → "Offline demo validation passed." |
| v1 lifecycle validator | `./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1` → passed |
| v1 external validator | `./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1` → passed |
| v1 report validator | `./scripts/run_benchmarks.sh validate-report` → passed |
| v2 lifecycle validator | `./scripts/run_benchmarks.sh validate-v2` → passed |
| v2 external validator | `./scripts/run_benchmarks.sh validate-external-v2` → passed |
| v2 consistency validator | `./scripts/run_benchmarks.sh validate-v2-consistency` → passed |
| report-v2 validator | `./scripts/run_benchmarks.sh validate-report-v2` → passed |

Test-count note: `docs/phase9_closure.md` cites 1036 tests as of
Prompt 8; the final Phase 9 commit (`340cab0`) added
`tests/test_phase9_closure_docs.py` (7 tests), giving the current
1043. All pass; no deviation from the accepted Phase 10 baseline.

Historical artifact inventory (all present, digest-locked, validated
read-only above; Phase 11 must not modify, regenerate, or reinterpret
any of them):

| Evidence | Path | Normalized digest |
|---|---|---|
| Phase 8 lifecycle (v1) | `benchmarks/results/committed/lifecycle-offline-v1/` | `8b0e245d914a43bc578923111e8ff40e70d9c8aa487664c00125fc52fa319b33` |
| Phase 8 LongMemEval (v1) | `benchmarks/results/committed/longmemeval-50-subset-v1/` | per `artifact_manifest.json` |
| Phase 8 report (v1) | `benchmarks/results/committed/report-v1/` + `docs/benchmark_report.md` | per `report_spec.json` |
| Phase 9 lifecycle v2 ablation | `benchmarks/results/committed/lifecycle-v2-ablation/` | `ee437bb3e9fde909f343112e40aaa6ecf63155a07a81ad67e017e310fbefb547` |
| Phase 9 LongMemEval v2 | `benchmarks/results/committed/longmemeval-50-subset-v2/` | `19b66cacb330e943b0460ccdb33e8cc6577fccb17621cb7a129f7420f5c7868f` |
| Phase 9 report v2 | `benchmarks/results/committed/report-v2/` + `docs/benchmark_report_v2.md` | report data `3bc955b0c4940ef73a01c4066bff695596fc45cc144f8c850441ed30f5ab76fd` |

Historical system IDs (frozen; never rename): `stateless`,
`full_history`, `append_only`, `naive_top_k`, `experienceos_rules`,
`experienceos_local`, and the eight Phase 9 v2 IDs declared on
`benchmarks/contract/system.py:SystemId`, including
`experienceos_hybrid_full_v2`.

Repository hygiene (verified): 316 tracked files; the only tracked
sensitive-pattern match is `.env.example` (4 placeholder keys, no
values); no tracked GGUF/ONNX/safetensors/SQLite/credential files; the
largest tracked files are the committed benchmark JSONL evidence
(≤ 6.9 MB, expected); `.gitignore` covers `.env`, `*.gguf`,
`*.sqlite`/`*.sqlite3`, `.experienceos/`, `benchmarks/results/local/`,
`benchmarks/.cache/`, `benchmarks/data/external/`, `__pycache__/`, and
`.venv/`. A local `.env` exists and is correctly ignored. Gap for
Phase 11: no explicit ignore entries yet for embedding-model formats
(`*.onnx`, `*.safetensors`, `*.pt`) or embedding caches — Prompt 2
must add narrow entries alongside the code that could produce such
files, and must default all model/cache paths outside the repository
(the `~/.cache/experienceos/` convention used by the local GGUF
runner). No ignore edit is needed in Prompt 1 because no code can yet
produce those files.

## 3. Architecture authority boundaries (binding)

- **`ExperienceEngine`** (`experienceos/engine/experience_engine.py:36`)
  remains the sole mutation authority: only
  `_apply_memory_actions` applies CREATE/SUPERSEDE/FORGET to the
  store, after engine-side lifecycle validation (`target_not_active`,
  `duplicate_of_active` rejection).
- **`ExperienceManager`** (`experienceos/policy/manager.py:53`)
  remains validation and fallback authority: proposal validation,
  whole-batch low-confidence rejection, contradiction resolution, and
  deterministic fallback. It holds no store access and applies no
  mutations.
- **`ContextBuilder`** (`experienceos/context/builder.py:88`) remains
  final context selection and rendering authority, delegating audited
  selection to the retrieval/selection strategies it owns.
- **Controllers are proposal-only.** No Phase 11 controller
  (MemoryGate included) may receive a `MemoryStore` reference, a
  mutation callback, or the `EventBus`. Controllers receive frozen
  inputs and return proposal dataclasses; the kernel decides.
- **Embedding providers never touch the store.** An
  `EmbeddingProvider` receives only text (queries and memory texts)
  and returns vectors and status metadata. It never sees
  `ExperienceEntry` lifecycle fields, never mutates anything, and
  never performs lifecycle reasoning.
- **Lifecycle filtering is a hard boundary before learned scoring.**
  Eligibility is decided before any similarity computation (see §4 and
  §10). Embedding similarity operates only on the already-admitted
  population and can never re-admit an excluded record.

## 4. Current retrieval architecture (verified from code)

Call path for one interaction:

`ExperienceOS` (`experienceos/sdk.py:47`, composition root) →
`ExperienceEngine.run_interaction`
(`experienceos/engine/experience_engine.py:57`) →
`memory_store.active_for_user(user_id)` (plus SUPERSEDED records only
when `context_builder.wants_inactive_candidates` is true — i.e., a
temporal policy is configured; FORGOTTEN records are never fetched) →
`ContextBuilder.build_context` (`experienceos/context/builder.py:112`)
→ `HybridRetrievalStrategy.retrieve`
(`experienceos/context/retrieval.py:410`) → optional
`CoverageSelectionStrategy.select`
(`experienceos/context/selection.py:335`) → rendered sections and
`ContextBuildResult` → `experience_manager.plan(PolicyContext)` →
engine-side validation → `_apply_memory_actions` → provider
`ModelProvider.complete`.

`HybridRetrievalStrategy.retrieve` sequence (exact, verified):

1. **Lifecycle filtering — hard pre-filter**
   (`retrieval.py:433-459`): without a temporal policy, only
   `status == MemoryStatus.ACTIVE` records are admitted; everything
   else is diverted into the audit trail with reason
   `inactive_{status}` and is never scored. With a temporal policy,
   `TemporalRetrievalPolicy.admit`
   (`experienceos/memory/temporal.py`) decides: superseded records are
   admitted only under explicit historical/as-of/timeline intents;
   forgotten records are never admitted in any mode; not-yet-valid
   active records are held for current queries.
2. **Corpus statistics** (`retrieval.py:461-471`): per-document token
   sets and a BM25-style IDF over the admitted population only.
3. **Scoring** (`retrieval.py:473-495`, `_score` at 635): per-memory
   component scores (see §"signals" below); `final_score <= 0` →
   excluded as `zero_relevance`; the temporal policy then refines
   (bonus) already-relevant candidates and never creates relevance.
4. **Deterministic ranking** (`retrieval.py:497-510`): sort key
   `(-final_score, -(phrase+entity), -kind_priority, -confidence,
   -created_at, memory.id)`; `candidate_limit` trims to
   `max(candidate_limit, k)` with reason `below_candidate_limit`.
5. **Selection** (`retrieval.py:518-544`): either the default top-K
   loop with optional `token_budget` enforcement (reasons `not_top_k`,
   `token_budget`) or delegation to `CoverageSelectionStrategy`
   (MMR-style utility, conflict containment, timeline chronology,
   per-step audit records and skipped-reason dict).

Current scoring signals, all computed in
`HybridRetrievalStrategy._score` (`retrieval.py:635-704`) and weighted
by `SCORING_WEIGHTS` (`retrieval.py:48`): `lexical_score` (summed IDF
over exact/alias-expanded/prefix-matched tokens — unbounded ≥ 0),
`phrase_score`, `entity_score`, `attribute_score`, `value_score`,
`scope_score`, `domain_score` (small counts / indicator values), plus
`kind_priority` and `confidence`, which refine ranking but — via the
`relevance > 0.0` gate at `retrieval.py:698-704` — can never create
relevance on their own. Scores are **not normalized**; `final_score`
is an unbounded non-negative float rounded to 6 decimals. Recency is a
tie-break only, never a score. Alias classes and their canonical names
are exported as `ALIAS_CLASSES` / `ALIAS_CANONICAL`
(`retrieval.py:178-193`) and consumed by
`selection.py:extract_query_facets`.

Diagnostics: per-candidate `component_scores`, `matched_tokens/
phrases/entities/domains`, and `exclusion_reason`; strategy counters
(`retrievals`, `inactive_filtered`, `zero_relevance_excluded`,
`skipped_not_top_k`, `skipped_token_budget`, `latency_ms_total`, …)
published via `summary()`, which already declares
`lifecycle_filtering: "active_only_before_ranking"`.

Two verified caveats the Phase 11 design must respect:

- The hard pre-filter is enforced **per strategy**. The only place
  admission can widen is `TemporalRetrievalPolicy.admit` — a
  deliberate, audited, mode-gated door, not a scoring path. Phase 11
  must not add a second door.
- The **legacy builder path** (`ContextBuilder._rank_candidates`,
  `builder.py:271`, used when no `retrieval_strategy` is injected)
  performs no lifecycle filtering itself; it relies on the engine
  fetching only active memories. Phase 11 semantic scoring must attach
  exclusively to the strategy path and leave the legacy path byte-
  identical.

## 5. Planned Phase 11 architecture (seams)

All Phase 11 additions are strictly additive and default-off. With no
embedding provider configured, every code path, rendered context, test
result, and benchmark digest listed in §2 must remain identical.

- **`EmbeddingProvider`** — new package `experienceos/embeddings/`
  mirroring the conventions of `experienceos/providers/` (module
  boundary) and `experienceos/policy/local_runner.py` (optional-dep
  pattern): `base.py` with a `typing.Protocol` (the repo's seam
  convention: `RetrievalStrategy`, `MemoryPolicy`,
  `LocalModelRunner`), a frozen `EmbeddingAvailability` status
  dataclass (shallow check, never loads weights), and frozen result
  metadata (provider ID, model ID, dimension). Configuration by
  constructor-arg > env var > default, matching `local_runner.py`.
- **Deterministic embedding provider** —
  `experienceos/embeddings/deterministic.py`: a dependency-free,
  hash-based provider (stable token-feature vectors) used by all
  default tests and CI. It is a *test double for the interface*, not a
  claim of semantic quality, and must be labeled as such in all
  diagnostics and artifacts.
- **Optional local embedding provider** —
  `experienceos/embeddings/local.py`: lazy-imported (module
  discovered via `importlib.util.find_spec`, imported only on first
  embed), CPU-only, loads only from an explicitly configured local
  path, never downloads, exposed behind a new packaging extra in
  `pyproject.toml` alongside the existing `demo`/`dev`/`local`
  extras. Exact library chosen in Prompt 2.
- **Semantic scoring** — inside `HybridRetrievalStrategy`, strictly
  after the step-1 lifecycle filter: a `semantic_score` component
  entering the existing `component_scores` dict and `SCORING_WEIGHTS`
  fusion. Two modes: *rescore* (semantic refines candidates that
  already have lexical relevance) and *generate* (semantic similarity
  may create relevance for lexically-missed but lifecycle-admitted
  memories — the mode that targets the 19 candidate-absence cases).
  Both modes score only the post-filter `active` list.
- **Embedding cache** — process-local in Prompt 3 (dict keyed per
  §13), owned by the retrieval configuration, never by the store.
  SQLite persistence is deferred unless the criteria in §13 are met;
  no schema migration of `experience_entries` is anticipated or
  permitted for caching.
- **Score fusion** — deterministic fixed-weight combination in
  `_score`/`SCORING_WEIGHTS` with a defined normalization boundary
  (§11). No per-query learning, no per-case tuning.
- **MemoryGate** — `experienceos/controllers/gate.py`: a proposal-only
  controller evaluated in shadow after selection (fed from the
  `RetrievalResult`/`ContextBuildResult` audit data), emitting
  `GateProposal` diagnostics with `affected_selection: false` in every
  canonical Phase 11 mode (§14).
- **Specialized controller contracts** —
  `experienceos/controllers/base.py`: frozen proposal dataclasses and
  `Protocol` interfaces for the six controller roles (§15); only
  MemoryGate gets a meaningful implementation in Phase 11.
- **Diagnostics** — additive fields on the existing audit surfaces:
  `component_scores["semantic_score"]`, retrieval `summary()` gaining
  `retrieval_mode`, embedding provider/model labels, cache counters,
  and embedding latency; gate-shadow records carried in the
  `CONTEXT_BUILT` event payload the same tolerant, `.get`-guarded way
  the dashboard already consumes older payloads.
- **Benchmark integration** — new system IDs (§6) wired through
  `benchmarks/contract/system.py:SystemId` and
  `benchmarks/adapters/factory.py`, new metric definitions in
  `benchmarks/contract/metrics.py`, evaluated by the existing
  contract runner; new committed artifacts under §7 paths with the
  established digest discipline (`canonical_json`,
  `normalize_for_digest` — latency stays excluded from digests).
- **Dashboard visibility** — Prompt 8 only: a retrieval-diagnostics
  extension adjacent to the existing "Context selection (last turn)"
  panel (`demo/app.py:300-311`), implemented as new `.get`-guarded
  helpers in `demo/support.py` beside
  `selection_records`/`selection_summary`, following the verified
  backward-compatible payload pattern. No optional model may load
  during initial render (the existing shallow
  `local_runtime_status` pattern is the model).

## 6. New system IDs (reserved)

| System ID | Meaning |
|---|---|
| `experienceos_hybrid_full_v2_reference` | Phase 9 final configuration re-run unchanged inside the Phase 11 harness — the comparison anchor. Must reproduce the Phase 9 behavior exactly (identical selection decisions on the frozen datasets). |
| `experienceos_embedding_only_v1` | Semantic similarity as the sole relevance signal (lexical weights zeroed), lifecycle filter and limits unchanged — the isolation ablation. |
| `experienceos_fused_retrieval_v1` | Full v2 + fixed-weight semantic fusion (the candidate recommended system). |
| `experienceos_gate_shadow_v1` | `experienceos_fused_retrieval_v1` + MemoryGate shadow diagnostics; selection decisions must be provably identical to `experienceos_fused_retrieval_v1`. |

Historical IDs are never renamed or redefined. Further ablation IDs
(e.g., a rescore-only variant) may be added in Prompt 7 only with a
documented rationale in the Prompt 7 report.

## 7. Artifact paths

New Phase 11 committed evidence (consistent with the existing
`benchmarks/results/committed/<name>/` convention and file set —
`aggregate.json`, `cases.jsonl`, `run_config.json`,
`execution_manifest.json`, `artifact_manifest.json`,
`provenance.json`, `failures.json`, `metric_contributions.jsonl`,
`README.md`):

- `benchmarks/results/committed/phase11-semantic-retrieval/` —
  LongMemEval 50-case subset runs for the §6 systems.
- `benchmarks/results/committed/phase11-retrieval-ablation/` —
  frozen lifecycle-scenario runs for the §6 systems.
- `benchmarks/results/committed/report-phase11/` — digest-locked
  report data, tables, and failure summary, with the human-readable
  report at `docs/benchmark_report_phase11.md`.

Runtime-only and real-local-provider evidence stays under the
gitignored `benchmarks/results/local/`. Existing committed directories
are immutable inputs only.

## 8. Metric definitions

Conventions (all inherited from the existing contract): every ratio
metric is emitted as a `MetricDefinition` cell with explicit
`numerator`, `denominator`, `numerator_definition`,
`denominator_definition`, `sample_count`, and `undefined_count`
(`benchmarks/contract/metrics.py`); a case that does not execute is a
run failure, not a silently skipped denominator entry; a metric whose
denominator is 0 is reported as undefined, never as 0% or 100%;
aggregation is the sum of per-case numerators over the sum of per-case
denominators unless stated; ties in any ranking are already resolved
deterministically by the §4 sort key before metrics are computed, so
no metric needs a tie rule of its own; all latency measurements are
wall-clock `time.perf_counter()` spans, reported as mean/p50/p95, and
excluded from artifact digests (`writer.py:_strip_latency`).

| Metric | Numerator | Denominator |
|---|---|---|
| Candidate recall (external) | cases where ≥1 answer-bearing session's memory appears among post-limit candidates | 50 evaluated cases |
| Answer-bearing candidate rate | same as candidate recall (existing `answer_session_candidate_rate`) | 50 |
| Recall@K (lifecycle) | expected-memory probes found in the selected top-K | probes defined by the frozen scenarios (17 in v2 evidence) |
| MRR (external) | sum over cases of 1/rank of the first answer-bearing selection (0 when never selected) | 50 |
| Selection rate (external) | cases where an answer-bearing memory is selected into context (existing `answer_session_selection_rate`) | 50 |
| Relevant-memory selection (lifecycle) | scenario-expected memories selected | scenario-expected memories retrievable |
| Context tokens | total estimated context tokens across cases (existing estimator; reported as a total and per-case mean) | — |
| Average selected memories | selected memories across turns | turns with retrieval |
| Inactive contamination | selected memories with `status != active` outside explicit historical modes | selected memories |
| Forgotten leakage | forgotten memories appearing in any candidate list or context | forgotten memories probed |
| Superseded leakage (current mode) | superseded memories selected for current-mode queries | superseded memories probed |
| Stale leakage | outdated values rendered when a newer active value exists (frozen scenario definition, 11 probes) | stale-value probes |
| Retrieval latency | per-`retrieve()` span, entry to result | — |
| Embedding latency | per-embed-call span inside the provider, reported separately for query and batch embeds | — |
| Cache hit rate | cache hits | cache lookups (misses + hits; 0 lookups → undefined) |
| Fallback count | retrievals that fell back to lexical-only because a provider failed or was unavailable at runtime | retrievals in embedding-enabled modes |
| Optional-provider skip count | cases/systems skipped because an optional provider is not installed (recorded with reason, like the existing `EXTERNAL_UNSUPPORTED` convention) | — |
| Gate-shadow recommendation distribution | count per proposal type (admit/trim/defer per §14) | gate proposals emitted |
| Gate effect count | selections changed by the gate — **must be 0 in every canonical Phase 11 mode** | selections evaluated by the gate |

Unavailable-provider treatment: a system whose required provider is
unavailable is excluded from that artifact with an explicit
skip-reason entry (never silently, never scored as zero). The
deterministic provider is always available, so committed canonical
artifacts never contain provider skips.

## 9. Benchmark modes

1. **Reference:** `experienceos_hybrid_full_v2_reference` — no
   embeddings; must reproduce Phase 9 selection behavior exactly.
2. **Embedding-only:** `experienceos_embedding_only_v1`.
3. **Fused:** `experienceos_fused_retrieval_v1`.
4. **Fused + gate shadow:** `experienceos_gate_shadow_v1`.

Held constant across all four modes: both frozen datasets (lifecycle
scenario manifest and the pinned LongMemEval 50-case subset,
`benchmarks/external/longmemeval/manifest.json`, source fingerprint
verified); candidate limit; selection K; context budget; lifecycle
filtering semantics; the deterministic offline answer provider; the
embedding provider and model ID (deterministic provider for committed
canonical artifacts); fusion weights; and seeds (the pipeline is
seed-free by construction — any new stochastic step is prohibited
rather than seeded). Real learned-embedding runs are evidence under
`benchmarks/results/local/` with provider labels, clearly separated
from committed canonical artifacts, exactly like the Phase 9
real-local-model evidence.

## 10. Lifecycle safety invariants (binding)

1. Forgotten memories cannot enter current-retrieval candidates (and
   remain unfetched by the engine).
2. Superseded memories cannot enter current-mode candidates.
3. Inactive memories cannot become eligible through embedding
   similarity — similarity is computed only over the post-admission
   population from `retrieval.py` step 1.
4. Cross-user memories remain excluded (`active_for_user` scoping is
   untouched).
5. Historical mode remains explicit (`TemporalRetrievalPolicy`
   intents); semantic scoring must not create a second admission door.
6. Forgotten memories remain excluded from user-facing historical
   context; no audit-only inspection path exists today and Phase 11
   does not add one.
7. Learned scores cannot bypass `candidate_limit`.
8. Learned scores cannot bypass selection K.
9. Learned scores cannot bypass the context token budget.
10. MemoryGate cannot change lifecycle eligibility.
11. Controllers cannot mutate `MemoryStore` (they never receive it).
12. Semantic retrieval cannot apply lifecycle transitions (only
    `ExperienceEngine._apply_memory_actions` mutates status).
13. The legacy builder path (`_rank_candidates`) remains byte-
    identical and embedding-free.

Every invariant above must have at least one dedicated test by the end
of the prompt that makes it violable (Prompts 3–5), and invariants
1–3 must additionally be visible in benchmark leakage metrics.

## 11. Score-fusion contract

- **Component inventory (current, verified):** `lexical_score`
  (unbounded ≥ 0), `phrase_score`, `entity_score`, `attribute_score`,
  `value_score`, `scope_score`, `domain_score`, `kind_priority`,
  `confidence`, plus mode-gated temporal bonus components. Phase 11
  adds `semantic_score`.
- **Normalization:** `semantic_score` must be presented to fusion in
  [0, 1] (cosine similarity mapped from [-1, 1], or the provider's
  documented range). Existing components are *not* retroactively
  renormalized — Phase 9 behavior with semantic weight 0 must remain
  bit-identical. Prompt 4 must document the chosen scale relationship
  (e.g., an effective-weight analysis against typical lexical
  magnitudes on the frozen datasets) rather than assume comparability.
- **Missing scores:** an absent semantic score (provider unavailable,
  cache miss with failed embed) contributes exactly 0 and increments
  the fallback diagnostics; it never blocks lexical scoring.
- **Deterministic fixed weights:** one global weight set, checked into
  code/spec, identical across all cases of a run; per-case or
  per-query weight adjustment is prohibited. Weight *selection* in
  Prompt 4 may compare a small enumerated grid across ablation runs,
  but the chosen set must be justified in the Prompt 4 report,
  recorded in the run config of every artifact, and frozen before
  Prompt 7 committed artifacts are generated. Tuning weights against
  per-case oracle inspection of the frozen benchmarks is prohibited
  (no benchmark oracle data enters runtime decisions).
- **Relevance-creation rule:** in *fused/generate* mode
  `semantic_score` may create relevance (that is its purpose); in
  *rescore* mode it enters the post-relevance refinement term and, by
  the existing `relevance > 0.0` gate pattern, cannot. The mode is
  part of the system configuration, never query-dependent.
- **Tie-breaking:** the existing deterministic sort key (§4) is
  unchanged; `semantic_score` participates only through
  `final_score`.
- **Diagnostics:** `component_scores` must always carry
  `semantic_score` (0.0 with a distinguishing `semantic_status`
  marker when unavailable) so ranking is explainable per candidate.
- **Ablation support:** weight sets per §6 system IDs, configured at
  construction like the existing `weights` parameter.

## 12. Embedding provider contract

Required protocol surface (names finalized in Prompt 2):
`embed_query(text) -> vector`, `embed_batch(texts) -> vectors`,
`availability() -> EmbeddingAvailability` (shallow; never loads
weights — the `LocalModelAvailability` pattern at
`experienceos/policy/local_runner.py:65-77`), and frozen identity
metadata: `provider_id`, `model_id`, `dimension`. Rules:

- deterministic: same text → same vector within a provider+model;
- the deterministic provider is pure-stdlib and CI-default;
- optional providers: lazy import (`find_spec` for discovery, real
  import deferred to first embed), CPU-only default, explicit local
  model path (constructor > env > unavailable), **no automatic
  downloads**, no network in default tests;
- diagnostics never include absolute personal paths (report the env
  var name or a basename, matching the existing runner's redaction
  discipline) and never include credential values;
- providers receive raw text only — no `ExperienceEntry`, no store, no
  event bus, no lifecycle fields;
- provider failure raises a typed error that retrieval converts into
  lexical-only fallback plus a fallback counter, mirroring the
  `LocalModelRunnerError → FallbackReason` pattern.

## 13. Embedding cache contract

- **Key:** `(provider_id, model_id, dimension, sha256(normalized
  memory text))`. Any change to memory text produces a new key
  (content invalidation); any provider/model/dimension change misses
  by construction. No reliance on memory IDs alone.
- **Scope (Prompt 3):** process-local dict, bounded, owned by the
  retrieval-side embedding integration — not by `MemoryStore`, not in
  `experience_entries` (no schema migration).
- **Persistence:** a SQLite-backed cache may be introduced later only
  if measured embedding latency on the live demo path makes it
  necessary; if introduced it must be a separate gitignored file
  (covered by the existing `*.sqlite`/`.experienceos/` rules), never
  the memory database, and carry the same key discipline.
- **Fallback:** cache failures degrade to recomputation, then to
  lexical-only; never to an exception reaching the engine.
- **Diagnostics:** hit/miss/eviction counters in the retrieval
  `summary()`.
- **Population discipline:** only lifecycle-admitted (post-step-1)
  memories are embedded; forgotten/superseded records are never sent
  to a provider for current-mode retrieval. (Superseded records
  admitted under explicit historical modes may be embedded at that
  point, and this must be visible in cache diagnostics.)

## 14. MemoryGate shadow contract

- **Input:** frozen view of the selection outcome — query profile,
  ranked candidates with `component_scores`, selected/skipped sets
  with reasons, budget figures. No store, no bus, no mutation hooks.
- **Proposal fields (`GateProposal`):** per-evaluated-memory
  recommendation (`admit` / `trim` / `defer`), a bounded reason
  string, a confidence in [0, 1], plus batch metadata (gate version,
  evaluation latency).
- **Pass-through:** in every canonical Phase 11 mode the gate runs
  strictly after selection is final; its output is recorded with
  `affected_selection: false` and provably identical selections
  (`experienceos_gate_shadow_v1` vs `experienceos_fused_retrieval_v1`
  selection decisions must match exactly in committed artifacts, and a
  test must enforce it).
- **Heuristic shadow:** the Phase 11 gate may be a deterministic
  heuristic (e.g., redundancy/score-margin analysis) to prove the
  seam; a learned gate is out of scope.
- **Failure:** any gate exception is contained to a diagnostic
  (`gate_error`) and never affects the interaction.
- **No authority:** the gate cannot alter lifecycle eligibility,
  limits, or budgets — structurally impossible because it runs after
  selection and returns only data.

## 15. Specialized controller contracts

`experienceos/controllers/base.py` reserves proposal-only `Protocol`
interfaces and frozen proposal dataclasses for: `AdmissionController`,
`ExtractionController`, `UpdateController`, `ForgetIntentController`,
`MemoryGate`, and `TransitionVerifier`. Common rules: inputs are
frozen dataclasses or plain values; outputs are proposal dataclasses
with confidence and bounded reasons; no store, bus, or callback
parameters may appear in any signature; the kernel (engine/manager/
builder) maps proposals to decisions. **Only MemoryGate receives a
meaningful Phase 11 implementation**; the other five are interface
reservations aligning the existing planner/policy roles with the
Phase 10 controller doctrine, to be populated in later phases.

## 16. Optional dependency policy

- The default install (`pip install -e .` + `[dev]`) remains fully
  functional with zero embedding libraries; the full test suite and
  all committed-artifact validators pass without them.
- Root imports stay lightweight: importing `experienceos` or
  constructing `ExperienceOS` must not import any embedding library.
- No automatic model downloads anywhere; no model files committed
  (`*.gguf` already ignored; Prompt 2 adds `*.onnx`, `*.safetensors`,
  `*.pt` when it introduces code that could produce them).
- Unavailable optional providers skip (benchmarks) or fall back
  (runtime) cleanly, with reasons recorded.
- Local paths never appear in committed artifacts, reports, or the
  dashboard.
- The deterministic provider is the CI and committed-artifact path;
  learned-embedding evidence is local, labeled, and separate.

## 17. Benchmark adoption gates

Semantic retrieval (`experienceos_fused_retrieval_v1`) may be
promoted to "recommended" only if, on the frozen datasets versus
`experienceos_hybrid_full_v2_reference`:

1. answer-bearing candidate rate or MRR improves;
2. Recall@K does not materially regress;
3. inactive contamination remains 0;
4. forgotten leakage remains 0;
5. superseded leakage in current mode remains 0;
6. context tokens remain within the existing budget (total not above
   the reference's 5,527 by more than the §17 threshold);
7. deterministic lexical-only fallback remains available and tested;
8. CPU latency is acceptable for the live demo (proposed: added
   retrieval latency ≤ 250 ms p95 per turn with the optional local
   provider on this machine) or the provider remains optional;
9. per-candidate diagnostics fully explain ranking;
10. the report and/or dashboard make the benefit visible.

**Proposed "materially regress" threshold:** both benchmarks are
deterministic (identical reruns reproduce digests exactly), so there
is no run-to-run variance to calibrate against. Proposed: any drop of
more than 1 case on a frozen numerator (e.g., lifecycle Recall@K
17/17, external selection 12/50) or more than 2% relative on a
continuous metric (MRR, token total) is material. Prompt 7 must
ratify or tighten this threshold in its report before any adoption
decision, and may not loosen it.

## 18. Stop conditions

Phase 11 semantic work stops (and the phase closes with semantic
retrieval demoted to a documented experiment) if any of: semantic
candidates primarily add noise (candidate-rate gains do not translate
into selection/MRR gains); lexical retrieval already finds the same
relevant memories (fused ≈ reference on all headline metrics); CPU
latency is disproportionate to gains; deterministic reproducibility is
lost (any double-run digest mismatch); any §10 invariant weakens;
optional dependencies destabilize the default install; diagnostics
cannot explain selection; dashboard reliability declines; historical
artifacts would need modification; or the benchmark comparison is not
reproducible offline.

## 19. Validation matrix (Prompts 1–9)

Every prompt ends with: full `pytest` green, demo validation green,
all seven existing validators green, historical digests unchanged,
working tree clean, exactly one scoped commit, no push unless a later
prompt explicitly authorizes it.

| Prompt | Scope | Focused tests | Commit (subject sketch) | Acceptance decision |
|---|---|---|---|---|
| 1 | This contract | none (documentation-only; baseline suite re-verified) | `Define Phase 11 semantic retrieval contract` | `PHASE_11_CONTRACT_COMPLETE` |
| 2 | `experienceos/embeddings/` package: protocol, deterministic provider, optional local provider skeleton, ignore-rule additions, extras | provider protocol, determinism, availability shallowness, lazy-import proof (embedding lib absent from `sys.modules` on default paths), no-download proof | `Add embedding provider abstraction` | `EMBEDDING_ABSTRACTION_COMPLETE(_WITH_NOTES)` |
| 3 | Semantic candidate generation + cache in `HybridRetrievalStrategy` (default-off) | invariants §10 1–5, 13; cache key/invalidation; fallback; off-mode byte-identity of context and digests | `Add semantic candidate generation behind lifecycle filter` | `SEMANTIC_CANDIDATES_COMPLETE(_WITH_NOTES)` |
| 4 | Score fusion + normalization + ablation configs | invariants §10 7–9; weight determinism; missing-score handling; diagnostics completeness | `Add deterministic semantic score fusion` | `SCORE_FUSION_COMPLETE(_WITH_NOTES)` |
| 5 | Shadow MemoryGate | selection-identity proof; failure containment; `affected_selection=false`; §10 10 | `Add shadow MemoryGate controller` | `GATE_SHADOW_COMPLETE(_WITH_NOTES)` |
| 6 | Controller contracts (`experienceos/controllers/`) | signature/no-authority checks (no store/bus/callback params); proposal immutability; §10 11 | `Reserve specialized controller contracts` | `CONTROLLER_CONTRACTS_COMPLETE(_WITH_NOTES)` |
| 7 | Benchmarks: new system IDs, metrics, double-run digest-matched committed artifacts, threshold ratification | reference-reproduction test; leakage metrics; artifact validators extended to Phase 11 dirs | `Add Phase 11 retrieval benchmark artifacts` | `PHASE_11_ARTIFACTS_COMPLETE(_WITH_NOTES)` |
| 8 | Dashboard retrieval diagnostics (helper-level, backward-compatible) | `demo/support.py` helper tests incl. old-payload tolerance and empty states; no-model-on-render | `Show retrieval diagnostics in dashboard` | `DASHBOARD_DIAGNOSTICS_COMPLETE(_WITH_NOTES)` |
| 9 | Stabilization, report, closure doc, adoption/stop decision | closure-doc consistency tests (the `test_phase9_closure_docs.py` pattern) | `Close and document Phase 11` | `PHASE_11_COMPLETE(_WITH_NOTES)` |

Safety properties re-verified at every prompt: zero forgotten
leakage, zero inactive contamination in current mode, unchanged
historical digests, default-install independence from optional
libraries.

## 20. Closure requirements

The Phase 11 closure report and `docs/phase11_closure.md` must
include: final test count; the exact validation commands and results
(pytest, demo, all v1/v2/Phase 11 validators); benchmark metrics for
all four §9 modes with numerators and denominators; leakage results;
latency results (labeled per provider, digest-excluded); artifact
paths and normalized digests; embedding provider labels and versions;
every skip and its reason; the commit inventory; push verification
(only when a prompt explicitly authorizes publication); clean-tree and
local/remote-equality evidence; an explicit supported-claims versus
unsupported-claims section (no official LongMemEval score, no
state-of-the-art claim, no claim that embeddings inherently improve
retrieval, no claim the 0.5B local model reliably manages memory —
unless committed evidence newly and directly supports a claim, which
for the official-score claim it cannot); the adoption or stop decision
against §17/§18; and a recommended Phase 12 direction.

## 21. Uncertainties deferred

- ~~Choice of optional embedding library~~ **Resolved in Prompt 2:**
  sentence-transformers behind the `embeddings-local` extra, wrapped
  by `experienceos/embeddings/local.py` (CPU-only, lazy import,
  existing-local-path-only so downloads are impossible); the
  deterministic CI provider is `deterministic` /
  `stable-feature-hash-v1` at 512 dimensions. The specific local
  model (e.g. `all-MiniLM-L6-v2`) remains a Prompt 7 evaluation
  choice. See `docs/embedding_providers.md`.
- ~~Semantic candidate generation and cache design~~ **Resolved in
  Prompt 3** (see `docs/semantic_retrieval.md`): modes
  `disabled`/`score_only`/`semantic_only` fixed per strategy instance;
  process-local LRU `EmbeddingCache` (default 4096 entries) keyed
  `(provider_id, model_id, dimensions, sha256(canonical text))` with
  late-dimension discovery treated as a miss; canonical memory text =
  text + identity attribute/value/scope + sorted tags; semantic score
  = `max(0, cosine)` in [0, 1] with raw cosine retained; initial
  relevance floor 0.30 (measured against deterministic-provider noise
  ~0.25, not claimed optimal — Prompt 7 evaluates); deterministic
  lexical fallback on typed provider errors with sanitized reasons,
  `semantic_strict` opt-in raise; diagnostics additive on
  `RetrievalCandidate.semantic` / `RetrievalResult.semantic`.
- Whether embedding-only mode needs a different relevance floor per
  provider (the 0.30 default is calibrated on the deterministic
  provider; learned-embedding cosine distributions differ) —
  Prompt 7.
- Exact fusion weights and the lexical/semantic scale analysis
  (Prompt 4).
- ~~Whether embedding-only mode needs its own zero-relevance floor~~
  **Resolved in Prompt 3:** yes — the semantic relevance floor above
  (0.30, strictly-greater-than) fills the zero-relevance role for
  semantic candidates; below-floor entries are excluded as
  `below_semantic_floor`, never padded toward K.
- ~~Score-fusion design (§11)~~ **Resolved in Prompt 4** (see
  `docs/retrieval_score_fusion.md`): normalization `bounded_ratio-1`
  (lexical `x/(x+3)`, structured aggregate `x/(x+2)`, semantic
  identity, temporal `min(x,1)`); components classified
  lexical/structured/semantic as primary relevance, temporal (which
  contains the only provenance signal, `trust_score`) as
  compatibility, kind/confidence/recency/ID as unfused rank refiners;
  profiles `lexical_reference` (Phase 9 bypass, provider never
  inspected), `embedding_only`, `lexical_semantic` (.55/.45),
  `structured_semantic` (.55/.45), `full_fusion` (default: lexical
  .35, structured .25, semantic .30, temporal .10) — all version 1,
  frozen, validated, chosen from the range audit, never from
  benchmark labels; fused pool = union of lexical-relevant and
  above-floor semantic candidates (below-floor semantic refines
  lexically relevant candidates only); ranking tuple
  `(-fused_score, -(phrase+entity), -kind_priority, -confidence,
  -created_at, id)`; fallback = the exact lexical reference path with
  sanitized reasons; diagnostics reconstruct the fused score from
  per-component contributions.
- ~~MemoryGate shadow design (§14)~~ **Resolved in Prompt 5** (see
  `docs/memory_gate.md`): `experienceos/controllers/gate.py` with the
  proposal-only `MemoryGate` Protocol, frozen `GateCandidateEvidence`
  (bounded primitives, 300-char text cap) and construction-validated
  `GateProposal` (admit/reject/abstain, score+confidence in [0,1],
  `shadow_mode=True` / `affected_selection=False` enforced);
  `PassThroughMemoryGate` (`gate_pass_through-1`) and the
  deterministic `HeuristicShadowMemoryGate`
  (`gate_shadow_heuristic-1`: admit on precision/dual-evidence/
  strength ≥ 0.35, reject on near-floor semantic-only, abstain
  otherwise); integration via `memory_gate` strategy parameter and
  `experienceos/context/gating.py:evaluate_shadow_gate`, running
  strictly after selection and budget enforcement over the post-limit
  (rank > 0) pool; agreement rule selected+admit / skipped+reject =
  agreement, abstain = neutral, rest = disagreement; per-candidate
  failure containment recording exception type names only, optional
  `gate_strict` raise; `affected_selection` invariantly 0.
- ~~Specialized controller contracts (§15)~~ **Resolved in Prompt 6**
  (see `docs/controller_architecture.md`): interface-only,
  proposal-only contracts in `experienceos/controllers/` —
  `admission.py`, `extraction.py`, `update.py`, `forget.py`,
  `transition.py` over shared `base.py` conventions (frozen evidence
  and construction-validated proposals, `proposal_only=True` enforced,
  bounded reasons/diagnostics/text, typed `ControllerError` hierarchy,
  `EvidenceSpan` + `MemorySnapshot` models, memory-layer literals
  mirrored for structural isolation); deterministic defaults
  `admission_abstain-1`, `extraction_noop-1`, `update_abstain-1`,
  `forget_intent_none-1`, `transition_abstain-1` (abstain chosen over
  pass-through for the verifier); extraction proposals represent one
  grounded candidate or none with optional spans (Phase 12 shape);
  `MemoryGate` reused byte-unchanged; zero canonical integration — no
  default construction, no activation flag, no registry.
- SQLite cache persistence (only if §13 latency criteria demand it).
- The final "materially regress" threshold ratification (Prompt 7).
- Whether the gate heuristic produces useful recommendation
  distributions or the seam ships proof-only (Prompt 5/7).
