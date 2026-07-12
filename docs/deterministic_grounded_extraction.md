# Deterministic Grounded Extraction

`experienceos/memory/grounded_extraction.py` implements
`DeterministicGroundedExtractionController`, a rule-based,
provider-independent `ExtractionController` that answers one narrow
question per interaction: does it contain **one** durable,
user-grounded experience candidate? If yes, it proposes exactly one
candidate with an exact evidence span and a conservative
normalization, validated through `GroundedCandidateValidator` before
anything leaves the controller. If no, it returns none with a bounded
abstention reason.

The controller is deterministic, provider-independent, uses **no
model**, mutates **no memory**, is **not yet canonical**, and returns
**one candidate or none**. It is directly invokable only.

## 1. Purpose

Retrieval cannot recover experience that was never created. This
controller is the deterministic baseline that turns explicit and
semi-natural durable user statements into grounded, validated
proposals for later lifecycle consideration — the safe reference that
any future learned extractor must beat before adoption.

## 2. Proposal-Only Authority Boundary

> Models and learned components may propose experience. ExperienceOS
> decides what becomes durable, what replaces previous experience,
> what is forgotten, and what may enter context.

The controller receives no store, manager, engine, bus, provider,
model, or callback (constructor audited). It creates / updates /
supersedes / forgets / retrieves / ranks nothing, emits no lifecycle
events, and its diagnostics carry `canonical_effect: false`. The
canonical `HybridMemoryPlanner` is untouched, and nothing in
ExperienceOS constructs this controller (source-scan + subprocess
tested).

## 3. Controller Input

`extract(evidence: ExtractionEvidence)` — the existing controller
input type. Used fields: `user_text` (the current source), optional
`assistant_text` (context only, never scanned as an evidence source),
`provenance_label` (default `user_asserted`), and
`metadata["source_id"]`. No prior memories, store, provider, model,
network, environment, or recent conversation history is required or
used; the bounded interface is not widened.

## 4. Candidate-or-None Output

Returns an `ExtractionProposal`:

- **candidate**: `recommendation="candidate"` with one
  `ProposedMemoryCandidate` (canonical kind, normalized text, one
  `EvidenceSpan`, deterministic confidence) plus diagnostics.
- **none**: `recommendation="none"`, `candidate=None`, a bounded
  `abstention_reason`, and (when raw candidates were generated and
  rejected) `rejected_candidates` with validator codes.

A raw rule candidate that fails `GroundedCandidateValidator` is never
returned as usable — it appears only in bounded diagnostics.

## 5. Rule Families

Bounded, ordered, feature-named rules (each returns one raw candidate
or `None`), grouped by arbitration tier:

- **Tier 1 — current replacement / standing instruction**:
  `replacement-from-now-on`, `instruction-with-contrast`,
  `instruction-when-clause`, `instruction-negated-standing`,
  `preference-now-replacement`, `preference-change-contrast`.
- **Tier 3 — explicit statements**: `preference-explicit`,
  `preference-negated`.
- **Tier 4 — durable facts**: `fact-possessive`, `fact-stable-state`.
- **Tier 5 — scoped / habitual preferences**: `preference-scoped`
  (scope-carrying clauses; outranks bare habitual forms so scope
  survives).
- **Tier 6 — habitual preferences**: `preference-habitual`,
  `preference-leading-adverb`, `preference-do-all`,
  `preference-recurring-period`.
- **Tier 7 — conversational facts**: `fact-has-become`,
  `fact-acquired`, `fact-copular`.

No LLM, embeddings, probabilistic classification, or general parser.

## 6. Candidate Kind Assignment

Only `preference`, `fact`, `instruction`, assigned deterministically
by the matching rule: durable choices/inclinations/avoidances/defaults
→ preference; stable declared attributes/states → fact; standing
directives governing future agent behavior → instruction. One-off
imperatives are never instructions; temporary declarations are never
facts. Where a fixture allows several acceptable kinds, the rule that
fires chooses one stably (e.g. `From now on, …` → instruction).

## 7. Exact Evidence Spans

Zero-based character offsets over the exact unmodified source, start
inclusive, end exclusive, with `source[start:end] == evidence`
enforced by both the controller and the validator. Span selection
prefers the smallest complete supporting clause: trailing filler
(`anyway`, `though`, `after all`) is trimmed, and the terminal period
is included only when the match both starts its sentence and reaches
sentence end. Temporary requests and questions attached to a durable
assertion are excluded from the span. If no single contiguous span
supports the candidate, the controller abstains — evidence is never
synthesized or repaired.

## 8. Conservative Normalization

Normalizations stay within the cited span's vocabulary: first-person
verbs are conjugated to third-person singular by bounded morphology
(`prefer`→`prefers`, `fly`→`flies`, `choose`→`chooses`), possessives
and "I" subjects are dropped, and clauses are reordered — but no
synonym replacement, no universalizers, no strengthened frequency or
certainty, no added scope, no dropped negation. Every emitted
normalization must both pass the validator and (in fixtures) land in
the acceptable-normalization set; recorded unsupported normalizations
are never emitted (tested).

## 9. Grounding Validator Integration

Each raw candidate is wrapped as a `ProposedMemoryCandidate` and
validated via
`GroundedCandidateValidator.validate(candidate, ApprovedSource(source_id, text, provenance))`.
The validator remains authoritative for source identity, provenance,
exact offsets, evidence equality, source form, durability, and
normalized support. Valid → the candidate is eligible for arbitration
and the full validation diagnostics are preserved; invalid → excluded,
its rejection code recorded. Provenance comes only from the caller's
`ApprovedSource`, so the controller cannot upgrade its own trust
(e.g. `assistant_derived` yields no candidate).

## 10. Candidate Arbitration

Multiple raw candidates may be discovered; at most one is returned.
Deterministic sort key over the validated set: (tier, −confidence,
narrower span, earlier offset, stable rule ID). Unrelated claims are
never combined into a compound memory. Diagnostics record the raw and
valid candidate counts, the selected rule and family, and bounded
skipped/rejected candidate reasons.

## 11. Confidence Tiers

Documented, repeatable, rule-family-based (not learned calibration):
current replacement / standing instruction / explicit preference /
possessive fact ≈ 0.9; negated and explicit forms 0.85–0.9; habitual,
scoped, and conversational forms 0.8. Weak or ambiguous cases abstain
rather than emit a low-confidence memory.

## 12. Abstention Rules

Sentence-level pre-screens drop interrogative and hypothetical
sentences before any rule fires; the validator additionally rejects
temporary states, one-off requests, third-party preferences, and
unsupported normalization. Tested abstention scenarios: temporary
(today / this week / this month / this trip / until-date), one-off
requests, direct and embedded questions, hypotheticals and
counterfactuals, vague mood, assistant-only claims, third-party
preferences, and empty/whitespace input. Abstention reasons:
`no_rule_match`, `question`, `hypothetical`, `invalid_grounding`,
`empty_source`, `invalid_provenance`.

## 13. Diagnostics

Deterministic, JSON-safe, bounded. Candidate results carry controller
ID/version, source ID and provenance, matched rule and family, raw and
valid candidate counts, skipped candidates, evidence offsets, the full
validation diagnostics, `canonical_effect: false`, and an
`{"elapsed_ms": …}` timing block (digest-exclusion naming). Abstention
results carry the abstention reason and any rejected-candidate codes.
No secrets, model paths, personal paths, store objects, or unbounded
source text.

## 14. Development Fixture Coverage

Against the 37 committed development fixtures (development-only, **not
benchmark evidence**): 24/24 positive scenarios produce a valid
candidate with the expected exact span, an acceptable normalization,
and an acceptable kind; 13/13 negative scenarios abstain; no recorded
unsupported normalization is ever emitted; duplicate-restatement and
preference-change cases produce grounding-only proposals whose fixture
lifecycle expectations are invisible to the controller; the
deliberately unscorable ambiguity case abstains. These are
development-fixture coverage counts, not precision or recall.

## 15. Canonical Compatibility

`HybridMemoryPlanner`, `ExperienceManager`, `ExperienceEngine`, the
demo, and all committed benchmark results are unchanged; the full
suite and all eleven validators pass identically. The controller is
not enabled by default and is constructed by nothing in the kernel.

## 16. Known Limitations

Rules are bounded English patterns — real conversational phrasing
outside them abstains (`no_rule_match`) rather than guessing; synonym
normalizations remain unsupported (validator-blind); single-message
sources only, so a durable fact needing recent context is not
captured; multi-memory interactions yield one proposal by design;
kind boundaries (fact vs preference for conversational statements)
follow the rule that fires. None of this measures or improves
extraction on frozen benchmarks — no benchmark was run.

## 17. Examples of Positive Extraction

- "I prefer aisle seats for short work trips." → preference: "Prefers
  aisle seats for short work trips."
- "Window is fine for long flights, but for short work trips I usually
  want aisle." → preference: "Usually wants aisle for short work
  trips." (span = the scoped clause only)
- "My home airport is SJC." → fact: "Home airport is SJC."
- "When planning work trips, always include airport transfer time." →
  instruction (unchanged content).
- "From now on, use SJC as my default airport." → instruction: "Use
  SJC as the default airport from now on."
- "I do not prefer red-eye flights." → preference: "Does not prefer
  red-eye flights." (polarity preserved)
- "Book me an aisle seat for tomorrow - I always prefer aisle anyway."
  → preference: "Always prefers aisle." (span = the durable clause,
  "tomorrow" excluded)
- "I used to prefer window seats, but now I choose aisle." →
  preference: "Now chooses aisle." (new state only)

## 18. Examples of Abstention

- "Should I use SFO or SJC?" → none (`question`)
- "If I ever move to Seattle, I might use SEA." → none
  (`hypothetical`)
- "I am flying out of SFO this month." → none (`invalid_grounding` /
  temporary_state)
- "Book me an aisle seat for tomorrow." → none (one-off request)
- "My manager always prefers early flights." → none (third-party)
- "Lately I guess I lean toward quieter hotels, sort of." → none
- assistant-only claim → none (assistant text never scanned)
