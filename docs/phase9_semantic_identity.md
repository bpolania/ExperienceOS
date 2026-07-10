# Phase 9: Semantic Identity and Generalized Supersession

Prompt 2 of the [Phase 9 experiment contract](phase9_experiment_contract.md).
Implemented in `experienceos/memory/semantic.py` (identity model,
normalizer, conflict decisions) and
`experienceos/memory/semantic_planner.py` (the slots-v2 planning
strategy), exercised through the `experienceos_slots_v2` benchmark
system. **v1 behavior is frozen**: `experienceos_rules` keeps the
plain `MemoryPlanner`, and a fresh v1 full-offline run reproduces the
canonical Phase 8 digest exactly.

## What semantic identity is

A versioned structured identity for a durable memory — `(subject,
attribute, scope)` plus a normalized comparison value, qualifiers
(e.g. `historical`), cardinality, confidence, and extraction method —
stored under `metadata["semantic_identity"]` on the existing entry
metadata channel (additive; survives the SQLite round trip; legacy
rows without it remain fully valid and are normalized lazily).
Temporal/provenance fields (`valid_from`, `observed_at`,
`source_type`) are reserved seams for the later temporal prompt.

Subject, attribute, value, and scope matter because they turn "is
this new text similar to that old text?" into "do these two memories
occupy the same slot?": `current_phone/global` changing from
`pixel 6` to `pixel 9` is a replacement; `preferred_seat/
short_work_trip` and `preferred_seat/long_international_trip` are
different slots and must coexist.

## Duplicates vs conflicts

Duplicate: same slot, equivalent normalized value ("My current phone
is Pixel 9." after "My phone is a Pixel 9.") — no new record is
created and nothing is superseded. Conflict: same slot, incompatible
values, single-valued cardinality, full confidence — the old record
is superseded with bidirectional linkage. Everything else coexists.

## Why supersession stays conservative

Automatic replacement requires ALL of: exact normalized subject and
attribute equality (attributes come from a small deterministic
registry — phone/residence/employer aliases, a handful of preference
classes, routing instructions — never fuzzy similarity), identical
scopes (distinct explicit scopes coexist; default-vs-explicit
coexists), matching historical/current qualifiers (historical
wording never supersedes), single-valued cardinality (multi-valued
like `speaks_language` and unknown cardinality always coexist), and
1.0 identity confidence. The v2 planner also **vetoes** v1's narrow
keyed supersessions when semantic scopes differ, which is what fixes
scoped-seat coexistence. Multiple same-slot conflicts supersede
together only because each is independently confident.

All actions still flow through ExperienceManager validation and
ExperienceEngine lifecycle checks; the planner never touches storage.
Superseded records remain persisted, linked (`superseded_by` /
`replaces`), excluded from current retrieval and context, and
auditable via `memories_for_user(status="superseded")` and the
`memory_superseded` event, whose reason records the identity version,
strategy, attribute, and both values.

## The slots-v2 ablation (development evidence)

Frozen Phase 8 lifecycle dataset, identical configuration to
`experienceos_rules` except the planner. Development run (local
artifact, not final Phase 9 evidence — final v2 artifacts are
generated at phase closure):

| Metric | v1 rules | slots_v2 |
|---|---|---|
| Supersession accuracy | 2/7 | **5/7** |
| Old-value deactivation | 3/8 | **7/8** |
| Conflicting active memories | 3/7 | **0/7** |
| Stale rendered-context leakage | 10/11 | **6/11** |
| Recall@K | 15/17 | 15/17 (no regression) |
| Inactive-memory contamination | 2/20 | 0/18 |
| Creation precision / recall | 10/11, 10/13 | unchanged |
| Forget metrics / unrelated preservation | — | unchanged (no incorrect-target increase) |
| Scoped coexistence (updates_006 class) | failed | **passes** |

## Current limitations

Remaining stale leakage and the two unfixed update scenarios are
extraction gaps, not conflict gaps: v1 extraction (unchanged in this
ablation by design) never creates the memory ("goes to …" phrasing,
possessive-with-apostrophe subjects), so there is nothing to
supersede — deferred to the hybrid-extraction prompt. The attribute
registry is deliberately small; unknown identities safely coexist.
Leading-clause scopes ("For long international trips, I prefer …")
lose their scope in v1's stored text, which the scope-veto handles
safely but not perfectly. Nothing here claims universal semantic
understanding; the frozen-benchmark improvements above are the whole
claim, denominators included.
