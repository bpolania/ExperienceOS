"""Shared specialized-controller conventions (Phase 11, Prompt 6).

Controllers propose; the deterministic ExperienceOS kernel validates
and decides. Everything here supports proposal-only contracts: frozen
evidence snapshots, construction-validated proposals, bounded reasons,
JSON-safe diagnostics, and typed errors. Nothing in this package may
receive a store, engine, manager, bus, callback, or database session,
and no proposal is ever automatically applied.

Deliberately duplicated literals: memory kinds and lifecycle statuses
are mirrored here as plain tuples (matching
``experienceos.memory.schema``) so controller modules import nothing
from the memory layer — structural isolation over DRY.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

MAX_REASON_CHARS = 300
MAX_EVIDENCE_TEXT_CHARS = 2000
MAX_EXCERPT_CHARS = 200

RUNTIME_MODES = (
    "deterministic", "shadow", "offline", "optional_model", "unavailable",
)

# Mirrors of the kernel's vocabulary (never imported from the memory
# layer; see module docstring).
MEMORY_KINDS = ("preference", "fact", "instruction")
LIFECYCLE_STATUSES = ("active", "superseded", "forgotten")

SPAN_SOURCES = ("user", "assistant")


class ControllerError(RuntimeError):
    """Base for typed specialized-controller failures."""


class ControllerInputError(ControllerError):
    """Evidence violated its contract (bounds, IDs, enums, spans)."""


class ControllerProposalError(ControllerError):
    """A controller produced an invalid proposal."""


class ControllerUnavailableError(ControllerError):
    """An optional controller backend is not available."""


def bounded_text(text: str, limit: int = MAX_EVIDENCE_TEXT_CHARS) -> str:
    """Documented truncation for evidence text fields."""
    if not isinstance(text, str):
        raise ControllerInputError(
            f"text must be str, got {type(text).__name__}"
        )
    return text[:limit]


def validate_unit(name: str, value: float) -> float:
    """Finite value in [0, 1] (scores and confidences)."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ControllerProposalError(
            f"{name} must be finite in [0, 1], got {value!r}"
        )
    return float(value)


def validate_common_proposal(proposal) -> None:
    """Shared construction-time checks for every proposal model."""
    validate_unit("score", proposal.score)
    validate_unit("confidence", proposal.confidence)
    if not proposal.controller_id or not isinstance(
        proposal.controller_id, str
    ):
        raise ControllerProposalError(
            "controller_id must be a non-empty str"
        )
    if not isinstance(proposal.reason, str) or len(
        proposal.reason
    ) > MAX_REASON_CHARS:
        raise ControllerProposalError(
            f"reason must be a str of <= {MAX_REASON_CHARS} chars"
        )
    try:
        json.dumps(proposal.diagnostics)
    except (TypeError, ValueError) as exc:
        raise ControllerProposalError(
            f"diagnostics not JSON-serializable: {type(exc).__name__}"
        ) from exc
    if proposal.proposal_only is not True:
        raise ControllerProposalError(
            "controllers are proposal-only: proposal_only must be True"
        )


def validate_metadata(name: str, metadata: dict) -> dict:
    """Bounded, JSON-safe evidence metadata."""
    if not isinstance(metadata, dict):
        raise ControllerInputError(f"{name} must be a dict")
    try:
        json.dumps(metadata)
    except (TypeError, ValueError) as exc:
        raise ControllerInputError(
            f"{name} not JSON-serializable: {type(exc).__name__}"
        ) from exc
    return dict(metadata)


@dataclass(frozen=True)
class EvidenceSpan:
    """Grounding span over supplied source text (proposal schema for
    future grounded extraction; nothing in current production behavior
    creates these)."""

    source: str
    start: int
    end: int
    excerpt: str = ""
    text_digest: str | None = None

    def __post_init__(self):
        if self.source not in SPAN_SOURCES:
            raise ControllerInputError(
                f"span source must be one of {SPAN_SOURCES}"
            )
        if not isinstance(self.start, int) or not isinstance(
            self.end, int
        ):
            raise ControllerInputError("span offsets must be ints")
        if self.start < 0 or self.end <= self.start:
            raise ControllerInputError(
                "span requires 0 <= start < end"
            )
        if len(self.excerpt) > MAX_EXCERPT_CHARS:
            raise ControllerInputError(
                f"span excerpt exceeds {MAX_EXCERPT_CHARS} chars"
            )


@dataclass(frozen=True)
class MemorySnapshot:
    """Read-only view of one existing memory for controller evidence.

    A frozen primitive copy — never the live mutable record. Identity
    attribute/value/scope mirror the semantic-identity metadata when
    present.
    """

    memory_id: str
    kind: str
    text: str
    status: str
    tags: tuple = ()
    attribute: str = ""
    value: str = ""
    scope: str = ""

    def __post_init__(self):
        if not self.memory_id or not isinstance(self.memory_id, str):
            raise ControllerInputError("memory_id must be a non-empty str")
        if self.kind not in MEMORY_KINDS:
            raise ControllerInputError(
                f"kind must be one of {MEMORY_KINDS}, got {self.kind!r}"
            )
        if self.status not in LIFECYCLE_STATUSES:
            raise ControllerInputError(
                f"status must be one of {LIFECYCLE_STATUSES}, got "
                f"{self.status!r}"
            )
        object.__setattr__(self, "text", bounded_text(self.text))
        object.__setattr__(self, "tags", tuple(self.tags))
