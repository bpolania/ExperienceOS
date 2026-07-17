# Qwen extraction adoption and update-intelligence closure

Canonical decision record for two related pieces of work: adopting Qwen
extraction for the hackathon demo, and implementing and evaluating a
Qwen update-intelligence experiment. Detailed mechanics and metrics live
in the referenced documents and evidence; this report is the single
source of the decisions and does not duplicate the large metric tables.

## Decisions

- **Qwen extraction is adopted for the ExperienceOS hackathon demo**,
  and only there: the demo composition layer selects
  `QwenExtractionController` whenever a credentialed Qwen Cloud provider
  is configured (`demo.support.build_canonical_extraction_config`). The
  SDK default outside the demo is unchanged — `extraction=None` leaves
  grounded extraction disabled — so this is not a global change to every
  construction path. See [extraction_integration.md](extraction_integration.md).
- **Deterministic extraction remains available explicitly** as the
  alternate implementation for offline use, tests, and comparison
  benchmarks (selected when Qwen Cloud is not configured, and directly
  constructible).
- **Deterministic governance is unchanged.** The whole `experienceos/`
  core package is byte-for-byte identical to the published baseline
  `6f893f9`; the frozen benchmark corpus and annotations are unchanged.
  Qwen proposes candidates only — the unchanged `GroundedCandidateValidator`,
  lifecycle and transition validation, authorization, lineage,
  persistence, mutation authority, context builder, canonical action
  replacement, and deduplicated transition application remain
  authoritative. No retry or fallback was added; a failed Qwen call is an
  explicit non-candidate result, never a deterministic substitution.
- **Qwen update intelligence was implemented and evaluated.**
  `QwenUpdateController` (`experiments/qwen_update.py`) classifies a
  durable candidate against the active memories into NEW / UPDATE /
  COEXIST / DUPLICATE / IGNORE with one temperature-0 inference, strict
  structured output, no retries, and no fallback. It holds no mutation
  authority and is not wired into any runtime path. See
  [qwen_update_intelligence.md](qwen_update_intelligence.md).
- **Recommendation: KEEP_QWEN_UPDATE_EXPERIMENTAL.** Qwen update
  intelligence remains experimental and is not canonical. The
  deterministic update path stays authoritative.

## Benchmark result and its limitation

On the frozen update corpus (48 classification-applicable cases), the
deterministic controller scores 48/48 overall and Qwen scores 32/48
(UPDATE recall 16/17, 0 wrong targets, 6 false UPDATE, COEXIST recall
0/3, DUPLICATE recall 4/5, 0 provider failures, 0 invalid outputs, 0
unsafe proposals, 0 proposals reaching mutation authority). Full metrics:
`experiments/results/qwen_update/{results.json,report.md}`.

Two conclusions follow, and both matter:

1. Qwen did **not** outperform deterministic update intelligence on this
   benchmark and should not be adopted on this evidence.
2. This benchmark **cannot** establish that deterministic rules
   generalize better than Qwen on unseen real-world conversations. The
   corpus is small and was built around the deterministic transition
   rules — it is well suited to deterministic regression testing, not to
   an independent comparison of reasoning approaches. The deterministic
   ceiling (48/48) is therefore expected and does not measure Qwen's
   real-world value.

## Status and future work

No further architecture work is required to close this work; the
implementation is complete and verified. An independently authored,
held-out corpus that is not tuned to either implementation would be the
right instrument to re-evaluate Qwen update intelligence — this is
**optional future work after the hackathon**, not a blocker.

The published extraction controller identifier still contains `shadow`
(`grounded_qwen_shadow-1`); it is frozen history referenced by committed
evidence and is intentionally left unchanged.
