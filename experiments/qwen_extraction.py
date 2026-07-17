"""Qwen-backed grounded extraction controller (experimental, shadow-only).

A thin adapter that asks the same narrow question as the deterministic
extractor — *does this interaction contain one durable, user-grounded
experience candidate?* — but sources the structured answer from Qwen
Cloud instead of deterministic rules. It reuses the entire existing
learned-extraction pipeline: the model returns strict JSON, ExperienceOS
treats it as untrusted, strictly parses it, and only returns a candidate
if the existing ``GroundedCandidateValidator`` accepts it.

This adds no new schema, no new lifecycle, no new storage, and no new
mutation authority. The deterministic controller remains canonical and
the fallback; the Qwen path is optional, non-canonical, and does exactly
one temperature-0 inference with no retries and a bounded timeout. It is
not wired into memory creation here.

It lives outside ``experienceos/`` on purpose: the core package stays
provider-neutral and free of learned-path references, and this whole
experiment is removable by deleting the ``experiments/`` directory.
"""

from __future__ import annotations

import time
from dataclasses import replace

from experienceos.controllers.extraction import (
    ExtractionEvidence,
    ExtractionProposal,
)
from experienceos.memory.extraction import VALID_CANDIDATE_KINDS
from experienceos.memory.learned_extraction import (
    FALLBACK_ON_UNAVAILABLE,
    RUNNER_ERROR,
    RUNNER_OK,
    RUNNER_UNAVAILABLE,
    LearnedExtractionRequest,
    LearnedExtractionRunnerResult,
    LearnedGroundedExtractionController,
)

QWEN_EXTRACTION_RUNNER_ID = "qwen_extraction_runner-1"
QWEN_EXTRACTION_CONTROLLER_ID = "grounded_qwen_shadow-1"
QWEN_EXTRACTION_VERSION = "1"

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
    "kind; normalized_text (a concise canonical statement); evidence_text "
    "(the VERBATIM substring of the user message that grounds it); "
    "start_offset and end_offset (character offsets of evidence_text within "
    "the user message); confidence in [0,1]; a short reason.\n"
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
    Delegates to the learned controller (strict parse + grounded
    validation) and stamps the proposal with this controller's id so
    shadow comparison can attribute it to the Qwen path. Proposal-only:
    it persists nothing and holds no mutation authority. The provider is
    injected; inject a temperature-0, bounded-timeout provider for
    determinism.
    """

    controller_id = QWEN_EXTRACTION_CONTROLLER_ID

    def __init__(
        self,
        provider,
        *,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        fallback_mode: str = FALLBACK_ON_UNAVAILABLE,
    ):
        self._runner = QwenExtractionRunner(provider, timeout_ms=timeout_ms)
        self._inner = LearnedGroundedExtractionController(
            self._runner, fallback_mode=fallback_mode
        )

    def extract(self, evidence: ExtractionEvidence) -> ExtractionProposal:
        proposal = self._inner.extract(evidence)
        diagnostics = {
            **proposal.diagnostics,
            "runner_id": QWEN_EXTRACTION_RUNNER_ID,
            "provider": "qwen_cloud",
        }
        # A deterministic fallback proposal is NOT a Qwen proposal: keep
        # the fallback controller's attribution so shadow comparison never
        # over-credits the Qwen path.
        if proposal.diagnostics.get("fallback_used"):
            return replace(proposal, diagnostics=diagnostics)
        return replace(
            proposal, controller_id=self.controller_id, diagnostics=diagnostics
        )


def build_qwen_extraction_controller(
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    fallback_mode: str = FALLBACK_ON_UNAVAILABLE,
) -> QwenExtractionController:
    """Construct a controller backed by a temperature-0 Qwen provider.

    Determinism is enforced at construction: temperature 0 and a bounded
    timeout. Requires credentials only when actually invoked; without
    them the runner reports unavailable and the controller falls back to
    the deterministic extractor.
    """
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    provider = QwenCloudProvider(
        api_key=api_key,
        model=model,
        timeout=timeout_ms / 1000.0,
        temperature=0.0,
    )
    return QwenExtractionController(
        provider, timeout_ms=timeout_ms, fallback_mode=fallback_mode
    )
