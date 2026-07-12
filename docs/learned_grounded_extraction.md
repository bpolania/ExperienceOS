# Learned Grounded Extraction

`experienceos/memory/learned_extraction.py` implements an **optional**,
provider-neutral learned path (`LearnedGroundedExtractionController`)
that answers the same narrow question as the deterministic controller:
does the interaction contain one durable, user-grounded experience
candidate? A learned runner proposes structured output; ExperienceOS
treats it as untrusted, strictly parses it, reconstructs the candidate
from approved caller metadata plus validated model fields, verifies the
exact evidence span, and returns a candidate only if
`GroundedCandidateValidator` accepts it.

**The learned path is optional and not canonical; it cannot mutate
memory; every candidate must pass deterministic grounding validation;
no automatic model download occurs; default tests require no model or
credentials; the deterministic controller remains the baseline and
fallback.** Matching development-fixture coverage does not prove
superiority — formal adoption requires later benchmark evidence.

## 1. Purpose

Provide the safe foundation to evaluate whether a model-assisted
extractor can improve candidate creation beyond deterministic rules
without weakening grounding or lifecycle safety — evaluated shadow-only,
with the deterministic controller as the reference any learned path
must beat before adoption.

## 2. Proposal-Only Authority Boundary

> Models and learned components may propose experience. ExperienceOS
> decides what becomes durable, what replaces previous experience,
> what is forgotten, and what may enter context.

The controller and runners receive no store, manager, engine, bus,
callback, or lifecycle state (constructor audited); they create /
update / supersede / forget / retrieve / rank nothing, emit no events,
and every diagnostic carries `canonical_effect: false`. Nothing in
ExperienceOS constructs the learned controller (source-scan +
subprocess tested).

## 3. Runner Abstraction

`LearnedExtractionRunner` (Protocol): `availability() -> bool` and
`run(LearnedExtractionRequest) -> LearnedExtractionRunnerResult`. The
request carries only `source_text`, `allowed_kinds`, `schema_version`,
and optional `timeout_ms` — no memories, store, or callbacks. The
result carries only `raw_output` (bounded string), runner ID/version,
availability, a bounded `status`, latency, an `error_class` (type name
only), and optional `usage` — never credentials, headers, model paths,
or provider objects. The controller depends only on this protocol, not
on any concrete provider.

## 4. Learned Controller

`LearnedGroundedExtractionController` (`grounded_learned_shadow-1`,
version 1) conforms to the existing `ExtractionController` protocol.
Construction takes an injected runner, an optional injected validator,
an optional deterministic fallback controller, and a `fallback_mode`
(default `deterministic_on_unavailable`). It never constructs a
provider or model by default and is unselected by canonical runtime
construction.

## 5. Candidate-or-None Schema

Strict, closed schema (`additionalProperties: false`): `action` ∈
{candidate, none}; `kind` ∈ {preference, fact, instruction, null};
`normalized_text`, `evidence_text` (bounded strings); `start_offset`,
`end_offset` (integers); `confidence` (null or [0, 1]); `reason`
(bounded). Candidate fields are required when `action=candidate` and
must be null/absent when `action=none`.

## 6. Exact Evidence Requirements

Zero-based, start-inclusive/end-exclusive offsets over the exact
unmodified source; `source_text[start:end] == evidence_text` is
verified. No repair: incorrect offsets, trimmed evidence, casing or
punctuation differences, and out-of-range offsets are all rejected as
`malformed_output` — the controller never searches the source for a
better-matching occurrence, so span reliability is measured honestly.

## 7. Untrusted Output Handling

Model output never controls approved metadata: source ID comes from
`evidence.metadata["source_id"]`, provenance from
`evidence.provenance_label`, and the evidence span source is fixed to
`user`. The candidate is constructed from approved caller metadata plus
validated model fields only; a model-supplied provenance or source
identity is ignored. Strict parsing rejects markdown-wrapped JSON,
unknown fields, non-object roots, multiple candidates, unknown kinds,
non-integer offsets, out-of-bounds confidence, and oversized fields.

## 8. Grounding Validation

Every candidate is validated via
`GroundedCandidateValidator.validate(candidate, ApprovedSource(source_id, source_text, provenance))`.
The validator remains authoritative for source identity, provenance,
exact spans, evidence equality, questions, hypotheticals, temporary
states, one-off requests, durability, ownership, and normalized
support. A rejected candidate yields none (or fallback per mode) with
the validator's rejection code preserved. Validation cannot be
bypassed — no candidate leaves the controller without a passing
`GroundingValidation` (tested).

## 9. Fallback Modes

`none` (learned failure → none), `deterministic_on_unavailable`
(default; fall back only when the runner is unavailable),
`deterministic_on_error` (also on error/timeout),
`deterministic_on_invalid` (also on malformed output or
validator-rejected learned proposals). When fallback occurs, the
deterministic controller runs (with its own validator), and diagnostics
record the learned attempt, learned outcome, fallback reason, and
`final_proposal_source: "deterministic_fallback"` — the learned path is
never credited for a fallback proposal. The deterministic fallback
cannot bypass grounding validation.

## 10. Shadow-Oriented Use

The controller is directly invokable for shadow evaluation: it produces
a proposal and diagnostics while creating no memory, applying no
lifecycle action, replacing no canonical result, and changing no
response or context. Engine/runtime shadow orchestration is a later
workstream — this module delivers only the controller and runner
foundation.

## 11. Optional Local Runner

`LocalLearnedExtractionRunner` adapts the existing
`LlamaCppLocalModelRunner`: lazy import, explicit model path (via
constructor or `EXPERIENCEOS_LOCAL_MODEL_PATH`), shallow
`availability()` that never loads weights, and no automatic download. A
missing dependency or model path reports unavailable; the model path
never appears in the runner result. On this machine it is unavailable
(dependency not installed), so its smoke test skips cleanly.

## 12. Optional Qwen Cloud Runner

`CloudLearnedExtractionRunner` wraps any `ModelProvider` (e.g.
`QwenCloudProvider`) — an optional quality-ceiling / comparison path,
never canonical. It requires an explicitly-supplied provider; default
tests construct none and never touch the network. Provider errors map
to `runner_error` with the type name only (no message, no credentials).

## 13. Availability and Clean Skips

Missing optional dependency, missing model path, or missing credentials
all yield an unavailable status and a clean controller result; import
loads nothing heavy (subprocess-proven: no `llama_cpp`/`torch`/… on
`import experienceos.memory.learned_extraction`), and default
`ExperienceOS` construction pulls neither the learned controller nor
the local runtime.

## 14. Diagnostics

Bounded, JSON-safe, deterministic (timing excluded from equality):
controller ID/version, mode (`shadow`), runner ID/version/availability/
status/error-class, parser status, validation status, outcome,
candidate presence, proposed kind, bounded normalized text, evidence
offsets/length, fallback mode/used/reason, learned outcome,
`final_proposal_source`, `canonical_effect: false`, and an
`{"elapsed_ms", "runner_elapsed_ms"}` block. Outcome vocabulary:
`candidate`, `model_none`, `malformed_output`, `validation_rejected`,
`runner_unavailable`, `runner_error`, `runner_timeout`,
`fallback_used`. No secrets, model paths, personal paths, or provider
objects.

## 15. Development Fixture Use

Against the 37 development fixtures with fake oracle-fed runners:
positive fixtures flow through the learned gate and validate at the
expected span (with an oracle-acceptable normalization); negative
fixtures with a none output abstain; hallucinated candidates on
negative cases are gated out by the validator (never a fabricated
memory); recorded unsupported normalizations are rejected. This is
development evidence of schema/span/validation/abstention behavior —
not benchmark precision/recall and not adoption evidence.

## 16. Canonical Compatibility

`HybridMemoryPlanner`, `DeterministicGroundedExtractionController`,
`ExperienceManager`, `ExperienceEngine`, canonical memory creation,
context assembly, demo behavior, and benchmark outputs are all
unchanged; the learned path is not selected by default; root imports
remain lightweight; optional runners load only when explicitly
instantiated.

## 17. Known Limitations

Learned span reliability, local-model output quality, structured-output
compliance, and CPU latency are unmeasured (no runtime was available);
synonym normalizations remain validator-unsupported (fail closed);
single-message sources only; frozen-corpus extraction annotations do
not yet exist; and the deterministic baseline already saturates the
development fixtures, so these fixtures cannot demonstrate learned
superiority.

## 18. Adoption Status

Not adopted; shadow-oriented. The learned path may become canonical
only if it beats the deterministic baseline on predeclared primary
metrics without weakening any lifecycle-safety gate — otherwise it
stays shadow-only, candidate-only behind explicit configuration, or
deferred. Deterministic fallback remains permanently available.
