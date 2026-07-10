# Phase 9: Temporal and Provenance-Aware Experience

Prompt 6 of the [Phase 9 experiment contract](phase9_experiment_contract.md).
Implemented in `experienceos/memory/temporal.py` (models, deterministic
normalizer, query modes, read-time validity, retrieval policy) and
`experienceos/memory/temporal_planner.py` (the temporal planning
strategy), exercised through `experienceos_temporal_v2` (ablation F)
and a development-only pre-full-v2 composition. **Models propose;
ExperienceOS validates** — and all earlier systems reproduce exactly.

## Temporal metadata (version 1)

Additive optional fields on the existing entry-metadata JSON channel
(`metadata["temporal"]`; legacy rows stay fully readable, and no dates
are ever fabricated for them): `observed_at`, `event_time` (when the
described event happened — distinct from when ExperienceOS learned
it), `valid_from`, `valid_until`, `temporal_scope`
(current/historical/future/recurring/timeless/unknown),
`source_session_date`, `supersession_time`, `time_precision`
(day/month/year/range/relative/approximate/unknown),
`time_confidence`, `time_expression`, `reference_time`,
`uncertainty_reason`. Every user-asserted create records at least the
source session date when a runtime reference exists.

## Provenance (version 1)

`metadata["provenance"]`: source type (`user_asserted`,
`assistant_derived`, `tool_verified`, `jointly_confirmed`,
`system_observed`), role, message/session references, session date,
derivation references, confirmation status and confirmer, confidence,
provisional flag, tool references. Documented trust ordering:
tool_verified (5) > user_asserted (4) > jointly_confirmed (3) >
system_observed (2) > assistant_derived (1). **Trust refines a
relevant candidate; it never creates relevance** (a 0.05×trust
retrieval refinement applies only after lexical relevance exists).

## Deterministic temporal extraction

A bounded parser, never a general date engine: explicit dates (ISO,
"June 3, 2025", month-year, bare years with prepositions), relative
expressions resolved ONLY against a supplied reference date (session
date — never a wall clock; without a reference they stay `relative`
with an uncertainty reason), current/historical/future/recurring
cues, and ranges. No-fabrication rules are enforced and tested: "last
month" resolves to month precision (never an invented day), "a few
years ago" stays approximate at reduced confidence, a month-day
without a year resolves to nothing, and old age alone never expires a
memory.

## Validity transitions (strategy: derived-at-read, version 1)

Corrections use the Prompt 2 semantic supersession the temporal
planner composes in. Validity intervals are DERIVED AT READ TIME from
links — `resolve_validity` takes a superseded record's own
`valid_until` if stored, else its superseder's
`valid_from`/`event_time`/session date, else the recorded
supersession day — so no store mutation, no background workers, and
no transition date earlier than the evidence supports. The old record
keeps its original observation date and stays auditable; future facts
(`temporal_scope=future`) are held (`not_yet_valid`) until the
runtime reference reaches their `valid_from`, evaluated at retrieval
time. Historical statements ("My home city was Boston back in 2019.",
"I used to live in …" — a narrow past-tense extraction added for this
purpose) coexist with current facts and can never supersede them (a
planner veto backs this up).

## Assistant, tool, and confirmation eligibility

Assistant ingestion is feature-flagged (off by default; on for
`experienceos_temporal_v2` under policy
`explicit_confirmation_or_tool_or_deterministic_derivation-1`).
Durable assistant/tool content requires ONE of: an explicit,
unambiguous user confirmation of a recognizable assistant proposal
(both references stored; "either/or" proposals and vague replies are
rejected with audit events); a structured trusted tool result whose
fact text is grounded in the payload's own values (a free-text fact
never grounds itself); or a deterministic derivation from
user-provided dates (start + duration → end, stored as
`system_observed` with derivation refs, never mislabeled as a user
assertion). Unconfirmed suggestions ("You probably prefer window
seats.") are never stored — hallucination containment is tested.

## Query modes (version 1)

Deterministic intent: `current` (default — casual past tense never
exposes superseded records), `historical` ("what was my old …",
"before"), `as_of` ("in 2025", "as of March 2024" — validity evaluated
at the reference, with unknown bounds permissive so uncertainty never
hides evidence), `timeline` ("how has … changed", "show my …
history"). Historical modes ADMIT superseded records (labeled, never
as current truth); **forgotten memories remain excluded from every
user-facing mode**. Timeline/historical selection treats same-slot
values as chronology (ordered by derived validity), not redundancy or
concealable conflict, while current mode keeps all Prompt 5 rules.

## Rendering and diagnostics

The single ContextBuilder path gains an optional annotator: concise
labels like `[user asserted, current]`, `[historical 2025-01-05–
2026-07-10, superseded]`, `[future, from 2026-08]`, `[tool verified]`,
`[approximate time]` — only in temporal configurations; earlier
systems render byte-identical context. Audit events cover detected/
unresolved expressions, historical coexistence, tool acceptance/
rejection, confirmation links, and derivations; latency stays out of
digested fields and reruns are digest-stable.

## Configuration and isolation

`experienceos_temporal_v2` = rules extraction + Prompt 2 semantic
supersession + Prompt 4 retrieval + Prompt 5 coverage + Prompt 6
temporal/provenance, unchanged K/budget/provider/data; full
provenance recorded. The development pre-full-v2 composition
(`dev_composition=True`, ID `dev_full_temporal`) adds Prompt 3 hybrid
extraction and is never a contract system. All earlier systems keep
`temporal_policy=None` and reproduce exactly (v1 digest match; Prompt
4/5 ablation rows identical).

## Known limitations and the Prompt 7 boundary

Relative-time coverage is bounded (weekday names, locale-ambiguous
formats, and "soon" remain unresolved by design); temporal labels add
~6–7% context tokens; the lifecycle dataset exercises few explicit
historical queries; as-of matching is permissive under unknown
bounds. Forget detection/resolution and local-policy reliability are
Prompt 7; final Phase 9 evidence is Prompt 8. Temporal evaluation
here is development evidence, and the LongMemEval subset is not an
official score.
