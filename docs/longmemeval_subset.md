# LongMemEval 50-case stratified subset

The external benchmark track: a bounded, reproducible integration of
a recognized long-term-memory benchmark, entirely **separate from the
custom lifecycle benchmark** — the two evidence tracks are never
combined into one score.

## Official source (verified 2026-07-10)

- **Benchmark**: *LongMemEval: Benchmarking Chat Assistants on
  Long-Term Interactive Memory*, ICLR 2025 (arXiv:2410.10813)
- **Repository**: github.com/xiaowu0162/LongMemEval — MIT license
- **Dataset**: huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
  — MIT license (HF card), revision
  `98d7416c24c778c2fee6e6f3006e7a073259d48f`
  (last modified 2025-09-19); files `longmemeval_oracle.json`
  (15.4 MB), `longmemeval_s_cleaned.json` (277 MB),
  `longmemeval_m_cleaned.json`
- **Item schema**: `question_id`, `question_type`, `question`,
  `answer`, `question_date`, `haystack_session_ids`,
  `haystack_dates`, `haystack_sessions` (user/assistant turns,
  evidence turns marked `has_answer`), `answer_session_ids`
- **Types**: single-session-user / single-session-assistant /
  single-session-preference / temporal-reasoning / knowledge-update /
  multi-session; **abstention** instances carry an `_abs` suffix on
  `question_id`
- **Official evaluation**: GPT-4o judge via the repository's
  `evaluate_qa.py`. An *official* score requires the full 500-question
  set and that judge protocol — **nothing in this repository is an
  official LongMemEval score, leaderboard entry, or full-benchmark
  result.** The exact required label everywhere is
  **"LongMemEval 50-case stratified subset"**.

## The subset

- **Version**: `longmemeval-50-subset-v1`; manifest at
  `benchmarks/external/longmemeval/manifest.json`
  (hash `a077cca377469ac3450ef5446e7d289bcbd42eb2c95beed677220f69fca73030`),
  IDs only — no dataset content is committed (MIT permits
  redistribution; we conservatively commit references).
- **Categories** (10 each, 50 total): information-extraction
  (non-abstention single-session-user), multi-session-reasoning,
  temporal-reasoning, knowledge-updates, abstention (the `_abs`
  cases).
- **Selection algorithm v1** (committed before any results, blind to
  questions/answers/histories/system behavior): categorize by
  official metadata → sort each category's question IDs
  lexicographically → take 10 evenly spaced IDs
  (`floor(i·n/10)`) → concatenate categories in fixed order →
  hash-lock with the official source fingerprint (SHA-256 over the
  sorted (id, type) identity set). Regeneration from the same source
  revision is byte-identical; changed source identity changes the
  manifest hash (tested).

## Data access

Official data is **never committed**; it lives in the gitignored
`benchmarks/data/external/longmemeval/`. Obtain it from the official
HuggingFace dataset (MIT), e.g.:

```
curl -L "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json" \
  -o benchmarks/data/external/longmemeval/longmemeval_s_cleaned.json
```

No command in this repository downloads anything, searches the
filesystem, or records personal absolute paths (basenames only).
Ordinary tests need no official data: official-data tests skip
automatically when the file is absent.

## Execution

Three systems, identical session content, identical budgets
(K = memory budget = 6), identical deterministic offline answer
provider, `ceil(chars/4)` accounting; the expected answer and
`answer_session_ids` never reach any system:

- **full_history** — every history turn (both roles, chronological,
  date-prefixed) plus the dated final question; untruncated offline
  (`full_history_untruncated`).
- **naive_top_k** — every history turn is one retrieval unit; the
  Prompt 3 formula (1.0·word-overlap + 0.5·recency, stable
  tie-break); top 6 into context.
- **experienceos_rules** — real production ingestion: each **user**
  turn through `chat()` per official session (assistant turns are not
  ingested — a disclosed architectural property), memory persists
  across the item's sessions, one isolated identity per item, full
  reset between items; the dated final question runs through the same
  path with ExperienceOS selection/compression.

```
./scripts/run_benchmarks.sh longmemeval-fixture              # offline synthetic
./scripts/run_benchmarks.sh longmemeval-prepare  <data-path> # verify source + subset
./scripts/run_benchmarks.sh longmemeval-structural <data-path> [out]
./scripts/run_benchmarks.sh validate-external <result-dir>
./scripts/run_benchmarks.sh longmemeval-live ...             # opt-in; not implemented as default
```

## Evaluation modes and metrics

- **Offline fixture** (default tests): synthetic official-shape
  fixtures — never a benchmark result.
- **Structural official-data run** (the committed artifact): real
  selected cases, deterministic provider. Real evidence: retrieval
  against the official `answer_session_ids` oracle
  (candidate/selection/MRR), answer-content context presence (via
  official `has_answer` turns), context tokens, token reduction vs
  full history. Answer-quality **proxies**
  (`normalized_exact_match_proxy`, `answer_entity_match_proxy`)
  are computed against the deterministic echo provider — equal for
  all systems and *not* live answer quality. Abstention evaluation is
  deferred (requires a live labeled run).
- **Live** (opt-in only, unimplemented default): same live answer
  model for every system, fixed decoding, documented judge; never
  part of default validation.

External metrics live in their own registry
(`benchmarks/external/longmemeval/evaluate.py`) — proxy metrics carry
a `proxy: true` flag end-to-end and validators reject label drift.

## Limitations (bounded, preserved)

- 50 cases ≠ the 500-question official benchmark; no official judge;
  no answer-quality claims from structural runs.
- ExperienceOS does not ingest assistant turns and does not model
  structured temporal relationships; multi-session evidence can be
  partially selected; conflicting facts can remain co-active
  (unkeyed domains). These are measured, not patched.
- Structural proxies against the echo provider are floor evidence
  only; a live run is required for answer quality.
