# Transition verification benchmark

Adoption classification: **TRANSITION_PATH_CANDIDATE_ONLY**

every blocking safety gate passes, but one or more quality gates fail: gate 1 (Semantic duplicate active-memory count decreases materially). Candidate mode remains non-mutating, so the path may keep running for diagnostics and candidate translation without affecting canonical state.

This classification does not change the runtime default, which remains `disabled`. No controller is canonical.

## Systems

Every system runs against its own isolated in-memory store seeded from the same frozen before-state, through the real `ExperienceManager` and `ExperienceEngine`. The oracle scores output; it never generates it.

## Headline (historical-scored, 28 cases)

- reference: 6 stale active pairs, 0 duplicate pairs
- adopted (isolated): 1 stale, 10 duplicate pairs

Gates: 18 passed, 1 failed, 1 inconclusive, 0 unavailable.

Latency is measured and recorded beside the deterministic content; it is excluded from content digests.

Regenerate: `./scripts/run_benchmarks.sh transition-benchmark`
Verify: `./scripts/run_benchmarks.sh transition-benchmark-verify`
