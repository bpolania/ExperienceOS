# Transition Demo Runbook

> **Current status (canonical activation).** Since this runbook was
> written the canonical lifecycle path has been **activated**: adopted is
> the default transition mode in the demo, it is offered in the dashboard
> selector, and obsolete memories are superseded/forgotten by the bounded
> runtime authority + governed replacement. The script below is preserved
> as the original offline candidate-only walkthrough; for the current
> lifecycle behavior and a judge walkthrough see
> [canonical_lifecycle_transitions.md](canonical_lifecycle_transitions.md),
> [bounded_runtime_transition_authority.md](bounded_runtime_transition_authority.md),
> and the "Judge walkthrough" section of the main `README.md`.

A presenter script for demonstrating ExperienceOS transition
intelligence — how the system decides that a new statement *replaces*,
*coexists with*, or *removes* an existing memory.

The historical walkthrough below runs **offline**: no Qwen credentials, no
network, no model download. Budget 8–10 minutes. It documents the
pre-activation state in which the transition path proposed correctly but
was classified candidate-only pending the governed-replacement fix that
Phase 20 later delivered.

## 1. Preparation

```bash
pip install -e ".[demo]"
./scripts/run_benchmarks.sh validate-transition-verification
PYTHONPATH=. streamlit run demo/app.py
```

The validation step is worth running in front of the audience: it
re-verifies all three committed artifact families against their digests
in a couple of seconds, which is the claim that every number shown later
comes from committed evidence rather than the running process.

Confirm before you start:

- provider is **Mock** (the default);
- the sidebar **Transition intelligence** selector reads **Disabled
  (default)**;
- the status header reads **Candidate only** and **Canonical
  controller: None**.

If those three are right, the demo is in its shipped default state.

## 2. The demonstration (12 steps)

**Steps 1–3 — the default is off.**

1. Point at the sidebar: transition integration is **Disabled**. The
   dashboard is showing normal ExperienceOS runtime, not an experiment.
   Nothing in the transition stack runs unless someone opts in.
2. Click **Run experience lifecycle demo**. The ten-turn lifecycle runs
   exactly as it always has — remember, recall, update, forget,
   compress. The transition work changed no default behavior.
3. Note the status header: **18 passed, 1 failed, 1 inconclusive**, and
   **9 blocking gates, all passed**. Read the failure out loud now
   rather than letting someone find it later.

**Steps 4–7 — the intelligence, in shadow.**

4. Switch **Transition intelligence** to **Shadow**. This is
   non-mutating by construction — it observes and proposes, and the
   engine ignores it.
5. Send: *"Actually, my home airport is now SJC."* Open the
   **transition trace**. Walk the 13 stages: Source → Routing →
   Controller → Identity → Target resolution → Proposal →
   Verification → Canonical-effect eligibility → Authorization →
   Translation → Admission → Application → Resulting state. Each stage
   carries **PASS**, **REJECTED**, **NOT RUN**, or **INFO** as text.
6. Stop on **Identity**. The controller did not match on similarity — it
   projected *subject: home airport*, *attribute: value*, *scope:
   general*, and found an existing memory with the same target key and a
   different value. That is what licenses supersession. A float never
   decides this.
7. Stop on **Authorization** and **Application**: both read **NOT RUN**.
   The proposal was correct and was still not applied, because shadow
   mode cannot reach durable state. `NOT RUN` never means "passed".

**Steps 8–10 — the safety boundaries.**

8. Send: *"Could you remove my airport preference?"* The controller
   classifies this as a **question**, not a directive. Nothing is
   proposed for removal. A system that deletes memory when asked whether
   it could delete memory is not safe, and this is where most naive
   implementations fail.
9. Send: *"I prefer aisle seats for work trips."* against the existing
   unscoped seat preference. The result is **scoped coexistence**, not
   supersession — a narrower scope does not overwrite a general one. The
   benchmark records 0 scoped memories lost across all cases.
10. Switch to **Candidate** mode and re-send an ambiguous removal (a
    directive with more than one plausible target). The controller
    **abstains**: ambiguous targets fail closed rather than guess. 0
    ambiguous cases were ever guessed into a mutation.

**Steps 11–12 — the finding, and the refusal.**

11. Open **Benchmark evidence → the central finding**. Three columns:
    reference (applied), candidate projection, isolated applied. The
    projection is cleaner than the reference — stale pairs 6 → 1, and
    11/11 targets resolved with 0 wrong where the reference resolves
    none. But under isolated adoption, duplicate pairs go **0 → 10**:
    the integration *adds* its replacement create alongside the
    canonical planner's create, so both survive.
12. Open the **gate table**. Gate 1 fails on exactly that. Every one of
    the 9 blocking safety gates passes — and the path is still
    classified **candidate-only**, because passing every safety gate is
    not the same as earning adoption. Close here: ExperienceOS
    benchmarked its own intelligence, found the proposals sound and the
    applied outcome wrong, and declined to adopt it. The remaining fix
    is integration semantics — replace rather than add — and it is
    documented, not hidden.

## 3. Safety notes

- **Adopted mode is not offered in the dashboard**, and this is not an
  oversight. Adopted requires an authorization bound to 20 exact fields
  of one specific verified proposal; no dropdown can supply that.
  `build_transition_config("adopted")` raises rather than silently
  degrading.
- All four selectable modes — Disabled, Shadow, Candidate, Verify-only —
  are **non-mutating**. Mode selection affects only the current
  dashboard session; reset returns to the shipped default.
- The isolated applied numbers come from benchmark runs through the real
  manager and engine. They are **never** presented as normal runtime
  state, and a projection never appears under an "Applied" heading.
- The dashboard **reads** committed evidence. It recomputes no metric
  and re-derives no classification. If a display value ever disagrees
  with a committed artifact, the artifact is right and the display is
  the bug.
- Benchmark partitions stay labeled: 28 historical scored cases, 27
  development fixtures. Several safety categories — negative forget,
  hypothetical forget, broad forget, ambiguous targets — exist **only**
  as fixtures, and the dashboard names them so engineering evidence is
  never mistaken for historical production evidence.

## 4. Recovery

| Symptom | Recovery |
|---|---|
| Dashboard will not start | `pip install -e ".[demo]"`, then relaunch with `PYTHONPATH=.` |
| Qwen warning appears | Switch the provider back to **Mock** in the sidebar; no credentials are needed for any step here |
| Benchmark panels read "artifacts unavailable" | Run `./scripts/run_benchmarks.sh validate-transition-verification`; the panel states the absence rather than showing zeros |
| Numbers look stale after editing an artifact | The bundle is cached per process; call `reload_artifacts()` or restart Streamlit |
| Transition trace is empty | Integration is **Disabled** — that is the default and the panel says so; switch to Shadow to populate it |
| Optional systems show "Unavailable" | Correct and intended: the learned and live-Qwen systems produced no metrics, so none are shown |
| A step misbehaves live | Fall back to **Benchmark evidence** (steps 11–12). It is committed and offline, and it carries the whole argument on its own |

## 5. What not to claim

Read from `claims.json`, not from enthusiasm. The evidence does **not**
support: open-domain transition intelligence, production-grade update or
forget understanding, autonomous memory management, learned transition
reasoning, multilingual generalization, canonical adoption, improved
answer quality, broad forget support, complete duplicate elimination, or
complete target resolution.

The corpus is small (28 scored cases), semantic-duplicate evidence is a
single scored case, forget evidence is 4 exact-target directives, and
the controller vocabulary shares domains with the corpus — so the
accuracy shown does not generalize beyond them. Say so before a judge
asks.
