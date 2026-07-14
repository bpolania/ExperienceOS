# Transition Verification Evidence Audit

This audit records the historical evidence inspected, the transition
candidates reviewed, what was scored, what was left unresolved or
excluded, and the coverage of the development fixtures. It accompanies
`README.md`, `schema.json`, `manifest.json`, and the annotation files.
Frozen historical evidence was inspected read-only and left unchanged.

## Historical evidence families inspected

Committed evidence was inspected by its frozen directory names (never
renamed):

- `benchmarks/scenarios/lifecycle/` — the 40 lifecycle scenario source
  files (creation, updates, forgetting, retrieval, context, containment),
  each with setup `turns`, a `current_message`, and a committed
  `expected` oracle (`memory_actions`, `active`, `superseded`,
  `forgotten` by `logical_id` + `match_terms`). **This is the primary
  scored source.**
- `benchmarks/results/committed/lifecycle-offline-v1/` and
  `lifecycle-v2-ablation/` — frozen lifecycle results (per-case JSONL,
  aggregates) confirming the scenario oracles.
- `benchmarks/results/committed/grounded-extraction-ablation/` and
  `report-grounded-extraction/` — the grounded-extraction per-case
  records and report, source of the forget-directive false-positive
  cross-reference and the durable-creation observation.
- `benchmarks/results/committed/longmemeval-50-subset-v1/`,
  `longmemeval-50-subset-v2/`, `phase11-retrieval-ablation/`,
  `phase11-semantic-retrieval/`, `report-v1/`, `report-v2/`,
  `report-phase11/` — inspected for transition-relevant evidence; these
  are retrieval/answer benchmarks and carry no reconstructable
  before/after transition oracles, so they contributed no scored cases.

## Candidate review and disposition

All 40 lifecycle scenarios were reviewed and each was dispositioned:

- **28 historical-scored** (`historical-scored.jsonl`): every creation,
  updates, and forgetting scenario, plus the four safe-containment cases,
  the active/inactive editor case, and the three question scenarios.
- **2 historical-unresolved** (`unresolved-candidates.jsonl`):
  `containment_005` (a one-sentence local supersession whose committed
  expected block leaves the aisle preference neither superseded nor
  active) and `containment_006` (a vague "doesn't matter anymore" whose
  expected active state omits the gym memory). Both keep fail-closed
  evaluation possible but cannot support strict after-state scoring
  without inventing a target's fate.
- **10 excluded** (`unresolved-candidates.jsonl`): the pure
  retrieval/selection scenarios (`retrieval_001`–`005`, `context_001`–
  `004`, `context_006`) whose current message is a query or task with a
  trivial no-op oracle and no supersession/forget/duplicate/coexistence
  transition to verify beyond preservation already covered by scored
  containment/context cases.
- **1 excluded** cross-family observation: the grounded-extraction
  finding that extraction did not improve durable creation is an
  extraction-recall metric, not a transition oracle.

No candidate disappears silently; every reviewed scenario appears in one
partition with a recorded disposition.

## Mapping of the prior measured transition limitations

| Prior limitation | Disposition |
|---|---|
| semantic-duplicate active memories | scored `semantic_duplicate_noop` (`creation_006`) + development fixtures `semantic_duplicate`, `similar_wording_different_scope`; the specific two-active-memory adoption observation is referenced in the grounded-extraction report and covered by fixtures |
| missed update-phrased preferences | scored `supersede_existing` (`updates_004` "now prefer", `updates_005` "instead of") |
| difficult repeated-correction cases | scored `supersede_existing` (`updates_008` chain) + development fixture `repeated_correction` (three sequential values) |
| forget directive misread as positive preference | scored `forget_existing` with `forget_as_creation_prevention` (`forgetting_003`), cross-referencing the committed grounded-extraction false positive; the correct oracle forgets the target and creates nothing |
| stale active-memory cases at the extraction/transition boundary | scored `reject_question`/`reject_unsupported` with `stale_leakage`/`superseded_leakage` (`retrieval_008`, `context_005`, `containment_002`) |
| no durable creation improvement from extraction | excluded as an extraction-recall metric, not a transition oracle (documented) |

## Oracle provenance

Every scored record's `oracle_origin` is
`inherited_historical_benchmark_oracle` — the committed scenario's own
`expected` block. Before-state is reconstructed from the scenario setup
`turns`; semantic identity fields (subject, attribute, value, scope) are
derived from the structured `logical_id`s, with `not_represented` where
the frozen evidence does not expose a field. No manual adjudication was
required, and no record claims an inherited oracle it lacks.

## Before-state reconstruction limitations

The frozen scenarios expose lifecycle state, kind, and text but not
explicit qualifiers or full semantic-scope oracles, so `qualifiers`,
`supersession_lineage`, and `forgotten_lineage` are marked
`not_represented` in before-state. The five fresh-creation scored cases
have an empty before-state by design (no prior memory). Fifty of the
scorable records carry a populated before-state; five are the empty
before-state creation cases.

## Development-fixture coverage

All required transition categories are covered by authored fixtures
(`development-fixtures.jsonl`): exact and semantic duplicates,
current-state replacement (two domains), direct / instead-of /
used-to-now replacement, correction (two), a three-value repeated
correction chain, scoped coexistence, similar-wording-different-scope,
affirmative / negative forget, forget and memory-inspection questions,
broad and ambiguous forget, instruction replacement, temporary exception,
historical statement, unrelated-memory preservation (two), ambiguous and
unsupported transitions, hypothetical update, and a historical
current-state conflict.

## Category counts

- By classification: 28 historical-scored, 27 development-only, 2
  historical-unresolved, 11 excluded (68 total).
- By primary transition type (scored + development): `supersede_existing`
  17, `reject_unsupported` 8, `create_new` 6, `reject_question` 6,
  `forget_existing` 5, `duplicate_noop` 3, `scoped_coexistence` 3,
  `reject_ambiguous` 2, `reject_temporary` 2, `semantic_duplicate_noop`
  2, `reject_hypothetical` 1.
- Selected scoring categories: `supersession` 18, `update_target` 18,
  `lineage` 17, `rejection` 17, `no_op` 24, `unrelated_preservation` 8,
  `forgotten_leakage` 7, `forget_directive` 6, `superseded_leakage` 4,
  `semantic_duplicate` 3, `exact_duplicate` 2,
  `forget_as_creation_prevention` 2, `stale_leakage` 1.

## Known ambiguities

Four records are flagged ambiguous: the two historical-unresolved cases
(genuine oracle ambiguity in the frozen expected state) and the two
authored ambiguous fixtures (`ambiguous_forget`, `ambiguous_transition`)
that require fail-closed rejection. Zero records required manual
adjudication.

## Integrity

Frozen historical evidence was inspected read-only; no scenario file,
result artifact, oracle, report, manifest, digest, or system ID was
modified. Provenance for every scored case cites committed source paths.
