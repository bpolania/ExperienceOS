"""Rule-based memory planner: deterministic detection of preferences,
facts, and instructions, with conflict-driven superseding and explicit
forget requests.

The planner is a seam: an alternative planner with smarter extraction
can replace it without touching the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from experienceos.memory.schema import ExperienceEntry, MemoryKind

CREATE = "create"
SUPERSEDE = "supersede"
FORGET = "forget"

# "I prefer X", "I like X", "I don't like X", optionally prefixed with
# "Remember (that) ...". Change phrasings like "Actually, I prefer X now"
# match too — leading words are ignored and trailing modifiers stripped.
_PREFERENCE_PATTERN = re.compile(
    r"(?:\bremember\s+(?:that\s+)?)?"
    r"\bi\s+(?:now\s+)?"
    r"(?P<verb>prefer|like|love|enjoy|don'?t\s+like|dislike|hate|avoid)\s+"
    r"(?P<object>[^.!?\n;]+)",
    re.IGNORECASE,
)

_TRAILING_MODIFIERS = re.compile(
    r"\s+(now|instead(?:\s+of\s+[^.!?\n;]+)?|these days|going forward"
    r"|from now on)$",
    re.IGNORECASE,
)

# Explicit forget requests. Each pattern captures a topic phrase that is
# matched against existing active memories by content-word overlap.
_FORGET_PATTERNS = (
    re.compile(
        r"\bforget\s+(?:that\s+)?(?P<topic>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi\s+no\s+longer\s+"
        r"(?:want\s+you\s+to\s+remember|need\s+you\s+to\s+remember|"
        r"prefer|like|love|enjoy|care\s+about)\s+"
        r"(?P<topic>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi\s+(?:do\s+not|don'?t)\s+care\s+about\s+(?P<topic>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
)

# Words ignored when matching a forget topic against memory texts, so
# "my morning flight preference" matches "Prefers morning flights."
_MATCH_STOPWORDS = frozenset(
    {
        "a", "an", "and", "the", "that", "this", "my", "your", "i", "you",
        "me", "to", "of", "for", "with", "in", "on", "at", "it", "is",
        "are", "was", "be", "about", "do", "dont", "not", "no", "longer",
        "anymore", "any", "more", "now", "please", "remember", "forget",
        "want", "need", "care", "prefer", "prefers", "preference",
        "preferences", "like", "likes", "dislike", "dislikes", "love",
        "loves", "enjoy", "enjoys", "hate", "hates", "avoid", "avoids",
    }
)


def _content_words(text: str) -> set[str]:
    """Normalized content words for conservative forget matching."""
    words = set()
    for word in re.findall(r"[a-z0-9']+", text.lower()):
        word = word.replace("'", "")
        if word in _MATCH_STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        words.add(word)
    return words


def _remove_spans(message: str, spans: list[tuple[int, int]]) -> str:
    """Message with the given character spans removed."""
    if not spans:
        return message
    parts, last = [], 0
    for start, end in sorted(spans):
        parts.append(message[last:start])
        last = max(last, end)
    parts.append(message[last:])
    return " ".join(parts)


_POSITIVE_TEMPLATES = {
    "prefer": "Prefers {}.",
    "like": "Likes {}.",
    "love": "Likes {}.",
    "enjoy": "Likes {}.",
}
_NEGATIVE_TEMPLATE = "Dislikes {}."
_POSITIVE_PREFIXES = ("Prefers ", "Likes ")

# Durable user facts: "My home airport is SFO.", "I work out of Santa
# Clara.", "I live near San Francisco.", "I'm based in San Jose."
_FACT_SUBJECT_PATTERN = re.compile(
    r"\bmy\s+(?P<subject>[a-z][a-z ]{0,40}?)\s+is\s+(?P<value>[^.!?\n;]+)",
    re.IGNORECASE,
)
_FACT_VERB_PATTERNS = (
    (
        re.compile(
            r"\bi\s+work\s+(?P<prep>out\s+of|from|in|at)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "Works",
    ),
    (
        re.compile(
            r"\bi\s+live\s+(?P<prep>near|in|at|around)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "Lives",
    ),
    (
        re.compile(
            r"\bi(?:'m|\s+am)\s+based\s+(?P<prep>in|near|at|out\s+of)"
            r"\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "Based",
    ),
)

# Standing instructions: "Remember to X.", "From now on, X.",
# "X from now on.", "When <clause>, X.", "Always X."
_INSTRUCTION_PATTERNS = (
    (
        re.compile(
            r"\b(?:please\s+)?remember\s+to\s+(?P<action>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        re.compile(r"\bfrom\s+now\s+on,?\s+(?P<action>[^.!?\n;]+)", re.IGNORECASE),
        False,
    ),
    (
        re.compile(
            r"\bgoing\s+forward,?\s+(?P<action>[^.!?\n;]+)", re.IGNORECASE
        ),
        False,
    ),
    (
        re.compile(
            r"\b(?:please\s+)?(?P<action>[^.!?\n;,]+?)\s+from\s+now\s+on\b",
            re.IGNORECASE,
        ),
        False,
    ),
    (
        re.compile(
            r"\bwhen\s+(?P<clause>[^,.!?\n;]+),\s*(?P<action>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(r"\balways\s+(?P<action>[^.!?\n;]+)", re.IGNORECASE),
        False,
    ),
    # Bare "Please <verb> ..." with a durable-instruction verb; requests
    # like "Please help me book ..." stay requests.
    (
        re.compile(
            r"\bplease\s+(?P<action>(?:keep|give|include|use|avoid|answer"
            r"|respond|reply|show|add)\b[^.!?\n;]*)",
            re.IGNORECASE,
        ),
        False,
    ),
)

# Update keys: a new fact/instruction supersedes an older active one of
# the same kind only when both map to the same key. Content instructions
# ("Include airport transfer time ...") get no key and accumulate; only
# detail-level/style instructions within a domain supersede each other.
_STYLE_WORDS = frozenset(
    {
        "concise", "brief", "short", "shorter", "long", "longer",
        "detailed", "detail", "essential", "verbose", "minimal", "compact",
    }
)
_PLANNING_WORDS = frozenset({"plan", "planning"})
_TRAVEL_WORDS = frozenset(
    {"trip", "travel", "flight", "airport", "hotel", "layover", "red-eye"}
)
_RESPONSE_WORDS = frozenset(
    {"answer", "response", "reply", "explanation", "recommendation"}
)


def _key_words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[a-z0-9-]+", text.lower()):
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        words.add(word)
    return words


def update_key(kind: str, text: str) -> str | None:
    """Stable update domain for a fact/instruction text, or None."""
    lowered = text.lower()
    if kind == MemoryKind.FACT:
        if "home airport" in lowered:
            return "fact:home_airport"
        if lowered.startswith(("works ", "based ")) or "work out of" in lowered:
            return "fact:work_location"
        if "company" in lowered:
            return "fact:company_location"
        return None
    if kind == MemoryKind.INSTRUCTION:
        words = _key_words(text)
        style = bool(words & _STYLE_WORDS)
        if words & _PLANNING_WORDS:
            return "instruction:planning" if style else None
        if words & _TRAVEL_WORDS:
            return "instruction:travel" if style else None
        if words & _RESPONSE_WORDS:
            return "instruction:response_style"
        return None
    return None

# Actions that are really first-person preference statements, not
# standing instructions ("From now on, I prefer window seats").
_INSTRUCTION_GUARD = re.compile(
    r"^(?:i|we)\b|^(?:prefer|like|love|enjoy|dislike|hate|avoid)\b",
    re.IGNORECASE,
)


def _clean_instruction_action(action: str) -> str:
    action = action.strip().rstrip(".!?,")
    action = re.sub(r"^please\s+", "", action, flags=re.IGNORECASE)
    action = re.sub(r",?\s+from\s+now\s+on$", "", action, flags=re.IGNORECASE)
    action = re.sub(r"^(\w+)\s+me\b", r"\1", action, flags=re.IGNORECASE)
    action = re.sub(r"\s+", " ", action).strip()
    if not action:
        return ""
    return action[0].upper() + action[1:]


def _normalized_text(text: str) -> str:
    """Normalized form for lightweight duplicate detection."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))

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
    """One planned memory operation: a create, supersede, or forget."""

    action: str
    kind: str = MemoryKind.PREFERENCE
    text: str = ""
    memory_id: str | None = None  # supersede/forget target
    replaces: str | None = None  # for creates that replace an old memory
    reason: str | None = None
    request: str | None = None  # the user phrase that triggered a forget
    metadata: dict | None = None  # extra entry metadata (e.g. semantic identity)


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

        forget_actions, forget_spans = self._plan_forgets(message, existing)
        actions.extend(forget_actions)
        # Forget-request phrases must not double as creation statements
        # ("Forget that I prefer ..." should not create that preference).
        message = _remove_spans(message, forget_spans)

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

        seen = {(m.kind, _normalized_text(m.text)) for m in existing}
        superseded_ids = {a.memory_id for a in actions if a.action == SUPERSEDE}
        for kind, text in [
            *((MemoryKind.FACT, t) for t in self._detect_fact_texts(message)),
            *(
                (MemoryKind.INSTRUCTION, t)
                for t in self._detect_instruction_texts(message)
            ),
        ]:
            dedup_key = (kind, _normalized_text(text))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            conflict = self._find_update_conflict(
                kind, text, existing, superseded_ids
            )
            if conflict is not None:
                domain = update_key(kind, text).split(":", 1)[1].replace("_", " ")
                superseded_ids.add(conflict.id)
                actions.append(
                    MemoryAction(
                        action=SUPERSEDE,
                        kind=kind,
                        memory_id=conflict.id,
                        text=conflict.text,
                        reason=f"Conflicts with updated {domain} {kind}.",
                    )
                )
            actions.append(
                MemoryAction(
                    action=CREATE,
                    kind=kind,
                    text=text,
                    replaces=conflict.id if conflict else None,
                    reason=f"User updated this {kind}." if conflict else None,
                )
            )
        return actions

    @staticmethod
    def _find_update_conflict(
        kind: str,
        text: str,
        existing: list[ExperienceEntry],
        already_superseded: set[str],
    ) -> ExperienceEntry | None:
        """First active memory of the same kind sharing the same update key."""
        key = update_key(kind, text)
        if key is None:
            return None
        for memory in existing:
            if (
                memory.kind == kind
                and memory.id not in already_superseded
                and memory.text != text
                and update_key(memory.kind, memory.text) == key
            ):
                return memory
        return None

    @staticmethod
    def _plan_forgets(
        message: str, existing: list[ExperienceEntry]
    ) -> tuple[list[MemoryAction], list[tuple[int, int]]]:
        """Forget actions for active memories matching an explicit request.

        A memory matches when every content word of the request topic
        appears in the memory text — conservative on purpose, so
        unrelated memories are never forgotten. A request that matches
        nothing produces no action.
        """
        actions: list[MemoryAction] = []
        spans: list[tuple[int, int]] = []
        targeted: set[str] = set()
        for pattern in _FORGET_PATTERNS:
            for match in pattern.finditer(message):
                spans.append(match.span())
                topic_words = _content_words(match.group("topic"))
                if not topic_words:
                    continue
                request = match.group(0).strip()
                for memory in existing:
                    if memory.id in targeted:
                        continue
                    if topic_words <= _content_words(memory.text):
                        targeted.add(memory.id)
                        actions.append(
                            MemoryAction(
                                action=FORGET,
                                kind=memory.kind,
                                memory_id=memory.id,
                                text=memory.text,
                                reason="User asked to forget this experience.",
                                request=request,
                            )
                        )
        return actions, spans

    def _detect_preference_texts(self, message: str) -> list[str]:
        texts: list[str] = []
        for match in _PREFERENCE_PATTERN.finditer(message):
            verb = re.sub(r"\s+", " ", match.group("verb").lower())
            template = _POSITIVE_TEMPLATES.get(verb, _NEGATIVE_TEMPLATE)
            for item in self._split_items(match.group("object")):
                texts.append(template.format(item))
        return texts

    @staticmethod
    def _clean_fact_value(value: str) -> str:
        """Strip leading/trailing update modifiers: "now SJC", "SJC now"."""
        value = value.strip().rstrip(".!?,")
        value = re.sub(r"^now\s+", "", value, flags=re.IGNORECASE)
        return _TRAILING_MODIFIERS.sub("", value)

    def _detect_fact_texts(self, message: str) -> list[str]:
        texts: list[str] = []
        for match in _FACT_SUBJECT_PATTERN.finditer(message):
            subject = match.group("subject").strip()
            value = self._clean_fact_value(match.group("value"))
            # Conservative: short noun-phrase subjects, no clause values.
            if not value or len(subject.split()) > 4:
                continue
            if value.lower().startswith("that "):
                continue
            texts.append(f"{subject[0].upper()}{subject[1:]} is {value}.")
        for pattern, verb in _FACT_VERB_PATTERNS:
            for match in pattern.finditer(message):
                prep = re.sub(r"\s+", " ", match.group("prep").lower())
                value = self._clean_fact_value(match.group("value"))
                if value:
                    texts.append(f"{verb} {prep} {value}.")
        return texts

    @staticmethod
    def _detect_instruction_texts(message: str) -> list[str]:
        texts: list[str] = []
        spans: list[tuple[int, int]] = []

        def overlaps(span: tuple[int, int]) -> bool:
            return any(span[0] < end and span[1] > start for start, end in spans)

        for pattern, has_clause in _INSTRUCTION_PATTERNS:
            for match in pattern.finditer(message):
                if overlaps(match.span()):
                    continue
                action = match.group("action").strip()
                if _INSTRUCTION_GUARD.match(action):
                    continue
                text = _clean_instruction_action(action)
                if not text:
                    continue
                if has_clause:
                    clause = match.group("clause").strip()
                    text = f"{text} when {clause}"
                spans.append(match.span())
                texts.append(f"{text}.")
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
