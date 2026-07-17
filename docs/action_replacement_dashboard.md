# Governed Action Replacement — Dashboard Visibility

Companion to `docs/action_replacement.md`, `..._validation.md`, and
`..._adoption_report.md`. It documents the read-only dashboard surface
that makes the replacement lifecycle and the adoption evidence visible.
The dashboard changes no classification, no runtime default, and no
benchmark result; it only displays committed evidence and live
diagnostic events.

## 26.1 Purpose

The "Action replacement" section of `demo/app.py` renders, read-only:
why a replacement occurred or was rejected, what changed in the action
list, the measured duplicate reduction, the twenty adoption gates, and
why the transition path remains candidate-only. Every number comes from
`demo/transition_diagnostics.py` — the single read-only source — which
reads committed artifacts and never recomputes a metric, re-derives a
gate, or applies a replacement.

## 26.2 Replacement Lifecycle

The authority chain is shown explicitly:

```
controller proposes → verifier verifies → matcher matches →
plan builder projects → authorization permits → manager admits →
engine applies (sole durable mutation boundary)
```

The matcher, plan builder, and authorization mutate nothing; a failed
replacement falls back to the canonical planner list — never
append-both, never a partial replacement. The live replacement record
(`replacement_record`) surfaces the bounded governance fields the engine
already publishes on the transition event: attempted, applied, matcher
decision, plan status, canonical effect, authorization status and any
mismatched fields, fallback used and reason, suppressed occurrence index,
and shortened digests. No token, secret, or path is exposed.

## 26.3 Original, Projected, and Applied Lists

The dashboard distinguishes what the planner intended, what the
replacement *would* project (shadow/candidate, non-mutating), and what
actually reached engine application. A projection is never rendered as
applied state, and adopted-infrastructure benchmark execution is never
rendered as canonical runtime adoption.

## 26.4 Authorization and Fallback

Authorization is shown as an exact governance check bound to one plan:
accepted or rejected, with the mismatched field names on rejection. The
rejection paths (missing authorization, mismatch, no/ambiguous match,
lifecycle rejection, pure-create no-op) each render the planner-only
fallback — the planner action retained, the transition sequence not
appended, no partial replacement.

## 26.5 Benchmark Evidence

The comparison panel shows reference **0**, append **10**, governed
replacement **4**; supersede-bearing **6 → 0**; pure-create residual
**4**; stale pairs **6 → 1**; six replacements applied; lineage correct
6/6; and zero scoped/unrelated losses. A genuine historical case
(`updates_001`) is shown before/after from committed evidence — the old
append path is labeled historical benchmark behavior and is never
executed to render it.

## 26.6 Gate Evidence

All twenty frozen gates are rendered with their blocking flag and their
replacement-enabled decision: **Gate 1 FAIL**, **Gate 6 INCONCLUSIVE**,
and the nine blocking gates (4, 5, 8, 9, 10, 11, 12, 19, 20) **PASS**.
The tally is **18 / 1 / 1**. No failed or inconclusive gate is hidden or
relabeled. The supersede-bearing 6 → 0 result is shown as supplementary
evidence under Gate 1, but the overall Gate 1 result remains FAIL. The
twenty-two additional acceptance conditions are shown separately (22/22
PASS), never merged into the frozen gate framework.

## 26.7 Candidate-Only Classification

The classification `TRANSITION_PATH_CANDIDATE_ONLY` is shown prominently,
with runtime default **disabled**, canonical controller **none**, and
adopted infrastructure marked benchmark/test-only. The evidence-based
reason is visible: replacement solved the measured supersede-bearing
class, four pure-create duplicates remain, the frozen overall duplicate
gate did not pass, so ExperienceOS refused canonical adoption.

## 26.8 Pure-Create Residuals

The four residual cases (`creation_001`, `creation_002`, `creation_003`,
`updates_006`) are shown with their append and replacement duplicate
counts and the reason replacement does not apply (no supersede-bearing
transition). The dashboard states plainly that canonical action
replacement is not generic create deduplication and that this phase did
not solve them; no control attempts to.

## 26.9 Safety

Rendering is read-only: initial render constructs no provider, calls no
model, loads no local model, accesses no network, regenerates no
benchmark, and mutates no memory or committed file. Committed artifacts
are read through a cached loader; a missing or malformed artifact renders
a neutral unavailable state rather than crashing. Old events without
replacement data render as unavailable and are never migrated. These
properties are asserted in `tests/test_dashboard_action_replacement.py`.

## 26.10 Next-Step Boundary

The next step aligns documentation with the measured results, freezes the
technical work, publishes the commit chain after final validation, and
records the final result — preserving the candidate-only classification,
the disabled default, and no canonical controller.
