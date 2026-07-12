"""Optional learned grounded extraction.

A provider-neutral, proposal-only path that answers the SAME narrow
question as the deterministic controller: does the interaction contain
one durable, user-grounded experience candidate? A learned runner
proposes structured output; ExperienceOS treats it as untrusted,
strictly parses it, reconstructs the candidate from APPROVED caller
metadata plus validated model fields, verifies the exact evidence
span, and only returns a candidate if ``GroundedCandidateValidator``
accepts it. If anything fails, the controller returns none (or, per an
explicit fallback mode, defers to the deterministic controller — never
crediting the learned path for a fallback proposal).

Everything here is optional and non-canonical: no runner is
constructed by default, the local/cloud adapters load lazily and skip
cleanly when unavailable, model output never controls source identity,
provenance, offsets, or lifecycle, and ``canonical_effect`` is false
in every diagnostic. The deterministic controller remains the baseline
and fallback. This is not wired into memory creation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Mapping, Protocol

from experienceos.controllers.base import EvidenceSpan
from experienceos.controllers.extraction import (
    ExtractionEvidence,
    ExtractionProposal,
    ProposedMemoryCandidate,
)
from experienceos.memory.extraction import (
    MAX_EVIDENCE_LENGTH,
    MAX_STATEMENT_LENGTH,
    VALID_CANDIDATE_KINDS,
)
from experienceos.memory.grounded_extraction import (
    DeterministicGroundedExtractionController,
)
from experienceos.memory.grounding import (
    ApprovedSource,
    GroundedCandidateValidator,
)

LEARNED_CONTROLLER_ID = "grounded_learned_shadow-1"
LEARNED_CONTROLLER_VERSION = "1"
EXTRACTION_OUTPUT_SCHEMA_VERSION = "1"

MAX_RAW_OUTPUT_CHARS = 4000
MAX_REASON_CHARS = 300

# Runner status vocabulary (bounded, machine-readable).
RUNNER_OK = "ok"
RUNNER_UNAVAILABLE = "runner_unavailable"
RUNNER_ERROR = "runner_error"
RUNNER_TIMEOUT = "runner_timeout"

# Controller outcome vocabulary.
OUTCOME_CANDIDATE = "candidate"
OUTCOME_MODEL_NONE = "model_none"
OUTCOME_MALFORMED = "malformed_output"
OUTCOME_VALIDATION_REJECTED = "validation_rejected"
OUTCOME_RUNNER_UNAVAILABLE = "runner_unavailable"
OUTCOME_RUNNER_ERROR = "runner_error"
OUTCOME_RUNNER_TIMEOUT = "runner_timeout"
OUTCOME_FALLBACK_USED = "fallback_used"

# Fallback modes (feature-named; conservative default).
FALLBACK_NONE = "none"
FALLBACK_ON_UNAVAILABLE = "deterministic_on_unavailable"
FALLBACK_ON_ERROR = "deterministic_on_error"
FALLBACK_ON_INVALID = "deterministic_on_invalid"
FALLBACK_MODES = (
    FALLBACK_NONE, FALLBACK_ON_UNAVAILABLE, FALLBACK_ON_ERROR,
    FALLBACK_ON_INVALID,
)

# The strict output schema. Kept small for local-model feasibility.
EXTRACTION_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "reason"],
    "properties": {
        "action": {"enum": ["candidate", "none"]},
        "kind": {"enum": ["preference", "fact", "instruction", None]},
        "normalized_text": {"type": ["string", "null"]},
        "evidence_text": {"type": ["string", "null"]},
        "start_offset": {"type": ["integer", "null"]},
        "end_offset": {"type": ["integer", "null"]},
        "confidence": {"type": ["number", "null"]},
        "reason": {"type": "string"},
    },
}
_ALLOWED_FIELDS = frozenset(EXTRACTION_OUTPUT_SCHEMA["properties"])


# --------------------------------------------------------------------------
# Runner contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LearnedExtractionRequest:
    """Bounded runner input. No store, memories, callbacks, or
    lifecycle state — only what the model needs to read the message."""

    source_text: str
    allowed_kinds: tuple = tuple(sorted(VALID_CANDIDATE_KINDS))
    schema_version: str = EXTRACTION_OUTPUT_SCHEMA_VERSION
    timeout_ms: int | None = None


@dataclass(frozen=True)
class LearnedExtractionRunnerResult:
    """Bounded runner output; carries no provider objects or secrets."""

    raw_output: str | None
    runner_id: str
    runner_version: str
    available: bool
    status: str  # RUNNER_OK / RUNNER_UNAVAILABLE / RUNNER_ERROR / …
    elapsed_ms: float | None = None
    error_class: str | None = None
    usage: dict | None = None


class LearnedExtractionRunner(Protocol):
    """Provider-neutral structured-extraction seam."""

    runner_id: str
    runner_version: str

    def availability(self) -> bool:
        ...

    def run(
        self, request: LearnedExtractionRequest
    ) -> LearnedExtractionRunnerResult:
        ...


# --------------------------------------------------------------------------
# Strict output parsing (model output is untrusted)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedExtraction:
    action: str
    kind: str | None
    normalized_text: str | None
    evidence_text: str | None
    start_offset: int | None
    end_offset: int | None
    confidence: float | None
    reason: str


class ExtractionParseError(ValueError):
    """Raw learned output violated the strict schema."""


def parse_extraction_output(raw: str | None) -> ParsedExtraction:
    """Strictly parse one top-level JSON object. No Markdown fences,
    no unknown fields, no multiple candidates, bounded lengths."""
    if not isinstance(raw, str) or not raw.strip():
        raise ExtractionParseError("empty output")
    if len(raw) > MAX_RAW_OUTPUT_CHARS:
        raise ExtractionParseError("output exceeds bounded length")
    text = raw.strip()
    if text.startswith("```"):
        raise ExtractionParseError("markdown-wrapped output rejected")
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ExtractionParseError(
            f"invalid json: {type(exc).__name__}"
        ) from exc
    if not isinstance(data, dict):
        raise ExtractionParseError("top-level value is not an object")
    unknown = set(data) - _ALLOWED_FIELDS
    if unknown:
        raise ExtractionParseError(f"unknown fields: {sorted(unknown)}")

    action = data.get("action")
    if action not in ("candidate", "none"):
        raise ExtractionParseError(f"unknown action {action!r}")
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS:
        raise ExtractionParseError("reason missing or too long")

    if action == "none":
        for field_name in ("kind", "normalized_text", "evidence_text",
                            "start_offset", "end_offset"):
            if data.get(field_name) is not None:
                raise ExtractionParseError(
                    f"none result must not carry {field_name!r}"
                )
        return ParsedExtraction(
            "none", None, None, None, None, None, None, reason
        )

    kind = data.get("kind")
    if kind not in VALID_CANDIDATE_KINDS:
        raise ExtractionParseError(f"invalid kind {kind!r}")
    normalized = data.get("normalized_text")
    evidence = data.get("evidence_text")
    for name, value, limit in (
        ("normalized_text", normalized, MAX_STATEMENT_LENGTH),
        ("evidence_text", evidence, MAX_EVIDENCE_LENGTH),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ExtractionParseError(f"{name} missing")
        if len(value) > limit:
            raise ExtractionParseError(f"{name} exceeds bounded length")
    start = data.get("start_offset")
    end = data.get("end_offset")
    for name, value in (("start_offset", start), ("end_offset", end)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ExtractionParseError(f"{name} must be an integer")
    confidence = data.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(
            confidence, (int, float)
        ) or not 0.0 <= float(confidence) <= 1.0:
            raise ExtractionParseError("confidence out of bounds")
    return ParsedExtraction(
        "candidate", kind, normalized, evidence, start, end,
        float(confidence) if confidence is not None else None, reason,
    )


# --------------------------------------------------------------------------
# Learned controller
# --------------------------------------------------------------------------


class LearnedGroundedExtractionController:
    """One learned durable candidate, or none — every candidate gated
    by deterministic grounding validation."""

    controller_id = LEARNED_CONTROLLER_ID
    version = LEARNED_CONTROLLER_VERSION

    def __init__(
        self,
        runner: LearnedExtractionRunner,
        validator: GroundedCandidateValidator | None = None,
        fallback_controller: (
            DeterministicGroundedExtractionController | None
        ) = None,
        fallback_mode: str = FALLBACK_ON_UNAVAILABLE,
    ):
        if fallback_mode not in FALLBACK_MODES:
            raise ValueError(
                f"unknown fallback_mode {fallback_mode!r}; expected "
                f"one of {FALLBACK_MODES}"
            )
        self.runner = runner
        self.validator = validator or GroundedCandidateValidator()
        self.fallback_mode = fallback_mode
        # Fallback controller is constructed only if a fallback mode
        # might use it; it never mutates anything.
        self._fallback = fallback_controller
        if fallback_mode != FALLBACK_NONE and self._fallback is None:
            self._fallback = DeterministicGroundedExtractionController(
                validator=self.validator
            )

    def extract(self, evidence: ExtractionEvidence) -> ExtractionProposal:
        started = time.perf_counter()
        source_text = evidence.user_text or ""
        provenance = evidence.provenance_label or "user_asserted"
        source_id = str(
            evidence.metadata.get("source_id", "user-message")
        )
        stages = {
            "runner_status": None,
            "parser_status": "skipped",
            "validation_status": "skipped",
        }

        runner_result = self._invoke_runner(source_text)
        stages["runner_status"] = runner_result.status

        if runner_result.status != RUNNER_OK:
            return self._maybe_fallback(
                evidence, runner_result, stages, started,
                outcome={
                    RUNNER_UNAVAILABLE: OUTCOME_RUNNER_UNAVAILABLE,
                    RUNNER_ERROR: OUTCOME_RUNNER_ERROR,
                    RUNNER_TIMEOUT: OUTCOME_RUNNER_TIMEOUT,
                }.get(runner_result.status, OUTCOME_RUNNER_ERROR),
                fallback_triggers=(
                    (FALLBACK_ON_UNAVAILABLE, FALLBACK_ON_ERROR,
                     FALLBACK_ON_INVALID)
                    if runner_result.status == RUNNER_UNAVAILABLE
                    else (FALLBACK_ON_ERROR, FALLBACK_ON_INVALID)
                ),
            )

        try:
            parsed = parse_extraction_output(runner_result.raw_output)
            stages["parser_status"] = "parsed"
        except ExtractionParseError as exc:
            stages["parser_status"] = "malformed"
            return self._maybe_fallback(
                evidence, runner_result, stages, started,
                outcome=OUTCOME_MALFORMED,
                fallback_triggers=(FALLBACK_ON_INVALID,),
                error_detail=type(exc).__name__,
            )

        if parsed.action == "none":
            return self._result(
                runner_result, stages, started, OUTCOME_MODEL_NONE,
                candidate=None, source="learned",
                reason=f"learned none: {parsed.reason[:120]}",
            )

        # Model output is untrusted: reconstruct from APPROVED metadata
        # + validated fields. No offset repair, no evidence search.
        if not (
            0 <= parsed.start_offset < parsed.end_offset
            <= len(source_text)
        ):
            stages["parser_status"] = "invalid_offsets"
            return self._maybe_fallback(
                evidence, runner_result, stages, started,
                outcome=OUTCOME_MALFORMED,
                fallback_triggers=(FALLBACK_ON_INVALID,),
                error_detail="offsets_out_of_range",
            )
        exact = source_text[parsed.start_offset:parsed.end_offset]
        if exact != parsed.evidence_text:
            stages["parser_status"] = "evidence_offset_mismatch"
            return self._maybe_fallback(
                evidence, runner_result, stages, started,
                outcome=OUTCOME_MALFORMED,
                fallback_triggers=(FALLBACK_ON_INVALID,),
                error_detail="evidence_not_at_offsets",
            )

        candidate = ProposedMemoryCandidate(
            kind=parsed.kind,
            text=parsed.normalized_text,
            grounded=True,
            confidence=(
                parsed.confidence if parsed.confidence is not None
                else 0.5
            ),
            evidence_spans=(
                EvidenceSpan(
                    source="user",
                    start=parsed.start_offset,
                    end=parsed.end_offset,
                    excerpt=exact,
                ),
            ),
        )
        validation = self.validator.validate(
            candidate,
            ApprovedSource(
                source_id=source_id, text=source_text,
                provenance=provenance,
            ),
        )
        stages["validation_status"] = validation.code
        if not validation.valid:
            return self._maybe_fallback(
                evidence, runner_result, stages, started,
                outcome=OUTCOME_VALIDATION_REJECTED,
                fallback_triggers=(FALLBACK_ON_INVALID,),
                validation=validation.diagnostics,
            )

        return self._result(
            runner_result, stages, started, OUTCOME_CANDIDATE,
            candidate=candidate, source="learned",
            reason="learned candidate validated by grounding",
            validation=validation.diagnostics,
            confidence=candidate.confidence,
        )

    # -- runner invocation -------------------------------------------------------

    def _invoke_runner(self, source_text):
        try:
            if not self.runner.availability():
                return LearnedExtractionRunnerResult(
                    raw_output=None,
                    runner_id=getattr(self.runner, "runner_id",
                                      "unknown"),
                    runner_version=getattr(self.runner, "runner_version",
                                           "unknown"),
                    available=False, status=RUNNER_UNAVAILABLE,
                )
            request = LearnedExtractionRequest(source_text=source_text)
            result = self.runner.run(request)
            if not isinstance(result, LearnedExtractionRunnerResult):
                return LearnedExtractionRunnerResult(
                    raw_output=None,
                    runner_id=getattr(self.runner, "runner_id",
                                      "unknown"),
                    runner_version="unknown", available=True,
                    status=RUNNER_ERROR,
                    error_class="invalid_runner_result",
                )
            return result
        except TimeoutError:
            return LearnedExtractionRunnerResult(
                raw_output=None,
                runner_id=getattr(self.runner, "runner_id", "unknown"),
                runner_version=getattr(self.runner, "runner_version",
                                       "unknown"),
                available=True, status=RUNNER_TIMEOUT,
                error_class="TimeoutError",
            )
        except Exception as exc:  # bounded: mapped to a status
            return LearnedExtractionRunnerResult(
                raw_output=None,
                runner_id=getattr(self.runner, "runner_id", "unknown"),
                runner_version=getattr(self.runner, "runner_version",
                                       "unknown"),
                available=True, status=RUNNER_ERROR,
                error_class=type(exc).__name__,
            )

    # -- fallback ----------------------------------------------------------------

    def _maybe_fallback(self, evidence, runner_result, stages, started,
                        outcome, fallback_triggers, error_detail=None,
                        validation=None):
        if self.fallback_mode in fallback_triggers and (
            self._fallback is not None
        ):
            deterministic = self._fallback.extract(evidence)
            return self._result(
                runner_result, stages, started, OUTCOME_FALLBACK_USED,
                candidate=deterministic.candidate,
                source="deterministic_fallback",
                reason=(
                    f"learned {outcome}; deterministic fallback used"
                ),
                fallback_reason=outcome,
                learned_outcome=outcome,
                deterministic_recommendation=(
                    deterministic.recommendation
                ),
                error_detail=error_detail,
                validation=validation,
            )
        return self._result(
            runner_result, stages, started, outcome,
            candidate=None, source="learned",
            reason=f"no candidate: {outcome}",
            error_detail=error_detail, validation=validation,
        )

    # -- result assembly ---------------------------------------------------------

    def _result(self, runner_result, stages, started, outcome,
                candidate, source, reason, validation=None,
                fallback_reason=None, learned_outcome=None,
                deterministic_recommendation=None, error_detail=None,
                confidence=None):
        span = (
            candidate.evidence_spans[0]
            if candidate is not None and candidate.evidence_spans
            else None
        )
        diagnostics = {
            "controller_id": self.controller_id,
            "controller_version": self.version,
            "mode": "shadow",
            "runner_id": runner_result.runner_id,
            "runner_version": runner_result.runner_version,
            "runner_available": runner_result.available,
            "runner_status": stages["runner_status"],
            "runner_error_class": runner_result.error_class,
            "parser_status": stages["parser_status"],
            "validation_status": stages["validation_status"],
            "outcome": outcome,
            "candidate_present": candidate is not None,
            "proposed_kind": candidate.kind if candidate else None,
            "normalized_text": (
                str(candidate.text)[:MAX_STATEMENT_LENGTH]
                if candidate else None
            ),
            "evidence_start": span.start if span else None,
            "evidence_end": span.end if span else None,
            "evidence_length": (
                span.end - span.start if span else None
            ),
            "fallback_mode": self.fallback_mode,
            "fallback_used": outcome == OUTCOME_FALLBACK_USED,
            "fallback_reason": fallback_reason,
            "learned_outcome": learned_outcome,
            "final_proposal_source": source,
            "canonical_effect": False,
            "evaluation": {
                "elapsed_ms": round(
                    (time.perf_counter() - started) * 1000.0, 3
                ),
                "runner_elapsed_ms": runner_result.elapsed_ms,
            },
        }
        if error_detail:
            diagnostics["error_detail"] = error_detail
        if validation is not None:
            diagnostics["validation"] = validation
        if deterministic_recommendation is not None:
            diagnostics["deterministic_recommendation"] = (
                deterministic_recommendation
            )
        if runner_result.usage:
            diagnostics["usage"] = runner_result.usage
        recommendation = "candidate" if candidate is not None else "none"
        return ExtractionProposal(
            recommendation=recommendation,
            candidate=candidate,
            score=confidence or 0.0,
            confidence=confidence or 0.0,
            reason=reason[:MAX_REASON_CHARS],
            controller_id=self.controller_id,
            diagnostics=diagnostics,
        )


# --------------------------------------------------------------------------
# Optional runner adapters (lazy; skip cleanly when unavailable)
# --------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You extract at most ONE durable, user-grounded memory from a "
    "single user message, or none. Durable means it should stay "
    "useful across future sessions: stable preferences, standing "
    "instructions, and lasting facts. Return exactly one candidate or "
    "none.\n"
    "Rules: copy evidence_text EXACTLY and CONTIGUOUSLY from the "
    "message; start_offset/end_offset must index the original message "
    "so message[start:end] == evidence_text. Only kinds preference, "
    "fact, instruction. Do not: infer sensitive attributes; turn "
    "assistant text into user truth; turn a question or hypothetical "
    "into an assertion; turn a temporary or one-off event into a "
    "durable memory; broaden scope; strengthen certainty; drop "
    "negation or ownership; produce multiple memories; or choose any "
    "lifecycle action. Respond with one JSON object only, no prose, "
    "no markdown.\n"
    "Examples:\n"
    '{"action":"candidate","kind":"preference","normalized_text":'
    '"Prefers aisle seats","evidence_text":"I prefer aisle seats",'
    '"start_offset":0,"end_offset":19,"confidence":0.9,"reason":'
    '"durable preference"}\n'
    '{"action":"candidate","kind":"instruction","normalized_text":'
    '"Send summaries as bullet points","evidence_text":"send me '
    'summaries as bullet points","start_offset":13,"end_offset":45,'
    '"confidence":0.85,"reason":"standing instruction"}\n'
    '{"action":"none","kind":null,"normalized_text":null,'
    '"evidence_text":null,"start_offset":null,"end_offset":null,'
    '"confidence":null,"reason":"one-off request"}\n'
    '{"action":"none","kind":null,"normalized_text":null,'
    '"evidence_text":null,"start_offset":null,"end_offset":null,'
    '"confidence":null,"reason":"question"}\n'
    '{"action":"none","kind":null,"normalized_text":null,'
    '"evidence_text":null,"start_offset":null,"end_offset":null,'
    '"confidence":null,"reason":"hypothetical"}\n'
    '{"action":"none","kind":null,"normalized_text":null,'
    '"evidence_text":null,"start_offset":null,"end_offset":null,'
    '"confidence":null,"reason":"unsupported normalization"}'
)


def build_prompts(source_text: str) -> tuple[str, str]:
    """The bounded system/user prompt pair for any structured runner."""
    return _SYSTEM_PROMPT, f"Message:\n{source_text}"


class LocalLearnedExtractionRunner:
    """Adapter over the optional local structured-inference runtime.

    Lazy: the ``LlamaCppLocalModelRunner`` discovers its dependency and
    model path shallowly (``availability()`` never loads weights) and
    never downloads. Constructing this adapter imports nothing heavy;
    a missing dependency or model path reports unavailable.
    """

    runner_id = "local_llama_extraction"
    runner_version = "1"

    def __init__(self, local_runner=None, model_path=None):
        if local_runner is not None:
            self._local = local_runner
        else:
            from experienceos.policy.local_runner import (
                LlamaCppLocalModelRunner,
            )

            self._local = LlamaCppLocalModelRunner(model_path=model_path)

    def availability(self) -> bool:
        return bool(self._local.availability().available)

    def run(
        self, request: LearnedExtractionRequest
    ) -> LearnedExtractionRunnerResult:
        system_prompt, user_prompt = build_prompts(request.source_text)
        started = time.perf_counter()
        try:
            result = self._local.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=EXTRACTION_OUTPUT_SCHEMA,
            )
        except Exception as exc:
            return LearnedExtractionRunnerResult(
                raw_output=None, runner_id=self.runner_id,
                runner_version=self.runner_version, available=True,
                status=RUNNER_ERROR, error_class=type(exc).__name__,
                elapsed_ms=round(
                    (time.perf_counter() - started) * 1000.0, 3
                ),
            )
        return LearnedExtractionRunnerResult(
            raw_output=json.dumps(result.data),
            runner_id=self.runner_id,
            runner_version=self.runner_version,
            available=True, status=RUNNER_OK,
            elapsed_ms=result.elapsed_ms,
            usage=(
                {"prompt_tokens": result.prompt_tokens,
                 "completion_tokens": result.completion_tokens}
                if result.prompt_tokens is not None else None
            ),
        )


class CloudLearnedExtractionRunner:
    """Optional Qwen Cloud comparison runner (a quality-ceiling path,
    never canonical). Requires an explicitly-supplied provider; default
    tests never construct one and never touch the network."""

    runner_id = "cloud_extraction"
    runner_version = "1"

    def __init__(self, provider):
        self._provider = provider

    def availability(self) -> bool:
        return self._provider is not None

    def run(
        self, request: LearnedExtractionRequest
    ) -> LearnedExtractionRunnerResult:
        system_prompt, user_prompt = build_prompts(request.source_text)
        started = time.perf_counter()
        try:
            raw = self._provider.complete(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
        except Exception as exc:
            return LearnedExtractionRunnerResult(
                raw_output=None, runner_id=self.runner_id,
                runner_version=self.runner_version, available=True,
                status=RUNNER_ERROR, error_class=type(exc).__name__,
                elapsed_ms=round(
                    (time.perf_counter() - started) * 1000.0, 3
                ),
            )
        return LearnedExtractionRunnerResult(
            raw_output=raw, runner_id=self.runner_id,
            runner_version=self.runner_version, available=True,
            status=RUNNER_OK,
            elapsed_ms=round(
                (time.perf_counter() - started) * 1000.0, 3
            ),
        )
