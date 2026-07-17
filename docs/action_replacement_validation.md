# Governed Action Replacement — Applied-State Validation

Companion to `docs/action_replacement.md`. It records how the governed
replacement path was verified against the frozen historical transition
corpus, and the measured result. It changes no runtime, no
authorization, and no frozen evidence, and it makes **no adoption
decision**.

## Benchmark Procedure

`benchmarks/action_replacement/` runs every historical scored case
(`benchmarks/annotations/transition-verification/historical-scored.jsonl`,
consumed read-only) twice:

- **Run A — append**: the existing add-not-replace behavior, via the real
  adopted stack (`transition_benchmark.systems.run_case`).
- **Run B — governed replacement**: the real pipeline (planner, manager,
  verifier, matcher, plan builder, authorization, engine). The
  replacement authorization is generated deterministically from the same
  immutable inputs the engine uses, exactly as the runtime integration
  requires; no mock planner output is used.

Every measurement is behavioral and deterministic: runtime UUIDs are
mapped to stable first-seen labels and no wall-clock timing enters any
recorded value. Artifacts:
`benchmarks/results/committed/action-replacement/` (per-case results,
summary, manifest) and `.../report-action-replacement/` (headline
report, README, manifest). Regenerate with
`./scripts/run_benchmarks.sh run-action-replacement`; verify with
`./scripts/run_benchmarks.sh validate-action-replacement`.

## Historical Comparison (measured)

| Metric | Append (Run A) | Replacement (Run B) |
|---|---:|---:|
| Semantic duplicate pairs (all 28 cases) | **10** | **4** |
| Supersede-bearing duplicates | **6** | **0** |
| Pure-create residual duplicates | 4 | 4 |

Reduction: **6** duplicate pairs, entirely within the supersede-bearing
class. Six replacements were applied; all reported `ACTION_REPLACED`,
suppressed exactly the conflicting planner create, inserted the
transition create exactly once, retired the old value, and preserved
lineage (`superseded_by` → the active replacement). No applied
replacement lost a seeded memory.

## Measured Improvement

For the supersede-bearing class the applied duplicate count goes
**6 → 0**. This is reported as measured; it is **not** a Gate 1
determination and no adoption is decided here. The overall corpus figure
is **10 → 4** because the pure-create residual is unchanged.

## Remaining Residuals

Four residual duplicates remain, all in the **pure-create** class
(`creation_001`, `creation_002`, `creation_003`, `updates_006`): the
planner and the transition each create the same new memory with no
supersede, so no replacement applies. This class is explicitly out of
scope; no generic semantic deduplication is introduced.

One supersede-bearing case (`updates_008`) applies no replacement: the
planner emits no action for it and its transition authorization is denied
by the coordinator, so it contributes 0 duplicates in both runs (0 → 0)
and no replacement is attempted. It is reported honestly rather than
folded into the applied set.

## Preservation Guarantees

Verified for every applied replacement: the conflicting planner create is
absent from the final action list; the transition create appears exactly
once; the supersede is applied once; lineage is intact; unrelated and
scoped-compatible seeded memories remain active; and extraction actions
are never suppressed. Forced failure paths (missing/mismatched
authorization across all bound fields, manager rejection, atomic
sequence rejection, plan inconsistency) each fall back to the canonical
planner list — never append-both, never a partial replacement — and are
covered in `tests/test_action_replacement_integration.py`.

## Unsupported Cases

- pure-create redundant duplicates (measured residual: 4);
- extraction replacement (extraction is never a replacement candidate);
- generic semantic deduplication (not introduced);
- canonical default adoption (default stays disabled; no adoption
  decision here).

## Applied-State Verification Boundary (next step)

The next step evaluates whether this measured evidence is sufficient to
authorize transition-path adoption and whether Gate 1 can be considered
satisfied for the supersede-bearing class — without changing any frozen
benchmark evidence.
