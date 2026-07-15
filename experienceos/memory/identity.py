"""Deterministic semantic memory identity: projection and comparison.

This module answers one question, and only that question: *given an
existing durable memory and a newly proposed statement, do they name the
same experience, conflicting current experience, compatible scoped
experience, unrelated experience, or an unsafe ambiguity?*

It is deliberately split into two layers, never one opaque boolean:

- **projection** (:class:`IdentityProjector`) turns a memory or a raw
  proposed statement into a structured :class:`MemoryIdentity` —
  subject, attribute, value, scope, qualifiers, temporal status,
  durability, kind, provenance — recording which fields are unknown and
  why;
- **comparison** (:class:`IdentityComparer`) relates two identities and
  explains which fields matched, conflicted, differed, or stayed
  unknown.

Boundaries this module keeps:

- it never mutates memory, never emits lifecycle actions, and never
  calls a store, planner, manager, or engine — ``ExperienceManager``
  remains lifecycle-policy authority and ``ExperienceEngine`` remains
  the sole durable-mutation boundary;
- it never calls a model, an embedding, or the network;
- structured metadata beats reparsed text: an entry carrying committed
  ``semantic_identity`` metadata is read, not guessed at;
- unknown critical fields produce ambiguity, never an optimistic match.

Scope of the deterministic lexicon is bounded on purpose. It covers the
travel, food, work, study, device, family, and editor domains that the
evaluated evidence exercises, and it reports ``unknown`` outside them
rather than pretending to general language understanding. See
``docs/semantic_memory_identity.md`` for the supported patterns.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace

from experienceos.memory.planner import _normalized_text
from experienceos.memory.schema import ExperienceEntry, MemoryKind
from experienceos.memory.semantic import (
    METADATA_KEY,
    SemanticIdentity,
)

IDENTITY_PROJECTION_VERSION = "1"
IDENTITY_COMPARISON_VERSION = "1"

#: Sentinel for a field the projection could not establish from evidence.
UNKNOWN = "unknown"

#: Scope value used when a statement asserts no explicit scope. Distinct
#: from :data:`UNKNOWN`: the statement is well-formed, it simply carries
#: no scope. Two unscoped statements share a scope; an unscoped and an
#: explicitly scoped statement do **not** (see :class:`ScopeRelation`).
UNSCOPED = "general"


class TemporalStatus:
    """Temporal reading of a statement."""

    CURRENT = "current"
    HISTORICAL = "historical"
    TEMPORARY = "temporary"
    HYPOTHETICAL = "hypothetical"
    QUESTION = "question"
    UNKNOWN = "unknown"


class Durability:
    """Whether a statement asserts durable experience."""

    DURABLE = "durable"
    NON_DURABLE = "non_durable"
    UNKNOWN = "unknown"


class IdentityRelation:
    """How a proposed identity relates to an existing one."""

    EXACT_DUPLICATE = "exact_duplicate"
    SEMANTIC_DUPLICATE = "semantic_duplicate"
    SCOPED_COEXISTENCE = "scoped_coexistence"
    CURRENT_STATE_CONFLICT = "current_state_conflict"
    UNRELATED = "unrelated"
    TEMPORARY_EXCEPTION = "temporary_exception"
    HISTORICAL = "historical"
    HYPOTHETICAL = "hypothetical"
    QUESTION = "question"
    AMBIGUOUS = "ambiguous"


#: Relations that must never justify a durable mutation downstream.
NON_MUTATING_RELATIONS = frozenset(
    {
        IdentityRelation.EXACT_DUPLICATE,
        IdentityRelation.SEMANTIC_DUPLICATE,
        IdentityRelation.TEMPORARY_EXCEPTION,
        IdentityRelation.HISTORICAL,
        IdentityRelation.HYPOTHETICAL,
        IdentityRelation.QUESTION,
        IdentityRelation.AMBIGUOUS,
    }
)


class FieldRelation:
    """How one identity field compares across two identities."""

    EQUAL = "equal"  # identical normalized token
    EQUIVALENT = "equivalent"  # different wording, same canonical meaning
    DIFFERENT = "different"
    UNKNOWN = "unknown"


class ScopeRelation:
    """How two scopes compare."""

    EQUAL = "equal"
    COMPATIBLE = "compatible"
    DISJOINT = "disjoint"
    OVERLAPPING = "overlapping"  # one contains the other: never a clean call
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IdentityField:
    """One projected field plus how it was established."""

    value: str = UNKNOWN
    known: bool = False
    source: str = "none"  # structured_metadata | lexicon | pattern | none
    evidence: str = ""  # the matched surface form, for diagnostics

    @classmethod
    def unknown(cls, reason: str = "") -> "IdentityField":
        return cls(value=UNKNOWN, known=False, source="none", evidence=reason)

    def to_record(self) -> dict:
        return {
            "value": self.value,
            "known": self.known,
            "source": self.source,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class MemoryIdentity:
    """Structured, comparable identity of one memory or proposal."""

    source_text: str
    normalized_text: str
    comparison_text: str
    subject: IdentityField
    attribute: IdentityField
    value: IdentityField
    scope: IdentityField
    kind: str = MemoryKind.PREFERENCE
    qualifiers: dict = field(default_factory=dict)
    temporal_status: str = TemporalStatus.UNKNOWN
    durability: str = Durability.UNKNOWN
    value_domain: str = UNKNOWN
    scope_specified: bool = False
    historical_value: str | None = None
    markers: tuple = ()
    provenance_ref: str | None = None
    evidence_ref: str | None = None
    unknown_fields: tuple = ()
    completeness: float = 0.0
    projection_method: str = "deterministic_rules"
    projection_version: str = IDENTITY_PROJECTION_VERSION

    @property
    def projected(self) -> bool:
        """True when at least subject and attribute were established."""
        return self.subject.known and self.attribute.known

    def target_key(self) -> str | None:
        """Lifecycle slot key: subject + attribute + scope + kind.

        Deliberately excludes the value, so a replacement of the value
        still lands on the same key. ``None`` when a component is
        unknown — a fabricated key is worse than no key.
        """
        if not (self.subject.known and self.attribute.known):
            return None
        return "|".join(
            (
                self.kind,
                self.subject.value,
                self.attribute.value,
                self.scope.value,
            )
        )

    def semantic_key(self) -> str | None:
        """Target key + normalized value + temporal status.

        Two identities share a semantic key exactly when they assert the
        same value in the same slot with the same temporal reading.
        """
        target = self.target_key()
        if target is None or not self.value.known:
            return None
        return "|".join((target, self.value.value, self.temporal_status))

    def to_record(self) -> dict:
        """Deterministic, JSON-safe projection record."""
        return {
            "normalized_text": self.normalized_text,
            "kind": self.kind,
            "subject": self.subject.to_record(),
            "attribute": self.attribute.to_record(),
            "value": self.value.to_record(),
            "scope": self.scope.to_record(),
            "scope_specified": self.scope_specified,
            "value_domain": self.value_domain,
            "qualifiers": dict(self.qualifiers),
            "temporal_status": self.temporal_status,
            "durability": self.durability,
            "historical_value": self.historical_value,
            "markers": list(self.markers),
            "provenance_ref": self.provenance_ref,
            "evidence_ref": self.evidence_ref,
            "unknown_fields": list(self.unknown_fields),
            "completeness": self.completeness,
            "target_key": self.target_key(),
            "semantic_key": self.semantic_key(),
            "projection_method": self.projection_method,
            "projection_version": self.projection_version,
        }


@dataclass(frozen=True)
class IdentityDiagnostic:
    """One structured reason contributing to a comparison outcome."""

    code: str
    detail: str = ""

    def to_record(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class IdentityComparison:
    """Explained relation between an existing and a proposed identity."""

    relation: str
    exact_text_match: bool = False
    subject_relation: str = FieldRelation.UNKNOWN
    attribute_relation: str = FieldRelation.UNKNOWN
    value_relation: str = FieldRelation.UNKNOWN
    scope_relation: str = ScopeRelation.UNKNOWN
    qualifier_relation: str = FieldRelation.UNKNOWN
    temporal_relation: str = FieldRelation.UNKNOWN
    kind_compatible: bool = False
    durability_compatible: bool = False
    conflict_fields: tuple = ()
    unknown_fields: tuple = ()
    rationale: tuple = ()  # tuple[IdentityDiagnostic, ...]
    fail_closed: bool = False
    target_key: str | None = None
    supersession_candidate: bool = False
    comparison_version: str = IDENTITY_COMPARISON_VERSION

    def to_record(self) -> dict:
        return {
            "relation": self.relation,
            "exact_text_match": self.exact_text_match,
            "subject_relation": self.subject_relation,
            "attribute_relation": self.attribute_relation,
            "value_relation": self.value_relation,
            "scope_relation": self.scope_relation,
            "qualifier_relation": self.qualifier_relation,
            "temporal_relation": self.temporal_relation,
            "kind_compatible": self.kind_compatible,
            "durability_compatible": self.durability_compatible,
            "conflict_fields": list(self.conflict_fields),
            "unknown_fields": list(self.unknown_fields),
            "rationale": [d.to_record() for d in self.rationale],
            "fail_closed": self.fail_closed,
            "target_key": self.target_key,
            "supersession_candidate": self.supersession_candidate,
            "comparison_version": self.comparison_version,
        }


# --- Text normalization ------------------------------------------------------

_ARTICLES = re.compile(r"\b(?:a|an|the)\b")
_APOSTROPHES = dict.fromkeys(map(ord, "‘’ʼ′"), "'")
_DASHES = dict.fromkeys(map(ord, "–—−"), "-")


def normalize_text(text: str) -> str:
    """Deterministic comparison form: NFKC, lowercase, tidy whitespace.

    Punctuation that carries no durable meaning is dropped, but the
    question mark is preserved upstream of this call (marker detection
    reads the original text).
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(_APOSTROPHES).translate(_DASHES)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def comparison_text(text: str) -> str:
    """Normalized token form used for exact-duplicate detection.

    Reuses the planner's duplicate-detection form so identity and the
    canonical planner agree on what "same text" means, then drops
    articles so harmless wording variation ("the aisle seat" vs "aisle
    seat") still reads as an exact duplicate.
    """
    tokens = _normalized_text(normalize_text(text))
    return " ".join(_ARTICLES.sub(" ", tokens).split())


def _slug(text: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", normalize_text(text)))


# --- Non-durable markers -----------------------------------------------------

_TEMPORARY_MARKERS = (
    "this time only",
    "for this trip only",
    "this trip only",
    "today only",
    "just this once",
    "just for this booking",
    "for this booking only",
    "temporarily",
    "until tomorrow",
    "for now only",
    "this once",
    "this time",
)

_HISTORICAL_MARKERS = (
    "used to",
    "previously",
    "formerly",
    "last year",
    "before i switched",
    "when i lived in",
    "i once preferred",
)

_HISTORICAL_YEAR = re.compile(r"\b(?:back in|in|during)\s+(?:19|20)\d{2}\b")

_HYPOTHETICAL_MARKERS = (
    "if i ",
    "i might",
    "i would",
    "suppose ",
    "hypothetically",
    "what if",
)

# Conservative: an explicit interrogative opener or a question mark. A
# bare imperative ("Use SFO.") is never a question.
_QUESTION_MARKERS = (
    "can you",
    "could you",
    "would you",
    "do you remember",
    "do you know",
    "what would happen",
    "what do you",
)

# "I used to prefer X, but now I prefer Y" — the current clause wins,
# the historical clause is preserved rather than silently collapsed.
_COMPOUND_NOW = re.compile(
    r"^(?P<past>.*\bused to\b.*?)"
    r"(?:,\s*|\.\s*|\s+)(?:but\s+)?now\b(?P<current>.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _detect_markers(text: str) -> tuple:
    """All non-durable markers present, as (category, surface) pairs."""
    lowered = normalize_text(text)
    found = []
    if "?" in (text or ""):
        found.append((TemporalStatus.QUESTION, "?"))
    for marker in _QUESTION_MARKERS:
        if lowered.startswith(marker) or f" {marker}" in lowered:
            found.append((TemporalStatus.QUESTION, marker))
            break
    for marker in _HYPOTHETICAL_MARKERS:
        if marker in lowered:
            found.append((TemporalStatus.HYPOTHETICAL, marker))
            break
    for marker in _TEMPORARY_MARKERS:
        if marker in lowered:
            found.append((TemporalStatus.TEMPORARY, marker))
            break
    for marker in _HISTORICAL_MARKERS:
        if marker in lowered:
            found.append((TemporalStatus.HISTORICAL, marker))
            break
    else:
        if _HISTORICAL_YEAR.search(lowered):
            found.append((TemporalStatus.HISTORICAL, "year reference"))
    return tuple(found)


# --- Bounded attribute lexicon -----------------------------------------------


@dataclass(frozen=True)
class AttributeSpec:
    """One deterministic identity slot in a supported domain.

    ``value_domain`` groups attributes whose values share a vocabulary
    (all seat values, all airport codes). It lets an elliptical
    statement ("Actually, make it window.") project a value and a domain
    without guessing which specific slot it targets — the set-level
    resolver decides that, and fails closed when more than one active
    memory matches.
    """

    subject: str
    attribute: str
    value_domain: str
    values: tuple = ()  # canonical value vocabulary, if closed
    value_pattern: re.Pattern | None = None  # open-valued slots
    context: tuple = ()  # phrases required for a confident slot match
    context_any: bool = True


_SEAT_VALUES = ("aisle", "window", "middle")
_TRANSPORT_VALUES = ("rental car", "public transit")

_ATTRIBUTES = (
    AttributeSpec(
        subject="travel",
        attribute="seat",
        value_domain="seat",
        values=_SEAT_VALUES,
        context=("seat", "seats"),
    ),
    AttributeSpec(
        subject="travel",
        attribute="home_airport",
        value_domain="airport",
        value_pattern=re.compile(r"\bhome airport is (?:a |an |the )?(?P<value>[a-z0-9]{3,})\b"),
        context=("home airport",),
    ),
    AttributeSpec(
        subject="travel",
        attribute="work_flight_airport",
        value_domain="airport",
        value_pattern=re.compile(r"\buse (?P<value>[a-z0-9]{3,})\b"),
        context=("work flight", "work flights"),
    ),
    AttributeSpec(
        subject="travel",
        attribute="ground_transport",
        value_domain="ground_transport",
        values=_TRANSPORT_VALUES,
        context=("trip", "trips", "transport", "transportation", "transit"),
    ),
    AttributeSpec(
        subject="travel",
        attribute="flight_time",
        value_domain="flight_time",
        values=("morning", "afternoon", "evening", "red-eye"),
        context=("flight", "flights"),
    ),
    AttributeSpec(
        subject="food",
        attribute="morning_drink",
        value_domain="drink",
        values=("coffee", "tea"),
        context=("morning",),
    ),
    AttributeSpec(
        subject="food",
        attribute="team_lunch_style",
        value_domain="cuisine",
        values=("vegetarian",),
        context=("team lunch", "team lunches"),
    ),
    AttributeSpec(
        subject="work",
        attribute="base_office",
        value_domain="office",
        value_pattern=re.compile(r"\bbased in (?:a |an |the )?(?P<value>[a-z]+) office\b"),
        context=("office",),
    ),
    AttributeSpec(
        subject="work",
        attribute="daily_status_channel",
        value_domain="channel",
        value_pattern=re.compile(r"#(?P<value>[a-z0-9-]+)\b"),
        context=("daily status", "status summary"),
    ),
    AttributeSpec(
        subject="study",
        attribute="time_of_day",
        value_domain="time_of_day",
        values=("morning", "afternoon", "evening", "night"),
        context=("studying", "study"),
    ),
    AttributeSpec(
        subject="devices",
        attribute="phone_model",
        value_domain="phone_model",
        value_pattern=re.compile(
            r"\bphone is (?:a |an |the )?(?P<value>[a-z0-9 ]+?)(?:\s+now)?\s*\.?\s*$"
        ),
        context=("phone",),
    ),
    AttributeSpec(
        subject="family",
        attribute="soccer_practice_day",
        value_domain="weekday",
        value_pattern=re.compile(
            r"\bsoccer practice is on (?P<value>monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b"
        ),
        context=("soccer practice",),
    ),
    AttributeSpec(
        subject="dev",
        attribute="editor_theme",
        value_domain="theme",
        values=("dark", "light"),
        context=("editor", "mode"),
    ),
    AttributeSpec(
        subject="food",
        attribute="allergy",
        value_domain="allergen",
        value_pattern=re.compile(r"\ballergic to (?P<value>[a-z ]+?)\.?$"),
        context=("allergic",),
    ),
    AttributeSpec(
        subject="food",
        attribute="dislike",
        value_domain="food_item",
        value_pattern=re.compile(r"\b(?:don't|do not|dont) like (?P<value>[a-z ]+?)\.?$"),
        context=("like",),
    ),
    AttributeSpec(
        subject="food",
        attribute="pizza_friday",
        value_domain="food_item",
        value_pattern=re.compile(r"\b(?:like ordering|order) (?P<value>pizza)\b"),
        context=("pizza",),
    ),
)

# Airport codes are the one open vocabulary an elliptical statement can
# name without any slot context ("Correction: use SFO."). Bounded to a
# three-letter uppercase token in the source text so ordinary words
# never read as an airport.
_AIRPORT_CODE = re.compile(r"\b([A-Z]{3})\b")

_ELLIPTICAL_VALUE = re.compile(
    r"\b(?:make it|back to|switch to|change it to|use)\s+(?P<value>[a-z0-9-]+)\b"
)


# --- Synonym and scope canonicalization --------------------------------------

#: Domain-scoped synonyms. Keyed by value_domain so "window" in the seat
#: domain can never canonicalize a device or workflow term (§13.4).
_VALUE_SYNONYMS = {
    "seat": {
        "aisle seat": "aisle",
        "aisle seats": "aisle",
        "window seat": "window",
        "window seats": "window",
        "middle seat": "middle",
        "middle seats": "middle",
    },
    "ground_transport": {
        "rental cars": "rental car",
        "car rental": "rental car",
        "car rentals": "rental car",
        "public transportation": "public transit",
        "public transit": "public transit",
    },
    "cuisine": {
        "vegetarian restaurants": "vegetarian",
        "vegetarian places": "vegetarian",
        "vegetarian": "vegetarian",
    },
}

#: Canonical scope buckets. Order matters: longer, more specific phrases
#: are matched first so "short work trips" never degrades to "work trips".
_SCOPE_ALIASES = (
    ("short work trips", "short_work_trip"),
    ("short business trips", "short_work_trip"),
    ("short domestic flights", "short_domestic"),
    ("short domestic trips", "short_domestic"),
    ("long international flights", "long_international"),
    ("long international trips", "long_international"),
    ("weekend personal trips", "weekend_personal"),
    ("personal trips", "personal"),
    ("work flights", "work"),
    ("work trips", "work_trip"),
    ("business trips", "work_trip"),
)

#: Scope containment: child -> parent. A child and its parent overlap;
#: neither clean coexistence nor a clean conflict can be claimed.
_SCOPE_PARENTS = {
    "short_work_trip": "work_trip",
    "weekend_personal": "personal",
    "short_domestic": "domestic",
    "long_international": "international",
}

_SCOPE_PHRASE = re.compile(r"\bfor (?:my )?(?P<scope>[a-z' -]+?)(?:\s*[,.]|$)")


def canonical_scope(phrase: str) -> tuple:
    """(canonical_scope, matched_alias) for a scope phrase."""
    lowered = normalize_text(phrase)
    for alias, canonical in _SCOPE_ALIASES:
        if alias in lowered:
            return canonical, alias
    return _slug(lowered) or UNKNOWN, ""


def _surface_forms(spec: "AttributeSpec") -> tuple:
    """Every surface wording that names a value in this slot.

    Canonical values plus the domain's synonym keys, longest first so
    "public transportation" is never shortened to a partial match.
    """
    forms = set(spec.values) | set(_VALUE_SYNONYMS.get(spec.value_domain, {}))
    return tuple(sorted(forms, key=len, reverse=True))


def canonical_value(value_domain: str, raw: str) -> tuple:
    """(canonical_value, matched_synonym) inside one value domain."""
    lowered = normalize_text(raw).strip(" .")
    table = _VALUE_SYNONYMS.get(value_domain, {})
    if lowered in table:
        return table[lowered], lowered
    for surface, canonical in table.items():
        if re.search(rf"\b{re.escape(surface)}\b", lowered):
            return canonical, surface
    return lowered, ""


# --- Projection ---------------------------------------------------------------

# "X instead of Y [for <scope>]": Y is the value being replaced, so it
# must not be read as the asserted value. A trailing scope phrase is
# left intact — it qualifies X, not Y.
_INSTEAD_OF = re.compile(
    r",?\s*\binstead of\b[^.;]*?(?=\s+for\b|[.;]|$)", re.IGNORECASE
)
_LEAD_INS = re.compile(
    r"^(?:actually|correction|quick note|one more change|okay|ok|so|and|but)\b"
    r"[\s,:—-]*",
    re.IGNORECASE,
)


_PREFERENCE_FORMS = (
    re.compile(r"\bi\s+(?:now\s+)?(?:prefer|like|love|enjoy|dislike|hate|avoid)\b"),
    re.compile(r"\b(?:don't|do not|dont)\s+like\b"),
    re.compile(r"\bmy usual choice\b"),
    re.compile(r"\b(?:is|are)\s+what\s+i\b"),
)

_FACT_FORMS = (
    re.compile(r"\bmy\s+[\w' ]+\s+is\b"),
    re.compile(r"\bi\s+am\s+(?:based|allergic|located|living)\b"),
)

_INSTRUCTION_OPENER = re.compile(
    r"^(?:from now on[\s,]*)?(?:please\s+)?"
    r"(?:use|send|include|order|route|switch|make|change|add|always|never|stop)\b"
)


def infer_kind(text: str) -> str:
    """Deterministic memory kind for a statement.

    Bounded and ordered: an explicit preference verb wins over a
    possessive fact form ("I prefer my window seat" is a preference),
    which wins over an imperative opener. Defaults to ``preference``,
    the kind the canonical planner also defaults to.
    """
    lowered = normalize_text(_LEAD_INS.sub("", (text or "").strip()))
    for pattern in _PREFERENCE_FORMS:
        if pattern.search(lowered):
            return MemoryKind.PREFERENCE
    for pattern in _FACT_FORMS:
        if pattern.search(lowered):
            return MemoryKind.FACT
    if _INSTRUCTION_OPENER.search(lowered):
        return MemoryKind.INSTRUCTION
    return MemoryKind.PREFERENCE


class IdentityProjector:
    """Projects memories and proposed statements into identities.

    Structured metadata is preferred over reparsing text: an
    ``ExperienceEntry`` carrying committed ``semantic_identity`` metadata
    contributes its subject/attribute/value/scope directly. Text
    projection is the fallback, and returns ``unknown`` rather than a
    guess whenever the bounded lexicon does not support the statement.
    """

    version = IDENTITY_PROJECTION_VERSION

    def project_entry(self, entry: ExperienceEntry) -> MemoryIdentity:
        """Project a stored memory. Never mutates ``entry``."""
        identity = self.project_text(
            entry.text,
            kind=entry.kind,
            provenance_ref=entry.metadata.get("provenance")
            or entry.source_session_id
            or None,
            evidence_ref=entry.metadata.get("evidence_span_ref"),
        )
        stored = entry.metadata.get(METADATA_KEY)
        if stored:
            identity = self._merge_stored(identity, stored)
        return identity

    def _merge_stored(self, identity, stored) -> MemoryIdentity:
        """Overlay committed semantic-identity metadata onto a projection.

        Stored metadata is evidence the system already committed to, so
        it fills fields the text projection left unknown. It never
        overrides a field the text projection established, because the
        two vocabularies are versioned independently.
        """
        semantic = SemanticIdentity.from_metadata(stored)
        if semantic is None:
            return identity
        updates = {}
        if not identity.attribute.known:
            updates["attribute"] = IdentityField(
                value=semantic.attribute,
                known=True,
                source="structured_metadata",
                evidence=METADATA_KEY,
            )
        if not identity.value.known and semantic.value:
            updates["value"] = IdentityField(
                value=semantic.value,
                known=True,
                source="structured_metadata",
                evidence=METADATA_KEY,
            )
        if not updates:
            return identity
        merged = replace(identity, projection_method="structured_metadata", **updates)
        return replace(merged, **_completeness(merged))

    def project_text(
        self,
        text: str,
        kind: str | None = None,
        provenance_ref: str | None = None,
        evidence_ref: str | None = None,
    ) -> MemoryIdentity:
        """Project a raw statement into a structured identity.

        ``kind`` is taken from the caller when known (the planner and
        the extractor both know it); otherwise it is inferred
        deterministically from the statement.
        """
        source_text = text or ""
        if kind is None:
            kind = infer_kind(source_text)
        markers = _detect_markers(source_text)
        categories = [c for c, _ in markers]

        # A compound "used to X ... now Y" asserts a current value. The
        # historical clause is recorded, never collapsed into the value.
        working = source_text
        historical_value = None
        compound = _COMPOUND_NOW.match(normalize_text(source_text))
        if compound and TemporalStatus.QUESTION not in categories:
            historical_value = self._clause_value(compound.group("past"), kind)
            working = compound.group("current")
            categories = [c for c in categories if c != TemporalStatus.HISTORICAL]
            markers = markers + ((TemporalStatus.CURRENT, "used to ... now"),)

        temporal, durability = self._temporal(categories)

        # "window seats instead of aisle seats": the replaced value is
        # context, never the asserted value.
        stripped = _INSTEAD_OF.sub("", working)
        stripped = _LEAD_INS.sub("", stripped.strip())

        subject, attribute, value, scope, specified, domain = self._slots(
            stripped, source_text, kind
        )

        identity = MemoryIdentity(
            source_text=source_text,
            normalized_text=normalize_text(source_text),
            comparison_text=comparison_text(source_text),
            subject=subject,
            attribute=attribute,
            value=value,
            scope=scope,
            kind=kind,
            qualifiers=_qualifiers(categories),
            temporal_status=temporal,
            durability=durability,
            value_domain=domain,
            scope_specified=specified,
            historical_value=historical_value,
            markers=tuple(f"{c}:{s}" for c, s in markers),
            provenance_ref=provenance_ref,
            evidence_ref=evidence_ref,
        )
        return replace(identity, **_completeness(identity))

    def _clause_value(self, clause: str, kind: str) -> str | None:
        _, _, value, _, _, _ = self._slots(clause, clause, kind)
        return value.value if value.known else None

    def _temporal(self, categories) -> tuple:
        for category in (
            TemporalStatus.QUESTION,
            TemporalStatus.HYPOTHETICAL,
            TemporalStatus.TEMPORARY,
            TemporalStatus.HISTORICAL,
        ):
            if category in categories:
                return category, Durability.NON_DURABLE
        return TemporalStatus.CURRENT, Durability.DURABLE

    def _slots(self, text: str, source_text: str, kind: str) -> tuple:
        """Resolve (subject, attribute, value, scope, specified, domain)."""
        lowered = normalize_text(text)
        scope_field, specified = self._scope(lowered)
        # Scope phrases are context for the slot, not part of the value.
        body = _SCOPE_PHRASE.sub(" ", lowered)

        best = self._match_attribute(lowered, body)
        if best is not None:
            spec, value, evidence = best
            return (
                IdentityField(spec.subject, True, "lexicon", spec.attribute),
                IdentityField(spec.attribute, True, "lexicon", evidence),
                IdentityField(value, True, "lexicon", evidence),
                scope_field,
                specified,
                spec.value_domain,
            )

        # Elliptical correction: a value with no slot context. The value
        # domain is projected; the specific attribute stays unknown and
        # is resolved (or failed closed) against the active set.
        value, domain, evidence = self._elliptical(lowered, source_text)
        if value is not None:
            return (
                IdentityField.unknown("no slot context"),
                IdentityField.unknown("no slot context"),
                IdentityField(value, True, "lexicon", evidence),
                scope_field,
                specified,
                domain,
            )
        return (
            IdentityField.unknown("unsupported statement"),
            IdentityField.unknown("unsupported statement"),
            IdentityField.unknown("unsupported statement"),
            scope_field,
            specified,
            UNKNOWN,
        )

    def _match_attribute(self, lowered: str, body: str):
        """First attribute spec whose context and value both match."""
        for spec in _ATTRIBUTES:
            if spec.context and not any(
                re.search(rf"\b{re.escape(c)}\b", lowered) for c in spec.context
            ):
                continue
            if spec.value_pattern is not None:
                match = spec.value_pattern.search(lowered)
                if match:
                    raw = match.group("value").strip()
                    value, _ = canonical_value(spec.value_domain, raw)
                    return spec, value, raw
                continue
            for candidate in _surface_forms(spec):
                if re.search(rf"\b{re.escape(candidate)}\b", body):
                    value, synonym = canonical_value(spec.value_domain, candidate)
                    return spec, value, synonym or candidate
        return None

    def _elliptical(self, lowered: str, source_text: str) -> tuple:
        match = _ELLIPTICAL_VALUE.search(lowered)
        if match:
            raw = match.group("value")
            for spec in _ATTRIBUTES:
                if raw in spec.values:
                    value, _ = canonical_value(spec.value_domain, raw)
                    return value, spec.value_domain, raw
            code = _AIRPORT_CODE.search(source_text or "")
            if code and normalize_text(code.group(1)) == raw:
                return raw, "airport", code.group(1)
        return None, UNKNOWN, ""

    def _scope(self, lowered: str) -> tuple:
        match = _SCOPE_PHRASE.search(lowered)
        if not match:
            return IdentityField(UNSCOPED, True, "pattern", ""), False
        canonical, alias = canonical_scope(match.group("scope"))
        return (
            IdentityField(canonical, True, "lexicon", alias or match.group("scope")),
            True,
        )


def _qualifiers(categories) -> dict:
    return {
        "historical": TemporalStatus.HISTORICAL in categories,
        "temporary": TemporalStatus.TEMPORARY in categories,
        "hypothetical": TemporalStatus.HYPOTHETICAL in categories,
        "question": TemporalStatus.QUESTION in categories,
    }


_CRITICAL_FIELDS = ("subject", "attribute", "value", "scope")


def _completeness(identity: MemoryIdentity) -> dict:
    unknown = tuple(
        name
        for name in _CRITICAL_FIELDS
        if not getattr(identity, name).known
    )
    known = len(_CRITICAL_FIELDS) - len(unknown)
    return {
        "unknown_fields": unknown,
        "completeness": round(known / len(_CRITICAL_FIELDS), 4),
    }


# --- Comparison ---------------------------------------------------------------

_COMPATIBLE_KINDS = frozenset(
    {
        (MemoryKind.PREFERENCE, MemoryKind.PREFERENCE),
        (MemoryKind.FACT, MemoryKind.FACT),
        (MemoryKind.INSTRUCTION, MemoryKind.INSTRUCTION),
        # A standing instruction and a preference can name the same
        # durable slot ("Include public transit options for work trips."
        # vs "Use rental cars ... for work trips."). Identity may relate
        # them; lifecycle policy still decides what to do about it.
        (MemoryKind.INSTRUCTION, MemoryKind.PREFERENCE),
        (MemoryKind.PREFERENCE, MemoryKind.INSTRUCTION),
    }
)


def _scope_relation(existing: MemoryIdentity, proposed: MemoryIdentity) -> str:
    if not (existing.scope.known and proposed.scope.known):
        return ScopeRelation.UNKNOWN
    if existing.scope_specified != proposed.scope_specified:
        # One statement names a scope and the other does not. Never
        # assume they share it: the caller resolves this against the
        # active set or fails closed.
        return ScopeRelation.UNKNOWN
    if existing.scope.value == proposed.scope.value:
        # Neither statement names a scope: compatible by default rather
        # than proven identical. Both readings permit a conflict, but
        # only one of them was actually asserted.
        if not existing.scope_specified:
            return ScopeRelation.COMPATIBLE
        return ScopeRelation.EQUAL
    if (
        _SCOPE_PARENTS.get(existing.scope.value) == proposed.scope.value
        or _SCOPE_PARENTS.get(proposed.scope.value) == existing.scope.value
    ):
        return ScopeRelation.OVERLAPPING
    return ScopeRelation.DISJOINT


def _field_relation(a: IdentityField, b: IdentityField) -> str:
    """Relate two fields, distinguishing identical from canonicalized.

    ``equivalent`` means the two sides reached the same canonical value
    from different surface wording ("aisle seat" vs "aisle"), which is
    what separates a semantic duplicate from an exact one.
    """
    if not (a.known and b.known):
        return FieldRelation.UNKNOWN
    if a.value != b.value:
        return FieldRelation.DIFFERENT
    if a.evidence != b.evidence:
        return FieldRelation.EQUIVALENT
    return FieldRelation.EQUAL


class IdentityComparer:
    """Ordered, explainable comparison of two projected identities."""

    version = IDENTITY_COMPARISON_VERSION

    def compare(
        self, existing: MemoryIdentity, proposed: MemoryIdentity
    ) -> IdentityComparison:
        """Relate ``proposed`` to ``existing``. Pure and non-mutating."""
        rationale = []
        kind_compatible = (existing.kind, proposed.kind) in _COMPATIBLE_KINDS
        exact_text = (
            bool(existing.comparison_text)
            and existing.comparison_text == proposed.comparison_text
        )
        base = dict(
            exact_text_match=exact_text,
            subject_relation=_field_relation(existing.subject, proposed.subject),
            attribute_relation=_field_relation(existing.attribute, proposed.attribute),
            value_relation=_field_relation(existing.value, proposed.value),
            scope_relation=_scope_relation(existing, proposed),
            qualifier_relation=(
                FieldRelation.EQUAL
                if existing.qualifiers == proposed.qualifiers
                else FieldRelation.DIFFERENT
            ),
            temporal_relation=(
                FieldRelation.EQUAL
                if existing.temporal_status == proposed.temporal_status
                else FieldRelation.DIFFERENT
            ),
            kind_compatible=kind_compatible,
            durability_compatible=existing.durability == proposed.durability,
            unknown_fields=proposed.unknown_fields,
            target_key=proposed.target_key(),
        )

        def result(relation, *, fail_closed=False, candidate=False, conflicts=()):
            return IdentityComparison(
                relation=relation,
                conflict_fields=tuple(conflicts),
                rationale=tuple(rationale),
                fail_closed=fail_closed,
                supersession_candidate=candidate,
                **base,
            )

        # 1. Exact text identity short-circuits: same durable meaning.
        if exact_text and kind_compatible:
            rationale.append(
                IdentityDiagnostic("exact_text_match", "identical normalized text")
            )
            return result(IdentityRelation.EXACT_DUPLICATE)

        # 2. Non-durable proposals never establish a durable relation.
        if proposed.temporal_status == TemporalStatus.QUESTION:
            rationale.append(IdentityDiagnostic("question_marker", proposed.markers[0] if proposed.markers else ""))
            return result(IdentityRelation.QUESTION, fail_closed=True)
        if proposed.temporal_status == TemporalStatus.HYPOTHETICAL:
            rationale.append(IdentityDiagnostic("hypothetical_marker", ", ".join(proposed.markers)))
            return result(IdentityRelation.HYPOTHETICAL, fail_closed=True)
        if proposed.temporal_status == TemporalStatus.TEMPORARY:
            rationale.append(
                IdentityDiagnostic("temporary_marker", ", ".join(proposed.markers))
            )
            return result(IdentityRelation.TEMPORARY_EXCEPTION, fail_closed=True)
        if proposed.temporal_status == TemporalStatus.HISTORICAL:
            rationale.append(
                IdentityDiagnostic("historical_marker", ", ".join(proposed.markers))
            )
            return result(IdentityRelation.HISTORICAL, fail_closed=True)

        # 3. Kind compatibility.
        if not kind_compatible:
            rationale.append(
                IdentityDiagnostic(
                    "kind_incompatible", f"{existing.kind} vs {proposed.kind}"
                )
            )
            return result(IdentityRelation.UNRELATED)

        # 4/5. Subject and attribute. Both known and different means the
        # memories name different experience: preserve, never target.
        if base["subject_relation"] == FieldRelation.DIFFERENT or (
            base["attribute_relation"] == FieldRelation.DIFFERENT
        ):
            rationale.append(
                IdentityDiagnostic(
                    "distinct_identity",
                    f"{existing.subject.value}.{existing.attribute.value} vs "
                    f"{proposed.subject.value}.{proposed.attribute.value}",
                )
            )
            return result(IdentityRelation.UNRELATED)

        # A proposal with no established value cannot relate to anything.
        if not proposed.value.known:
            rationale.append(
                IdentityDiagnostic("unknown_value", "value not established from evidence")
            )
            return result(IdentityRelation.AMBIGUOUS, fail_closed=True)

        # Elliptical proposal: no attribute, but a value domain. Relate
        # only within the same value domain, and only as a candidate —
        # the set-level resolver confirms or fails closed.
        if not proposed.attribute.known:
            if (
                proposed.value_domain != UNKNOWN
                and proposed.value_domain == existing.value_domain
            ):
                if proposed.value.value == existing.value.value:
                    rationale.append(
                        IdentityDiagnostic("elliptical_same_value", proposed.value.value)
                    )
                    return result(IdentityRelation.SEMANTIC_DUPLICATE)
                rationale.append(
                    IdentityDiagnostic(
                        "elliptical_value_conflict",
                        f"{existing.value.value} -> {proposed.value.value} "
                        f"in domain {proposed.value_domain}",
                    )
                )
                return result(
                    IdentityRelation.CURRENT_STATE_CONFLICT,
                    candidate=True,
                    conflicts=("value",),
                )
            rationale.append(
                IdentityDiagnostic("unknown_attribute", "no slot context in evidence")
            )
            return result(IdentityRelation.AMBIGUOUS, fail_closed=True)

        if not existing.attribute.known:
            rationale.append(
                IdentityDiagnostic("existing_unprojected", "existing identity unknown")
            )
            return result(IdentityRelation.AMBIGUOUS, fail_closed=True)

        # 6. Scope.
        scope_relation = base["scope_relation"]
        if scope_relation == ScopeRelation.DISJOINT:
            if proposed.value.value == existing.value.value:
                rationale.append(
                    IdentityDiagnostic(
                        "same_value_distinct_scope",
                        f"{existing.scope.value} vs {proposed.scope.value}",
                    )
                )
            else:
                rationale.append(
                    IdentityDiagnostic(
                        "distinct_supported_scope",
                        f"{existing.scope.value} vs {proposed.scope.value}",
                    )
                )
            return result(IdentityRelation.SCOPED_COEXISTENCE)
        if scope_relation == ScopeRelation.OVERLAPPING:
            rationale.append(
                IdentityDiagnostic(
                    "scope_containment",
                    f"{existing.scope.value} contains or is contained by "
                    f"{proposed.scope.value}",
                )
            )
            return result(IdentityRelation.AMBIGUOUS, fail_closed=True)

        # 7. Value, within an equal or unresolved scope.
        if proposed.value.value == existing.value.value:
            relation = (
                IdentityRelation.EXACT_DUPLICATE
                if exact_text
                else IdentityRelation.SEMANTIC_DUPLICATE
            )
            rationale.append(
                IdentityDiagnostic(
                    "same_slot_same_value",
                    f"{proposed.target_key()} = {proposed.value.value}",
                )
            )
            return result(relation)

        if scope_relation == ScopeRelation.UNKNOWN:
            rationale.append(
                IdentityDiagnostic(
                    "unresolved_scope_value_conflict",
                    f"{existing.value.value} -> {proposed.value.value}; "
                    "scope not established on both sides",
                )
            )
            return result(
                IdentityRelation.CURRENT_STATE_CONFLICT,
                candidate=True,
                conflicts=("value",),
            )

        rationale.append(
            IdentityDiagnostic(
                "current_value_conflict",
                f"{existing.value.value} -> {proposed.value.value} "
                f"in scope {proposed.scope.value}",
            )
        )
        return result(
            IdentityRelation.CURRENT_STATE_CONFLICT,
            candidate=True,
            conflicts=("value",),
        )


# --- Public API ---------------------------------------------------------------

_PROJECTOR = IdentityProjector()
_COMPARER = IdentityComparer()


def project_memory(entry: ExperienceEntry) -> MemoryIdentity:
    """Project a stored memory into its identity. Never mutates it."""
    return _PROJECTOR.project_entry(entry)


def project_statement(
    text: str, kind: str | None = None, **kwargs
) -> MemoryIdentity:
    """Project a proposed statement into its identity.

    ``kind`` is inferred from the statement when the caller omits it.
    """
    return _PROJECTOR.project_text(text, kind=kind, **kwargs)


def compare_memory_identity(
    existing: MemoryIdentity, proposed: MemoryIdentity
) -> IdentityComparison:
    """Relate a proposed identity to an existing one."""
    return _COMPARER.compare(existing, proposed)


@dataclass(frozen=True)
class IdentityResolution:
    """Set-level outcome of one proposal against an active snapshot.

    Pairwise comparison cannot resolve an elliptical or unscoped
    proposal on its own: "Actually, make it window." names a value but
    no slot. This resolver confirms such a conflict only when exactly
    one active memory is a candidate, and fails closed otherwise —
    ambiguity never selects a supersession target.
    """

    relation: str
    target_index: int | None = None
    comparisons: tuple = ()
    fail_closed: bool = False
    rationale: tuple = ()

    def to_record(self) -> dict:
        return {
            "relation": self.relation,
            "target_index": self.target_index,
            "fail_closed": self.fail_closed,
            "rationale": [d.to_record() for d in self.rationale],
            "comparisons": [c.to_record() for c in self.comparisons],
        }


#: Relation precedence when several active memories are compared. The
#: first match wins: a duplicate or conflict is more specific than
#: coexistence, which is more specific than unrelated.
_PRECEDENCE = (
    IdentityRelation.EXACT_DUPLICATE,
    IdentityRelation.SEMANTIC_DUPLICATE,
    IdentityRelation.CURRENT_STATE_CONFLICT,
    IdentityRelation.SCOPED_COEXISTENCE,
    IdentityRelation.AMBIGUOUS,
    IdentityRelation.UNRELATED,
)


def resolve_identity(
    proposed: MemoryIdentity, active: list
) -> IdentityResolution:
    """Relate one proposal to an active snapshot of identities.

    ``active`` is a list of :class:`MemoryIdentity`. Returns the
    strongest relation found, plus the resolved target index when — and
    only when — exactly one active memory is a supersession candidate.
    """
    comparisons = tuple(_COMPARER.compare(existing, proposed) for existing in active)

    # A non-durable proposal is decided by the statement alone.
    for comparison in comparisons:
        if comparison.relation in (
            IdentityRelation.QUESTION,
            IdentityRelation.HYPOTHETICAL,
            IdentityRelation.TEMPORARY_EXCEPTION,
            IdentityRelation.HISTORICAL,
        ):
            return IdentityResolution(
                relation=comparison.relation,
                comparisons=comparisons,
                fail_closed=True,
                rationale=comparison.rationale,
            )

    if not comparisons:
        return IdentityResolution(
            relation=IdentityRelation.UNRELATED,
            comparisons=(),
            rationale=(IdentityDiagnostic("empty_active_set", "no memory to compare"),),
        )

    conflicts = [
        index
        for index, comparison in enumerate(comparisons)
        if comparison.relation == IdentityRelation.CURRENT_STATE_CONFLICT
    ]
    if len(conflicts) > 1:
        return IdentityResolution(
            relation=IdentityRelation.AMBIGUOUS,
            comparisons=comparisons,
            fail_closed=True,
            rationale=(
                IdentityDiagnostic(
                    "multiple_conflict_targets",
                    f"{len(conflicts)} active memories could be the target",
                ),
            ),
        )

    for relation in _PRECEDENCE:
        for index, comparison in enumerate(comparisons):
            if comparison.relation != relation:
                continue
            return IdentityResolution(
                relation=relation,
                target_index=index if relation in (
                    IdentityRelation.CURRENT_STATE_CONFLICT,
                    IdentityRelation.EXACT_DUPLICATE,
                    IdentityRelation.SEMANTIC_DUPLICATE,
                ) else None,
                comparisons=comparisons,
                fail_closed=comparison.fail_closed,
                rationale=comparison.rationale,
            )
    return IdentityResolution(
        relation=IdentityRelation.UNRELATED, comparisons=comparisons
    )
