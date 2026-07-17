# Qwen update intelligence (experimental)

`QwenUpdateController` (`experiments/qwen_update.py`) classifies one
durable candidate memory against the user's already-active memories into
exactly one of five relationships:

- **NEW** — durable, not already represented, replaces nothing
- **UPDATE** — changes/corrects/reverses/supersedes exactly one existing
  memory (carries that memory's real id as the target)
- **COEXIST** — related to an existing memory but both stay valid
- **DUPLICATE** — semantically equivalent to an active memory
- **IGNORE** — should produce no durable memory

It is **experimental and not canonical**. The deterministic
`experienceos_transition_rules_v1` controller remains the authoritative
update path. Qwen **classifies and proposes only**: it holds no store,
engine, manager, or mutation authority, never applies or authorizes a
transition, never creates lineage or writes persistence, and never
selects an action after a deterministic rejection. Every downstream gate
— grounded validation, transition validation, lifecycle authority,
persistence — is unchanged.

## Inference contract

One temperature-0 Qwen inference per candidate, bounded timeout, strict
JSON only (`{"classification": ..., "target_memory_id": ...}`), no
reasoning or chain of thought requested. No retries, no fallback, no
repair loop. A provider failure (unavailable / error / timeout) and an
invalid structured output are recorded as distinct bounded outcomes; a
failure never silently invokes the deterministic controller. The strict
parser rejects malformed JSON, extra keys/prose, unknown classifications,
missing UPDATE targets, targets on non-UPDATE classes, and fabricated
ids (any id not in the supplied active set). Diagnostics carry bounded
labels only — never source text, candidate text, active-memory text,
secrets, or a provider exception message.

## Where it is injected

Only in the experiment layer, exactly like the Qwen extraction
controller, so the core `experienceos/` package stays provider-neutral
and both no-Qwen-core-coupling invariants keep passing. The comparison
harness (`experiments/qwen_update_benchmark.py`) selects between the
existing `DeterministicUpdateController` and `QwenUpdateController` over
the same frozen cases. It is not wired into the runtime demo path and is
not canonical.

## Comparison benchmark

Reuses the existing frozen update corpus and its committed transition
annotations (`transition_verification_frozen`) — no new benchmark
framework, no annotation changes. Both implementations are scored in one
shared five-class space derived from the committed annotations, over
exactly the 48 classification-applicable records the deterministic
update benchmark scores (forget-boundary and unscored records excluded
identically). Run it live (temperature-0 provider, credentials in the
environment):

```python
from experienceos.providers.qwen_cloud import QwenCloudProvider
from experiments.qwen_update_benchmark import run_and_write
run_and_write(QwenCloudProvider(temperature=0.0, timeout=8.0))
```

Evidence is written to `experiments/results/qwen_update/`
(`results.json` — ids and metrics only, no source text; `report.md` —
the human-readable comparison). The existing Qwen extraction evidence
under `experiments/results/qwen_extraction_shadow/` is not touched.

## Recommendation

**KEEP_QWEN_UPDATE_EXPERIMENTAL.** On the frozen corpus (48 cases) the
deterministic controller scores 48/48; Qwen scores 32/48. Qwen improves
none of update recall, coexistence detection, or duplicate recognition
here, and over-proposes on non-durable messages (6 false UPDATE, COEXIST
recall 0/3, IGNORE recall 6/17). It is, however, safe where it commits:
0 wrong targets on its 16 correct UPDATEs, 0 fabricated ids, 0 invalid
outputs, 0 provider failures, and structurally 0 proposals reaching
mutation authority. The corpus is small and was tuned to the
deterministic rules, so it cannot demonstrate Qwen improvement; this
result argues for keeping Qwen update intelligence experimental, not
adopting it.
