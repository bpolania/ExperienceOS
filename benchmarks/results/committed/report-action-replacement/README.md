# Governed Action Replacement — Applied-State Verification

Measured by running the frozen historical transition corpus through the real governed pipeline (planner, manager, verifier, matcher, plan builder, authorization, engine). No frozen evidence is modified and no adoption decision is made.

- Cases: **28** (7 supersede-bearing, 6 pure-create, 15 no-transition)
- Semantic duplicate pairs: **10 (append) → 4 (replacement)**, a reduction of **6**
- Supersede-bearing duplicates: **6 → 0**
- Pure-create residual duplicates (out of scope): **4**
- Replacements applied: 6; lineage correct 6/6; seeded memories lost 0; transition create present exactly once 6/6

Gate 1 (semantic duplicate active-memory count) is reported as measured for the supersede-bearing class only; the pure-create residual is a separate, out-of-scope class and is not folded in. This document makes no adoption decision.

Regenerate: `./scripts/run_benchmarks.sh run-action-replacement`  
Verify: `./scripts/run_benchmarks.sh validate-action-replacement`
