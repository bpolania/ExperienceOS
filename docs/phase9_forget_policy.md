# Phase 9: Forget Resolution and Local-Policy Reliability

Prompt 7 of the [Phase 9 experiment contract](phase9_experiment_contract.md).
Implemented in `experienceos/memory/forget.py` (intent detection,
target description, conservative resolution) and
`experienceos/policy/local_v2.py` (one-action local proposals,
strict parsing, per-action fallback), exercised through
`experienceos_local_v2`. **Models propose; ExperienceOS decides** —
and every earlier system reproduces exactly.

## Forget resolution (resolver version 1)

Intent and target resolution are separate. The detector recognizes
generalized durable forms (forget/erase/remove/delete X, stop
remembering, "don't remember … anymore", "no longer keep", "I don't
care about … anymore") and GUARDS against non-durable ones: negation
("Don't forget X" can never forget X — a v1 bug the resolver-owned
path fixes), questions, hypotheticals, quoted speech, and
current-turn-only instructions. Bulk requests ("forget everything")
return a structured unsupported result — **bulk fuzzy deletion never
happens**.

Targets are described structurally (content tokens via the planner's
forget-tuned stopwords, entities, alias-class attribute hints, kind
hints, historical qualifiers) and scored against ACTIVE memories only
under explicit versioned weights: exact text 5.0, attribute 2.0
(registry links like "morning drink" ↔ preferred_drink/coffee), value
1.5, entity 2.0, scope 1.0, kind 0.5, lexical 0.6/token
(prefix-aware, so lunch↔lunches and study↔studying match), full-
coverage bonus 1.5. Auto-resolution requires score ≥ 1.0 AND a 0.5
margin over the runner-up — **ambiguity is rejected, never guessed**
("forget my seat preference" with aisle+window active → ambiguous).
Superseded/forgotten records are never targets
(`inactive_target_only`); explicit "X and Y" requests resolve each
part independently (max 3); plural wording never widens the action.
Forget remains distinct from supersession, forgotten records keep
their metadata, cannot later be superseded, and stay excluded from
current, historical, as-of, AND timeline retrieval (tested).

## Local-policy v2 (schema version 1)

One action per generation: `remember | update | forget | none` with a
bounded memory candidate, a target restricted to short prompt aliases
of the shown active memories (mapped back internally — invented IDs
are rejected), quoted evidence, confidence, and reason. Forbidden by
schema: action arrays, lifecycle status, metadata injection,
supersession links, timestamps, trust fields, unknown fields.
`none` is a valid expected answer, not a fallback.

**Parsing** is strict with SYNTAX-ONLY repair (outer-object
extraction, markdown fences, trailing commas, surrounding commentary)
and at most ONE bounded retry after structural failure; semantic
repair — changing actions, inventing targets, rewriting evidence,
normalizing out-of-scale confidences — never happens. **Per-action
fallback** never broadens the action: a malformed forget can only fall
back to deterministic FORGET actions; remember/update only to
creates/updates; an unclassifiable failure applies the full
deterministic plan (the Phase 8 containment contract); no safe action
means no mutation. Every decision records raw-to-applied audit
evidence (mode, raw excerpt, repairs, retries, validity stages,
rejection reason, fallback type, latency, tokens), and every applied
action still passes ExperienceManager and ExperienceEngine validation
— malformed output cannot mutate state (tested end-to-end).

## `experienceos_local_v2` and evaluation modes

Composition: pre-full-v2 (semantic supersession + hybrid extraction +
hybrid retrieval + coverage selection + temporal/provenance) + the
Prompt 7 forget resolver + local-policy v2. Unchanged K, budget,
provider, datasets. Modes: **scripted** (canonical offline — a
SIMULATED well-behaved proposer serializes the deterministic plan into
one v2 proposal per turn and runs the REAL parse/validate/fallback
pipeline; reproducible containment evidence, never real-model
accuracy), **deterministic** (dev-only ID, isolates the forget
resolver), **real** (the optional local GGUF through the same
pipeline; separately labeled development evidence). Scripted and
real-model results are never combined, and fallback results are never
counted as direct model accuracy.

## Measured results (development evidence)

Frozen lifecycle dataset: forget detection 2/4 → **4/4**, correct
targets 4/4, forgotten exclusion 0/2 → **2/2**, resurrection 0/6,
unrelated preservation 3/3, Recall@K 17/17, supersession 6/7, creation
12/13 precision and recall, 21 passed cases (best of the phase);
scripted policy: structural validity 104/104, fallback 0/104 (Phase 8
reference: 97/104), zero state corruption. Real Qwen2.5-0.5B (Q4_K_M):
0/15 direct valid proposals (percentage-scale confidences, action
confusion, prompt-echo evidence — the known 0.5B schema weakness),
retries unsuccessful, ALL decisions contained by per-action fallback
with a fully correct final lifecycle state — lower fallback is not
sufficient without correct state, and with this model the
deterministic fallback IS the correct behavior.

## Known limitations and the Prompt 8 boundary

Some paraphrase classes remain conservatively unresolved (that is the
design: containment over guessing); the real 0.5B model cannot yet
follow the schema directly (grammar-constrained decoding beyond the
runner's JSON response-format is future work); bulk forgetting remains
unsupported pending an explicit product contract. Final v2 benchmark
evidence, composition selection, and artifact generation belong to
Prompt 8; the LongMemEval subset is not an official score.
