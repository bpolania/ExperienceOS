"""Qwen-backed grounded extraction controller.

Canonical when Qwen Cloud is configured: the demo composition layer
selects this controller over the deterministic one whenever credentials
are present (see ``demo.support.build_canonical_extraction_config``).
The deterministic controller remains the alternate implementation for
offline runs, tests, and comparison benchmarks.

A thin adapter that asks the same narrow question as the deterministic
extractor — *does this interaction contain one durable, user-grounded
experience candidate?* — but sources the structured answer from Qwen
Cloud instead of deterministic rules. It reuses the entire existing
learned-extraction pipeline: the model returns strict JSON, ExperienceOS
treats it as untrusted, strictly parses it, and only returns a candidate
if the existing ``GroundedCandidateValidator`` accepts it.

This adds no new schema, no new lifecycle, no new storage, and no new
mutation authority. It proposes only: every candidate must still pass
the unchanged ``GroundedCandidateValidator`` and the engine's existing
authority. It does exactly one temperature-0 inference with no retries
and a bounded timeout, and there is no fallback — an unavailable or
failing call is an explicit non-candidate result, never a deterministic
proposal substituted on Qwen's behalf.

It lives outside ``experienceos/`` on purpose: the core package stays
provider-neutral and free of learned-path references, so the choice of
controller is made in composition rather than in the kernel.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

from experienceos.controllers.extraction import (
    ExtractionEvidence,
    ExtractionProposal,
)
from experienceos.memory.extraction import VALID_CANDIDATE_KINDS
from experienceos.memory.learned_extraction import (
    FALLBACK_NONE,
    RUNNER_ERROR,
    RUNNER_OK,
    RUNNER_UNAVAILABLE,
    LearnedExtractionRequest,
    LearnedExtractionRunnerResult,
    LearnedGroundedExtractionController,
)

QWEN_EXTRACTION_RUNNER_ID = "qwen_extraction_runner-1"
QWEN_EXTRACTION_CONTROLLER_ID = "grounded_qwen_shadow-1"
# v2: the first live run showed the model returns the correct verbatim
# evidence_text but miscounts character offsets, so every candidate was
# rejected on the offset check. Fix (parsing at the experimental
# boundary): recompute offsets from the model's own evidence_text when it
# is a genuine substring of the message — no evidence search, no repair
# of content the model did not supply.
# v3: the second live run showed the model paraphrased first-person
# statements into third person ("The user is based in ..."), which the
# unchanged grounding validator could not confirm was supported by the
# first-person evidence (indeterminate_support). Fix: instruct the model
# to keep normalized_text first-person and close to the source wording.
# The validator is not changed.
QWEN_EXTRACTION_VERSION = "3"

#: One bounded inference; no chains of thought, no retries.
DEFAULT_TIMEOUT_MS = 8000

# Deterministic instruction. The model returns ONLY the strict JSON the
# learned pipeline already validates; anything else is rejected upstream.
_SYSTEM_INSTRUCTION = (
    "You extract at most one durable, user-grounded memory from a single "
    "user message for a personal-assistant memory system. Reply with ONE "
    "JSON object and nothing else — no prose, no markdown, no code fences.\n"
    "\n"
    "Schema (exact keys, no others):\n"
    '{"action": "candidate"|"none", "kind": "preference"|"fact"|'
    '"instruction"|null, "normalized_text": string|null, "evidence_text": '
    'string|null, "start_offset": integer|null, "end_offset": integer|null, '
    '"confidence": number|null, "reason": short string}\n'
    "\n"
    "Rules:\n"
    "- A durable memory is a stable preference, fact, or standing "
    "instruction the user asserts about themselves. Questions, "
    "hypotheticals, one-time requests, and small talk are NOT durable.\n"
    "- If nothing durable is present, return action \"none\" with every "
    "other field null and a short reason.\n"
    "- If one durable memory is present, return action \"candidate\" with: "
    "kind; normalized_text; evidence_text (the VERBATIM substring of the "
    "user message that grounds it); start_offset and end_offset (character "
    "offsets of evidence_text within the user message); confidence in "
    "[0,1]; a short reason.\n"
    "- normalized_text must keep the user's own wording and first-person "
    "perspective. Do NOT rewrite \"I ...\" as \"The user ...\". Do NOT add "
    "any subject, name, location, identity, motivation, or context the "
    "message does not state. Only drop conversational filler (greetings, "
    "\"actually\", \"now\", \"quick note\") when the remaining clause is "
    "still directly supported by the evidence. Prefer a short "
    "source-grounded clause over an abstract paraphrase.\n"
    "  Example: \"I work from the Denver office.\" -> normalized_text \"I "
    "work from the Denver office.\" (NOT \"The user is based in the Denver "
    "office.\").\n"
    "- Never invent evidence: evidence_text must appear exactly in the "
    "message. Never emit more than one candidate.\n"
)


def build_extraction_messages(source_text: str, allowed_kinds=None) -> list:
    """Deterministic message list for one extraction inference."""
    kinds = sorted(allowed_kinds or VALID_CANDIDATE_KINDS)
    system = _SYSTEM_INSTRUCTION + f"\nAllowed kinds: {kinds}.\n"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": source_text},
    ]


def _normalize_candidate_offsets(raw: str, source_text: str) -> str:
    """Recompute a candidate's offsets from its own evidence_text.

    Language models return the correct verbatim evidence but miscount
    character offsets. When ``evidence_text`` is a genuine substring of
    the message, replace the model's offsets with its true position; the
    downstream strict validator still re-verifies the substring at the
    new offsets. Any parse issue leaves ``raw`` untouched so the strict
    parser rejects it. This searches for nothing the model did not
    supply and never edits the message or the evidence text.
    """
    if not isinstance(raw, str):
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(data, dict) or data.get("action") != "candidate":
        return raw
    evidence = data.get("evidence_text")
    if not isinstance(evidence, str) or not evidence:
        return raw
    index = source_text.find(evidence)
    if index < 0:
        return raw  # not a genuine substring: let the validator reject it
    data["start_offset"] = index
    data["end_offset"] = index + len(evidence)
    return json.dumps(data)


class QwenExtractionRunner:
    """Provider-neutral runner that performs one Qwen inference.

    Implements the existing ``LearnedExtractionRunner`` protocol so the
    learned controller does all parsing, validation, and fallback. Holds
    only a model provider — no store, no memories, no lifecycle state.
    """

    runner_id = QWEN_EXTRACTION_RUNNER_ID
    runner_version = QWEN_EXTRACTION_VERSION

    def __init__(self, provider, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._provider = provider
        self._timeout_ms = timeout_ms

    def availability(self) -> bool:
        """True when the provider is present and configured (offline-safe)."""
        if self._provider is None:
            return False
        configured = getattr(self._provider, "is_configured", True)
        return bool(configured)

    def run(
        self, request: LearnedExtractionRequest
    ) -> LearnedExtractionRunnerResult:
        if not self.availability():
            return LearnedExtractionRunnerResult(
                raw_output=None,
                runner_id=self.runner_id,
                runner_version=self.runner_version,
                available=False,
                status=RUNNER_UNAVAILABLE,
            )
        messages = build_extraction_messages(
            request.source_text, request.allowed_kinds
        )
        started = time.perf_counter()
        try:
            raw = self._provider.complete(messages)  # one inference, no retry
        except Exception as exc:  # noqa: BLE001 — contained; never crash the turn
            return LearnedExtractionRunnerResult(
                raw_output=None,
                runner_id=self.runner_id,
                runner_version=self.runner_version,
                available=True,
                status=RUNNER_ERROR,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                error_class=type(exc).__name__,
            )
        # Boundary correction: fix the model's miscounted offsets from its
        # own verbatim evidence before strict validation.
        raw = _normalize_candidate_offsets(raw, request.source_text)
        return LearnedExtractionRunnerResult(
            raw_output=raw,
            runner_id=self.runner_id,
            runner_version=self.runner_version,
            available=True,
            status=RUNNER_OK,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )


class QwenExtractionController:
    """Qwen-backed extraction controller behind the existing interface.

    Returns the exact ``ExtractionProposal`` the pipeline already accepts.
    Delegates to the learned pipeline for strict parse + grounded
    validation, then stamps the proposal with this controller's id.

    **No deterministic fallback.** The experiment measures Qwen against
    the deterministic baseline, so Qwen must speak for itself: an
    unavailable provider, an error, a timeout, or malformed output all
    produce an explicit non-candidate Qwen result (recorded in
    diagnostics as ``runner_status``/``outcome``) — never a deterministic
    proposal substituted on Qwen's behalf. Proposal-only: it persists
    nothing and holds no mutation authority. Inject a temperature-0,
    bounded-timeout provider for determinism.
    """

    controller_id = QWEN_EXTRACTION_CONTROLLER_ID

    def __init__(
        self,
        provider,
        *,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        self._runner = QwenExtractionRunner(provider, timeout_ms=timeout_ms)
        # FALLBACK_NONE: the learned pipeline never constructs or defers to
        # the deterministic controller, so every result here is genuinely
        # Qwen's own — candidate, model-none, or an explicit failure.
        self._inner = LearnedGroundedExtractionController(
            self._runner, fallback_mode=FALLBACK_NONE
        )

    def extract(self, evidence: ExtractionEvidence) -> ExtractionProposal:
        proposal = self._inner.extract(evidence)
        return replace(
            proposal,
            controller_id=self.controller_id,
            diagnostics={
                **proposal.diagnostics,
                "runner_id": QWEN_EXTRACTION_RUNNER_ID,
                "provider": "qwen_cloud",
            },
        )


def build_qwen_extraction_controller(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> QwenExtractionController:
    """Construct a controller backed by a temperature-0 Qwen provider.

    Determinism is enforced at construction: temperature 0 and a bounded
    timeout. Extraction therefore never inherits a chat provider's
    sampling settings — a caller passes connection settings (credentials,
    endpoint, model), not a provider instance. Requires credentials only
    when actually invoked; without them the runner reports unavailable
    and the controller returns an explicit non-candidate result (no
    deterministic substitution).
    """
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    provider = QwenCloudProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout_ms / 1000.0,
        temperature=0.0,
    )
    return QwenExtractionController(provider, timeout_ms=timeout_ms)
