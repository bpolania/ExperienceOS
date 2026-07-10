"""Deterministic logical-reference resolution for evaluation.

Maps the oracle's logical memory references onto runtime evidence
(final-state entries, candidates, applied actions) by match terms.
Strictly observational: runs after execution, never alters system
state, ranking, or responses. Ambiguity and non-resolution are
explicit outcomes that produce evaluation errors for affected
metrics — never a fabricated or silently-chosen match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Resolution:
    logical_id: str
    memory_ids: tuple[str, ...]
    status: str  # resolved | unresolved | ambiguous

    def to_payload(self) -> dict:
        return {
            "memory_ids": list(self.memory_ids),
            "status": self.status,
        }


def matches_ref(ref, text: str) -> bool:
    body = text.lower()
    return bool(ref.match_terms) and all(
        term.lower() in body for term in ref.match_terms
    )


def resolve_ref(ref, entries) -> Resolution:
    """Resolve one reference against (memory_id, text) pairs.

    Exactly one match = resolved; zero = unresolved; multiple =
    ambiguous (distinct versioned records must use distinguishing
    terms in the oracle — the resolver never picks one).
    """
    if ref.memory_id is not None:
        matched = tuple(
            mid for mid, _ in entries if mid == ref.memory_id
        )
        status = "resolved" if len(matched) == 1 else (
            "unresolved" if not matched else "ambiguous"
        )
        return Resolution(ref.logical_id, matched, status)
    matched = tuple(
        mid for mid, text in entries if matches_ref(ref, text)
    )
    if len(matched) == 1:
        return Resolution(ref.logical_id, matched, "resolved")
    if not matched:
        return Resolution(ref.logical_id, (), "unresolved")
    return Resolution(ref.logical_id, matched, "ambiguous")


def entries_of(snapshot_entries):
    return [(e.memory_id, e.text) for e in snapshot_entries]


def candidate_entries(turn):
    return [(c.memory_id, c.text) for c in turn.candidates]
