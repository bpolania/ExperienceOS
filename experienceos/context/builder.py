"""Context builder.

Selects the most relevant active memories within a budget and assembles
the context messages sent to the model provider. Selection is
deterministic: keyword overlap with the current message, then kind
priority (instructions > facts > preferences), then recency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from experienceos.memory.schema import ExperienceEntry, MemoryKind

MEMORY_HEADER = "ExperienceOS retrieved these active user experiences:"
DEFAULT_MEMORY_BUDGET = 4

_KIND_SECTIONS = (
    (MemoryKind.PREFERENCE, "Preferences:"),
    (MemoryKind.FACT, "Facts:"),
    (MemoryKind.INSTRUCTION, "Instructions:"),
)

# Instructions guide behavior, facts anchor it, preferences flavor it.
_KIND_PRIORITY = {
    MemoryKind.INSTRUCTION: 2,
    MemoryKind.FACT: 1,
    MemoryKind.PREFERENCE: 0,
}

_SELECTION_STOPWORDS = frozenset(
    {
        "a", "an", "and", "the", "to", "of", "for", "with", "in", "on",
        "at", "is", "are", "be", "it", "me", "my", "i", "you", "we",
        "help", "please", "when", "that", "this",
    }
)


def _selection_words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in _SELECTION_STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        words.add(word)
    return words


@dataclass
class ContextSelectionRecord:
    """Why one candidate memory was selected or skipped."""

    memory_id: str
    text: str
    kind: str
    status: str
    selected: bool
    rank: int
    score: int
    matched_keywords: list[str]
    kind_priority: int
    reason: str


@dataclass
class ContextBuildResult:
    """Messages plus the selection decisions behind them."""

    messages: list[dict[str, str]]
    selected_memories: list[ExperienceEntry] = field(default_factory=list)
    skipped_memories: list[ExperienceEntry] = field(default_factory=list)
    candidate_memories: list[ExperienceEntry] = field(default_factory=list)
    memory_budget: int | None = None
    selection_records: list[ContextSelectionRecord] = field(default_factory=list)


class ContextBuilder:
    """Builds provider context messages for one interaction."""

    def __init__(self, memory_budget: int = DEFAULT_MEMORY_BUDGET):
        self.memory_budget = memory_budget

    def build_context(
        self,
        user_id: str,
        session_id: str,
        message: str,
        memories: list[ExperienceEntry] | None = None,
    ) -> ContextBuildResult:
        candidates = list(memories or [])
        ranked = self._rank_candidates(message, candidates)
        selected = [m for m, _, _ in ranked[: self.memory_budget]]
        skipped = [m for m, _, _ in ranked[self.memory_budget :]]
        records = [
            self._selection_record(rank, memory, matched, priority)
            for rank, (memory, matched, priority) in enumerate(ranked, start=1)
        ]

        context: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "ExperienceOS is active. Use any retrieved user "
                    "experience to personalize responses."
                ),
            }
        ]
        if selected:
            context.append(
                {
                    "role": "system",
                    "content": f"{MEMORY_HEADER}\n\n"
                    + "\n\n".join(self._kind_sections(selected)),
                }
            )
        return ContextBuildResult(
            messages=context,
            selected_memories=selected,
            skipped_memories=skipped,
            candidate_memories=candidates,
            memory_budget=self.memory_budget,
            selection_records=records,
        )

    def select_memories(
        self, message: str, candidates: list[ExperienceEntry]
    ) -> tuple[list[ExperienceEntry], list[ExperienceEntry]]:
        """Deterministically rank candidates and split at the budget."""
        ranked = [m for m, _, _ in self._rank_candidates(message, candidates)]
        return ranked[: self.memory_budget], ranked[self.memory_budget :]

    @staticmethod
    def _rank_candidates(
        message: str, candidates: list[ExperienceEntry]
    ) -> list[tuple[ExperienceEntry, list[str], int]]:
        """Candidates with their matched keywords and kind priority,
        sorted by relevance, kind priority, recency, then id."""
        message_words = _selection_words(message)
        scored = [
            (
                memory,
                sorted(_selection_words(memory.text) & message_words),
                _KIND_PRIORITY.get(memory.kind, 0),
            )
            for memory in candidates
        ]
        scored.sort(
            key=lambda entry: (
                -len(entry[1]),
                -entry[2],
                -entry[0].created_at.timestamp(),
                entry[0].id,
            )
        )
        return scored

    def _selection_record(
        self,
        rank: int,
        memory: ExperienceEntry,
        matched: list[str],
        priority: int,
    ) -> ContextSelectionRecord:
        selected = rank <= self.memory_budget
        if selected:
            match_part = (
                f"matched {', '.join(matched)}" if matched else "no keyword match"
            )
            reason = f"selected: {match_part}; {memory.kind} priority; within budget"
        else:
            reason = (
                f"skipped: budget reached after "
                f"{self.memory_budget} selected memories"
            )
        return ContextSelectionRecord(
            memory_id=memory.id,
            text=memory.text,
            kind=memory.kind,
            status=memory.status,
            selected=selected,
            rank=rank,
            score=len(matched),
            matched_keywords=matched,
            kind_priority=priority,
            reason=reason,
        )

    @staticmethod
    def _kind_sections(memories: list[ExperienceEntry]) -> list[str]:
        """Memories grouped under kind labels, known kinds first."""
        known_kinds = {kind for kind, _ in _KIND_SECTIONS}
        groups = [
            *_KIND_SECTIONS,
            *(((m.kind, f"{m.kind.capitalize()}:") for m in memories
               if m.kind not in known_kinds)),
        ]
        sections, rendered = [], set()
        for kind, label in groups:
            if kind in rendered:
                continue
            rendered.add(kind)
            group = [m for m in memories if m.kind == kind]
            if group:
                sections.append(
                    label + "\n" + "\n".join(f"- {m.text}" for m in group)
                )
        return sections
