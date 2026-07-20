"""Semantic memory identity and conservative conflict detection.

A ``SemanticIdentity`` names the slot a durable memory occupies —
(subject, attribute, scope) — plus a normalized comparison value, so
ExperienceOS can recognize that "Phone is a Pixel 9." replaces
"Phone is a Pixel 6." without a per-domain rule, while "Prefers aisle
seats for short work trips." and "Prefers window seats for long
international trips." coexist because their scopes differ.

Design principles:

- Exact structured identity beats fuzzy text similarity: attributes
  come from a small deterministic registry, never broad matching.
- Unknown identity is a valid outcome: memories without a confident
  identity remain ordinary durable memories and never participate in
  generalized supersession.
- Unknown cardinality, ambiguous scope, or low confidence always mean
  coexistence, never destructive replacement.
- Identities are versioned metadata stored through the existing
  ``ExperienceEntry.metadata`` JSON channel — additive, backward
  compatible, and it survives the SQLite round trip unchanged.
- Extension seams (``valid_from``/``valid_until``/``observed_at``/
  ``source_type``) are reserved for the temporal/provenance
  work and are carried but not yet interpreted.

No benchmark oracle data (scenario IDs, expected answers, answer
sessions) is referenced anywhere in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from experienceos.memory.schema import ExperienceEntry, MemoryKind

SEMANTIC_IDENTITY_VERSION = "1"
CONFLICT_STRATEGY_VERSION = "conservative-1"

METADATA_KEY = "semantic_identity"

DEFAULT_SUBJECT = "user"
DEFAULT_SCOPE = "global"


class Cardinality:
    SINGLE = "single"  # one current value per (subject, attribute, scope)
    MULTI = "multi"  # values accumulate (languages spoken, ...)
    UNKNOWN = "unknown"  # conservative: coexist


@dataclass(frozen=True)
class SemanticIdentity:
    subject: str
    attribute: str
    value: str  # normalized comparison value
    display_value: str  # original wording, preserved
    scope: str = DEFAULT_SCOPE
    qualifiers: dict = field(default_factory=dict)
    cardinality: str = Cardinality.UNKNOWN
    confidence: float = 1.0
    extraction_method: str = "deterministic"
    version: str = SEMANTIC_IDENTITY_VERSION

    def slot(self) -> tuple[str, str, str]:
        return (self.subject, self.attribute, self.scope)

    def is_historical(self) -> bool:
        return bool(self.qualifiers.get("historical"))

    def to_metadata(self) -> dict:
        return {
            "version": self.version,
            "subject": self.subject,
            "attribute": self.attribute,
            "value": self.value,
            "display_value": self.display_value,
            "scope": self.scope,
            "qualifiers": dict(self.qualifiers),
            "cardinality": self.cardinality,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
        }

    @classmethod
    def from_metadata(cls, data: dict) -> "SemanticIdentity | None":
        if not isinstance(data, dict) or "attribute" not in data:
            return None
        return cls(
            subject=data.get("subject", DEFAULT_SUBJECT),
            attribute=data["attribute"],
            value=data.get("value", ""),
            display_value=data.get("display_value", data.get("value", "")),
            scope=data.get("scope", DEFAULT_SCOPE),
            qualifiers=dict(data.get("qualifiers", {})),
            cardinality=data.get("cardinality", Cardinality.UNKNOWN),
            confidence=float(data.get("confidence", 1.0)),
            extraction_method=data.get("extraction_method", "deterministic"),
            version=data.get("version", SEMANTIC_IDENTITY_VERSION),
        )


def _slug(text: str) -> str:
    words = re.sub(r"[^\w\s-]", "", text.lower()).split()
    if words and len(words[-1]) > 3 and words[-1].endswith("s"):
        words[-1] = words[-1][:-1]  # crude, consistent de-pluralization
    return "_".join(words)


def _normalize_value(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip(".!,").lower())


_HISTORICAL = re.compile(
    r"\b(?:in|back in|during)\s+(?:19|20)\d{2}\b|\bused to\b", re.IGNORECASE
)

# --- Attribute alias registry (small, deterministic, testable) ---------------

_FACT_ATTRIBUTE_ALIASES = {
    "phone": "current_phone",
    "mobile phone": "current_phone",
    "current phone": "current_phone",
    "device": "current_phone",
    "employer": "employer",
    "company": "employer",
    "home city": "residence",
    "city": "residence",
    "residence": "residence",
}

# Preference attribute classes keyed by value vocabulary. Each entry:
# (attribute, value-word pattern, cardinality).
_PREFERENCE_CLASSES = (
    ("preferred_seat", re.compile(r"\b(aisle|window|middle)\b.*\bseats?\b"), Cardinality.SINGLE),
    ("preferred_flight_time", re.compile(r"\b(morning|evening|afternoon|red-eye|late-night)\b.*\bflights?\b"), Cardinality.SINGLE),
    ("preferred_hotel", re.compile(r"\b(\w+)\b.*\bhotels?\b"), Cardinality.SINGLE),
    ("preferred_drink", re.compile(r"\b(tea|coffee)\b"), Cardinality.SINGLE),
    ("study_time", re.compile(r"\bstudying\b"), Cardinality.SINGLE),
    ("editor_theme", re.compile(r"\b(dark|light)\b mode\b.*\beditors?\b"), Cardinality.SINGLE),
)

_FACT_PATTERN = re.compile(
    r"^(?P<attr>[A-Za-z][\w' -]*?) is (?:a |an |the )?(?P<value>.+?)\.?$"
)
_RESIDENCE_PATTERN = re.compile(
    r"^Lives in (?P<value>.+?)\.?$"
)
_EMPLOYER_PATTERN = re.compile(
    r"^(?:Works (?:for|at)|Employer is) (?P<value>.+?)\.?$"
)
_LANGUAGE_PATTERN = re.compile(r"^Speaks (?P<value>.+?)\.?$")
_PREFERENCE_PATTERN = re.compile(
    r"^Prefers (?P<value>.+?)"
    r"(?: for (?P<scope>[\w' -]+?))?(?: in the (?P<time>morning|evening|afternoon))?\.?$"
)
_ROUTING_PATTERN = re.compile(
    r"^(?:From now on, )?[Ss]end (?:my )?(?P<what>[\w -]+?) to "
    r"(?:the )?(?P<value>#?[\w-]+)(?: channel)?"
    r"(?:\s+(?:instead|now|going forward))?\.?$"
)
_UNITS_PATTERN = re.compile(
    r"^Use (?P<value>[\w -]+?)(?: units)?(?: for (?P<scope>[\w -]+?))?\.?$"
)


class SemanticNormalizer:
    """Deterministic identity extraction from STORED memory text.

    Operates on the planner's normalized memory texts (the same form
    persisted in the store), so it applies uniformly to new create
    actions and to legacy entries lacking identity metadata. Returns
    None whenever confidence would be low — unknown identity is safe.
    """

    version = SEMANTIC_IDENTITY_VERSION

    def normalize(self, kind: str, text: str) -> SemanticIdentity | None:
        text = text.strip()
        qualifiers: dict = {}
        if _HISTORICAL.search(text):
            qualifiers["historical"] = True

        if kind == MemoryKind.FACT:
            return self._normalize_fact(text, qualifiers)
        if kind == MemoryKind.PREFERENCE:
            return self._normalize_preference(text, qualifiers)
        if kind == MemoryKind.INSTRUCTION:
            return self._normalize_instruction(text, qualifiers)
        return None

    # -- facts ---------------------------------------------------------------

    def _normalize_fact(self, text, qualifiers):
        match = _RESIDENCE_PATTERN.match(text)
        if match:
            return self._identity(
                "residence", match.group("value"), qualifiers,
                Cardinality.SINGLE,
            )
        match = _EMPLOYER_PATTERN.match(text)
        if match:
            return self._identity(
                "employer", match.group("value"), qualifiers,
                Cardinality.SINGLE,
            )
        match = _LANGUAGE_PATTERN.match(text)
        if match:
            return self._identity(
                "speaks_language", match.group("value"), qualifiers,
                Cardinality.MULTI,
            )
        match = _FACT_PATTERN.match(text)
        if match:
            attr_words = _normalize_value(match.group("attr"))
            attribute = _FACT_ATTRIBUTE_ALIASES.get(attr_words)
            if attribute is None:
                # Generic possessive current-state fact ("X is Y" from
                # the planner's "My X is Y" template): single current
                # value per exact attribute slug.
                attribute = _slug(attr_words)
                if not attribute:
                    return None
            return self._identity(
                attribute, match.group("value"), qualifiers,
                Cardinality.SINGLE,
            )
        return None

    # -- preferences ------------------------------------------------------------

    def _normalize_preference(self, text, qualifiers):
        match = _PREFERENCE_PATTERN.match(text)
        if not match:
            return None
        raw_value = match.group("value")
        scope = DEFAULT_SCOPE
        if match.group("scope"):
            scope = _slug(match.group("scope"))
        elif match.group("time"):
            scope = match.group("time")
        lowered = f"{raw_value} {match.group('scope') or ''}".lower()
        time = match.group("time")
        for attribute, pattern, cardinality in _PREFERENCE_CLASSES:
            value_match = pattern.search(lowered)
            if not value_match:
                continue
            if attribute == "study_time":
                # The time of day IS the value here ("studying in the
                # evening"), not a scope; without an explicit time the
                # identity is not confident.
                if not time:
                    return None
                return self._identity(
                    attribute, time, qualifiers, cardinality,
                    scope=DEFAULT_SCOPE, display_value=raw_value,
                )
            value = (
                value_match.group(1)
                if value_match.groups()
                else value_match.group(0)
            )
            return self._identity(
                attribute, value, qualifiers, cardinality,
                scope=scope, display_value=raw_value,
            )
        return None  # unknown preference class: no generalized identity

    # -- instructions -------------------------------------------------------------

    def _normalize_instruction(self, text, qualifiers):
        match = _ROUTING_PATTERN.match(text)
        if match:
            return self._identity(
                f"routing:{_slug(match.group('what'))}",
                match.group("value"), qualifiers, Cardinality.SINGLE,
            )
        match = _UNITS_PATTERN.match(text)
        if match:
            scope = (
                _slug(match.group("scope"))
                if match.group("scope")
                else DEFAULT_SCOPE
            )
            return self._identity(
                "units", match.group("value"), qualifiers,
                Cardinality.SINGLE, scope=scope,
            )
        return None

    def _identity(
        self, attribute, value, qualifiers, cardinality,
        scope=DEFAULT_SCOPE, display_value=None,
    ) -> SemanticIdentity:
        return SemanticIdentity(
            subject=DEFAULT_SUBJECT,
            attribute=attribute,
            value=_normalize_value(value),
            display_value=(display_value or value).strip().strip("."),
            scope=scope,
            qualifiers=qualifiers,
            cardinality=cardinality,
        )


def identity_of(
    entry: ExperienceEntry, normalizer: SemanticNormalizer
) -> SemanticIdentity | None:
    """Entry identity: stored metadata first, lazy computation for
    legacy entries. Never mutates the entry."""
    stored = entry.metadata.get(METADATA_KEY)
    if stored:
        return SemanticIdentity.from_metadata(stored)
    return normalizer.normalize(entry.kind, entry.text)


# --- Conflict decisions --------------------------------------------------------


class Decision:
    DUPLICATE = "duplicate"
    SUPERSEDE = "supersede"
    COEXIST = "coexist"


@dataclass(frozen=True)
class ConflictDecision:
    decision: str
    reason: str
    entry: ExperienceEntry | None = None


def _scopes_compatible(a: str, b: str) -> bool:
    """Conservative: only identical scopes conflict. A default-scope
    memory and an explicitly scoped one coexist; distinct explicit
    scopes coexist; ambiguity never justifies replacement."""
    return a == b


def _qualifiers_compatible(a: dict, b: dict) -> bool:
    return bool(a.get("historical")) == bool(b.get("historical"))


def evaluate_pair(
    new: SemanticIdentity, old: SemanticIdentity, old_entry: ExperienceEntry
) -> ConflictDecision:
    if new.subject != old.subject:
        return ConflictDecision(Decision.COEXIST, "different subjects")
    if new.attribute != old.attribute:
        return ConflictDecision(Decision.COEXIST, "different attributes")
    if not _scopes_compatible(new.scope, old.scope):
        return ConflictDecision(
            Decision.COEXIST,
            f"distinct scopes coexist ({old.scope} vs {new.scope})",
        )
    if not _qualifiers_compatible(new.qualifiers, old.qualifiers):
        return ConflictDecision(
            Decision.COEXIST, "historical and current statements coexist"
        )
    if new.value == old.value:
        return ConflictDecision(
            Decision.DUPLICATE,
            f"equivalent value for {new.attribute} ({new.value})",
            entry=old_entry,
        )
    if new.is_historical():
        return ConflictDecision(
            Decision.COEXIST, "historical statement never supersedes"
        )
    if Cardinality.SINGLE not in (new.cardinality, old.cardinality) or (
        Cardinality.MULTI in (new.cardinality, old.cardinality)
    ):
        return ConflictDecision(
            Decision.COEXIST,
            f"non-single cardinality for {new.attribute}: coexist",
        )
    if min(new.confidence, old.confidence) < 1.0:
        return ConflictDecision(
            Decision.COEXIST, "low identity confidence: coexist"
        )
    return ConflictDecision(
        Decision.SUPERSEDE,
        f"{new.attribute} changed from "
        f"{old.value!r} to {new.value!r} (scope {new.scope})",
        entry=old_entry,
    )


def resolve_conflicts(
    new: SemanticIdentity,
    active_entries: list[ExperienceEntry],
    normalizer: SemanticNormalizer,
) -> list[ConflictDecision]:
    """All non-coexist decisions for a new identity against the active
    snapshot. Forgotten/superseded entries never appear here because
    callers pass active entries only."""
    decisions = []
    for entry in active_entries:
        old = identity_of(entry, normalizer)
        if old is None:
            continue
        decision = evaluate_pair(new, old, entry)
        if decision.decision != Decision.COEXIST:
            decisions.append(decision)
    return decisions
