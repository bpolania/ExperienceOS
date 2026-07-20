"""Optional local-model memory candidate extractor.

A proposer only, implementing the ``MemoryCandidateExtractor`` seam on
top of the existing ``LocalModelRunner`` abstraction — no second
inference stack, no model download, disabled unless explicitly
constructed with a runner. The model detects durable user-provided
experience and returns structured candidates with quoted grounding
evidence; it never proposes forgets, supersedes, memory IDs, lifecycle
states, or storage operations. All of its output still passes the
deterministic ``CandidateValidator`` and the ordinary planner/manager/
engine lifecycle controls.

Failure containment: structural validation is strict; malformed or
unsupported output is rejected safely as a no-candidate result with a
recorded reason — never fabricated fallback memory. Broader local
reliability work is out of scope here.
"""

from __future__ import annotations

import time

from experienceos.memory.extraction import (
    EXTRACTION_SCHEMA_VERSION,
    ExtractionRequest,
    ExtractionResult,
    MemoryCandidate,
    VALID_CANDIDATE_KINDS,
)
from experienceos.policy.local_runner import (
    LocalModelInvalidOutput,
    LocalModelRunner,
    LocalModelRunnerError,
)

# Small structured-output schema: candidates only. No IDs, no lifecycle
# fields, no supersession targets.
MEMORY_CANDIDATE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["preference", "fact", "instruction"],
                    },
                    "statement": {"type": "string"},
                    "evidence": {"type": "string"},
                    "subject": {"type": "string"},
                    "attribute": {"type": "string"},
                    "value": {"type": "string"},
                    "scope": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": [
                    "kind",
                    "statement",
                    "evidence",
                    "subject",
                    "attribute",
                    "value",
                    "scope",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

_CANDIDATE_FIELDS = frozenset(
    {
        "kind",
        "statement",
        "evidence",
        "subject",
        "attribute",
        "value",
        "scope",
        "confidence",
    }
)

_SYSTEM_PROMPT = """\
You detect durable user experience worth remembering across sessions.

Return structured candidates ONLY for durable content the user states
about themselves or their world: stable preferences, personal or
organizational facts, relationships, routines, schedules, devices,
residence, employer, languages, durable instructions.

Rules:
- evidence must QUOTE the exact supporting span of the user message.
- statement must be one concise normalized sentence.
- subject is "user" unless the fact is about someone else the user
  named (e.g. "daughter").
- Never invent values, dates, places, or qualifiers not in the message.
- Never propose forgetting, replacing, or updating existing memories.
- Ignore greetings, one-off requests, questions, hypotheticals, quoted
  third-party speech, and statements limited to the current turn.
- When uncertain, return an empty candidates list.
"""


class LocalModelCandidateExtractor:
    """Structured candidate proposals from an optional local model."""

    extractor_id = "local_model_candidates"
    extractor_version = "1"

    def __init__(self, runner: LocalModelRunner, max_candidates: int = 3):
        self.runner = runner
        self.max_candidates = max_candidates

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        started = time.perf_counter()
        try:
            result = self.runner.generate_structured(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=f"USER MESSAGE\n{request.source_text}",
                schema=MEMORY_CANDIDATE_SCHEMA,
            )
        except LocalModelRunnerError as exc:
            return ExtractionResult(
                candidates=(),
                valid=False,
                status="failed_safe",
                reason=f"{exc.reason}: {str(exc)[:160]}",
                parse_ok=not isinstance(exc, LocalModelInvalidOutput),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                fallback=True,
                extractor_id=self.extractor_id,
                extractor_version=self.extractor_version,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        try:
            candidates = self._to_candidates(result.data)
        except LocalModelInvalidOutput as exc:
            return ExtractionResult(
                candidates=(),
                valid=False,
                status="invalid_output",
                reason=str(exc)[:160],
                raw_output=str(result.data)[:400],
                parse_ok=False,
                elapsed_ms=elapsed_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                fallback=True,
                extractor_id=self.extractor_id,
                extractor_version=self.extractor_version,
            )

        status = "proposed" if candidates else "no_candidates"
        return ExtractionResult(
            candidates=tuple(candidates[: request.max_candidates]),
            status=status,
            reason="" if candidates else "model returned no candidates",
            elapsed_ms=elapsed_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
        )

    def _to_candidates(self, data) -> list[MemoryCandidate]:
        """Strict structural validation; no semantic repair."""
        raw = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            raise LocalModelInvalidOutput(
                "Extractor output must contain a 'candidates' list."
            )
        if len(raw) > self.max_candidates:
            raise LocalModelInvalidOutput(
                f"Too many candidates: {len(raw)} > {self.max_candidates}."
            )
        candidates = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise LocalModelInvalidOutput(
                    f"Candidate {index} must be an object."
                )
            if set(item) != _CANDIDATE_FIELDS:
                raise LocalModelInvalidOutput(
                    f"Candidate {index} fields must be exactly "
                    f"{sorted(_CANDIDATE_FIELDS)}."
                )
            for key in (
                "kind", "statement", "evidence", "subject", "attribute",
                "value", "scope",
            ):
                if not isinstance(item[key], str):
                    raise LocalModelInvalidOutput(
                        f"Candidate {index} field {key!r} must be a string."
                    )
            if item["kind"] not in VALID_CANDIDATE_KINDS:
                raise LocalModelInvalidOutput(
                    f"Candidate {index} has unsupported kind "
                    f"{item['kind']!r}."
                )
            confidence = item["confidence"]
            if isinstance(confidence, bool) or not isinstance(
                confidence, (int, float)
            ):
                raise LocalModelInvalidOutput(
                    f"Candidate {index} field 'confidence' must be a number."
                )
            candidates.append(
                MemoryCandidate(
                    kind=item["kind"],
                    statement=item["statement"].strip(),
                    evidence=item["evidence"].strip(),
                    subject=item["subject"].strip() or "user",
                    attribute=item["attribute"].strip(),
                    value=item["value"].strip(),
                    display_value=item["value"].strip(),
                    scope=item["scope"].strip() or "global",
                    confidence=float(confidence),
                    durability_confidence=float(confidence),
                    extraction_method="local_model",
                    schema_version=EXTRACTION_SCHEMA_VERSION,
                )
            )
        return candidates
