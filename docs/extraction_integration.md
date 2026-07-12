# Grounded Extraction Integration

**Status: implemented and verified against the live repository.**

This document governs how the grounded-extraction controllers become
observable — and, under explicit authorization, effective — inside the
execution pipeline. It defines one bounded seam with four effect modes
(`disabled`, `shadow`, `candidate`, `adopted`) that never creates a
second memory-mutation path. Where this document and a controller's own
claims disagree, the boundaries here win: the coordinator re-validates
every proposal and the engine remains the sole mutation authority.

## 1. Purpose and scope

The deterministic and learned grounded-extraction controllers each
turn one approved source excerpt into at most one proposed durable
memory candidate. On their own they are inert — they propose, they do
not persist. This seam connects them to `ExperienceEngine.run_interaction`
so that:

- their proposals can be observed against real traffic (`shadow`),
- their proposals can be lifecycle-evaluated without mutation
  (`candidate`), and
- an explicitly authorized controller's proposals can affect canonical
  memory through the existing application path (`adopted`),

all without introducing any new way to write durable state.

Out of scope: retrieval, ranking, compression, the model call, and any
change to canonical planning. Canonical behavior with the default
(disabled) configuration is byte-identical to the pre-integration
engine.

## 2. Authority boundaries (unchanged)

- `ExperienceEngine` is the **sole durable-mutation boundary**. Every
  write still flows through `_apply_memory_actions` over one
  `valid_actions` list.
- `ExperienceManager` remains **lifecycle policy authority**. The
  coordinator never supersedes, forgets, or re-targets memory.
- `GroundedCandidateValidator` remains the **grounding authority**. The
  coordinator calls it again at the integration boundary rather than
  trusting a controller's self-report.
- The coordinator holds **no store, engine, manager, bus, credentials,
  model path, or mutation method**. It returns a bounded decision; the
  engine decides what, if anything, that decision means.

## 3. The four effect modes

| Mode | Controller runs | Proposal translated | Lifecycle evaluated | Canonical effect |
| --- | --- | --- | --- | --- |
| `disabled` (default) | no | no | no | none — identical to baseline |
| `shadow` | yes | no | no | none — observe only |
| `candidate` | yes | yes | yes, non-mutating | none |
| `adopted` | yes | yes | yes, real | only if authorized **and** admissible |

`disabled` is the default and constructs no controller at all. Learned
extraction begins shadow-only. No controller is ever adopted by
accumulated evidence; adoption requires an explicit configuration
authorization (section 8) and still passes every downstream check.

## 4. Controller selection

`controller_type` selects `deterministic` (default) or `learned` — a
capability word, never a provider name. The deterministic controller is
dependency-free and is lazily constructed on demand
(`DeterministicGroundedExtractionController(validator=...)`) when no
instance is supplied. The learned controller must be supplied
explicitly; requesting `learned` without an instance is a configuration
error, not a silent fallback.

## 5. Coordinator contract

`ExtractionIntegrationCoordinator.evaluate(evidence, source_id,
provenance)` returns an `IntegrationOutcome`:

- `effect_mode`, `controller_type` — echoed configuration.
- `proposal` — the controller's raw proposal (or `None` on error).
- `translated_action` — a `MemoryAction` **only** in `candidate` and
  `adopted` modes, and only for a fully validated proposal; always
  `None` in `shadow`.
- `authorized` — true only for an authorized adopted proposal.
- `status` — one value from the bounded status vocabulary (section 9).
- `final_proposal_source` — which stage produced the final text (e.g.
  `controller`, `deterministic_fallback`), used for authorization.
- `diagnostics` — a bounded, JSON-serializable event payload.

The coordinator never applies the action. In `adopted` mode it only
marks the outcome authorized; the engine performs the merge.

## 6. Defense-in-depth revalidation

A controller claiming its candidate is grounded is not sufficient.
Before translating, the coordinator independently re-runs
`GroundedCandidateValidator.validate` against an `ApprovedSource` built
from the same evidence, and additionally requires: the candidate is a
`ProposedMemoryCandidate`, its kind is one of
`{preference, fact, instruction}`, and it carries **exactly one**
evidence span. Any failure yields `integration_rejected` or
`grounding_rejected` and no action — regardless of what the controller
recommended.

## 7. Translation shape

A validated proposal becomes a `CREATE` `MemoryAction` only:

- `action=CREATE`, `kind`, `text` from the candidate,
- `reason="grounded_extraction"`,
- `metadata["extraction_origin"]` recording `controller_id`,
  `final_proposal_source`, `source_id`, `source_provenance`,
  `grounding_code`, `confidence`, and the evidence offsets.

It carries **no** memory id, lifecycle status, supersede/forget target,
or `replaces` link. Those remain the kernel's to decide. A controller
can therefore never express a supersede or a forget through this seam.

## 8. Adoption authorization

`AdoptionAuthorization` is frozen configuration evidence that a
specific `(controller_id, controller_version, final_proposal_source)`
is permitted to affect canonical state in adopted mode. It is **not**
lifecycle authority: it cannot bypass grounding, manager validation, or
the engine's admission rules, and carries no store or credentials.

Adopted mode fails closed:

- no authorizations at all → `authorization_missing`,
- authorizations present but none match the controller and final
  source → `authorization_mismatch` (e.g. a deterministic fallback text
  under a learned-only authorization).

Only `authorized` status makes an action eligible for merge.

## 9. Status vocabulary

`no_candidate`, `grounding_rejected`, `integration_rejected`,
`authorization_missing`, `authorization_mismatch`, `proposed`
(valid; shadow/candidate, never applied), `authorized` (valid +
authorized adopted merge), `controller_error` (a controller raised;
contained). The set is closed and appears verbatim in diagnostics as
`integration_status`.

## 10. Engine hook placement

The hook lives in `run_interaction` **after** canonical validation
produces `valid_actions` and **before** `_apply_memory_actions` — the
sole mutation boundary. When the coordinator is absent or disabled,
this branch is skipped entirely.

- `candidate`: `_evaluate_extraction` runs the coordinator, then
  lifecycle-evaluates the translated action with the same admission
  check used by canonical planning (plus same-batch dedup, section 11).
  Nothing is appended; `action_applied` stays false.
- `adopted` + `authorized`: the action is admission-checked and, if
  admissible, appended to the **same** `valid_actions` list the engine
  already applies. No separate write path exists.

The integration event is emitted once, immediately before application,
as `extraction_integration_evaluated`.

## 11. Same-batch de-duplication

`_reject_reason` (shared by canonical planning and extraction) rejects
a create that duplicates a pre-existing active memory. Extraction adds
`_extraction_reject_reason`, which also rejects a controller create
equivalent (same kind + normalized text) to a canonical create already
in this batch — reason `duplicate_of_planned`. This prevents the
canonical planner and an adopted controller from both creating "Home
airport is SJC." and violating the one-active-durable-memory rule.
Canonical planning is unchanged; the extra check applies only to
controller-originated actions.

Known limitation: de-duplication compares exact normalized text, not
semantic equivalence. Two differently-worded equivalents ("Always add
transfer time when planning work trips" vs. "When planning work trips,
always add transfer time") are not detected as duplicates — consistent
with the engine's existing duplicate handling.

## 12. `canonical_effect` semantics

`canonical_effect` is decided by the engine and is true **only** when a
controller-originated action is authorized, admissible, and appended to
`valid_actions` for application. It is false in disabled, shadow, and
candidate modes, on any rejection, and on controller error. The
coordinator defaults it to false; only the adopted-merge branch sets it
true.

## 13. Controller-error containment

Controllers validate their own inputs and may raise (for example, an
over-long evidence excerpt exceeding the span limit). The coordinator
wraps `controller.extract(...)` in a bounded catch: any exception
produces an outcome with `status=controller_error`, `error_class` set
to the exception type name only (no message, no paths, no source text),
no candidate, and `canonical_effect` false. A controller fault
therefore never crashes the interaction and never leaks raw input.

## 14. Diagnostics and event payload

Every non-disabled interaction emits one
`extraction_integration_evaluated` event whose payload is bounded and
JSON-serializable. It includes: integration id/version, effect mode,
controller type/id, source id and provenance, `proposal_present`,
`proposed_kind`, bounded `normalized_text` (truncated), evidence
offsets and length, controller/grounding/runner/parser statuses,
fallback fields, `final_proposal_source`, `integration_status`,
`adoption_authorized`, and the engine-owned fields
`lifecycle_evaluation`, `lifecycle_rejection_reason`,
`duplicate_or_conflict`, `action_generated`, `action_applied`, and
`canonical_effect`. Raw source text is never echoed.

## 15. Configuration and SDK usage

```python
from experienceos import ExperienceOS
from experienceos.memory.extraction_integration import (
    ExtractionIntegrationConfig, MODE_SHADOW,
)
from experienceos.providers.mock import MockProvider

agent = ExperienceOS(
    model=MockProvider(),
    extraction=ExtractionIntegrationConfig(effect_mode=MODE_SHADOW),
)
```

`ExperienceOS(extraction=...)` accepts either an
`ExtractionIntegrationConfig` (wrapped in a coordinator) or a ready
`ExtractionIntegrationCoordinator`; `None` (the default) leaves the
engine fully unchanged. Anything else raises `ValueError`.

## 16. Safety invariants

1. Disabled is byte-identical to the pre-integration engine.
2. Shadow never changes canonical memory for any input.
3. The coordinator has no store and no mutation method.
4. A translated action is `CREATE`-only, with no lifecycle fields.
5. Adopted mode fails closed without a matching authorization.
6. Every proposal is re-validated at the boundary; controller claims
   are never trusted.
7. An adopted action passes the same admission check and same
   application path as canonical actions.
8. A controller exception is contained, not propagated.

## 17. Tests and development evidence

- `tests/test_extraction_integration.py` — coordinator and engine
  behavior: mode vocabulary, disabled byte-identity, shadow/candidate/
  adopted paths, authorization missing/mismatch, same-batch dedup,
  no-store/no-mutation, translation carries no lifecycle fields,
  serialization and no-leak safety, controller-error containment.
- `tests/test_extraction_integration_fixtures.py` — the development
  fixtures driven through the modes: disabled invokes nothing; shadow
  proposes for positives and abstains for negatives without canonical
  effect; kind matches the expected kind (excluding the deliberately
  unsupported-normalization markers); shadow never changes canonical
  memory; candidate evaluates positives without mutation; preference-
  change fixtures never supersede or forget.

These are development-only signals of behavior, not benchmark
precision or recall.

## 18. Naming

All identifiers introduced here name what they are or do
(`extraction_integration`, `effect_mode`, `shadow`, `candidate`,
`adopted`, `controller_error`). No project-stage vocabulary appears in
any committed name, event, status, or identifier.

## 19. Known limitations

- Semantic (not exact-text) duplicate detection is out of scope
  (section 11).
- The unsupported-normalization fixtures propose a best-effort kind;
  the deterministic baseline does not recover their expected kind, and
  the kind-match test excludes them by design.
- Adoption is per-`(controller, final source)`; there is no partial or
  probabilistic adoption.

## 20. Closure

The seam is implemented, the four modes behave as specified, the
default is disabled and byte-identical, and no second mutation path was
introduced. The coordinator is inert by construction and defensive at
its boundary; the engine retains sole mutation authority.
