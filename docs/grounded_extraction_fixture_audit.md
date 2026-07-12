# Grounded-Extraction Fixture Audit

Companion to `docs/grounded_extraction_contract.md`: the audit of
where current extraction fails, which failures the development
fixtures cover, and which oracle gaps remain for the annotation
workstream. Verified against the live repository and committed
evidence at commit `66097ed`. This document reports audit findings and
fixture design only — no extraction behavior changed, no benchmark was
run, and nothing here is a measured improvement or an official score.

## 1. Purpose

Ground the extractor and grounding-validation work in observed
failures rather than invented scenarios: confirm the candidate-absence
and extraction-noise patterns from committed evidence, design a small
development-only fixture set that covers them, and inventory the
oracle fields later scoring will need.

## 2. Source Evidence Reviewed

- `benchmarks/results/committed/report-v2/failure_summary_v2.json`
  (external candidate-absence and candidate-unselected case lists)
- `benchmarks/results/committed/lifecycle-v2-ablation/`
  (`metric_contributions.jsonl`, `failures.json` — per-case creation,
  supersession, and leakage evidence)
- `benchmarks/results/committed/report-phase11/report_data_phase11.json`
  (retrieval-mode candidate rates)
- `docs/benchmark_report_v2.md`,
  `docs/phase11_semantic_retrieval_report.md`
- Live code: `experienceos/memory/hybrid_planner.py`,
  `experienceos/controllers/extraction.py`, extraction audit events.

## 3. Current Extraction Path

`HybridMemoryPlanner` (rules-first): rule matching, then extractor
candidates through a versioned durability gate and versioned grounding
validator, per-candidate schema/grounding/durability validation,
duplicate handling, and audit events (gate passed/rejected, invoked,
failed-safe). The controller seam (`ExtractionController`,
`ProposedMemoryCandidate`, `EvidenceSpan`) exists interface-only.
Engine-side validation and `_apply_memory_actions` retain sole
mutation authority.

## 4. Confirmed Candidate-Absence Findings

- **External: 19/50 cases with no answer-bearing candidate**
  (verified: `failure_summary_v2.json → external_final_system →
  candidate_absent_count = 19`; case IDs `08f4fc43`, `0ddfec37`,
  `0ddfec37_abs`, `1faac195`, `45dc21b6`, `5a7937c8`, `5c40ec5b`,
  `5e1b23de`, `66f24dbb`, `71315a70`, `76d63226`, `8e9d538c`,
  `982b5123_abs`, `a3838d2b`, `ad7109d1`, `bc8a6e93_abs`, `e831120c`,
  `gpt4_1e4a8aec`, `gpt4_468eb064`). Classification:
  `candidate_absent` — durable content in natural conversational
  phrasing was never extracted into memory.
- **Semantic retrieval added no candidates** (verified: candidate rate
  31/50 for reference, embedding-only, fused, and gate-shadow alike in
  the retrieval evidence): ranking cannot recover memories that were
  never created — the gap is extraction-side.
- **Lifecycle creation recall 12/13**: the single miss is
  `updates_008_repeated_correction_chain` (verified from
  `metric_contributions.jsonl`) — a repeated-correction chain where
  the final corrected value did not become the created memory.
  Classification: `candidate_absent`/`stale_creation` boundary.

## 5. Confirmed Extraction-Noise Findings

- **Creation precision 12/13**: the single false positive is
  `context_005_active_and_inactive_versions` (verified) — a creation
  the oracle did not expect in an active/inactive-versions scenario.
  Classification: `stale_creation`/`duplicate_noise` boundary.
- **Stale active-memory leakage 7/11**, all in the update family
  (`updates_001_preference_replacement_cross_session`,
  `updates_002_fact_correction`, `updates_003_instruction_replacement`,
  `updates_004_now_prefer_wording`, `updates_005_instead_of_wording`,
  `updates_007_correction_with_distractors`,
  `updates_008_repeated_correction_chain`): the new value is stated,
  but the transition is not fully realized — part extraction quality
  (recognizing change language), part supersession (lifecycle) work.
  Classification: `stale_creation`.
- **Not found in committed evidence:** measurable rates of
  `temporary_promoted`, `question_promoted`, `hypothetical_promoted`,
  `assistant_claim_promoted`, or `unsupported_normalization` — the
  frozen benchmarks do not instrument these categories (no oracle
  fields exist for them; see §7). The current durability gate is
  designed to reject them, and the existing suite covers some paths,
  but no committed benchmark measures the rates. These classes are
  represented in fixtures as **design targets**, not as confirmed
  production failures — no failure claim is made for them.

## 6. Cases Excluded as Retrieval-Only

The **19 candidate-unselected external cases** (candidate existed but
selection missed it; `candidate_unselected_count = 19`) are
retrieval/selection work, not extraction failures — excluded from
fixture design. Lifecycle non-passed cases in the retrieval and
context families (`retrieval_001/005/006/008`, `context_001`,
`containment_*`) are likewise `retrieval_only` or
`not_extraction_related` and excluded, except where a stale value was
also created/retained (`retrieval_008_stale_would_mislead` overlaps
the stale family).

## 7. Oracle Gaps

Existing frozen oracles provide: durable-candidate existence and
expected memories (13 lifecycle creation probes), duplicate identity,
current-vs-obsolete state (update scenarios), downstream
answer-bearing sessions (external), and full source text. **Missing
everywhere:** exact evidence spans; acceptable normalized-text sets;
rejection categories (question/hypothetical/temporary/assistant-only/
unsupported); per-case expected kind on some external cases; and any
instrumentation of the noise classes in §5. Later scoring therefore
requires **additive** annotation files keyed by stable case IDs
(contract §13; recommended roots
`benchmarks/scenarios/annotations/grounded-extraction/` and
`benchmarks/external/longmemeval/annotations/grounded-extraction/`).
No structural stub was created in this workstream — the development
fixtures below carry full oracle fields themselves, which is
sufficient for extractor design and unit testing.

## 8. Development Fixture Design

`benchmarks/fixtures/grounded-extraction/cases.jsonl`: 37 cases
(24 positive, 13 negative) across 17 categories, loaded and validated
by `benchmarks/fixtures/grounded_extraction.py` and protected by
`tests/test_grounded_extraction_fixtures.py`. Schema per contract §7/
§8: stable feature-based IDs (`<category>-NNN`), exact computed spans
(`user_message[start:end] == expected_evidence_text`, zero-based,
end-exclusive), acceptable-normalization sets, explicit rejection
categories, `unsupported_normalized_texts` for expansion patterns,
`existing_memories` + `lifecycle_expectation` for duplicate/change
cases (proposal vs lifecycle expectations kept separate),
`development_only: true` on every case, bounded `source_reference`
(committed-evidence ID or `synthetic-development-scenario`).

## 9. Fixture-to-Failure Coverage

| Failure class | Evidence source | Count / examples | Fixture IDs | Polarity | Annotation still needed |
|---|---|---|---|---|---|
| candidate_absent | failure_summary_v2 external | 19 confirmed | candidate-gap-001/002, natural-durable-fact-001, semi-natural-preference-001/002, workflow-preference-001/002 | positive | yes (external spans/kinds) |
| candidate_incomplete | not directly measured | unknown | semi-natural-preference-001, one-off-request-002 | positive | yes |
| wrong_memory_kind | not directly measured | unknown | natural-durable-fact-001, preference-change-002 (acceptable-kind sets) | positive | yes |
| unsupported_normalization | oracle insufficient | not measured | unsupported-normalization-001/002, negation-polarity-001 | positive + unsupported patterns | yes |
| temporary_promoted | oracle insufficient | not measured | temporary-state-001..004, one-off-request-001 | negative | yes |
| question_promoted | oracle insufficient | not measured | question-001/002 | negative | yes |
| hypothetical_promoted | oracle insufficient | not measured | hypothetical-001/002 | negative | yes |
| assistant_claim_promoted | oracle insufficient | not measured | assistant-only-001 | negative | yes |
| duplicate_noise | lifecycle duplicate oracles; context_005 precision miss | 1 confirmed | duplicate-restatement-001/002 | mixed (valid proposal, duplicate lifecycle) | partial (existing duplicate oracles) |
| ambiguous_durability | not directly measured | unknown | ambiguous-durability-001/002 | mixed (one unscorable) | yes |
| stale_creation | lifecycle stale leakage + recall/precision misses | 7 + 2 confirmed | preference-change-001/002/003 | positive + lifecycle expectation | partial (update oracles exist) |
| retrieval_only | failure_summary_v2 unselected | 19 confirmed | excluded by design | — | no (existing retrieval metrics) |

Third-party (`third-party-001/002`) and negation
(`negation-polarity-001/002`) cover contract durability/polarity rules
with no measured production counterpart (`not directly measured`).

## 10. Frozen-Evidence Separation

Fixtures live under `benchmarks/fixtures/grounded-extraction/` — not
under `benchmarks/results/committed/`, not referenced by any artifact
manifest, not consumed by any canonical benchmark module (tested:
no non-fixture `benchmarks/` module references the loader), and marked
`development_only` on every case. No frozen record was edited; all
historical digest validators pass unchanged.

## 11. Known Limitations

Counts for the noise classes are honestly `not measured` — the frozen
benchmarks lack those oracles, so fixtures for them are design
targets, not confirmed failure reproductions. The external
candidate-absence cases are cited by stable ID but their span/kind
oracles remain future annotation work. The unscorable ambiguity case
(`ambiguous-durability-002`) is deliberately excluded from future
precision/recall denominators. Whether the extractor needs recent
context beyond the current message (e.g. for `candidate-gap`-style
mid-history facts) remains an open extractor-workstream question; the
fixtures use single messages, which bounds but does not fully answer
it.
