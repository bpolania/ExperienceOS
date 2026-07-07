"""Experience compression: groups of related active memories become one
compact summary for context.

Compression is a context-assembly behavior, not a memory lifecycle
behavior: source memories stay in storage unchanged, and only active
memories that were already selected for context are ever compressed.
Grouping and summary text are deterministic and template-based — no
model calls, no embeddings.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from experienceos.memory.schema import ExperienceEntry, MemoryKind

TRAVEL_DOMAIN = "travel"
TRAVEL_MIN_GROUP_SIZE = 2
GENERIC_MIN_GROUP_SIZE = 3

# A memory joins the travel group when any of these terms appears in its
# text (plural-folded, hyphens preserved so "red-eye" matches).
_TRAVEL_TERMS = frozenset(
    {
        "travel", "flight", "airport", "seat", "timing", "transfer",
        "hotel", "planning", "plan", "trip", "aisle", "window",
        "red-eye", "layover", "airline", "boarding",
    }
)

_PREF_CLAUSES = (
    ("Prefers ", "prefer "),
    ("Likes ", "like "),
    ("Dislikes ", "avoid "),
)


def _words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[a-z0-9-]+", text.lower()):
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        words.add(word)
    return words


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:] if text else text


def _capitalize_first(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


@dataclass
class ExperienceSummary:
    """One compact summary standing in for a group of related memories."""

    text: str
    domain: str
    source_memory_ids: list[str]
    source_texts: list[str]
    reason: str
    original_chars: int
    compressed_chars: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def saved_chars(self) -> int:
        return self.original_chars - self.compressed_chars

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "domain": self.domain,
            "source_memory_ids": list(self.source_memory_ids),
            "source_texts": list(self.source_texts),
            "reason": self.reason,
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "saved_chars": self.saved_chars,
        }


class ExperienceCompressor:
    """Deterministically groups related active memories into summaries.

    Travel-related memories form one group (two or more members);
    remaining memories fall back to per-kind groups (three or more
    members). Groups whose summary does not actually shrink the rendered
    context are discarded by the context builder.
    """

    def compress(self, memories: list[ExperienceEntry]) -> list[ExperienceSummary]:
        travel, rest = [], []
        for memory in memories:
            (travel if self._is_travel(memory) else rest).append(memory)

        summaries: list[ExperienceSummary] = []
        if len(travel) >= TRAVEL_MIN_GROUP_SIZE:
            summaries.append(self._travel_summary(travel))

        by_kind: dict[str, list[ExperienceEntry]] = {}
        for memory in rest:
            by_kind.setdefault(memory.kind, []).append(memory)
        for kind, group in by_kind.items():
            if len(group) >= GENERIC_MIN_GROUP_SIZE:
                summaries.append(self._generic_summary(kind, group))
        return summaries

    @staticmethod
    def _is_travel(memory: ExperienceEntry) -> bool:
        return bool(_words(memory.text) & _TRAVEL_TERMS)

    def _travel_summary(self, group: list[ExperienceEntry]) -> ExperienceSummary:
        facts = [m for m in group if m.kind == MemoryKind.FACT]
        others = [m for m in group if m.kind != MemoryKind.FACT]
        sentences = [self._fact_sentence(m.text) for m in facts]
        clauses = [self._clause(m.text) for m in others]
        if clauses:
            sentences.append(self._join_clauses(clauses))
        text = "Travel experience summary:\n" + " ".join(sentences)
        return self._build(TRAVEL_DOMAIN, group, text)

    def _generic_summary(
        self, kind: str, group: list[ExperienceEntry]
    ) -> ExperienceSummary:
        clauses = [self._clause(m.text) for m in group]
        text = (
            f"{kind.capitalize()} experience summary:\n"
            + self._join_clauses(clauses)
        )
        return self._build(kind, group, text)

    @staticmethod
    def _build(
        domain: str, group: list[ExperienceEntry], text: str
    ) -> ExperienceSummary:
        # Approximate the space the group would occupy rendered
        # individually: kind section labels, one bullet line per memory,
        # and blank lines between sections.
        kinds = {m.kind for m in group}
        original = (
            sum(len(f"{kind.capitalize()}:") + 1 for kind in kinds)
            + sum(len(f"- {m.text}") + 1 for m in group)
            + max(0, (len(kinds) - 1) * 2)
        )
        return ExperienceSummary(
            text=text,
            domain=domain,
            source_memory_ids=[m.id for m in group],
            source_texts=[m.text for m in group],
            reason=(
                f"Grouped {len(group)} related {domain} memories into one "
                f"compact summary to save context space."
            ),
            original_chars=original,
            compressed_chars=len(text),
        )

    @staticmethod
    def _fact_sentence(text: str) -> str:
        if text.startswith(("Works ", "Lives ", "Based ")):
            return f"The user {_lower_first(text)}"
        return f"The user's {_lower_first(text)}"

    @staticmethod
    def _clause(text: str) -> str:
        for prefix, replacement in _PREF_CLAUSES:
            if text.startswith(prefix):
                return replacement + _lower_first(text[len(prefix):]).rstrip(".")
        return _lower_first(text).rstrip(".")

    @staticmethod
    def _join_clauses(clauses: list[str]) -> str:
        if len(clauses) == 1:
            return f"{_capitalize_first(clauses[0])}."
        joined = ", ".join(clauses[:-1])
        if len(clauses) > 2:
            joined += ","
        return f"{_capitalize_first(joined)} and {clauses[-1]}."
