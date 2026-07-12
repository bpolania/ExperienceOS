# Grounded Experience Extraction Contract

**Status: contract complete — this document governs all subsequent
grounded-extraction work.**

This is the binding contract for the grounded-extraction initiative:
the verified starting baseline, the audited current architecture, the
narrow extraction task and its authority boundaries, evidence-span and
durability rules, benchmark systems, metric and oracle definitions,
adoption gates, stop conditions, and closure requirements. Where this
contract and a later workstream disagree, the safety boundaries here
win. Everything in "Current" sections was verified against the live
repository at commit `66097ed` on 2026-07-11; everything in "Planned"
sections is design intent, not yet implemented.

Naming note (repository policy): all NEW files, directories, system
IDs, headings, and identifiers created under this contract use
feature-based names (`grounded-extraction`, `grounded_rules`, …).
Existing committed names containing project-stage vocabulary (e.g.
`report-phase11/`, `docs/phase11_contract.md`) are frozen history and
are cross-referenced unchanged.

## 1. Purpose

Retrieval cannot recover experience that was never created. The
committed semantic-retrieval evidence
(`benchmarks/results/committed/report-phase11/`,
`docs/phase11_semantic_retrieval_report.md`) shows the dominant
external failure is candidate absence — 19 of 50 cases have no
answer-bearing memory candidate at all — and semantic retrieval added
zero new answer-bearing candidates. The frozen lifecycle evidence
shows creation recall at 12/13. This initiative therefore targets one
narrow controller question:

> Does this interaction contain one durable, user-grounded experience
> candidate? If yes, propose exactly one candidate with exact source
> evidence. If no, return none.

Extraction remains proposal-only. The deterministic kernel retains
lifecycle authority. The governing principle, verbatim:

> Models and learned components may propose experience. ExperienceOS
> decides what becomes durable, what replaces previous experience,
> what is forgotten, and what may enter context.

## 2. Verified Starting Baseline (2026-07-11)

| Item | Verified value |
|---|---|
| Branch | `main` |
| Local HEAD | `66097edfe0874d1c50c63840f399188a17a887d8` ("Stabilize Phase 11 documentation and validation") |
| `origin/main` | same (ahead 0 / behind 0) |
| Working tree | clean |
| Full test suite | `PYTHONPATH=. .venv/bin/python -m pytest` → 1,339 passed, 0 skipped |
| Demo validation | `PYTHON=.venv/bin/python ./scripts/validate_demo.sh` → passed |
| Historical validators (7) | v1 artifact/external/report + v2 lifecycle/external/consistency/report-v2 → all passed |
| Semantic-retrieval validators (4) | `validate-phase11`, `validate-external-phase11`, `validate-phase11-consistency`, `validate-report-phase11` → all passed |

## 3. Historical Artifact Inventory (immutable inputs)

| Evidence | Path | Normalized digest |
|---|---|---|
| Lifecycle v1 | `benchmarks/results/committed/lifecycle-offline-v1/` | `8b0e245d914a43bc…` |
| External v1 | `benchmarks/results/committed/longmemeval-50-subset-v1/` | `2b3e2000647b8d3c…` |
| Report v1 | `benchmarks/results/committed/report-v1/` + `docs/benchmark_report.md` | per manifest |
| Lifecycle v2 ablation | `benchmarks/results/committed/lifecycle-v2-ablation/` | `ee437bb3e9fde909…` |
| External v2 | `benchmarks/results/committed/longmemeval-50-subset-v2/` | `19b66cacb330e943…` |
| Report v2 | `benchmarks/results/committed/report-v2/` + `docs/benchmark_report_v2.md` | per manifest |
| Retrieval ablation | `benchmarks/results/committed/phase11-retrieval-ablation/` | `5fb0fb8825956933…` |
| Semantic retrieval | `benchmarks/results/committed/phase11-semantic-retrieval/` | `5ff129ce4d638eda…` |
| Retrieval report | `benchmarks/results/committed/report-phase11/` + `docs/phase11_semantic_retrieval_report.md` | per `report_manifest.json` |

Rules: no historical artifact, digest, manifest, report, dataset, or
system ID may be renamed, rewritten, regenerated, normalized, or
updated. The existing digest validators (the eleven commands in §19)
are the preservation mechanism; closure must re-run all of them. This
initiative creates new system IDs and new result directories only.

Historical system IDs (frozen): `stateless`, `full_history`,
`append_only`, `naive_top_k`, `experienceos_rules`,
`experienceos_local`, the eight v2 IDs, and the four retrieval IDs
(`…_hybrid_full_v2_reference`, `…_embedding_only_v1`,
`…_fused_retrieval_v1`, `…_gate_shadow_v1`).

Repository hygiene (verified): no tracked secrets (only
`.env.example` placeholders), no model/weight/cache/database files
tracked, no personal paths in public artifacts; `.gitignore` covers
`.env`, `*.gguf`, `*.onnx`, `*.safetensors`, `*.pt(h)`, SQLite files,
and `benchmarks/results/local/`.

## 4. Current Architecture Findings (verified from code)

1. **Where extraction occurs today:**
   `experienceos/memory/hybrid_planner.py:HybridMemoryPlanner` (line
   88) — the rules-first hybrid conversational extractor: rule
   matching first (`_rules_match`), then a versioned durability gate
   and versioned grounding validator over extractor candidates
   (`_extend_with_candidates` → gate → `_accept_candidate` with
   per-candidate schema/grounding/durability validation and duplicate
   handling in `_duplicate`). Deterministic and rule-based; no
   provider assistance in the canonical path. The scripted local
   policy (`experienceos/policy/local_v2.py`) serializes the same
   deterministic plan through the parse/validate/audit pipeline.
2. **Proposal types today:** planner-side action tuples plus the
   policy layer's `MemoryDecisionProposal`
   (`experienceos/policy/base.py`); controller-side, the
   interface-only `ProposedMemoryCandidate`
   (`experienceos/controllers/extraction.py:56`) with `EvidenceSpan`
   (`experienceos/controllers/base.py:119`) — **already defined, not
   executable in production**: `ExtractionController` (line 122) is a
   Protocol with a `NoOpExtractionController` default, constructed by
   nothing.
3. **Proposal flow:** planner path → engine-side validation
   (`ExperienceEngine.run_interaction`: `target_not_active`,
   `duplicate_of_active`) → `_apply_memory_actions` (the only durable
   mutation site, with event emission). Policy path additionally
   passes `ExperienceManager.plan` (structure/kind/confidence/action
   validation, contradiction resolution, whole-batch fallback).
4. **Memory kinds (canonical):** `preference`, `fact`, `instruction`
   (`experienceos/memory/schema.py:MemoryKind`). No new ontology.
5. **Provenance (canonical):** `user_asserted`, `assistant_derived`,
   `system_observed`, `jointly_confirmed`, `tool_verified`
   (`experienceos/memory/temporal.py`, trust-ordered) — assistant
   ingestion is feature-flagged OFF in canonical configurations;
   questions/hypotheticals/temporary statements are rejected today by
   the durability gate; assistant-only text is not user truth by
   default.
6. **Extraction diagnostics today:** seven audit event types
   (`experienceos/events/schema.py:27-33`, gate passed/rejected,
   invoked, failed-safe, …), planner counters
   (`candidates_grounding_rejected`, …), and versioned
   gate/validator metadata in `summary()`.
7. **Benchmark reuse:** lifecycle scenarios already carry
   creation-oracle metrics (`memory_creation_precision/recall`),
   duplicate/contamination/leakage metrics, and the external subset
   carries answer-session oracles. New: span-level and
   rejection-category oracles (additive annotations, §13), proposal-
   layer metrics, and the new system IDs.
8. **Narrowest integration seam:** an `ExtractionController`
   implementation evaluated beside `HybridMemoryPlanner`'s existing
   extractor stage — its `ExtractionProposal` translated into the
   same gate → grounding → validation → engine path that rule
   candidates already traverse (shadow first: proposals recorded,
   canonical behavior unchanged). No second mutation path exists or
   will be created.

## 5. Extraction Task Boundary

**Input** (planned): the current user message (bounded), minimal
interaction metadata (session ref, turn/event identifier), an approved
source identifier, provenance metadata, and optionally recent context
only via an existing safe interface (`ExtractionEvidence` already
bounds text at 2,000 chars). **Never provided:** `MemoryStore` or any
mutation handle, durable create/update/forget callbacks, lifecycle
mutation access, supersession/forget authority, or context-injection
authority — the existing controller conventions enforce this
structurally (no store/engine/manager/bus/callback/session parameters;
tested).

**Output:** exactly one candidate proposal, or none. One candidate per
interaction is a hard cap.

## 6. Authority and Mutation Boundaries (non-negotiable)

Extraction controllers: propose only; cannot mutate `MemoryStore`;
cannot invoke durable create/update/supersede/forget; cannot decide
final admission; cannot bypass `ExperienceManager`,
`ExperienceEngine`, duplicate detection, lifecycle validation, source
validation, or context budgets; cannot make forgotten or superseded
memories active; cannot retrieve inactive memories into context;
cannot silently alter canonical behavior in shadow mode (shadow
proposals carry `canonical_effect = false` and canonical outputs must
be provably identical, following the established shadow-gate pattern).
The manager/policy layer validates proposals; the engine remains the
only durable mutation and event-emission authority.

## 7. Candidate Proposal Schema (planned; implemented later)

Extends the existing `ProposedMemoryCandidate`/`ExtractionProposal`
shapes rather than replacing them: proposed kind (canonical vocabulary
only), normalized candidate text (bounded, non-empty), exactly one or
more `EvidenceSpan`s citing the source (at least one required for any
positive proposal), source identifier and type, confidence in [0, 1],
bounded reason, durability rationale, controller ID and mode, and
JSON-safe diagnostics. Construction-validated (the existing
`ControllerProposalError` conventions), with recommendation/candidate
consistency already enforced. No durable ID, no lifecycle status, no
supersession links, no timestamps — those exist only after kernel
admission.

## 8. EvidenceSpan Rules

The span schema already exists (`EvidenceSpan`: `source`, `start`,
`end`, bounded `excerpt`, optional `text_digest`) and validates
non-negative `start < end` and allowed sources. This contract fixes
the remaining conventions:

- **Offsets:** zero-based character offsets over the exact unmodified
  source string; start inclusive, end exclusive; the invariant is
  `source_text[start_offset:end_offset] == evidence_text`.
- **Fields per positive proposal:** source identifier, source type,
  start, end, evidence text, and the turn/event identifier when
  available (additive fields on the existing dataclass are permitted;
  its current field names are kept).
- **Deterministic validation (machine-checkable):** offsets in range
  of the supplied source; non-negative; `start < end`; non-empty
  evidence; exact slice equality; allowed source type; source
  identity matches the supplied interaction; structural schema
  validity. Zero tolerance: any accepted proposal with an invalid
  span is a defect.
- **Policy/semantic validation (oracle- or rule-assisted, not provable
  by string equality alone):** question rejection, hypothetical
  rejection, temporary-state rejection, assistant-only rejection,
  unsupported-normalized-claim rejection. Exact span equality proves
  the evidence exists verbatim; it does NOT prove the normalized
  candidate is semantically supported — both layers are validated and
  reported separately.

**Source-type policy:** allowed by default: `user_asserted`. Allowed
only through the existing validated paths: `jointly_confirmed` (the
confirmation flow) and `tool_verified` (the tool-result flow), both
already implemented with grounding checks. Rejected by default:
unconfirmed `assistant_derived`, unsupported `system_observed`,
unknown provenance.

## 9. Durability Rules

A durable candidate is one reasonably expected to remain useful in
later sessions. Positive categories: stable preferences; recurring
defaults; durable user facts; persistent workflow instructions;
enduring communication, travel, tool, or environment preferences;
explicit "always/usually/normally/by default/from now on" statements
when semantically durable. Negative categories (must be rejected or
return none): one-off requests; temporary plans and current-session
state; transient location and temporary travel details; questions;
hypotheticals and uncommitted possibilities; vague moods;
assistant-authored claims not confirmed by the user; unsupported
inferences; normalized claims containing information absent from the
evidence; quoted third-party preferences without user ownership.
Keywords alone never decide durability — "always" inside a hypothetical
or quotation does not create a candidate; classification operates on
the asserted commitment, not the token.

## 10. Source Provenance Rules

Provenance vocabulary and trust ordering are the existing canonical
set (§4.5). The extractor receives provenance metadata and must carry
it through unchanged; validation rejects proposals whose provenance is
outside the allowed set for their source type. Assistant ingestion
stays feature-flagged off in canonical configurations; nothing in this
initiative widens it.

## 11. System IDs (reserved; never reuse a historical ID)

| System ID | Meaning |
|---|---|
| `experienceos_hybrid_full_v2_reference` | existing canonical reference (reused unchanged — the comparison anchor) |
| `experienceos_grounded_rules_v1` | deterministic grounded extraction (the adoption candidate) |
| `experienceos_grounded_learned_shadow_v1` | optional learned extractor, shadow-only (conditional) |
| `experienceos_grounded_learned_candidate_v1` | learned extractor as candidate mode, only if learned gates pass (conditional) |
| `experienceos_grounded_qwen_ceiling_v1` | optional live-Qwen extraction ceiling, credentials required, never committed as canonical evidence (optional) |

A system ID identifies a reproducible behavior configuration. Changed
behavior requires a new ID.

## 12. Benchmark Sources and Systems

Sources: the frozen lifecycle scenario benchmark (unmodified); the
pinned LongMemEval 50-case subset when locally available (offline,
fingerprint-verified — results are project-specific, never an
official LongMemEval score); new development fixtures (committed,
clearly labeled development-only, kept apart from frozen evaluation
evidence); the existing synthetic fixture path as fallback when the
external source is unavailable (labeled fixture, never combined with
external results). Required comparisons: reference vs
`grounded_rules_v1` on both benchmarks; conditional: learned shadow /
learned candidate; optional: the Qwen ceiling (local evidence only).

**Evaluation layers (reported separately, never conflated):**
(1) extraction proposal quality; (2) grounding validation quality;
(3) final lifecycle admission; (4) persisted lifecycle state;
(5) downstream retrieval/selection effects. A rejected invalid
proposal is not state corruption. A good shadow proposal is not a
canonical improvement. More proposals is not better.

## 13. Oracle Rules

Existing oracles: lifecycle scenarios define expected durable
memories (creation precision/recall, 13 creation probes), duplicate
identity, leakage probes; the external subset defines answer-bearing
sessions. Missing and to be added **additively**: span-level evidence
oracles, expected-kind labels where absent, rejection categories
(question/hypothetical/temporary/assistant-only/unsupported), and
acceptable-normalization sets. These live in new annotation files
keyed by stable case IDs — proposed path
`benchmarks/scenarios/annotations/grounded-extraction/` (lifecycle)
and `benchmarks/external/longmemeval/annotations/grounded-extraction/`
(external) — frozen records are never edited in place.

Scoring rules: exact match scores; normalized semantic match scores
against a documented acceptable-normalization set (multiple
acceptable normalizations allowed per case); wrong kind with correct
content = kind error (counted in correct-kind rate, not creation
precision failure); correct kind with unsupported content = precision
failure + unsupported claim; valid span with wrong candidate =
precision failure; correct candidate with invalid span = grounding
failure (never counted as a success); duplicate restatement scored by
the duplicate metrics, not as new creation; conflicting preferences
follow existing supersession oracles; ambiguous durable candidates are
annotated ambiguous and excluded from precision/recall denominators;
no-candidate is a first-class prediction (§14); malformed proposals =
validation failures, never silently dropped; controller-unavailable =
clean skip, not failure; cases lacking oracle evidence are marked
unscorable and reported, never silently counted either way.

**Multi-candidate cases:** because the controller proposes at most one
candidate per interaction, recall is scored as *any-acceptable*: a
case counts as recalled when any oracle-acceptable candidate for that
interaction is proposed. Cases whose oracle requires multiple distinct
durable memories from one interaction are annotated as such and
reported separately, not silently failed.

## 14. Metric Definitions

Conventions: every ratio ships as numerator/denominator plus rate
(`31/50 (62.0%)` style); zero denominators are undefined, never 0% or
100%; skipped/unscorable cases are excluded from denominators and
counted separately; latency is wall-clock `time.perf_counter()`, warm
process (first-call warm-up excluded from aggregates when measured),
reported as count/mean/median/p95 (p95 only when n ≥ 20), and always
excluded from artifact digests per the established convention.

**Proposal metrics.** *Proposal rate* = interactions with a positive
proposal / evaluated interactions. *Valid proposal rate* = proposals
passing the full validation pipeline (structural + grounding +
semantic-support + provenance) / all positive proposals.
*Direct-valid proposal rate* (chosen meaning, documented): proposals
that are structurally valid AND span-exact AND semantically supported
by the cited span, measured **before** duplicate/conflict/lifecycle
admission / all positive proposals — isolating extractor quality from
downstream state. *Deterministic fallback rate* = learned-controller
attempts requiring deterministic fallback (dependency unavailable,
malformed output, timeout, validation failure, controller error) /
learned attempts; configured shadow-only execution and intentionally
disabled learned paths are recorded as modes, not counted as
fallbacks.

**Grounding metrics.** *Grounded-span validity* = positive proposals
with in-range offsets + exact slice equality + permitted source type
(deterministic part), reported alongside the *semantically supported*
subset (oracle part) / positive proposals. *Unsupported-claim rate* =
proposals whose normalized candidate adds facts, scope, certainty,
ownership, or durability absent from the cited span / positive
proposals.

**Creation quality.** *Precision* = proposals that are oracle-positive
with correct semantic content, acceptable kind, and valid grounding /
all positive proposals. *Recall* = oracle-positive interactions with
an acceptable proposal (any-acceptable rule, §13) / oracle-positive
interactions. *F1* = harmonic mean; undefined when either denominator
is zero (reported as undefined). *Correct memory-kind rate* =
semantically correct proposals with the expected kind / semantically
correct proposals. *Normalized-text correctness* = proposals whose
normalized text has no unsupported details, correct ownership,
preserved modality/scope/polarity/temporal meaning, no
temporary→durable conversion, and semantic equivalence to the
supported claim / semantically scored proposals.

**Rejection metrics.** For each category C in {non-durable, question,
hypothetical, temporary-state, assistant-only, unsupported-claim}:
rejection rate = oracle-C interactions with NO accepted positive
proposal / oracle-C interactions (success = correctly producing none
or a rejected proposal).

**No-candidate metrics.** "None" is a first-class prediction.
*No-candidate precision* = predicted-none interactions that are
oracle-negative / predicted-none interactions. *No-candidate recall* =
oracle-negative interactions predicted none / oracle-negative
interactions. These are the complement-class dual of creation
precision/recall; both views are reported so abstention quality is
visible rather than hidden inside positive-class metrics.

**Lifecycle metrics** (existing definitions retained): duplicate
proposal rate; downstream accepted-memory rate (accepted / valid
proposals); accepted durable-memory count; rejected proposal count;
state corruption (invalid **persisted** lifecycle outcome only — a
rejected proposal is not corruption); stale leakage; forgotten
leakage; inactive contamination.

**Downstream metrics** (existing canonical definitions, unchanged):
answer-session candidate rate, selection rate, Recall@K, MRR, context
tokens.

**Operational metrics:** extraction latency, validation latency (when
separately measured), total interaction overhead vs the reference,
CPU feasibility statement, learned-controller availability status,
shadow/adoption status per system.

## 15. Adoption Gates

Deterministic grounded extraction (`experienceos_grounded_rules_v1`)
may become canonical only if ALL of the following hold on the frozen
benchmarks vs `experienceos_hybrid_full_v2_reference`. Materiality
rule (reused from the retrieval contract): a drop of more than 1 case
on a frozen numerator, or more than 2% relative on a continuous
metric, is material; given the small frozen denominators, every gate
decision also requires transparent paired case-level review in the
report.

1. **Recall/absence improvement (required):** lifecycle creation
   recall improves by ≥ 1 case (12/13 → 13/13) OR external
   answer-bearing candidate rate improves by ≥ 2 cases
   (31/50 → ≥ 33/50).
2. **Precision defensible:** lifecycle creation precision regresses
   by at most 1 case vs 12/13; on fixture sets, precision ≥ 0.85 with
   case-level review of every false positive.
3. **Grounded-span validity:** 100% of accepted proposals
   (zero tolerance for invalid offsets/slices among accepted).
4. **Unsupported-claim rate:** 0 among accepted proposals (validation
   must reject them); ≤ 2% among raw proposals, each reviewed.
5. **No-candidate behavior defensible:** no-candidate recall on
   oracle-negative cases regresses by no more than 1 case vs the
   reference behavior.
6. **Inactive contamination:** 0. 7. **Forgotten leakage:** 0.
8. **Superseded-in-current-context leakage:** 0.
9. **State corruption:** 0.
10. **Downstream benefit:** external candidate or selection rate
    improves, or the report demonstrates concretely which new durable
    memories become retrievable.
11. **Latency:** deterministic extraction adds ≤ 5 ms mean per
    interaction over the reference (current rules are
    sub-millisecond; this is a generous ceiling), measured and
    digest-excluded.
12. **Diagnostics explain every decision** (§17 fields complete).
13. **Default tests remain offline and deterministic.**
14. **Optional learned paths skip cleanly when unavailable.**

**Learned extraction** may become canonical only if it beats
`grounded_rules_v1` on the predeclared primary metrics (creation
recall AND precision under gates 1–2, with gates 3–9 intact) —
otherwise it remains shadow-only, candidate-only behind explicit
configuration, or deferred. Deterministic fallback remains permanently
available regardless.

## 16. Learned-Controller Stop Conditions

The learned experiment stays disabled, shadow-only, or deferred if
any of: frequent unsupported memory invention; unreliable evidence
spans; question→assertion or hypothetical→fact conversion; material
precision regression; stale leakage, inactive contamination, or state
corruption attributable to it; heavy dependencies required by default
tests; automatic model downloads; root-import model loading; dashboard
instability; unexplained or missing diagnostics; no measurable benefit
over deterministic extraction; unacceptable CPU/latency behavior. A
failed learned experiment still counts as useful evidence when
measured honestly, canonical behavior stays safe, the deterministic
path or contract strengthens, and no unsafe path is adopted.

## 17. Diagnostics Requirements (planned)

Every extraction attempt records: controller ID and mode; source ID
and type; candidate-or-none; proposed kind; normalized text; evidence
text and offsets; confidence; durability rationale; controller reason;
structural, grounding, semantic-support, and lifecycle-admission
statuses; rejection reason; fallback status; `canonical_effect`
(always `false` for shadow proposals); latency (digest-excluded key
naming per the established `elapsed_ms` convention); error
classification (type names only — no messages, stack traces, or
paths); benchmark case ID when applicable. Rejected proposals are
never recorded as persisted memories; old events without these fields
remain renderable (the established tolerant-payload pattern); no
secrets or personal paths in any diagnostic.

## 18. Artifact Paths and Preservation Rules

New committed evidence (additive; feature-named per repository
policy; following the established committed-directory file set and
digest discipline):

- `benchmarks/results/committed/grounded-extraction-ablation/` —
  frozen lifecycle runs for the §11 systems.
- `benchmarks/results/committed/grounded-extraction/` — external
  fixed-subset runs.
- `benchmarks/results/committed/report-grounded-extraction/` —
  digest-locked report data, comparison tables, gate evaluation.
- Human-readable report: `docs/grounded_extraction_report.md`.
- Development fixtures: `benchmarks/fixtures/grounded-extraction/`
  (committed, labeled development-only, never mixed into frozen
  evaluation evidence).
- Local/optional evidence (learned smoke, Qwen ceiling):
  `benchmarks/results/local/…` (gitignored), clearly separated.

Requirements: stable case IDs (existing scenario/question IDs);
stable system IDs (§11); schema versioning on aggregates;
deterministic ordering; reproducible commands; timestamps normalized
out of digests per the existing writer; environment-dependent optional
runs recorded as skips with reasons; double-run digest equality before
committing (the established two-run rule). No fabricated results; no
pre-created result files.

## 19. Required Validation Commands

Required offline validation (all workstreams, and closure):

```bash
.venv/bin/python -m compileall experienceos demo benchmarks
PYTHONPATH=. .venv/bin/python -m pytest
PYTHON=.venv/bin/python ./scripts/validate_demo.sh
# historical preservation (7)
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1
./scripts/run_benchmarks.sh validate-report
./scripts/run_benchmarks.sh validate-v2
./scripts/run_benchmarks.sh validate-external-v2
./scripts/run_benchmarks.sh validate-v2-consistency
./scripts/run_benchmarks.sh validate-report-v2
# retrieval evidence (4)
./scripts/run_benchmarks.sh validate-phase11
./scripts/run_benchmarks.sh validate-external-phase11
./scripts/run_benchmarks.sh validate-phase11-consistency
./scripts/run_benchmarks.sh validate-report-phase11
```

Closure additionally requires: a quick benchmark smoke; the grounded-
extraction benchmark (or documented subset); report regeneration via
its established command only; artifact digest verification for every
new committed directory; dashboard smoke/AppTest if dashboard code
changed; optional learned-extractor smoke when configured (clean skip
otherwise); optional Qwen ceiling smoke only when credentials are
available (clean skip otherwise). Validation classes are distinct:
required-offline, optional-local-model, optional-live-Qwen — the
latter two must never be required for default tests.

## 20. Closure Evidence Requirements

The final closure/transfer report (returned through the governing
workflow, not committed) must contain: decision; executive summary;
starting baseline; final repository state; commit inventory;
architecture changes; the extraction-controller contract as built;
span/grounding validation results; deterministic extraction results;
optional learned-extraction results or clean-skip evidence; pipeline
integration; dashboard and diagnostics; benchmark results with the
§15 gate table; extraction improvements; downstream effects;
regressions/trade-offs; latency/CPU feasibility; lifecycle-safety
verification (all §15 zeros); supported claims; claims not supported;
remaining limitations; recommended next work; final transfer
statement. Publication (if authorized) follows the established
plain non-force push with pre-push remote lock and post-push
verification.

## 21. Known Contract Limitations

- Span-level and rejection-category oracles do not exist yet; the
  annotation workstream must create them additively, and until then
  semantic-support scoring is defined but not executable.
- The frozen creation oracle has only 13 probes; gates therefore pair
  small-numerator thresholds with mandatory case-level review.
- Exact span equality cannot prove semantic support; the two
  validation layers are deliberately separate, and the semantic layer
  depends on oracle quality.
- The one-candidate cap means multi-candidate interactions are scored
  any-acceptable; genuine multi-memory interactions are reported
  separately rather than solved here.
- The optional learned extractor's dependency and model remain
  unselected; nothing here commits to a specific model.
- Whether recent-context input (beyond the current message) is needed
  for acceptable recall is an open implementation question for the
  extractor workstream; the authority boundary does not change either
  way.

## 22. Acceptance Decision

**Status: contract complete.** This document was produced against the
verified baseline in §2 with no production-behavior changes, no
historical-artifact modifications, and no benchmark execution. It
governs all subsequent grounded-extraction workstreams: scenario audit
and development fixtures; proposal schema and span validation;
deterministic grounded extraction; optional learned extraction
(shadow-first); pipeline integration; benchmarking and gate
evaluation; dashboard visibility; stabilization and closure. Planned
behavior described here is not implemented; every adoption decision
defers to the §15 gates and §16 stop conditions.
