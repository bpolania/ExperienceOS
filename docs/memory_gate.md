# MemoryGate

The first specialized controller seam: a shadow-only gate that
inspects bounded retrieval evidence and proposes `admit` / `reject` /
`abstain` per candidate. **MemoryGate proposes; ExperienceOS
decides.** Currently every proposal is diagnostic: `shadow_mode` is
always true, `affected_selection` is always false, there is no
enforcement mode, and canonical selection, ordering, budgets, rendered
context, and memory state are provably unchanged by any gate —
including a failing one. MemoryGate is not an autonomous memory
manager, and no claim is made that gating improves retrieval;
the benchmark measures its shadow proposals.

## Proposal versus authority

`experienceos/controllers/gate.py` defines the seam:

- `MemoryGate` (Protocol): `controller_id` + `evaluate(evidence) ->
  GateProposal`. Deliberately absent: apply/admit/reject/update/
  delete/forget/select methods — the interface is structurally
  incapable of acting.
- `GateCandidateEvidence` (frozen): query, memory ID/kind, memory text
  (truncated to 300 chars), lifecycle status, canonical selected flag
  and rank, exclusion reason, token estimate, component-score copy,
  semantic evidence, fusion breakdown, retrieval
  mode, fusion profile ID. Never included: live memory records,
  stores, engines, buses, callbacks, vectors, cache objects, paths,
  or secrets.
- `GateProposal` (frozen, validated at construction): proposal ∈
  {admit, reject, abstain}; score and confidence finite in [0, 1];
  bounded reason (≤ 300 chars); JSON-serializable diagnostics;
  `shadow_mode=True` and `affected_selection=False` enforced —
  violations raise `GateProposalError`.

## Integration point

`HybridRetrievalStrategy.retrieve` runs the gate as its final step,
strictly after lifecycle admission, retrieval scoring, candidate
limits, canonical selection, and token-budget enforcement are
complete (`experienceos/context/gating.py:evaluate_shadow_gate`). The
gate observes the finished `RetrievalResult` and attaches additive
diagnostics; it never touches `selected`, eligibility, ordering,
scores, reasons, or token accounting. Configuration: the optional
`memory_gate` constructor parameter (default `None` = disabled, byte-
identical earlier behavior); fixed per strategy instance, never
query-dependent.

## Evaluation scope

The gate evaluates the final post-limit candidate set (rank > 0),
selected and skipped alike, so the benchmark can compare proposals against
canonical selection. Never evaluated: lifecycle-excluded records
(forgotten, superseded-in-current-mode, cross-user — proven with a
poisoned gate under maximum-evidence fixtures) and pre-ranking
exclusions (`zero_relevance`, `below_semantic_floor`,
`no_fused_evidence`, `below_candidate_limit`); they carry
`gate: {"considered": false}` and their existing reasons stay
authoritative. A superseded record explicitly admitted by the temporal
policy under historical intent is canonically eligible and may be
gate-evaluated; forgotten records never are, in any mode.

## Gates shipped

- **`PassThroughMemoryGate`** (`gate_pass_through-1`): admits every
  input with score 1.0 / confidence 1.0; dependency-free,
  deterministic across processes; the default choice when a gate is
  wanted but no opinion is.
- **`HeuristicShadowMemoryGate`** (`gate_shadow_heuristic-1`),
  deterministic documented rules evaluated in order: (1) **admit** on
  high-precision evidence (`phrase+entity >= 1`), dual
  lexical+semantic evidence, or strength ≥ 0.35; (2) **reject** on
  semantic-only evidence within 0.10 of the relevance floor (the
  documented collision-noise risk); (3) **abstain** otherwise.
  Strength = fused score, else semantic score (semantic-only mode),
  else `lexical/(lexical+3)`. Confidence fixed per outcome (0.9 /
  0.6 / 0.3). Rules use supplied evidence only — no benchmark labels,
  no query special cases, no models.

## Agreement semantics

selected + admit = agreement; skipped + reject = agreement; abstain =
neutral; selected + reject and skipped + admit = disagreement.
Disagreement is expected shadow evidence for the benchmark, never an error,
and never affects canonical behavior.

## Failure containment

Per-candidate: any typed gate error, runtime error, invalid proposal
(NaN/out-of-range/unknown value/non-serializable diagnostics), or
wrong return type is recorded as `status: "failed"` with the exception
type name only (no messages, stack traces, or paths), no proposal is
fabricated, and evaluation continues. The canonical result is always
preserved. `gate_strict=True` raises `GateEvaluationError` after
containment bookkeeping — selection is already final, so even strict
mode cannot change it. `BaseException` is never caught.

## Diagnostics

Candidate level (`RetrievalCandidate.gate`): considered, controller
ID, status, proposal, score, confidence, reason, shadow_mode,
affected_selection, canonical_selected, agreement_with_selection,
implementation diagnostics — or `{"considered": false}` /
failure records. Retrieval level (`RetrievalResult.gate`): enabled,
shadow_mode, controller ID, retrieval mode, evaluated/admit/reject/
abstain/agreement/disagreement/neutral counts,
selected_proposed_reject, skipped_proposed_admit, failures,
`affected_selection` (invariantly 0), status, first failure type, and
an `{"elapsed_ms": …}` timing block following the digest-exclusion
convention. All fields additive; no-gate mode leaves `gate` empty/None
so old events and consumers are untouched. Dashboard exposure comes
later.

## Verified guarantees

Selection identity across all four retrieval modes × {pass-through,
heuristic, always-reject, failing} gates on the full surface
(candidates, ranks, scores, reasons, selected/skipped, tokens,
rendered context); K and token budgets unaffected by admit proposals;
reject proposals leave selections intact; stores, events, and memory
metadata untouched; gate constructors accept no authority handles.

## Place in the controller architecture

MemoryGate is the first of six specialized controller seams and the
only one meaningfully integrated (shadow-only) so far; the other
five are interface-only contracts — see
`docs/controller_architecture.md`. The controller-architecture work changed nothing in this
module: gate IDs, proposal schema, invariants, and selection identity
are byte-unchanged.

## Measured status

Benchmarked at scale as `experienceos_gate_shadow_v1`: canonical metrics identical to the
fused system on both benchmarks, `affected_selection` 0 across every
case, zero gate failures, and measurable proposal distributions
(external: 34,148 evaluated — 5,028 admit, 2,047 reject, 27,073
abstain, 2,187 disagreements — see the report's gate-shadow table).
Agreement with the selector remains descriptive evidence, not a
quality metric.

## Limitations and future work

No enforcement, no learned gate, no local-model or Qwen gate, no
persistence of proposals, no controller registry. Whether shadow
proposals correlate with useful selection is unknown until benchmarking
measures agreement/disagreement on the frozen benchmarks; canonical
gate enforcement would additionally require explicit adoption in a
later phase.
