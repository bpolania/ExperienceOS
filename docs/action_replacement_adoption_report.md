# Action Replacement — Adoption Gate Re-Evaluation

## 19.1 Decision

**`TRANSITION_PATH_CANDIDATE_ONLY`.** The transition path is **not
adopted**. Gate definitions, thresholds, and frozen evidence are
unchanged; no runtime default changed and no controller became canonical.

## 19.2 Executive Summary

Governed replacement eliminates the entire supersede-bearing duplicate
class (**6 → 0**) and improves overall semantic duplicate pairs from
**10 → 4**. Every blocking safety gate passes and every additional
action-replacement acceptance condition passes. **Gate 1 still fails**
under its frozen overall definition — the reference leaves 0 duplicate
pairs and the replacement path leaves 4 (the pure-create residual), which
is not strictly fewer than the reference. A failed quality gate blocks
adoption, so the path remains candidate-only, default-disabled, with no
canonical controller.

## 19.3 Systems Compared

`benchmarks/results/committed/action-replacement-adoption/systems.json`:

| System ID | Mode | Applied duplicate pairs |
|---|---|---:|
| `experienceos_hybrid_full_v2_reference` | disabled (reference) | 0 |
| `experienceos_transition_candidate_v1` | candidate | 0 |
| `experienceos_transition_adopted_v1` (append baseline) | adopted | 10 |
| `experienceos_action_replacement_shadow_v1` | shadow | 0 |
| `experienceos_action_replacement_candidate_v1` | candidate | 0 |
| `experienceos_action_replacement_verify_only_v1` | verify-only | 0 |
| `experienceos_action_replacement_adopted_v1` (infrastructure) | adopted | 4 |
| `experienceos_action_replacement_ablation_no_replacement_v1` | adopted | 10 |
| `experienceos_action_replacement_ablation_replace_all_v1` | (negative control) | not run |

The adopted-infrastructure system is a **benchmark/test** system, not
canonical runtime behavior. System execution mode, benchmark
infrastructure mode, and final governance classification are distinct;
only the last is `TRANSITION_PATH_CANDIDATE_ONLY`.

## 19.4 Gate 1

Frozen definition (`report-transition-verification/gate_summary.json`):
*"Semantic duplicate active-memory count decreases materially"*,
non-blocking, threshold **"strictly fewer than reference; 0 for the
strongest claim"**, reference **0**.

| Value | Count |
|---|---:|
| Reference | 0 |
| Committed append (adopted) | 10 |
| Replacement (overall) | **4** |
| Supersede-bearing class | 6 → **0** |
| Pure-create residual | 4 |

**Decision: FAIL.** 4 is not strictly fewer than the reference 0. The
supersede-bearing class is eliminated and reported separately, but the
frozen gate is defined on the overall count and is not split to hide the
residual. Material improvement is not a pass under this rule.

## 19.5 Gate 6

Frozen definition: *"Forget-directive creation false positives decrease"*,
non-blocking, threshold "strictly lower than reference and 0 for
adoption". Reference 0, adopted 0. Replacement is supersede-only and does
not affect forget-directive creation, so there is still no reduction to
demonstrate. **Decision: INCONCLUSIVE** (non-blocking; not rounded to
pass).

## 19.6 Full Twenty-Gate Table

The framework is unchanged (`gate_evaluation.json`). Replacement changes
only Gate 1's underlying value (10 → 4); its decision stays FAIL. Every
other gate's evidence is preserved under replacement (safety, scoped and
unrelated preservation, lineage, authorization, single mutation path, and
the stale-pair reduction 6 → 1 all hold). Tally: **18 pass / 1 fail
(Gate 1) / 1 inconclusive (Gate 6)** — identical to the committed
transition evaluation.

Blocking gates: **4, 5, 8, 9, 10, 11, 12, 19, 20**.

## 19.7 Nine Blocking Gates

All nine blocking gates **pass** under replacement; none is inconclusive.
Adoption is therefore not blocked by a safety gate — it is blocked by the
Gate 1 quality gate.

## 19.8 Additional Acceptance Conditions

All 22 action-replacement acceptance conditions **pass**
(`gate_evaluation.json`): unique occurrence match, exactly one suppression
per applied replacement, sequence inserted once, no unrelated/scoped/
extraction suppression, exact authorization with every bound-field
mismatch rejecting, missing-authorization rejection, fallback never
appending both, manager and engine authority, single mutation path,
complete diagnostics, digest binding, before-state reuse, lineage
preservation, deterministic artifacts, offline tests, and default
disabled.

## 19.9 Applied-State Results

Six replacements applied, all `ACTION_REPLACED`: the conflicting planner
create suppressed, the transition create present exactly once, the old
value superseded, lineage correct **6/6**, and **0** seeded memories
lost. Duplicate pairs 10 → 4; stale pairs 6 → 1; wrong targets 0; scoped
and unrelated losses 0.

## 19.10 Downstream Context

Replacement removes one duplicate active memory in each applied case, so
active-memory count does not increase and context-token use does not
regress; downstream selection is not made worse. Gates 13 and 14 remain
pass. No final-answer-quality improvement is claimed (the benchmark does
not measure it).

## 19.11 Latency

Replacement adds bounded, deterministic matcher + plan + authorization
work per supersede-bearing interaction. There is no frozen latency
threshold beyond Gate 15 ("acceptable for the demo"), which remains pass.
Timing is excluded from artifact digests per existing policy.

## 19.12 Supported Claims

- ExperienceOS can replace a uniquely matched conflicting planner create
  with a verified transition sequence.
- Governed replacement eliminated all measured supersede-bearing
  duplicate pairs (6 → 0).
- Overall duplicate pairs improved from 10 to 4.
- Four pure-create duplicate pairs remain.
- Replacement preserved unrelated and scoped memories in the measured
  corpus (0 lost) and lineage in all applied cases.
- Exact replacement authorization rejected every tested mismatch.
- `ExperienceManager` and `ExperienceEngine` remained authoritative;
  single mutation path preserved.
- The frozen transition benchmark was re-evaluated without changing its
  oracle, gates, or thresholds.
- ExperienceOS refused adoption because a frozen quality gate did not
  pass.

## 19.13 Unsupported Claims

Not claimed: all semantic duplicates solved; pure-create deduplication
solved; transition path adopted; production-grade replacement; all
updates or all forget directives solved; learned transition reasoning;
local-model reliability; official LongMemEval performance; final-answer
quality improvement; production authorization; production readiness; no
future memory defects.

## 19.14 Classification Rationale

Adoption requires Gate 1 to pass, every blocking gate to pass, and every
additional condition to pass. Blocking gates and additional conditions
all pass, but Gate 1 fails on its frozen overall definition. Therefore
the path is `TRANSITION_PATH_CANDIDATE_ONLY` — the implementation works
for its class and is safe, but a failed quality gate blocks adoption.

## 19.15 Runtime Default

Unchanged: transition integration remains **disabled** by default, the
adopted infrastructure remains benchmark/test-only, and no transition
controller is canonical. No runtime default was modified in this
evaluation.

## 19.16 Downstream Visibility Boundary (next step)

The next step exposes this measured replacement and gate evidence in the
dashboard — transition mode, replacement decision, original/matched/
suppressed/inserted/projected/applied lists, authorization and manager/
engine results, duplicate and stale counts, lineage, Gate 1, Gate 6, all
twenty gates, the pure-create residuals, planner fallback, and old-event
compatibility — **without changing the classification**.
