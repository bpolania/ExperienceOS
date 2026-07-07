"""Deterministic domain/tag classification for memories.

Simple keyword rules assign tags when memories are created, so
retrieval, selection explanations, and the dashboard can say *why* a
piece of experience mattered for a request. No taxonomy engine, no
model calls.
"""

from __future__ import annotations

import re

# Canonical ordering for deterministic tag lists.
TAG_ORDER = (
    "travel",
    "flight",
    "seat",
    "airport",
    "hotel",
    "timing",
    "transfer",
    "meal",
    "budget",
    "work",
    "company",
    "location",
    "style",
    "response_style",
    "planning",
)

_WORD_TRIGGERS: dict[str, tuple[str, ...]] = {
    "aisle": ("travel", "flight", "seat"),
    "window": ("travel", "flight", "seat"),
    "seat": ("travel", "flight", "seat"),
    "flight": ("travel", "flight"),
    "fly": ("travel", "flight"),
    "red-eye": ("travel", "flight", "timing"),
    "layover": ("travel", "flight", "timing"),
    "morning": ("timing",),
    "evening": ("timing",),
    "afternoon": ("timing",),
    "airport": ("travel", "airport"),
    "airline": ("travel", "flight"),
    "hotel": ("travel", "hotel"),
    "transfer": ("travel", "transfer"),
    "trip": ("travel",),
    "travel": ("travel",),
    "meal": ("meal",),
    "vegetarian": ("meal",),
    "food": ("meal",),
    "dining": ("meal",),
    "budget": ("budget",),
    "cost": ("budget",),
    "cheap": ("budget",),
    "work": ("work",),
    "company": ("work", "company"),
    "office": ("work", "location"),
    "live": ("location",),
    "plan": ("planning",),
    "planning": ("planning",),
    "concise": ("style",),
    "brief": ("style",),
    "detailed": ("style",),
    "short": ("style",),
    "shorter": ("style",),
    "essential": ("style",),
    "answer": ("style", "response_style"),
    "response": ("style", "response_style"),
    "reply": ("style", "response_style"),
    "explanation": ("style", "response_style"),
    "recommendation": ("style", "response_style"),
}

_PHRASE_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("based ", ("location",)),
    ("out of", ("location",)),
    ("near ", ("location",)),
)


def _fold(word: str) -> str:
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def assign_tags(text: str) -> list[str]:
    """Deterministic tags for a memory or request text, in canonical order."""
    lowered = text.lower()
    found: set[str] = set()
    for word in re.findall(r"[a-z0-9-]+", lowered):
        found.update(_WORD_TRIGGERS.get(_fold(word), ()))
    for phrase, tags in _PHRASE_TRIGGERS:
        if phrase in lowered:
            found.update(tags)
    return [tag for tag in TAG_ORDER if tag in found]


def domain_for(tags: list[str]) -> str | None:
    """Primary domain: the highest-priority tag."""
    return tags[0] if tags else None
