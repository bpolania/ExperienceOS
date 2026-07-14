# Transition Verification Annotations

Additive, provenance-backed oracles for before-to-after memory transition
verification. This corpus is the frozen scenario and oracle layer that
later transition implementations are measured against. It **defines
evidence and expected outcomes; it does not solve the transition task**,
and no oracle is tailored to any planned implementation.

## Purpose

For each case the corpus records the memory state before a source
statement, the source statement, the expected transition classification,
the expected target (if any), the memories that must be created,
superseded, forgotten, preserved, or unchanged, the expected final
lifecycle state, and whether the case is scored, development-only,
unresolved, or excluded. This makes one question testable: *given the
current memory state and a newly grounded statement, should ExperienceOS
create, preserve, replace, forget, no-op, or reject memory state?*

## Contract authority

The binding definitions — transition task boundary, the 14-class
transition vocabulary, semantic memory identity, supersession and
scoped-coexistence rules, forget-directive categories, before/after-state
requirements, metrics, adoption gates, and stop conditions — live in
`docs/transition_verification_contract.md`. This corpus conforms to that
contract and never redefines it.

## Partitions (mechanically separate)

| File | Classification | Scored | Purpose |
|---|---|---|---|
| `historical-scored.jsonl` | `historical_scored` | yes | cases derived from frozen historical evidence with sufficient provenance and a defensible oracle |
| `development-fixtures.jsonl` | `development_only` | no | authored cases exercising each transition category and boundary |
| `unresolved-candidates.jsonl` | `historical_unresolved`, `excluded` | no | reviewed cases lacking a strict oracle (unresolved) or set aside (excluded), each with a recorded reason |

Separation is enforced two ways: by physical file **and** by the
per-record `annotation_classification` / `benchmark_scored` /
`development_only` fields. **Development fixtures are never mixed into
historical benchmark claims**, and the validator rejects a scored
development fixture or a mis-filed classification.

## Record format

Each record carries: stable `case_id`; classification and flags; source
family, case id, split, and committed `source_paths`; `oracle_origin`;
`ambiguity` block; `scoring_categories`; the `source_statement`;
`before_state` (per-memory lifecycle state, kind, normalized value, and
the semantic identity fields derivable from the source — subject,
attribute, value, scope, provenance, temporal validity, with
`not_represented` where the frozen evidence does not expose a field);
`expected_transition` (primary type, target/created/superseded/forgotten/
preserved refs, rejection reason, `canonical_effect`); and `after_state`
(the full final lifecycle state, lineage edges, and duplicate/stale
counts). Unresolved and excluded records carry a `resolution` block
(reason, missing evidence, whether fail-closed evaluation remains
possible) and a null oracle. The full field contract is in `schema.json`.

## Transition taxonomy

`create_new`, `duplicate_noop`, `semantic_duplicate_noop`,
`supersede_existing`, `scoped_coexistence`, `forget_existing`,
`reject_forget_directive_as_creation`, `reject_unsupported`,
`reject_ambiguous`, `reject_temporary`, `reject_question`,
`reject_hypothetical`, `reject_unrelated`, `shadow_only`. Each record has
exactly one primary type; secondary properties are represented through
`scoring_categories` tags, never through a contradictory primary label.

## Case-ID rules

- Historical: `transition:<source-family>:<source-case-id>:<suffix>`
  (e.g. `transition:lifecycle:updates_005_instead_of_wording:supersede_existing`).
- Development: `transition:development:<category>:<ordinal>`.
- Deterministic and stable across regeneration; no UUIDs, line numbers,
  timestamps, machine paths, or process vocabulary. Uniqueness is enforced
  across all partitions.

## Oracle provenance

Historically scored cases inherit the committed scenario's own expected
block (`oracle_origin: inherited_historical_benchmark_oracle`). One case
(`transition:lifecycle:forgetting_003_forget_one_of_several:forget_existing`)
additionally cross-references the committed grounded-extraction ablation,
where the deterministic controller recorded a false positive by
extracting a positive preference from a forget directive; the correct
transition oracle forgets the target and creates nothing. Development
fixtures use `oracle_origin: authored_fixture`. No manual adjudication was
required, so no record claims an inherited oracle it does not have.

## Consuming the corpus

Later transition work should load these records read-only, evaluate a
proposed transition against `before_state` and the expected mutation
sets, and compare the resulting active set, lineage, and duplicate/stale
counts against `after_state`. Score only `historical_scored` records for
benchmark claims; use `development_only` fixtures for coverage and
regression, never for reported benchmark performance. Match memories by
`logical_id` and `match_terms` (semantic references — no generated
memory IDs are assumed).

## Prohibitions

- Do not mix development fixtures into historical benchmark results.
- Do not modify historical benchmark evidence, oracles, reports, system
  IDs, or digests.

## Commands

```bash
# validate the corpus (deterministic, offline)
python -m pytest tests/test_transition_verification_annotations.py

# regenerate the manifest
python -m benchmarks.annotations.transition_verification manifest

# validate + verify the committed manifest matches the corpus
python -m benchmarks.annotations.transition_verification verify
```

The same source files always produce the same manifest content (no
volatile timestamps). See `manifest.json` for content digests and counts,
and `audit.md` for the evidence audit and coverage.
