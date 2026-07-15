# Transition Dashboard

Makes transition intelligence visible: what the user said, what
ExperienceOS believed it meant, which prior experience it considered,
what it proposed, whether that proposal survived verification, and
whether anything actually changed.

The dashboard **reads evidence; it does not produce it**. It recomputes
no metric, re-derives no adoption classification, and reinterprets no
gate. If a display value ever disagrees with a committed artifact, the
artifact is right and the display is the bug.

## 1. What the dashboard says, honestly

Loaded from committed evidence, not asserted here:

| | |
|---|---|
| Runtime default | **Disabled** |
| Transition path | **Candidate only** |
| Canonical controller | **None** |
| Adoption gates | **18 passed, 1 failed, 1 inconclusive** |
| Latest applied controller action | **No** (unless an isolated demonstration says otherwise) |

Candidate-only is rendered with caution styling, never success styling,
because Gate 1 fails. "Adopted" never appears without "isolated
infrastructure".

## 2. Information architecture

Transition visibility lives inside the existing dashboard — there is no
second app:

- **Persistent status header** — default, configured mode, effective
  mode, classification, canonical controller, gate summary, latest
  applied status.
- **Transition trace (live)** — the pipeline for the most recent turn.
- **Memory lifecycle (live)** — active, superseded, forgotten, duplicate,
  stale, scoped, plus lineage.
- **Benchmark evidence** — the central finding, all twenty gates, system
  comparison, lifecycle chain, context budget, ablations, safety, claims
  and limitations, and a diagnostics/case explorer.

## 3. The live transition trace

Thirteen ordered stages: Source → Routing → Controller → Identity →
Target resolution → Proposal → Verification → Canonical-effect
eligibility → Authorization → Translation → Manager/engine admission →
Application → Resulting lifecycle state.

Each stage carries an explicit status: **PASS**, **REJECTED**, **NOT
RUN**, or **INFO** — as text, never colour alone. `NOT RUN` means the
stage did not execute; it never means the stage passed.

The trace keeps four things apart that are easy to blur:

- a controller **proposal** is not a verifier acceptance;
- a **verified** proposal is not authorized;
- an **authorized** proposal is not applied;
- only the engine's existing path sets `action_applied`.

## 4. Projected versus applied

Three states the dashboard never conflates:

| State | Meaning |
|---|---|
| **Candidate projection** | what a verified proposal *would* do |
| **Isolated applied** | what an authorized benchmark action really did, through the real manager and engine |
| **Normal runtime** | what happens by default — transition integration disabled |

A projection never appears under an "Applied" heading, and an isolated
benchmark result never appears as normal runtime state.

## 5. The central finding

The dashboard shows the trade-off rather than the headline:

| Metric | Reference (applied) | Candidate projection | Isolated applied |
|---|---:|---:|---:|
| Stale active pairs | 6 | 0 | **1** |
| Duplicate pairs | 0 | 0 | **10** |
| Targets deactivated | 5/11 | n/a (non-mutating) | 10/11 |
| Scoped memories lost | 0 | 0 | 0 |
| Unrelated memories lost | 0 | 0 | 0 |

The proposal intelligence is correct and the projection is cleaner. But
applying it **adds** the transition's replacement create alongside the
canonical planner's create, so both persist and form a duplicate. Gate 1
fails; the path stays candidate-only. The fix is action-replacement
integration semantics — **not done here, and not a dashboard
reinterpretation**.

## 6. Adoption gates

All twenty render in contract order with number, name, role, threshold or
decision procedure, reference, candidate, delta, decision, blocking
status, justification, and evidence paths. Anything not passing is
surfaced above the table, not buried in it:

- **Gate 1 — Fail.** Duplicate pairs 0 → 10.
- **Gate 6 — Inconclusive.** Both systems already create 0 memories from
  forget directives, so no reduction can be demonstrated. Absence of
  regression is not measured improvement, and the dashboard does not
  round it up to a pass.

Blocking gates are read from the artifact, never hardcoded: the committed
evidence marks **9** blocking gates (4, 5, 8, 9, 10, 11, 12, 19, 20), and
all pass.

## 7. Historical versus development separation

Every benchmark view labels its partition: historical evidence (28
cases), development fixtures (27 cases), unresolved (diagnostic only),
excluded. They are never merged into one headline.

Fixture-only categories are named explicitly — negative forget, forget
and inspection questions, hypothetical forget, broad forget, ambiguous
forget targets, switched-from-to, no-longer-now, overlapping scope — so
engineering evidence never reads as historical production evidence.

## 8. Unavailable systems

The optional learned and live-Qwen systems render as **Unavailable** with
their committed reason and **no metrics**. Showing them as zero-scoring
systems would invent a result they never produced.

## 9. Safe controls

The sidebar offers four modes: **Disabled (default)**, Shadow, Candidate,
Verify-only. All are non-mutating.

**Adopted is not offered.** It requires an authorization bound to an
exact verified proposal, which no dropdown can supply;
`build_transition_config("adopted")` raises. Selecting a mode affects
only the current dashboard session, and reset returns to the existing
default.

## 10. Empty and partial states

Truthful, never zero-filled:

- "No transition analysis ran because integration is disabled."
- "The controller abstained; no lifecycle proposal was produced."
- "Verification was not invoked."
- "Committed transition benchmark artifacts are unavailable. No metrics
  are shown and none are inferred."
- Unavailable optional systems get a reason, not a score.

## 11. Event compatibility

Transition annotations are optional. Old events without them render fine;
a partial annotation renders with `Unavailable` fields; a malformed one
fails boundedly with a reason and no fabricated values; unknown future
fields are ignored. The annotation version is surfaced in diagnostics.

## 12. Artifact sources

One read-only module — `demo/transition_diagnostics.py` — is the single
source for every benchmark number the UI shows, so two panels cannot
drift apart. It reads:

- `benchmarks/results/committed/report-transition-verification/` —
  report data, headline metrics, gate summary, claims, limitations;
- `benchmarks/results/committed/transition-verification/` — systems,
  per-case records;
- `benchmarks/results/committed/transition-ablation/` — ablations;
- `docs/transition_verification_report.md` — the human-readable report.

Reads are cached per process (the artifacts are committed files);
`reload_artifacts()` clears the cache. Artifact loading constructs no
provider, calls no model, touches no network, and never runs the
benchmark.

## 13. Privacy

Bounded source statements, bounded diagnostics, bounded candidate lists.
No authorization payloads, no secrets, no model prompts, no filesystem
paths beyond repository-relative artifact paths, and no unrelated memory
text.

## 14. Testing

`tests/test_dashboard_transition_apptest.py` covers default state, the
status header, all four modes, the pipeline, identity and target views,
gates, projected-versus-applied separation, ablations, claims and
limitations, the explorers, artifact failure, annotation compatibility,
and non-mutation. The prior dashboard AppTests still pass unchanged.

## 15. Known limitations

- The benchmark view is a read-only view of committed evidence.
- The transition path is candidate-only; Gate 1 failed; Gate 6 is
  inconclusive.
- Small historical corpus (28 cases), 1 historical semantic-duplicate
  case, 4 historical forget cases.
- Several safety categories are fixture-only.
- The controller vocabulary is bounded and shares domains with the
  corpus.
- No learned controller; adopted evidence is isolated only.
- The dashboard does **not** fix the duplicate-producing integration
  behavior, and does not offer a canonical-adoption control.
