"""Pure action-list projection for replacement plans.

Given the original canonical planner action list, the index of the
uniquely matched conflicting create, and the transition replacement
sequence, this module computes — without mutating anything — the action
list that *would* result if replacement were later authorized:

    walk the original in order; at the matched occurrence, insert the
    transition sequence in place of the matched create; preserve
    everything else, in order.

It performs no matching, no semantic projection, no store or engine
access, and no mutation. It relies only on the deterministic
action-content and occurrence identities from :mod:`.identity`. The
"scope" it records for each occurrence is the structural
``metadata['scope']`` used by the content digest, never a re-projected
semantic scope — semantic scope was already decided by the matcher.
"""

from __future__ import annotations

from dataclasses import dataclass

from experienceos.memory.planner import _normalized_text
from experienceos.memory.action_replacement.identity import (
    OccurrenceIdentity,
    action_content_digest,
    action_list_digest,
    occurrence_identity,
)

CLASSIFICATION_PRESERVED = "preserved"
CLASSIFICATION_SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class PlannedActionOccurrence:
    """One original planner action as an immutable occurrence record."""

    original_index: int
    content_digest: str
    occurrence: OccurrenceIdentity
    action_type: str
    kind: str
    normalized_text: str
    scope: str | None
    memory_id: str | None
    replaces: str | None
    classification: str

    def to_record(self) -> dict:
        return {
            "original_index": self.original_index,
            "content_digest": self.content_digest,
            "occurrence": self.occurrence.to_record(),
            "action_type": self.action_type,
            "kind": self.kind,
            "normalized_text": self.normalized_text,
            "scope": self.scope,
            "memory_id": self.memory_id,
            "replaces": self.replaces,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class ActionListProjection:
    """The projected action list plus the identities that produced it."""

    original_occurrences: tuple
    projected_actions: tuple
    original_digest: str
    projected_digest: str
    insertion_index: int
    inserted_digests: tuple

    def to_record(self) -> dict:
        return {
            "original_occurrences": [o.to_record() for o in self.original_occurrences],
            "original_digest": self.original_digest,
            "projected_digest": self.projected_digest,
            "insertion_index": self.insertion_index,
            "inserted_digests": list(self.inserted_digests),
        }


@dataclass(frozen=True)
class ActionListRewriteResult:
    """The full accounting of one projected rewrite."""

    projection: ActionListProjection
    preserved_occurrences: tuple
    suppressed_occurrence: OccurrenceIdentity
    original_count: int
    suppressed_count: int
    inserted_count: int
    projected_count: int

    def to_record(self) -> dict:
        return {
            "projection": self.projection.to_record(),
            "preserved_occurrences": [o.to_record() for o in self.preserved_occurrences],
            "suppressed_occurrence": self.suppressed_occurrence.to_record(),
            "original_count": self.original_count,
            "suppressed_count": self.suppressed_count,
            "inserted_count": self.inserted_count,
            "projected_count": self.projected_count,
        }


def _scope_of(action) -> str | None:
    return (action.metadata or {}).get("scope")


def build_occurrences(actions, list_digest: str, suppressed_index: int):
    """Immutable occurrence records for every original action.

    ``suppressed_index`` marks the one matched conflict; every other
    action is classified preserved. Deterministic; uses no object
    identity and no ``id()``.
    """
    records = []
    for index, action in enumerate(actions):
        records.append(
            PlannedActionOccurrence(
                original_index=index,
                content_digest=action_content_digest(action),
                occurrence=occurrence_identity(action, index, list_digest),
                action_type=action.action,
                kind=action.kind,
                normalized_text=_normalized_text(action.text or ""),
                scope=_scope_of(action),
                memory_id=action.memory_id,
                replaces=action.replaces,
                classification=(
                    CLASSIFICATION_SUPPRESSED
                    if index == suppressed_index
                    else CLASSIFICATION_PRESERVED
                ),
            )
        )
    return tuple(records)


def project_rewrite(
    original_actions, matched_index: int, transition_sequence
) -> ActionListRewriteResult:
    """Project the rewrite. Pure: never mutates ``original_actions``.

    The matched create at ``matched_index`` is replaced in place by the
    complete ``transition_sequence``; all other actions keep their order.
    """
    original = tuple(original_actions)
    sequence = tuple(transition_sequence)
    list_digest = action_list_digest(original)
    occurrences = build_occurrences(original, list_digest, matched_index)

    projected: list = []
    for index, action in enumerate(original):
        if index == matched_index:
            projected.extend(sequence)  # insert in place of the matched create
        else:
            projected.append(action)
    projected_tuple = tuple(projected)

    projection = ActionListProjection(
        original_occurrences=occurrences,
        projected_actions=projected_tuple,
        original_digest=list_digest,
        projected_digest=action_list_digest(projected_tuple),
        insertion_index=matched_index,
        inserted_digests=tuple(action_content_digest(a) for a in sequence),
    )
    preserved = tuple(
        o.occurrence
        for o in occurrences
        if o.classification == CLASSIFICATION_PRESERVED
    )
    suppressed = next(
        o.occurrence
        for o in occurrences
        if o.classification == CLASSIFICATION_SUPPRESSED
    )
    return ActionListRewriteResult(
        projection=projection,
        preserved_occurrences=preserved,
        suppressed_occurrence=suppressed,
        original_count=len(original),
        suppressed_count=1,
        inserted_count=len(sequence),
        projected_count=len(projected_tuple),
    )
