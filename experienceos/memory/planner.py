"""Rule-based memory planner: deterministic preference detection and
conflict-driven superseding.

The planner is a seam: an alternative planner with smarter extraction
can replace it without touching the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from experienceos.memory.schema import ExperienceEntry, MemoryKind

CREATE = "create"
SUPERSEDE = "supersede"

# "I prefer X", "I like X", "I don't like X", optionally prefixed with
# "Remember (that) ...". Change phrasings like "Actually, I prefer X now"
# match too — leading words are ignored and trailing modifiers stripped.
_PREFERENCE_PATTERN = re.compile(
    r"(?:\bremember\s+(?:that\s+)?)?"
    r"\bi\s+(?P<verb>prefer|like|love|enjoy|don'?t\s+like|dislike|hate|avoid)\s+"
    r"(?P<object>[^.!?\n;]+)",
    re.IGNORECASE,
)

_TRAILING_MODIFIERS = re.compile(
    r"\s+(now|instead|these days|going forward|from now on)$", re.IGNORECASE
)

_POSITIVE_TEMPLATES = {
    "prefer": "Prefers {}.",
    "like": "Likes {}.",
    "love": "Likes {}.",
    "enjoy": "Likes {}.",
}
_NEGATIVE_TEMPLATE = "Dislikes {}."
_POSITIVE_PREFIXES = ("Prefers ", "Likes ")

# Known preference domains for deterministic conflict detection. Two
# active preferences in the same domain (with the same polarity) conflict.
_DOMAIN_TERMS = {
    "seat": ("aisle seat", "window seat", "middle seat"),
    "flight_time": (
        "morning flight",
        "afternoon flight",
        "evening flight",
        "red-eye",
    ),
    "hotel": ("quiet hotel", "hotel near the office", "hotels near the office"),
}


def preference_domain(text: str) -> str | None:
    """Classify a memory text into a known preference domain, if any."""
    lowered = text.lower()
    for domain, terms in _DOMAIN_TERMS.items():
        if any(term in lowered for term in terms):
            return domain
    return None


def _is_positive(text: str) -> bool:
    return text.startswith(_POSITIVE_PREFIXES)


@dataclass(frozen=True)
class MemoryAction:
    """One planned memory operation: a creation or a supersede."""

    action: str
    kind: str = MemoryKind.PREFERENCE
    text: str = ""
    memory_id: str | None = None  # supersede target
    replaces: str | None = None  # for creates that replace an old memory
    reason: str | None = None


class MemoryPlanner:
    """Plans memory actions from a user message and existing active memories."""

    def plan_memory_actions(
        self,
        user_id: str,
        session_id: str,
        message: str,
        existing: list[ExperienceEntry] | None = None,
    ) -> list[MemoryAction]:
        existing = existing or []
        existing_texts = {m.text for m in existing}
        actions: list[MemoryAction] = []

        for text in self._detect_preference_texts(message):
            if text in existing_texts:
                continue
            conflict = self._find_conflict(text, existing)
            if conflict is not None:
                domain = preference_domain(text)
                actions.append(
                    MemoryAction(
                        action=SUPERSEDE,
                        memory_id=conflict.id,
                        text=conflict.text,
                        reason=f"Conflicts with new {domain} preference.",
                    )
                )
            actions.append(
                MemoryAction(
                    action=CREATE,
                    kind=MemoryKind.PREFERENCE,
                    text=text,
                    replaces=conflict.id if conflict else None,
                    reason="User changed preference." if conflict else None,
                )
            )
        return actions

    def _detect_preference_texts(self, message: str) -> list[str]:
        texts: list[str] = []
        for match in _PREFERENCE_PATTERN.finditer(message):
            verb = re.sub(r"\s+", " ", match.group("verb").lower())
            template = _POSITIVE_TEMPLATES.get(verb, _NEGATIVE_TEMPLATE)
            for item in self._split_items(match.group("object")):
                texts.append(template.format(item))
        return texts

    @staticmethod
    def _find_conflict(
        text: str, existing: list[ExperienceEntry]
    ) -> ExperienceEntry | None:
        """First active memory in the same known domain with the same polarity.

        Unknown domains never conflict — false negatives beat confusing
        false positives in a demo.
        """
        domain = preference_domain(text)
        if domain is None:
            return None
        for memory in existing:
            if (
                memory.kind == MemoryKind.PREFERENCE
                and memory.text != text
                and preference_domain(memory.text) == domain
                and _is_positive(memory.text) == _is_positive(text)
            ):
                return memory
        return None

    @staticmethod
    def _split_items(object_phrase: str) -> list[str]:
        """Split "aisle seats, quiet hotels and morning flights" into items."""
        items = re.split(r",\s*|\s+and\s+", object_phrase.strip())
        cleaned = []
        for item in items:
            item = item.strip().rstrip(".!?,")
            item = _TRAILING_MODIFIERS.sub("", item)
            if item:
                cleaned.append(item)
        return cleaned
