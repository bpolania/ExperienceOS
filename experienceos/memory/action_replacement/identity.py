"""Deterministic action identity for replacement matching.

Three identities are kept strictly separate, because the seam audit
(`docs/action_replacement_seam_audit.md` §16.9) proved that conflating
them is exactly how the wrong action gets suppressed:

* **semantic identity** — subject / attribute / value / scope, produced
  by :mod:`experienceos.memory.identity`. It answers "do these two
  statements name the same experience?" and is never computed here.
* **action-content identity** — a deterministic digest over the
  immutable content of one :class:`MemoryAction`. It answers "are these
  the same action?" Two actions with equivalent normalized content share
  it; a semantic duplicate with different surface text does **not**.
* **occurrence identity** — content digest + position in a specific
  action list + that list's digest. It answers "which occurrence?", so
  two identical creates in one list are never confused.

This module is pure: it reads immutable action content and returns
immutable values. It touches no store, engine, manager, model, or
network, and it never mutates its inputs. Mutable fields (ids,
timestamps) are deliberately excluded so a digest that later binds
authorization stays stable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from experienceos.memory.planner import MemoryAction, _normalized_text

ACTION_IDENTITY_VERSION = "1"

#: Provenance labels for a diagnostic candidate. Provenance is not a
#: field on ``MemoryAction`` (the seam audit proved it disappears after
#: append); the caller establishes it by which list an action arrives in.
CANDIDATE_PLANNER = "planner"
CANDIDATE_EXTRACTION = "extraction"
CANDIDATE_TRANSITION = "transition"
CANDIDATE_OTHER = "other"


def _content_payload(action: MemoryAction) -> dict:
    """The immutable, mutable-field-free content of one action.

    Scope is read from ``metadata['scope']`` when present. It is included
    because two creates that differ only by scope are valid coexistence,
    not duplicates, and must not collide (seam audit §16.9). Absent scope
    serializes as ``null`` — deterministically, the same as an explicit
    ``None``.
    """
    return {
        "action": action.action,
        "kind": action.kind,
        "normalized_text": _normalized_text(action.text or ""),
        "memory_id": action.memory_id,
        "replaces": action.replaces,
        "scope": (action.metadata or {}).get("scope"),
        "version": ACTION_IDENTITY_VERSION,
    }


def action_content_digest(action: MemoryAction) -> str:
    """Deterministic digest over one action's immutable content.

    Serialization is key-order independent (``sort_keys``); no mutable
    field participates; it is **not** a semantic identity.
    """
    payload = _content_payload(action)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def action_list_digest(actions) -> str:
    """Digest binding an ordered list of actions.

    Occurrence identity is only meaningful relative to a specific list;
    this digest pins that list so an occurrence index cannot be replayed
    against a different composition.
    """
    joined = "|".join(action_content_digest(a) for a in actions)
    return hashlib.sha256(joined.encode()).hexdigest()


@dataclass(frozen=True)
class OccurrenceIdentity:
    """Which occurrence of an action, within which list.

    Distinguishes two byte-identical actions by position. ``create A``
    followed by ``create A`` yields two occurrences with the same
    ``content_digest`` and different ``occurrence_index``.
    """

    content_digest: str
    occurrence_index: int
    action_list_digest: str

    def to_record(self) -> dict:
        return {
            "content_digest": self.content_digest,
            "occurrence_index": self.occurrence_index,
            "action_list_digest": self.action_list_digest,
        }


@dataclass(frozen=True)
class PlannerActionIdentity:
    """The three identities of one planner action, kept separate.

    ``semantic_key`` is the projected slot+value key from the identity
    layer (``None`` when the statement is outside the bounded lexicon).
    It is carried for diagnostics and must never be used as the action
    identity, nor the reverse.
    """

    content_digest: str
    occurrence: OccurrenceIdentity
    semantic_key: str | None

    def to_record(self) -> dict:
        return {
            "content_digest": self.content_digest,
            "occurrence": self.occurrence.to_record(),
            "semantic_key": self.semantic_key,
        }


def occurrence_identity(
    action: MemoryAction, index: int, list_digest: str
) -> OccurrenceIdentity:
    return OccurrenceIdentity(
        content_digest=action_content_digest(action),
        occurrence_index=index,
        action_list_digest=list_digest,
    )


def planner_action_identity(
    action: MemoryAction, index: int, list_digest: str, *, semantic_key: str | None
) -> PlannerActionIdentity:
    """Build the composite identity for a planner action.

    ``semantic_key`` is supplied by the caller (which owns the identity
    projector) so this module keeps no projection dependency and stays
    trivially pure.
    """
    return PlannerActionIdentity(
        content_digest=action_content_digest(action),
        occurrence=occurrence_identity(action, index, list_digest),
        semantic_key=semantic_key,
    )
