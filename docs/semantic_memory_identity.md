# Semantic Memory Identity

Deterministic, explainable comparison of memory meaning and lifecycle
identity. This layer answers one question and applies no answer:

> Given the current memory state and a newly grounded statement, do they
> name the same experience, conflicting current experience, compatible
> scoped experience, unrelated experience, or an unsafe ambiguity?

It is the identity foundation later transition verification builds on.
It is **not** a text-similarity score, and it never decides or applies a
lifecycle mutation.

## 1. Purpose

ExperienceOS keeps accumulated experience current. Doing that safely
requires knowing when two memories mean the same thing. Without a real
identity model a memory layer will:

- create duplicate active memories from paraphrases;
- replace unrelated experience;
- collapse valid scoped preferences into one;
- treat a historical statement as the current state;
- treat a temporary exception as durable;
- guess when identity is genuinely ambiguous.

This module makes each of those a rule-governed, inspectable decision.

## 2. Architecture boundary

`experienceos/memory/identity.py` is an independent component:

- `ExperienceManager` remains lifecycle-policy authority;
- `ExperienceEngine._apply_memory_actions` remains the sole durable
  mutation boundary;
- identity **proposes nothing and mutates nothing**.

The module imports only the memory schema, the planner's normalization
helper, and the committed semantic-identity metadata reader. It does not
import the engine, the manager, a store, a provider, embeddings, or the
network — a test enforces this.

It builds on the existing `experienceos/memory/semantic.py`
(`SemanticIdentity`, cardinality-driven conservative conflict
detection), which stays canonical and unchanged: it is what
`SemanticMemoryPlanner` already uses to plan real supersessions. This
module adds the richer relation vocabulary, the non-durable markers, the
identity keys, and the diagnostics that transition verification needs,
without altering any canonical behavior.

## 3. Identity projection

`IdentityProjector.project_entry` / `project_text` produce a
`MemoryIdentity`:

| Field | Meaning |
|---|---|
| `subject` | whose/what the memory is about (`travel`, `food`, `work`, …) |
| `attribute` | which property (`seat`, `home_airport`, `base_office`, …) |
| `value` | the asserted content, canonicalized within its domain |
| `scope` | the supported context (`short_work_trip`, `long_international`, …) |
| `qualifiers` | historical / temporary / hypothetical / question flags |
| `temporal_status` | `current`, `historical`, `temporary`, `hypothetical`, `question` |
| `durability` | `durable` / `non_durable` |
| `kind` | `preference` / `fact` / `instruction` |
| `provenance_ref`, `evidence_ref` | references, not copied source text |
| `unknown_fields`, `completeness` | which critical fields are unestablished |
| `projection_method`, `projection_version` | how and by which version |

Each field is an `IdentityField` carrying `value`, `known`, `source`
(`structured_metadata` / `lexicon` / `pattern` / `none`), and the matched
surface form as evidence.

**Structured metadata wins.** An `ExperienceEntry` carrying committed
`semantic_identity` metadata contributes its attribute and value
directly; text is only reparsed for fields the metadata leaves open.
Committed metadata never overrides a field the text projection
established, because the two vocabularies are versioned independently.

`completeness` is diagnostic only. Classification is rule-governed —
no floating-point threshold is a safety boundary.

## 4. Identity keys

Two keys, deliberately distinct:

- **target key** — `kind | subject | attribute | scope`. The lifecycle
  slot. It **excludes the value** so replacing a value still lands on
  the same key.
- **semantic key** — target key + normalized value + temporal status.
  Two identities share it exactly when they assert the same value in the
  same slot with the same temporal reading.

Both return `None` when a component is unknown. A fabricated key is
worse than no key. Keys are deterministic, stable, serialization-safe,
free of filesystem paths, and independent of random state and model
calls.

## 5. Normalization

- Unicode NFKC, lowercase, whitespace collapse, curly quotes and dashes
  folded, conservative punctuation removal.
- `comparison_text` reuses the planner's `_normalized_text` — so identity
  and the canonical planner agree on what "same text" means — then drops
  articles, making "the aisle seat" and "aisle seat" an exact duplicate.
- Original text is always preserved for diagnostics.
- No aggressive stemming: nothing collapses unrelated meanings.

**Synonyms are domain-scoped.** `_VALUE_SYNONYMS` is keyed by value
domain, so "window" in the seat domain can never canonicalize a device
or workflow term. Supported equivalences include: aisle/window/middle
seat wording, `public transportation` ↔ `public transit`, `rental cars`
/ `car rental` ↔ `rental car`, `vegetarian places` / `vegetarian
restaurants` ↔ `vegetarian`, and the scope alias `short business trips`
↔ `short work trips`.

## 6. Scope model

Scopes canonicalize to buckets (`short_work_trip`, `long_international`,
`short_domestic`, `weekend_personal`, `work_trip`, `work`, `personal`).
`ScopeRelation` distinguishes:

| Relation | Meaning |
|---|---|
| `equal` | same bucket, both explicitly scoped |
| `compatible` | neither statement names a scope |
| `disjoint` | different supported buckets → coexistence |
| `overlapping` | one contains the other → **fails closed** |
| `unknown` | one side names a scope and the other does not |

`equal` and `compatible` both permit a conflict, but only `equal`
reflects a scope the source actually asserted.

Two critical distinctions:

- **Unscoped is not unknown.** A statement with no scope phrase is
  well-formed and scoped `general`; two unscoped statements share a
  scope.
- **Unscoped never assumes a stated scope.** "I prefer window seats."
  against "aisle seats for short work trips" yields `unknown`, not
  `equal`. The set-level resolver decides, or fails closed.

Unknown is never treated as equal, and a missing scope is never inferred
from another memory.

## 7. Identity comparison

`IdentityComparer.compare(existing, proposed)` applies ordered rules:

1. identical normalized text (with compatible kinds) → **exact duplicate**;
2. non-durable proposal markers → **question / hypothetical / temporary
   / historical**, fail-closed;
3. kind incompatibility → **unrelated**;
4. subject differs → **unrelated**;
5. attribute differs → **unrelated**;
6. unknown value → **ambiguous**, fail-closed;
7. scope disjoint → **scoped coexistence**; scope overlapping →
   **ambiguous**;
8. same slot, same value → **exact** or **semantic duplicate**;
9. same slot, different value → **current-state conflict**.

The result explains itself: per-field relations, `conflict_fields`,
`unknown_fields`, structured `rationale` diagnostics, `fail_closed`, the
reusable `target_key`, and `supersession_candidate`.

Field relations distinguish `equal` (identical surface wording) from
`equivalent` (same canonical value reached from different wording) —
which is precisely what separates an exact duplicate from a semantic
one.

Never: semantic duplicate from lexical similarity alone; update because
values merely differ; coexistence without a supported distinct scope;
unrelated merely because normalized text differs.

## 8. Relations

| Relation | Meaning |
|---|---|
| `exact_duplicate` | same normalized durable meaning |
| `semantic_duplicate` | different wording, same slot and value |
| `scoped_coexistence` | same attribute, different supported scope; both stay true |
| `current_state_conflict` | same slot, conflicting current values → supersession *candidate* |
| `unrelated` | no shared lifecycle identity; must be preserved |
| `temporary_exception` | bounded one-time choice; durable preference preserved |
| `historical` | describes a prior state; never replaces current |
| `hypothetical` | conditional; not an assertion |
| `question` | an inspection, not an assertion |
| `ambiguous` | cannot classify safely → fail closed |

## 9. Set-level resolution

Pairwise comparison cannot resolve an elliptical proposal: *"Actually,
make it window."* names a value but no slot. `resolve_identity(proposed,
active)` relates one proposal to the whole active snapshot and confirms
a conflict **only when exactly one active memory is a candidate**. Two
candidates fail closed as ambiguous — ambiguity never selects a
supersession target.

This is how elliptical corrections stay safe: the value domain
(`seat`, `airport`) is projected even when the specific attribute is
unknown, and the active set either resolves it uniquely or it fails
closed.

## 10. Supported deterministic patterns

The lexicon is **bounded on purpose** and covers the domains the
evaluated evidence exercises:

- travel: seat, home airport, work-flight airport, ground transport,
  flight time;
- food: morning drink, team-lunch style, dislike, allergy;
- work: base office, daily status channel;
- study: time of day; devices: phone model; family: soccer practice day;
  dev: editor theme.

Statement forms: `I prefer X [for <scope>]`, `X are my usual choice`,
`X is what I prefer`, `My X is Y [now]`, `I am based in the X office`,
`I am allergic to X`, `I don't like X`, `Use X [instead of Y] [for
<scope>]`, `From now on, send ... to #channel`, `I used to ..., but now
...`, and elliptical corrections `make it X` / `back to X` / `use X`.

**Outside these patterns the projection returns `unknown` and the
comparison fails closed.** This is not general language understanding
and is not claimed to be.

## 11. Diagnostics

Every comparison carries bounded, structured diagnostics: projection
method and completeness, normalized text, both keys, per-field
relations, kind and durability compatibility, matched markers, conflict
fields, unknown critical fields, the final relation, and the
fail-closed reason. `rationale` is a tuple of `IdentityDiagnostic(code,
detail)` — structured codes, not free-form prose.

Diagnostics never expose secrets, API keys, filesystem paths, benchmark
file contents, model prompts or outputs, or unrelated user memories.
Provenance is carried by reference rather than by copying source text.

## 12. Evaluation

```bash
# measure on the frozen transition-verification corpus (read-only)
./scripts/run_benchmarks.sh evaluate-semantic-identity

# prove deterministic repeatability
./scripts/run_benchmarks.sh repeat-semantic-identity

# focused tests
python -m pytest tests/test_semantic_memory_identity.py
```

A record is evaluated only when it has an active memory to compare
against **and** its committed label names an identity relation. Records
that primarily test forget handling, question rejection, unsupported
transitions, or lifecycle preservation are counted not-applicable rather
than forced into an identity metric. Historical-scored and
development-only results are always reported separately; unresolved and
excluded records are never scored.

## 13. Measured results

Relation accuracy, on the frozen corpus:

| Partition | Applicable | Correct |
|---|---|---|
| historical-scored | 10 / 28 | **10 / 10** |
| development-only | 22 / 27 | **22 / 22** |

Zero-tolerance safety, both partitions: false duplicates **0**, false
update-conflicts **0**, false scoped-coexistence **0**, unsafe confident
classifications **0**.

Projection of the annotated before-state: subject 39/39, attribute
39/39, value 39/39, scope **35/39**. Latency p95 is well under
0.5 ms per comparison, inside the contract's 5 ms budget.

## 14. Measured limitations

- **Bounded vocabulary.** The lexicon covers the evaluated domains only.
  Unsupported phrasing yields `unknown` and fails closed — safe, but not
  general.
- **Sparse historical semantic-duplicate evidence.** Exactly one scored
  semantic-duplicate case exists. Development fixtures supplement it,
  and fixture performance is never reported as historical performance.
- **Small corpus.** 10 historical-scored applicable cases. 10/10 is a
  real result on real committed evidence; it is not evidence that
  semantic identity is solved.
- **Scope vocabulary granularity.** Four of 39 before-state scope
  projections disagree with the annotation's token (the corpus folds
  `cilantro` into scope and `team lunches` into the attribute; this
  module does the reverse). Both readings are internally consistent and
  none changes a relation, but they are counted as misses rather than
  explained away.
- **Limited compound parsing.** Only the `used to X, but now Y` form is
  separated into historical and current clauses.
- **Rule-maintenance cost.** Every new domain needs a lexicon entry;
  there is no learned fallback.

## 15. Claims not supported

This module does **not** provide open-domain semantic equivalence,
autonomous memory management, learned semantic reasoning,
production-grade natural-language understanding, complete duplicate
elimination, complete update targeting, or measured multilingual
equivalence.

## 16. No-mutation guarantee

Projection and comparison do not write to a store, do not alter input
memory objects, do not create lifecycle actions, do not call manager or
engine mutation paths, do not emit durable events, do not access the
network, and do not construct providers. Tests assert each of these.

## 17. Relationship to transition verification

Transition verification consumes this API read-only:

```python
existing = project_memory(entry)
proposed = project_statement("I now prefer window seats for work trips.")
comparison = compare_memory_identity(existing, proposed)
resolution = resolve_identity(proposed, [project_memory(e) for e in active])
```

`current_state_conflict` marks a supersession **candidate** and
`resolution.target_index` names the resolved target — but the decision
to supersede, and the authority to apply it, remain with
`ExperienceManager` and `ExperienceEngine`. The binding definitions live
in `docs/transition_verification_contract.md`.
