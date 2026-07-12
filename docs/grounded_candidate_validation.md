# Grounded Candidate Validation

`experienceos/memory/grounding.py` implements the deterministic
validation boundary for externally produced durable-memory proposals,
under `docs/grounded_extraction_contract.md`. The validator receives a
`ProposedMemoryCandidate` plus a caller-supplied `ApprovedSource` and
returns a bounded `GroundingValidation` — approve or reject for later
lifecycle consideration. It is not yet integrated into memory
creation: `canonical_effect` is false in every diagnostic, and no
extraction controller became executable.

## 1. Purpose

Determine whether a proposed candidate is structurally valid, exactly
grounded in an approved source span, provenance-safe, durable enough
for consideration, and free from unsupported normalization — before
any lifecycle logic ever sees it.

## 2. Proposal-Only Authority Boundary

> Models and learned components may propose experience. ExperienceOS
> decides what becomes durable, what replaces previous experience,
> what is forgotten, and what may enter context.

The validator receives no store, engine, manager, bus, callback, or
provider; it creates/updates/supersedes/forgets/retrieves/ranks
nothing; its result carries no lifecycle instruction, no update or
forget target, and no retrieval score (field-set tested). Constructor
signatures are audited for authority handles.

## 3. Validation Pipeline

`GroundedCandidateValidator.validate(candidate, source)` runs eight
stages in a fixed order; the first failure is the primary rejection
code and later stages are recorded `skipped`:

1. proposal schema → 2. memory kind → 3. source identity + provenance
→ 4. span structure → 5. exact span match → 6. source form (question /
hypothetical / one-off / temporary / third-party) → 7. durability →
8. normalized-text support.

## 4. EvidenceSpan Offset Convention

The existing `EvidenceSpan` is reused unchanged (it already rejects
negative, zero-length, and inverted offsets at construction). Offsets
are zero-based character positions over the exact unmodified source
string, start inclusive, end exclusive, with the invariant
`source_text[start_offset:end_offset] == evidence_text`. The validator
additionally checks the end offset against the actual source length,
non-empty evidence, and the repository's bounded evidence length.

## 5. Exact-Match Requirements

The slice equality is literal: trimming, casing, punctuation,
whitespace, and Unicode differences all reject as
`evidence_mismatch`. Nothing is silently repaired — a proposal with
wrong evidence is rejected, never rewritten into validity.

## 6. Source Provenance Rules

Provenance comes from the caller's `ApprovedSource` only — a proposal
cannot upgrade its own trust. Default allowed: `user_asserted`.
`jointly_confirmed` and `tool_verified` are grantable only via an
explicit constructor grant (the existing confirmation and tool-result
policy paths); anything else is ungrantable and rejected at
construction. Unconfirmed `assistant_derived` → `assistant_only_source`;
unknown values → `invalid_source_type`. Any cited span whose `source`
is `assistant` rejects regardless of source metadata.

## 7. Memory-Kind Rules

`preference` / `fact` / `instruction` only. `ProposedMemoryCandidate`
already makes other kinds unconstructable; the validator keeps a
deserialization-boundary guard (`invalid_memory_kind`) for duck-typed
inputs.

## 8. Question and Hypothetical Rejection

Questions: any `?` in the cited span, an auxiliary+subject question
opening ("should I…", "do you…"), or wondering constructions. A bare
interrogative word is deliberately not enough — "When planning work
trips, …" is a subordinate clause and validates. Hypotheticals: "if
I/we…", "I might/would…", suppose/imagine/counterfactual patterns,
composed with the existing durability gate's hypothetical cue. In both
cases the **cited span controls**: a durable assertion beside a
question or hypothetical clause validates when cited precisely.

## 9. Temporary and One-Off Rejection

Temporary markers (today/tomorrow/right now/for now/this
week/month/trip/session/…/until ⟨day⟩) reject `temporary_state`;
imperative request openings (book/order/reserve/find/…) without a
standing-scope override reject `one_off_request` (composed with the
existing gate's transient-request rule). A durable clause inside a
mixed message ("I normally prefer aisle seats, so book one for
tomorrow") validates through its own span.

## 10. Durability Validation

Composes the existing `DurabilityGate`: its negative decisions
(question, hypothetical, transient request, quoted third-party,
current-turn-only, greeting, fiction, brainstorm) are authoritative
rejections here too. When the gate finds merely `no_durable_cues`, a
documented supplementary cue set for externally produced proposals may
still accept (has-become/became, copular self-description,
acquired-possession, change-with-contrast, imperative instruction,
normally/often/generally/by-default, most-⟨period⟩, negated
preference, "I do all my") — phrasings the rules-first extractor never
emits, evaluated only after every form-rejection guard has run.
Keywords never decide durability alone: "always" inside a quotation,
hypothetical, question, or third-party statement is rejected by the
earlier stages. Canonical extraction behavior is unchanged — the gate
itself was not modified.

## 11. Normalized-Text Support Checks

Deterministic, conservative, and explicitly **not** general semantic
entailment: polarity must match in both directions (negation reuse of
the extraction module's single `_NEGATION` rule);
frequency/certainty strength must not increase (always/never >
usually/normally/most > sometimes/tend); universalizers
(all/every/any/…) must come from the evidence; and every content token
of the normalized text must be lexically supported by the cited span
under bounded morphology (exact, ±s/±es, ies↔y, shared prefix ≥ 5).
Unknown numbers or entity-like tokens are clear inventions →
`unsupported_normalization`; other unknown common words →
`indeterminate_support`, which **fails closed** (invalid): the
validator never guesses, and a stronger repository-owned rule may
establish support later. Safe grammatical normalization
("I prefer aisle seats." → "Prefers aisle seats.") passes.

## 12. Validation Result Vocabulary

`valid` plus 17 bounded rejection codes: `malformed_proposal`,
`invalid_memory_kind`, `missing_source`, `source_mismatch`,
`invalid_source_type`, `assistant_only_source`, `empty_evidence`,
`invalid_offsets`, `evidence_mismatch`, `question_derived`,
`hypothetical_derived`, `temporary_state`, `one_off_request`,
`unsupported_ownership`, `unsupported_normalization`, `non_durable`,
`indeterminate_support`. One primary code per result (deterministic
first-failure ordering), plus per-stage statuses and a bounded
human-readable explanation.

## 13. Diagnostics

Every attempt serializes to JSON-safe diagnostics: validator ID and
version, source ID and provenance, proposed kind, bounded candidate
text (≤ 240 chars), evidence offsets and length, per-stage statuses
(including the gate reason or supplementary cue used), overall
validity and code, `canonical_effect: false`, and an
`{"elapsed_ms": …}` timing block following the established
digest-exclusion naming. No secrets, model paths, personal paths,
store objects, or unbounded source text.

## 14. Fixture Coverage

All 37 development fixtures are exercised
(`tests/test_grounded_validation_fixtures.py`): every positive case
validates with at least one acceptable normalization (and each
declared acceptable kind); every recorded unsupported normalization
rejects; every negative case rejects a naive whole-message proposal
with a code consistent with its fixture category; the assistant-only
case rejects an assistant-cited span; mixed-message clause control is
proven; duplicate/change fixtures validate grounding only, with their
lifecycle expectations invisible to the validator. Six fixtures gained
an additional deterministically-supportable acceptable normalization
(existing entries kept as oracle-acceptable variants) — a bounded
correction recorded here.

## 15. Known Limitations

Support checking is lexical and conservative: synonym normalizations
("got" → "obtained") are `indeterminate_support` rather than
supported; the guards are pattern-based English heuristics with the
usual regex boundaries; third-party handling rejects third-party
*preferences* while the canonical planner's existing household-fact
support is untouched; single-message sources only (recent-context
input remains an open extractor-workstream question); none of this
measures or improves extraction recall/precision — no benchmark was
run.

## 16. Examples of Accepted Proposals

- "I prefer aisle seats for short work trips." → "Prefers aisle seats
  for short work trips." (scope preserved)
- "My home airport is SJC." → "Home airport is SJC."
- "When planning work trips, always include airport transfer time." →
  reordered instruction, same content
- "I usually fly from SJC. Should I use SFO this time?" with the span
  on the first sentence → "Usually flies from SJC."
- "I do not prefer red-eye flights." → "Does not prefer red-eye
  flights." (polarity preserved)

## 17. Examples of Rejected Proposals

- "Should I use SFO or SJC?" → `question_derived`
- "If I ever move to Seattle, I might use SEA." →
  `hypothetical_derived`
- "I am flying out of SFO this month." → `temporary_state`
- "Book me an aisle seat for tomorrow." → `one_off_request`
- "My manager always prefers early flights." →
  `unsupported_ownership`
- "I usually prefer aisle seats." → "Always requires aisle seats." →
  `unsupported_normalization` (certainty increase)
- "My home airport is SJC." → "Lives in San Jose and always departs
  from SJC." → `unsupported_normalization` (invented entity)
- evidence cited from assistant text → `assistant_only_source`
