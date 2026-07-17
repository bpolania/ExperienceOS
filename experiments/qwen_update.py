"""Qwen-backed update-intelligence controller (experimental).

Answers one narrow question about a durable candidate against the
already-active memories: is it genuinely new, does it change/replace an
existing memory, do the two coexist, is it a duplicate, or should it
produce no durable memory at all? Qwen sources the structured answer;
ExperienceOS treats that answer as untrusted and strictly validates it.

Like the Qwen extraction controller this is provider-backed and kept
outside ``experienceos/`` so the core stays provider-neutral. It
**classifies and proposes only**: it holds no store, engine, manager, or
mutation authority, never applies a transition, never authorizes one,
and never selects an action after a deterministic rejection. Every
downstream deterministic gate — grounded validation, transition
validation, lifecycle authority, persistence — remains authoritative and
unchanged.

One temperature-0 inference per candidate, a bounded timeout, and no
fallback: an unavailable provider, an error, a timeout, or malformed
output is an explicit bounded failure, never a deterministic proposal
substituted on Qwen's behalf. A provider failure is recorded separately
from a rejected (invalid) classification.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

QWEN_UPDATE_CONTROLLER_ID = "qwen_update-1"
QWEN_UPDATE_RUNNER_ID = "qwen_update_runner-1"
#: One fixed committed prompt version; recorded in the benchmark evidence.
QWEN_UPDATE_PROMPT_VERSION = "1"

DEFAULT_TIMEOUT_MS = 8000

# The five allowed classifications. Only UPDATE carries a target.
NEW = "NEW"
UPDATE = "UPDATE"
COEXIST = "COEXIST"
DUPLICATE = "DUPLICATE"
IGNORE = "IGNORE"
UPDATE_CLASSIFICATIONS = (NEW, UPDATE, COEXIST, DUPLICATE, IGNORE)

# Bounded outcome statuses. A provider failure is kept distinct from an
# invalid classification so the benchmark can report them separately.
STATUS_OK = "ok"
STATUS_PROVIDER_UNAVAILABLE = "provider_unavailable"
STATUS_PROVIDER_ERROR = "provider_error"
STATUS_INVALID_OUTPUT = "invalid_output"

_ALLOWED_KEYS = frozenset({"classification", "target_memory_id"})

_DEFINITIONS = (
    "Classify one durable candidate memory against the user's already-"
    "active memories. Reply with ONE JSON object and nothing else — no "
    "prose, no markdown, no code fences.\n"
    "\n"
    "classification is exactly one of:\n"
    "- NEW: durable information not already represented; replaces nothing.\n"
    "- UPDATE: changes, corrects, reverses, or supersedes exactly one "
    "existing memory.\n"
    "- COEXIST: related to an existing memory but both stay independently "
    "valid.\n"
    "- DUPLICATE: semantically equivalent to an active memory; creates no "
    "new memory.\n"
    "- IGNORE: should not produce any durable memory (questions, "
    "hypotheticals, temporary states, one-off requests, unsupported "
    "claims).\n"
    "\n"
    "Rules:\n"
    "- For UPDATE, set target_memory_id to the id of the single existing "
    "memory being replaced; it MUST be one of the listed ids. Never "
    "invent an id.\n"
    "- For NEW, COEXIST, DUPLICATE, and IGNORE, target_memory_id MUST be "
    "null.\n"
    "- Output only the two keys classification and target_memory_id.\n"
)

_SCHEMA = (
    'Schema: {"classification": "NEW"|"UPDATE"|"COEXIST"|"DUPLICATE"|'
    '"IGNORE", "target_memory_id": string|null}'
)


@dataclass(frozen=True)
class ActiveMemoryView:
    """One active memory offered to the controller as a possible target."""

    memory_id: str
    kind: str
    text: str


@dataclass(frozen=True)
class UpdateClassificationResult:
    """Bounded classification outcome — never an applied update.

    ``classification`` is one of the five values on success, else None.
    ``failed`` is true only for a provider failure (unavailable, error,
    timeout), which is kept distinct from an invalid structured output.
    ``diagnostics`` holds bounded metadata only: it never carries source
    text, candidate text, active-memory text, secrets, or a provider
    exception message.
    """

    classification: str | None
    target_memory_id: str | None
    controller_id: str
    status: str
    failed: bool
    latency_ms: float = 0.0
    diagnostics: dict = field(default_factory=dict)

    @property
    def proposal_only(self) -> bool:
        return True


def build_update_messages(
    message: str,
    candidate_text: str,
    candidate_kind: str | None,
    active_memories,
) -> list:
    """Deterministic message list for one update-classification inference.

    Exposes only what the decision needs: the definitions, the new user
    message, the normalized candidate, and the bounded active-memory
    records with their real ids. No lifecycle, persistence, or
    authorization internals are shown.
    """
    kind = candidate_kind or "unknown"
    lines = [
        f"New user message: {message}",
        f"Candidate memory (kind={kind}): {candidate_text}",
        "",
        "Active memories:",
    ]
    if active_memories:
        for view in active_memories:
            lines.append(f"- id={view.memory_id} (kind={view.kind}): {view.text}")
    else:
        lines.append("- (none)")
    return [
        {"role": "system", "content": _DEFINITIONS + "\n" + _SCHEMA},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_update_output(raw, allowed_ids) -> tuple:
    """Strictly parse and validate one classification.

    Returns ``(classification, target_memory_id, error)``. ``error`` is
    None on success; otherwise classification/target are None and the
    caller records ``invalid_output``. Enforces: single JSON object; only
    the two allowed keys; a valid classification; UPDATE carries exactly
    one target drawn from ``allowed_ids``; every other class carries no
    target. Fabricated or unknown ids are rejected.
    """
    if not isinstance(raw, str):
        return None, None, "non_string_output"
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None, None, "malformed_json"
    if not isinstance(data, dict):
        return None, None, "not_an_object"
    extra = set(data.keys()) - _ALLOWED_KEYS
    if extra:
        return None, None, "unexpected_keys"
    classification = data.get("classification")
    if classification not in UPDATE_CLASSIFICATIONS:
        return None, None, "unknown_classification"
    target = data.get("target_memory_id")
    if classification == UPDATE:
        if not isinstance(target, str) or not target:
            return None, None, "missing_target"
        if target not in allowed_ids:
            return None, None, "fabricated_target"
        return UPDATE, target, None
    if target is not None:
        return None, None, "unexpected_target"
    return classification, None, None


class QwenUpdateController:
    """Qwen-backed update classifier. Classify-and-propose only.

    Holds only a model provider and a bounded timeout — no store, engine,
    manager, bus, credentials path, or mutation callback. Inject a
    temperature-0, bounded-timeout provider for determinism.
    """

    controller_id = QWEN_UPDATE_CONTROLLER_ID
    prompt_version = QWEN_UPDATE_PROMPT_VERSION

    def __init__(self, provider, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._provider = provider
        self._timeout_ms = timeout_ms

    def _available(self) -> bool:
        if self._provider is None:
            return False
        return bool(getattr(self._provider, "is_configured", True))

    def _result(self, classification, target, status, failed, latency_ms,
                error=None):
        diagnostics = {
            "controller_id": self.controller_id,
            "runner_id": QWEN_UPDATE_RUNNER_ID,
            "prompt_version": self.prompt_version,
            "provider": "qwen_cloud",
            "status": status,
        }
        if error is not None:
            # A bounded reason label only — never message text.
            diagnostics["reason"] = error
        return UpdateClassificationResult(
            classification=classification,
            target_memory_id=target,
            controller_id=self.controller_id,
            status=status,
            failed=failed,
            latency_ms=latency_ms,
            diagnostics=diagnostics,
        )

    def classify(
        self,
        *,
        message: str,
        candidate_text: str,
        candidate_kind: str | None,
        active_memories,
    ) -> UpdateClassificationResult:
        active = tuple(active_memories or ())
        if not self._available():
            return self._result(
                None, None, STATUS_PROVIDER_UNAVAILABLE, True, 0.0
            )
        messages = build_update_messages(
            message, candidate_text, candidate_kind, active
        )
        started = time.perf_counter()
        try:
            raw = self._provider.complete(messages)  # one inference, no retry
        except Exception as exc:  # noqa: BLE001 — contained; never crash the turn
            # error_class is a type name only; the message may echo input.
            return self._result(
                None, None, STATUS_PROVIDER_ERROR, True,
                (time.perf_counter() - started) * 1000.0,
                error=type(exc).__name__,
            )
        elapsed = (time.perf_counter() - started) * 1000.0
        allowed_ids = frozenset(v.memory_id for v in active)
        classification, target, error = parse_update_output(raw, allowed_ids)
        if error is not None:
            return self._result(
                None, None, STATUS_INVALID_OUTPUT, False, elapsed, error=error
            )
        return self._result(classification, target, STATUS_OK, False, elapsed)


def build_qwen_update_controller(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> QwenUpdateController:
    """Construct a controller backed by a temperature-0 Qwen provider.

    Determinism is enforced at construction (temperature 0, bounded
    timeout), matching the validated temperature-0 extraction pattern;
    the update path never inherits chat sampling settings. Credentials
    are read only when a call is actually made.
    """
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    provider = QwenCloudProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout_ms / 1000.0,
        temperature=0.0,
    )
    return QwenUpdateController(provider, timeout_ms=timeout_ms)
