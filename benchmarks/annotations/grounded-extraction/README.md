# Grounded Extraction Annotations

Additive extraction oracles keyed to frozen benchmark case IDs. These
files add span-, kind-, and rejection-level oracles that the frozen
result datasets do not carry. **No frozen record is modified.** These
annotations live outside every committed result directory and outside
the development-fixture directory.

## Files

- `lifecycle.jsonl` — one record per frozen `experienceos-lifecycle-v1`
  scenario (40 records), keyed by `scenario_id`.
- `external.jsonl` — one record per frozen `longmemeval-50-subset-v1`
  question (50 records), keyed by `question_id`.

## Methodology

### Lifecycle

Each of the 40 lifecycle scenarios is classified by inspecting its
frozen `current_message` and its committed `expected.memory_actions`
oracle. The `current_message` text is short, project-authored, and
already committed in `benchmarks/scenarios/lifecycle/`; it is copied
into `source_text` so the extraction oracle is self-contained and
span offsets are checkable.

Classes:

- **Positive creation probe (13):** the message is a single durable
  assertion that should yield exactly one active memory of
  `expected_kind`. These are `creation_001/002/003`,
  `containment_004`, `forgetting_006`, and `updates_001`–`updates_008`
  — the durable value asserted in an update message is a creation
  target; the supersession of a prior memory is lifecycle intelligence
  outside the single-message extraction oracle.
- **Duplicate restatement (2):** `creation_005`, `creation_006`. A
  proposal is defensible, but the durable content already exists, so
  no second active memory may be created. Scored by the duplicate
  metric, never as new creation.
- **Oracle-negative (24):** the message is a question, one-off
  request, temporary state, or non-durable/forget-directive utterance;
  the correct extraction outcome is no accepted candidate.
  `rejection_category` records which.
- **Unscorable (1):** `containment_005` — a one-sentence local
  supersession whose committed expected outcome is supersession-
  specific with an empty action list, so there is no clean single-
  message creation oracle. `scorable=false` with a bounded reason.

The normalization oracle is token-based: `normalized_must_include`
lists lowercased tokens a correct normalization must contain and
`normalized_must_exclude` lists tokens it must not (unsupported
additions or reversed polarity). `acceptable_normalized_texts` gives
illustrative human normalizations; the machine oracle is the
include/exclude token sets plus `acceptable_kinds`.
`acceptable_evidence_spans` gives `[start, end]` offsets into
`source_text` for the supporting clause (used for exact-span checks);
for distractor messages the span is the supporting clause only.

### External

The frozen `longmemeval-50-subset-v1` artifacts retain only sha256
digests and bounded previews of session text — not full source — so an
exact single-message span/kind/normalization oracle **cannot** be
reconstructed for any external case. Every external record is therefore
`scorable=false` and classified for context only:

- **extraction-oracle-insufficient (10):** information-extraction
  questions whose answer-bearing content exists but is spread across
  sessions with no reconstructable single-message source.
- **downstream-only (10):** knowledge-updates questions answered by
  selecting an updated memory, not by single-message extraction.
- **retrieval-only (20):** multi-session and temporal reasoning
  questions answered by retrieval over history.
- **not-extraction-related (10):** abstention probes with no durable
  memory to extract.

External annotations set `span_scoring_available=false`. They are used
only to report candidate-absence context and to justify why the primary
extraction aggregates are computed on the lifecycle dataset.

## Guarantees

- Deterministic: authored from fixed classification tables; identical
  bytes every regeneration.
- Every `case_id` references a real frozen record.
- No frozen dataset, result, digest, or development fixture is touched.
- Unscorable and oracle-insufficient cases always carry a bounded
  reason in `annotation_notes`.
- No network access and no state mutation on load.

## Manual judgment

Rejection categories, duplicate identities, and the positive/negative
split reflect human reading of each frozen message against its
committed action oracle. Ambiguous cases are marked `scorable=false`
rather than forced into a class. Annotation confidence is recorded per
record.

These annotations are evaluation oracles. They are **not** development
fixtures and must never be mixed into the development-fixture smoke.
