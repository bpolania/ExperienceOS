# Specialized Controller Architecture (Phase 11, Prompt 6)

Controllers propose. The deterministic ExperienceOS kernel validates
and decides. This document records why ExperienceOS is moving from one
generic local memory-manager model to specialized, replaceable
controllers, what the kernel keeps, and exactly what each controller
contract may and may not do. No claim is made that specialized
controllers already improve quality — that requires benchmark evidence
that does not yet exist.

## Why specialized controllers

Phase 9 proved a single small local model cannot reliably own every
memory decision (0/15 and 0/8 directly valid proposals; contained by
deterministic fallback). Specialization is the response: different
memory decisions need different evidence; a narrow question ("does
this interaction request a forget?") is easier to benchmark, validate,
and bound than "manage memory"; failures isolate per controller
instead of corrupting a whole pipeline; each controller stays
replaceable (deterministic baseline ↔ optional learned backend)
behind the same contract; deterministic fallback always exists; and
durable state stays kernel-owned no matter what a controller says.

## The deterministic kernel (authoritative, unchanged)

Lifecycle state and transitions (`ExperienceEngine`, the only code
that applies CREATE/SUPERSEDE/FORGET), persistence (`MemoryStore`),
proposal validation and fallback (`ExperienceManager`), retrieval
eligibility and ranking (`HybridRetrievalStrategy`, lifecycle-first),
final selection and conflict containment (selection strategies),
context budgets and rendering (`ContextBuilder`).

## Controller inventory

| Controller | Question answered | Evidence in | Proposal out | Authority limit | Phase 11 status |
|---|---|---|---|---|---|
| `AdmissionController` | Should this interaction enter memory processing? | `AdmissionEvidence` (bounded messages, session ref, counts) | admit / reject / abstain | never decides durability | interface-only; `admission_abstain-1` default |
| `ExtractionController` | What candidate memory, if any, is grounded here? | `ExtractionEvidence` (bounded texts, role, temporal/provenance labels) | one `ProposedMemoryCandidate` or none / abstain | never persists; candidate has no ID, status, or links | interface-only; `extraction_noop-1` default |
| `UpdateController` | Does this candidate modify existing experience? | `UpdateEvidence` (candidate + `MemorySnapshot` + similarity signals) | no_relation / duplicate / reinforce / supersede / correct / merge_candidate / abstain | never applies updates or links | interface-only; `update_abstain-1` default |
| `ForgetIntentController` | Does this interaction request forgetting? | `ForgetIntentEvidence` (bounded message, target snapshots, detected phrases) | no_forget_intent / forget_candidate / ambiguous / abstain | never forgets or hides memory | interface-only; `forget_intent_none-1` default |
| `MemoryGate` | Does this retrieved candidate look useful? | `GateCandidateEvidence` (post-selection audit snapshot) | admit / reject / abstain | shadow-only; `affected_selection` always false | **integrated (shadow)** since Prompt 5 — see `docs/memory_gate.md` |
| `TransitionVerifier` | Is this proposed transition supported and allowed? | `TransitionEvidence` (transition type/target, snapshots, policy results) | approve / reject / abstain | never applies transitions | interface-only; `transition_abstain-1` default |

Every controller must eventually clear the same bar before adoption:
shadow measurement on the frozen benchmarks, zero lifecycle-safety
regressions, and an explicit adoption decision.

## Shared conventions (`experienceos/controllers/base.py`)

`Protocol` seams; frozen dataclasses; construction-time validation
(finite scores/confidences in [0, 1], bounded reasons ≤ 300 chars,
JSON-serializable diagnostics, `proposal_only=True` enforced);
documented text bounds (evidence 2000 chars, excerpts 200); typed
errors (`ControllerError` / `ControllerInputError` /
`ControllerProposalError` / `ControllerUnavailableError`); runtime-mode
vocabulary (`deterministic`, `shadow`, `offline`, `optional_model`,
`unavailable`); `EvidenceSpan` (validated offsets, a proposal schema
for future grounded extraction — nothing in production creates spans
today); `MemorySnapshot` (frozen primitive copy of one memory — the
live record is never passed). Memory kinds and lifecycle statuses are
mirrored as literals so controller modules import nothing from the
memory layer: structural isolation over DRY. Gate-specific invariants
(`shadow_mode=True`, `affected_selection=False`) stay in `gate.py`,
deliberately not generalized.

## Active status

`MemoryGate` is the only meaningfully integrated specialized
controller, and it is shadow-only. The five Prompt 6 contracts are
interface-only: their deterministic defaults abstain or return
no-op proposals (the transition default abstains rather than
"approving", so no output can be read as authority), exist for tests
and fallback semantics, and are constructed by nothing in
ExperienceOS — no default wiring, no environment flag, no registry,
no orchestration path. No controller proposal is automatically
applied anywhere.

## Future integration sequence

1. Define the narrow contract (done here).
2. Implement a deterministic baseline.
3. Implement an optional learned controller behind the same contract.
4. Run in shadow mode against canonical behavior.
5. Benchmark on the frozen datasets.
6. Validate lifecycle safety and quality gates.
7. Explicitly adopt or reject.
8. Keep the deterministic fallback permanently available.

Likely future integration seams (documented, not wired): admission →
before the planner's extraction gate in the policy path; extraction →
alongside the Phase 9 hybrid extractor; update → beside the
semantic-identity supersession logic; forget-intent → beside the
Phase 9 forget resolver; transition verification → beside the engine's
pre-application validation.

## Likely Phase 12 direction

Focused grounded extraction: one grounded candidate or none, evidence
spans over the source text, strict kernel validation, benchmarked
precision/recall — with no durable mutation authority. The
`ExtractionController` contract and `EvidenceSpan` schema here are
shaped for that; nothing of it is implemented yet.
