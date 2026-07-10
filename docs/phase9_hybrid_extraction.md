# Phase 9: Hybrid Conversational Memory Extraction

Prompt 3 of the [Phase 9 experiment contract](phase9_experiment_contract.md).
Implemented in `experienceos/memory/extraction.py` (durability gate,
extraction contract, deterministic conversational extractor, candidate
validator), `experienceos/memory/hybrid_planner.py` (the rules-first
coordinator), and `experienceos/policy/local_extractor.py` (the
optional local-model extractor), exercised through the
`experienceos_hybrid_extract_v2` benchmark system. **v1 behavior is
frozen**: `experienceos_rules` keeps the plain `MemoryPlanner`, and a
fresh v1 full-offline run reproduces the canonical Phase 8 digest.

## Rules-first extraction

For every user turn, the unchanged v1 deterministic rules run first
and stay authoritative — creation, keyed supersession, duplicate
skipping, forgetting. The turn is split into sentences; only sentences
no v1 detector matches continue to the auxiliary path (a conservative
sentence-level distinction, since v1 exposes no match spans). Turns
fully handled by the rules never invoke the auxiliary extractor.

## Durability gate

A deterministic, provider-independent screen (`DurabilityGate`,
version 1) decides whether an unmatched sentence MAY hold durable
experience. Overriding negatives reject outright: questions,
greetings, acknowledgements, current-turn-only instructions,
hypotheticals, quoted third-party speech, fiction/role-play,
brainstorming, and transient one-off requests (unless standing-scope
or explicit remember language overrides). Positives include explicit
remember/standing-scope language, recurring cues, first-person stable
state verbs (work for/live in/moved to/use/speak/...), third-person
and possessive state statements, routing rules, and preference
phrasings. **No cues means reject** — unclear durability creates no
memory, preserves the conversation, and stays visible in diagnostics.

## Candidate extraction interface

`MemoryCandidateExtractor` is a narrow provider-independent protocol:
`extract(ExtractionRequest) -> ExtractionResult`. Requests carry the
source sentence, a stable source reference, bounded recent user turns
(for unambiguous pronoun resolution only), the deterministic-match
status, and a configurable candidate limit (default 3 per turn) —
never benchmark answers, session oracles, evaluation labels, or
unbounded history. Candidates carry a normalized statement, a quoted
source-grounded evidence span, subject/attribute/value/scope,
qualifiers, confidence, and extraction method. Extractors return
proposals only; a proposal is not a stored memory.

## Deterministic offline mode

`DeterministicConversationalExtractor` (the canonical, reproducible
mode) covers generic conversational classes with composable phrase
patterns: possessive relationship facts ("My daughter's soccer
practice moved to Thursday."), affiliation and current-state verbs
("I work for Globex.", "She goes to Lincoln Middle School.", "We
moved to Seattle."), additive multi-value facts ("I speak Spanish and
Portuguese."), conversational preferences including leading-clause
scopes ("For long international trips, I usually go with a window
seat."), recurring schedules, whenever-instructions, and
current-state corrections. Pronoun subjects resolve only when the
bounded recent context names exactly one known relation; anything
ambiguous yields no candidate. Values must be grounded — "I upgraded
my phone" identifies no model and produces nothing. No scenario IDs,
fixture names, expected answers, or per-case mappings exist anywhere
in the extractor.

## Optional local-model mode

`LocalModelCandidateExtractor` implements the same protocol on the
existing `LocalModelRunner` seam (no second inference stack, no
downloads, disabled by default, unnecessary for the canonical offline
suite). The prompt asks only for durable candidates with quoted
evidence; the model never proposes forgets, supersedes, IDs, or
lifecycle states. Structural validation is strict; malformed output is
rejected safely with a recorded reason and produces no candidates —
never fabricated memory. A bounded development run of the verified
local Qwen2.5-0.5B (Q4_K_M) model showed safe containment but zero
grounding-accepted proposals (the model paraphrases instead of quoting
evidence — the known 0.5B weakness); real-local results are recorded
separately from canonical offline results and claim nothing general.

## Validation and lifecycle authority

Every candidate passes the ExperienceOS-owned `CandidateValidator`:
schema (supported kind, bounded statement, user role, confidence
bounds), deterministic grounding (evidence must be a span of the
source turn; value/scope/subject tokens must be grounded or resolved
by declared unambiguous coreference; quoted spans and negated sources
reject), and durability (gate must have passed). Accepted candidates
are deduplicated against the batch and active memories (exact
normalized text plus Prompt 2 semantic-duplicate detection), carry
semantic identity metadata (registry normalization first; otherwise a
conservative generic identity with unknown cardinality and sub-1.0
confidence that can never supersede under Prompt 2 rules), and become
plain CREATE actions flowing through the unchanged ExperienceManager
validation and ExperienceEngine lifecycle checks. **Models propose
candidates; ExperienceOS validates and applies them.** Extraction can
never supersede, forget, choose IDs, or bypass duplicate/conflict
validation. Failures are contained per candidate: one invalid
candidate never discards its valid siblings, and extractor failures
produce no auxiliary memory.

## Audit trail

The engine drains bounded planner records onto the existing event bus:
`memory_extraction_gate_passed/rejected`, `memory_extraction_invoked`,
`memory_candidate_proposed/rejected/accepted`, and
`memory_extraction_failed_safe`, each with a source reference, bounded
evidence excerpts, versions, and reasons. Accepted entries persist
extraction provenance (`metadata["extraction"]`: method, extractor,
versions, source_ref, evidence) alongside semantic identity metadata.

## v1/v2 isolation and benchmark configuration

`experienceos_hybrid_extract_v2` differs from `experienceos_rules`
ONLY in the planner: same dataset, provider behavior, retrieval
algorithm, K, context budget, metric semantics, and lifecycle
filtering — recorded in provenance (`retrieval_strategy` and
`selection_strategy` = `phase8_v1_unchanged`, `local_extractor_enabled
= false`). Hybrid extraction does not own retrieval; Prompt 4 does.
The extraction-only ablation retains v1 lifecycle planning: accepted
candidates create, never supersede — so a corrected value can newly
exist yet coexist with its stale predecessor until the Prompt 2
conflict strategy is composed in (an integration test proves
`HybridMemoryPlanner` feeds `SemanticMemoryPlanner` cleanly; no
combined system is registered yet). New `extraction_v2` metrics are
observational, additive, and absent from every v1 result.

## Known limitations

The gate is deliberately conservative: on natural LongMemEval
conversation it passes ~3.5% of unmatched sentences, and the
deterministic patterns propose on few of those, so external
candidate-rate gains are modest (development evidence; final Phase 9
evidence is generated at closure). Extraction-only leaves conflicting
actives unsuperseded by design. Pronoun coreference is single-relation
and bounded. Statements outside the pattern registry (and durable
content phrased as questions or implications) are not extracted.
Development fixtures under `benchmarks/fixtures/phase9_dev/` are never
final evidence.
