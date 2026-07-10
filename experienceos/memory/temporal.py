"""Temporal and provenance metadata for durable experience.

Phase 9 Prompt 6. This module owns:

- ``TemporalMetadata`` / ``ProvenanceMetadata``: additive, versioned,
  optional-field structures stored on the existing entry metadata JSON
  channel (legacy rows without them stay fully readable);
- ``TemporalNormalizer``: a bounded deterministic parser for explicit
  dates, relative expressions (resolved only against a supplied
  reference date), current/historical/future/recurring cues, and
  ranges — with explicit uncertainty and hard no-fabrication rules;
- ``interpret_query_mode``: deterministic current / historical /
  as-of / timeline query intent;
- ``resolve_validity``: validity intervals derived at read time from
  a record's own temporal metadata plus its supersession links —
  corrections never require store mutation or background workers.

Conservative rules enforced here: observation time is not event time;
old does not mean obsolete; relative time requires a reference date;
uncertain time stays uncertain; exact dates are never fabricated.

No benchmark oracle data is referenced anywhere in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace as dc_replace
from datetime import date, timedelta

TEMPORAL_VERSION = "1"
PROVENANCE_VERSION = "1"
TEMPORAL_KEY = "temporal"
PROVENANCE_KEY = "provenance"
QUERY_MODE_VERSION = "1"
VALIDITY_STRATEGY = "derived_at_read_from_links-1"


class TemporalScope:
    CURRENT = "current"
    HISTORICAL = "historical"
    FUTURE = "future"
    RECURRING = "recurring"
    TIMELESS = "timeless"
    UNKNOWN = "unknown"


class TimePrecision:
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    RANGE = "range"
    RELATIVE = "relative"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class SourceType:
    USER_ASSERTED = "user_asserted"
    ASSISTANT_DERIVED = "assistant_derived"
    TOOL_VERIFIED = "tool_verified"
    JOINTLY_CONFIRMED = "jointly_confirmed"
    SYSTEM_OBSERVED = "system_observed"


# Documented trust ordering (highest first). Trust refines a relevant
# candidate; it never creates relevance on its own.
TRUST_ORDER = {
    SourceType.TOOL_VERIFIED: 5,
    SourceType.USER_ASSERTED: 4,
    SourceType.JOINTLY_CONFIRMED: 3,
    SourceType.SYSTEM_OBSERVED: 2,
    SourceType.ASSISTANT_DERIVED: 1,
}


@dataclass(frozen=True)
class TemporalMetadata:
    """Optional-field temporal representation (version 1)."""

    observed_at: str | None = None  # when ExperienceOS learned it
    event_time: str | None = None  # when the described event occurred
    valid_from: str | None = None
    valid_until: str | None = None
    temporal_scope: str = TemporalScope.UNKNOWN
    source_session_date: str | None = None
    supersession_time: str | None = None
    time_precision: str = TimePrecision.UNKNOWN
    time_confidence: float = 1.0
    time_expression: str | None = None
    reference_time: str | None = None
    uncertainty_reason: str | None = None
    version: str = TEMPORAL_VERSION

    def to_metadata(self) -> dict:
        payload = {"version": self.version,
                   "temporal_scope": self.temporal_scope,
                   "time_precision": self.time_precision,
                   "time_confidence": self.time_confidence}
        for key in ("observed_at", "event_time", "valid_from",
                    "valid_until", "source_session_date",
                    "supersession_time", "time_expression",
                    "reference_time", "uncertainty_reason"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload

    @classmethod
    def from_metadata(cls, data) -> "TemporalMetadata | None":
        if not isinstance(data, dict):
            return None
        return cls(
            observed_at=data.get("observed_at"),
            event_time=data.get("event_time"),
            valid_from=data.get("valid_from"),
            valid_until=data.get("valid_until"),
            temporal_scope=data.get("temporal_scope", TemporalScope.UNKNOWN),
            source_session_date=data.get("source_session_date"),
            supersession_time=data.get("supersession_time"),
            time_precision=data.get("time_precision", TimePrecision.UNKNOWN),
            time_confidence=float(data.get("time_confidence", 1.0)),
            time_expression=data.get("time_expression"),
            reference_time=data.get("reference_time"),
            uncertainty_reason=data.get("uncertainty_reason"),
            version=data.get("version", TEMPORAL_VERSION),
        )


@dataclass(frozen=True)
class ProvenanceMetadata:
    """Source provenance (version 1)."""

    source_type: str = SourceType.USER_ASSERTED
    source_role: str = "user"
    source_message_ref: str | None = None
    source_session_id: str | None = None
    source_session_date: str | None = None
    derivation_refs: tuple = ()
    confirmation_status: str = "confirmed"  # confirmed|provisional|derived
    confirmed_by: str | None = "user"
    confidence: float = 1.0
    provisional: bool = False
    source_tool: str | None = None
    source_tool_result_ref: str | None = None
    version: str = PROVENANCE_VERSION

    def trust_level(self) -> int:
        return TRUST_ORDER.get(self.source_type, 0)

    def to_metadata(self) -> dict:
        payload = {
            "version": self.version,
            "source_type": self.source_type,
            "source_role": self.source_role,
            "confirmation_status": self.confirmation_status,
            "confidence": self.confidence,
            "provisional": self.provisional,
            "trust_level": self.trust_level(),
        }
        for key in ("source_message_ref", "source_session_id",
                    "source_session_date", "confirmed_by",
                    "source_tool", "source_tool_result_ref"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.derivation_refs:
            payload["derivation_refs"] = list(self.derivation_refs)
        return payload

    @classmethod
    def from_metadata(cls, data) -> "ProvenanceMetadata | None":
        if not isinstance(data, dict):
            return None
        return cls(
            source_type=data.get("source_type", SourceType.USER_ASSERTED),
            source_role=data.get("source_role", "user"),
            source_message_ref=data.get("source_message_ref"),
            source_session_id=data.get("source_session_id"),
            source_session_date=data.get("source_session_date"),
            derivation_refs=tuple(data.get("derivation_refs", ())),
            confirmation_status=data.get("confirmation_status", "confirmed"),
            confirmed_by=data.get("confirmed_by"),
            confidence=float(data.get("confidence", 1.0)),
            provisional=bool(data.get("provisional", False)),
            source_tool=data.get("source_tool"),
            source_tool_result_ref=data.get("source_tool_result_ref"),
            version=data.get("version", PROVENANCE_VERSION),
        )


# --------------------------------------------------------------------------
# Deterministic temporal extraction
# --------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}
_MONTH_RE = "|".join(_MONTHS)

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MDY = re.compile(
    rf"\b(?P<month>{_MONTH_RE})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
    r"(?:,?\s+(?P<year>(?:19|20)\d{2}))?\b",
    re.IGNORECASE,
)
_MONTH_YEAR = re.compile(
    rf"\b(?P<month>{_MONTH_RE})\s+(?P<year>(?:19|20)\d{{2}})\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:in|back in|during|since|until|of)\s+((?:19|20)\d{2})\b",
                   re.IGNORECASE)
_RELATIVE = re.compile(
    r"\b(?P<expr>today|yesterday|tomorrow"
    r"|last\s+(?:week|month|year)|next\s+(?:week|month|year)"
    r"|(?P<n>\w+)\s+(?P<unit>day|week|month|year)s?\s+ago"
    r"|(?P<n2>\w+)\s+(?P<unit2>day|week|month|year)s?\s+from\s+now)\b",
    re.IGNORECASE,
)
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a": 1, "an": 1,
}
_APPROXIMATE = re.compile(
    r"\b(?:a few|several|couple of|some)\s+(?:days|weeks|months|years)\s+ago\b"
    r"|\b(?:a while|long)\s+(?:ago|back)\b|\bsoon\b|\beventually\b"
    r"|\bin college\b|\bgrowing up\b",
    re.IGNORECASE,
)
_CURRENT_CUES = re.compile(
    r"\b(?:now|currently|these days|at the moment|from now on"
    r"|going forward|as of today)\b",
    re.IGNORECASE,
)
_HISTORICAL_CUES = re.compile(
    r"\b(?:used to|previously|back (?:in|then|when)|before i\b|formerly"
    r"|in college|when i (?:was|worked|lived)|no longer)\b",
    re.IGNORECASE,
)
_FUTURE_CUES = re.compile(
    r"\b(?:starting|beginning)\s+(?:next\s+\w+|on\b|\w+day\b|in\b|"
    rf"(?:{_MONTH_RE}))"
    r"|\bafter\s+(?:july|jan|feb|mar|apr|jun|aug|sep|oct|nov|dec|\d)"
    r"|\bwill\s+(?:start|begin|move|switch)\b|\bnext\s+(?:week|month|year)\b.*\bwill\b",
    re.IGNORECASE,
)
_RECURRING_CUES = re.compile(
    r"\b(?:every|each)\s+\w+|\bon weekdays\b|\bwhenever\b"
    r"|\b(?:daily|weekly|monthly|quarterly|annually)\b",
    re.IGNORECASE,
)
_RANGE = re.compile(
    rf"\bfrom\s+(?P<a>(?:{_MONTH_RE})(?:\s+(?:19|20)\d{{2}})?|(?:19|20)\d{{2}})"
    rf"\s+(?:to|until|through)\s+"
    rf"(?P<b>(?:{_MONTH_RE})(?:\s+(?:19|20)\d{{2}})?|(?:19|20)\d{{2}})\b"
    r"|\bbetween\s+(?P<c>(?:19|20)\d{2})\s+and\s+(?P<d>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday")


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


class TemporalNormalizer:
    """Bounded deterministic temporal expression extraction.

    ``normalize(text, reference)`` returns TemporalMetadata or None
    when the text carries no recognizable temporal signal. ``reference``
    is an ISO date string (e.g. the source session date) or None —
    relative expressions are resolved ONLY when a reference exists;
    otherwise they are preserved as unresolved with a reason. Exact
    days are never invented for month-level expressions.
    """

    version = TEMPORAL_VERSION

    def normalize(
        self, text: str, reference: str | None = None
    ) -> TemporalMetadata | None:
        scope = self._scope(text)
        explicit = self._explicit(text)
        time_range = self._range(text)
        approximate = _APPROXIMATE.search(text)
        # Approximate phrases ("a few years ago") are NOT resolvable
        # relative expressions; never coerce them into counts.
        relative = (
            None if approximate else self._relative(text, reference)
        )

        if explicit is None and relative is None and time_range is None \
                and not approximate and scope == TemporalScope.UNKNOWN:
            return None

        base = TemporalMetadata(
            temporal_scope=scope,
            source_session_date=reference,
            reference_time=reference,
        )
        if time_range is not None:
            start, end, expression = time_range
            return dc_replace(
                base,
                event_time=start, valid_from=start, valid_until=end,
                time_precision=TimePrecision.RANGE,
                time_expression=expression,
                temporal_scope=(
                    scope if scope != TemporalScope.UNKNOWN
                    else TemporalScope.HISTORICAL
                ),
            )
        if explicit is not None:
            value, precision, expression = explicit
            meta = dc_replace(
                base,
                event_time=value,
                time_precision=precision,
                time_expression=expression,
            )
            if scope == TemporalScope.FUTURE:
                meta = dc_replace(meta, valid_from=value)
            elif scope != TemporalScope.HISTORICAL:
                meta = dc_replace(meta, valid_from=value)
            return meta
        if relative is not None:
            return dc_replace(base, **relative)
        if approximate:
            return dc_replace(
                base,
                temporal_scope=(
                    scope if scope != TemporalScope.UNKNOWN
                    else TemporalScope.HISTORICAL
                ),
                time_precision=TimePrecision.APPROXIMATE,
                time_confidence=0.5,
                time_expression=approximate.group(0),
                uncertainty_reason="approximate expression",
            )
        # Scope cue only ("now", "used to", "every Monday").
        return dc_replace(
            base,
            time_precision=TimePrecision.UNKNOWN,
            time_expression=None,
        )

    @staticmethod
    def _scope(text: str) -> str:
        if _RECURRING_CUES.search(text):
            return TemporalScope.RECURRING
        if _FUTURE_CUES.search(text):
            return TemporalScope.FUTURE
        if _HISTORICAL_CUES.search(text):
            return TemporalScope.HISTORICAL
        if _CURRENT_CUES.search(text):
            return TemporalScope.CURRENT
        return TemporalScope.UNKNOWN

    @staticmethod
    def _explicit(text):
        match = _ISO_DATE.search(text)
        if match:
            value = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            if _parse_date(value):
                return value, TimePrecision.DAY, match.group(0)
        match = _MDY.search(text)
        if match and match.group("day") and int(match.group("day")) <= 31:
            month = _MONTHS[match.group("month").lower()]
            day = int(match.group("day"))
            year = match.group("year")
            if year:
                try:
                    value = date(int(year), month, day).isoformat()
                except ValueError:
                    return None
                return value, TimePrecision.DAY, match.group(0)
            # No year and no safe resolution: never invent one.
            return None
        match = _MONTH_YEAR.search(text)
        if match:
            month = _MONTHS[match.group("month").lower()]
            value = f"{match.group('year')}-{month:02d}"
            return value, TimePrecision.MONTH, match.group(0)
        match = _YEAR.search(text)
        if match:
            return match.group(1), TimePrecision.YEAR, match.group(0)
        return None

    @staticmethod
    def _relative(text, reference):
        match = _RELATIVE.search(text)
        if not match:
            return None
        expression = match.group("expr")
        if reference is None or _parse_date(reference) is None:
            return {
                "time_precision": TimePrecision.RELATIVE,
                "time_confidence": 0.5,
                "time_expression": expression,
                "uncertainty_reason": "no reference date for relative "
                                      "expression",
            }
        ref = _parse_date(reference)
        lowered = expression.lower()
        if lowered == "today":
            value, precision = ref.isoformat(), TimePrecision.DAY
        elif lowered == "yesterday":
            value, precision = (ref - timedelta(days=1)).isoformat(), \
                TimePrecision.DAY
        elif lowered == "tomorrow":
            value, precision = (ref + timedelta(days=1)).isoformat(), \
                TimePrecision.DAY
        elif lowered.startswith(("last", "next")):
            unit = lowered.split()[1]
            sign = -1 if lowered.startswith("last") else 1
            if unit == "week":
                anchor = ref + timedelta(days=7 * sign)
                value = anchor.isoformat()
                precision = TimePrecision.RANGE  # week-level, no exact day
            elif unit == "month":
                month = ref.month + sign
                year = ref.year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                value = f"{year}-{month:02d}"
                precision = TimePrecision.MONTH  # no invented exact day
            else:  # year
                value = str(ref.year + sign)
                precision = TimePrecision.YEAR
        else:
            count = match.group("n") or match.group("n2")
            unit = (match.group("unit") or match.group("unit2") or "").lower()
            number = _NUM_WORDS.get(str(count).lower())
            if number is None:
                try:
                    number = int(count)
                except (TypeError, ValueError):
                    return {
                        "time_precision": TimePrecision.RELATIVE,
                        "time_confidence": 0.4,
                        "time_expression": expression,
                        "uncertainty_reason": "unresolvable count",
                    }
            sign = -1 if "ago" in lowered else 1
            if unit == "day":
                value = (ref + timedelta(days=number * sign)).isoformat()
                precision = TimePrecision.DAY
            elif unit == "week":
                value = (ref + timedelta(days=7 * number * sign)).isoformat()
                precision = TimePrecision.RANGE
            elif unit == "month":
                month = ref.month + number * sign
                year = ref.year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                value = f"{year}-{month:02d}"
                precision = TimePrecision.MONTH
            else:
                value = str(ref.year + number * sign)
                precision = TimePrecision.YEAR
        scope_hint = (
            TemporalScope.FUTURE
            if ("from now" in lowered or lowered in ("tomorrow",)
                or lowered.startswith("next"))
            else TemporalScope.HISTORICAL
            if ("ago" in lowered or lowered in ("yesterday",)
                or lowered.startswith("last"))
            else TemporalScope.UNKNOWN
        )
        result = {
            "event_time": value,
            "time_precision": precision,
            "time_expression": expression,
        }
        if scope_hint != TemporalScope.UNKNOWN:
            result["temporal_scope"] = scope_hint
        if scope_hint == TemporalScope.FUTURE:
            result["valid_from"] = value
        return result

    @staticmethod
    def _range(text):
        match = _RANGE.search(text)
        if not match:
            return None

        def normalize_part(part):
            if part is None:
                return None
            part = part.strip().lower()
            if re.fullmatch(r"(?:19|20)\d{2}", part):
                return part
            pieces = part.split()
            month = _MONTHS.get(pieces[0])
            if month and len(pieces) == 2:
                return f"{pieces[1]}-{month:02d}"
            if month:
                return None  # month without year: cannot resolve safely
            return None

        start = normalize_part(match.group("a") or match.group("c"))
        end = normalize_part(match.group("b") or match.group("d"))
        if start is None and end is None:
            return None
        return start, end, match.group(0)


# --------------------------------------------------------------------------
# Query mode interpretation
# --------------------------------------------------------------------------


class QueryMode:
    CURRENT = "current"
    HISTORICAL = "historical"
    AS_OF = "as_of"
    TIMELINE = "timeline"


_TIMELINE_QUERY = re.compile(
    r"\bhow has\b.*\bchanged\b|\b(?:show|list|give me)\b.*\bhistory\b"
    r"|\bover time\b|\btimeline\b|\bchronolog",
    re.IGNORECASE,
)
_AS_OF_QUERY = re.compile(
    rf"\bas of\s+(?P<ref>(?:{_MONTH_RE})\s+(?:19|20)\d{{2}}|(?:19|20)\d{{2}})"
    rf"|\b(?:in|during)\s+(?P<year>(?:19|20)\d{{2}})\b",
    re.IGNORECASE,
)
_HISTORICAL_QUERY = re.compile(
    r"\bbefore\b|\bused to\b|\bback then\b|\bpreviously\b"
    r"|\bwhat was my\b|\bold\s+(?:phone|job|address|city|employer|one)\b"
    r"|\bdid i (?:use|have|live|work|prefer)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryTemporalIntent:
    mode: str = QueryMode.CURRENT
    reference: str | None = None  # as-of reference (year or YYYY-MM)
    version: str = QUERY_MODE_VERSION


def interpret_query_mode(query: str) -> QueryTemporalIntent:
    """Deterministic temporal intent. Ambiguity defaults to current —
    casual past tense never exposes superseded records."""
    if _TIMELINE_QUERY.search(query):
        return QueryTemporalIntent(mode=QueryMode.TIMELINE)
    match = _AS_OF_QUERY.search(query)
    if match:
        year = match.group("year")
        if year:
            return QueryTemporalIntent(mode=QueryMode.AS_OF, reference=year)
        ref = match.group("ref").lower().split()
        if len(ref) == 2 and ref[0] in _MONTHS:
            return QueryTemporalIntent(
                mode=QueryMode.AS_OF,
                reference=f"{ref[1]}-{_MONTHS[ref[0]]:02d}",
            )
        return QueryTemporalIntent(mode=QueryMode.AS_OF, reference=ref[0])
    if _HISTORICAL_QUERY.search(query):
        return QueryTemporalIntent(mode=QueryMode.HISTORICAL)
    return QueryTemporalIntent(mode=QueryMode.CURRENT)


# --------------------------------------------------------------------------
# Validity resolution (derived at read time)
# --------------------------------------------------------------------------


def temporal_of(entry) -> TemporalMetadata | None:
    return TemporalMetadata.from_metadata(entry.metadata.get(TEMPORAL_KEY))


def provenance_of(entry) -> ProvenanceMetadata | None:
    return ProvenanceMetadata.from_metadata(
        entry.metadata.get(PROVENANCE_KEY)
    )


@dataclass(frozen=True)
class ResolvedValidity:
    valid_from: str | None
    valid_until: str | None
    supersession_time: str | None
    scope: str
    precision: str


def resolve_validity(entry, by_id: dict) -> ResolvedValidity:
    """Validity interval derived at read time.

    A superseded record's valid_until is derived from (in order): its
    own stored valid_until, its superseder's valid_from/event_time, or
    the recorded supersession time — never fabricated beyond what the
    evidence supports. No store mutation, no background workers.
    """
    temporal = temporal_of(entry)
    valid_from = temporal.valid_from if temporal else None
    valid_until = temporal.valid_until if temporal else None
    scope = temporal.temporal_scope if temporal else TemporalScope.UNKNOWN
    precision = temporal.time_precision if temporal else TimePrecision.UNKNOWN
    supersession_time = entry.metadata.get("superseded_at")
    if entry.status == "superseded" and valid_until is None:
        superseder_id = entry.metadata.get("superseded_by")
        superseder = by_id.get(superseder_id) if superseder_id else None
        if superseder is not None:
            new_temporal = temporal_of(superseder)
            if new_temporal is not None:
                valid_until = (
                    new_temporal.valid_from
                    or new_temporal.event_time
                    or new_temporal.source_session_date
                )
        if valid_until is None and supersession_time:
            valid_until = supersession_time[:10]  # observation day
    return ResolvedValidity(
        valid_from=valid_from,
        valid_until=valid_until,
        supersession_time=supersession_time,
        scope=scope,
        precision=precision,
    )


def _period_key(value: str | None) -> str:
    return value or ""


def within_reference(validity: ResolvedValidity, reference: str) -> bool:
    """Whether a record was plausibly valid at an as-of reference
    (year or YYYY-MM prefix comparison; unknown bounds are permissive
    so uncertainty never silently hides evidence)."""
    start, end = validity.valid_from, validity.valid_until
    if start and _period_key(start)[: len(reference)] > reference:
        return False
    if end and _period_key(end)[: len(reference)] < reference:
        return False
    return True


def not_yet_valid(entry, reference: str | None) -> bool:
    """A future fact is not current before its valid-from time."""
    temporal = temporal_of(entry)
    if temporal is None or temporal.temporal_scope != TemporalScope.FUTURE:
        return False
    if temporal.valid_from is None:
        return True  # unresolved future: never current
    if reference is None:
        return True  # no runtime reference: hold conservatively
    return _period_key(temporal.valid_from) > reference


# --------------------------------------------------------------------------
# Retrieval-time temporal policy
# --------------------------------------------------------------------------


class TemporalRetrievalPolicy:
    """Mode-aware admission, scoring, and labeling for retrieval.

    Stateless per decision (mode is interpreted per query); the only
    mutable state is deterministic counters and the last interpreted
    intent (used for rendering labels). ``reference_time`` is an ISO
    date string supplied by the runtime (e.g. the question date) —
    never a wall clock — so future activation stays deterministic.
    """

    version = QUERY_MODE_VERSION

    def __init__(self, reference_time: str | None = None):
        self.reference_time = reference_time
        self.last_intent = QueryTemporalIntent()
        self.counters = {
            "retrievals": 0,
            "mode_current": 0,
            "mode_historical": 0,
            "mode_as_of": 0,
            "mode_timeline": 0,
            "not_yet_valid_held": 0,
            "historical_only_excluded": 0,
            "outside_as_of_excluded": 0,
            "superseded_admitted_historical": 0,
            "forgotten_excluded": 0,
        }

    def summary(self) -> dict:
        return {
            **self.counters,
            "temporal_query_mode_version": QUERY_MODE_VERSION,
            "temporal_metadata_version": TEMPORAL_VERSION,
            "provenance_version": PROVENANCE_VERSION,
            "validity_strategy": VALIDITY_STRATEGY,
            "forgotten_history_policy": "always_excluded_user_facing",
        }

    def interpret(self, query: str, historical_flag: bool = False):
        intent = interpret_query_mode(query)
        if historical_flag and intent.mode == QueryMode.CURRENT:
            intent = QueryTemporalIntent(mode=QueryMode.HISTORICAL)
        self.last_intent = intent
        self.counters["retrievals"] += 1
        self.counters[f"mode_{intent.mode}"] += 1
        return intent

    # -- admission -------------------------------------------------------------

    def admit(self, entry, intent) -> str | None:
        """None to admit; otherwise a deterministic exclusion reason.
        Forgotten records are excluded from every user-facing mode."""
        if entry.status == "forgotten":
            self.counters["forgotten_excluded"] += 1
            return "inactive_forgotten"
        if entry.status == "superseded":
            if intent.mode in (QueryMode.HISTORICAL, QueryMode.AS_OF,
                               QueryMode.TIMELINE):
                self.counters["superseded_admitted_historical"] += 1
                return None
            return "inactive_superseded"
        # Active records: temporal gating for current mode.
        if intent.mode == QueryMode.CURRENT:
            if not_yet_valid(entry, self.reference_time):
                self.counters["not_yet_valid_held"] += 1
                return "not_yet_valid"
            temporal = temporal_of(entry)
            if temporal is not None and temporal.temporal_scope == (
                TemporalScope.HISTORICAL
            ):
                self.counters["historical_only_excluded"] += 1
                return "historical_only"
        if intent.mode == QueryMode.AS_OF and intent.reference:
            validity = resolve_validity(entry, {})
            if not within_reference(validity, intent.reference):
                self.counters["outside_as_of_excluded"] += 1
                return "outside_as_of_interval"
        return None

    # -- scoring ---------------------------------------------------------------

    def score(self, entry, intent, by_id) -> tuple[dict, float]:
        """Temporal component scores and a bounded additive bonus.
        Trust and temporal fit REFINE relevant candidates; the caller
        must apply the bonus only when lexical relevance exists."""
        validity = resolve_validity(entry, by_id)
        temporal = temporal_of(entry)
        provenance = provenance_of(entry)
        components = {
            "temporal_mode_score": 0.0,
            "validity_score": 0.0,
            "as_of_score": 0.0,
            "source_date_score": 0.0,
            "temporal_confidence_score": (
                temporal.time_confidence if temporal else 0.0
            ),
            "trust_score": float(
                provenance.trust_level() if provenance else 0
            ),
        }
        if intent.mode == QueryMode.CURRENT:
            if entry.status == "active" and validity.valid_until is None:
                components["validity_score"] = 1.0
        elif intent.mode == QueryMode.AS_OF and intent.reference:
            if within_reference(validity, intent.reference):
                components["as_of_score"] = 1.0
        elif intent.mode in (QueryMode.HISTORICAL, QueryMode.TIMELINE):
            if entry.status == "superseded" or (
                validity.scope == TemporalScope.HISTORICAL
            ):
                components["temporal_mode_score"] = 1.0
        if temporal is not None and temporal.source_session_date:
            components["source_date_score"] = 0.5
        bonus = (
            0.4 * components["validity_score"]
            + 0.6 * components["as_of_score"]
            + 0.6 * components["temporal_mode_score"]
            + 0.05 * components["trust_score"]
        )
        return components, bonus

    # -- rendering labels -----------------------------------------------------------

    def annotate(self, entry, by_id) -> str:
        """Concise bounded label for rendered context."""
        parts = []
        provenance = provenance_of(entry)
        validity = resolve_validity(entry, by_id)
        if provenance is not None:
            label = provenance.source_type.replace("_", " ")
            parts.append(label)
            if provenance.provisional:
                parts.append("provisional")
        if entry.status == "superseded":
            interval = ""
            if validity.valid_from or validity.valid_until:
                interval = (
                    f" {validity.valid_from or '?'}–"
                    f"{validity.valid_until or '?'}"
                )
            parts.append(f"historical{interval}, superseded")
        elif validity.scope == TemporalScope.HISTORICAL:
            parts.append("historical")
        elif validity.scope == TemporalScope.FUTURE:
            parts.append(f"future, from {validity.valid_from or 'unknown'}")
        elif validity.scope == TemporalScope.RECURRING:
            parts.append("recurring")
        elif validity.valid_from:
            parts.append(f"current since {validity.valid_from}")
        elif provenance is not None or temporal_of(entry) is not None:
            parts.append("current")
        temporal = temporal_of(entry)
        if temporal is not None and temporal.time_precision in (
            TimePrecision.APPROXIMATE, TimePrecision.RELATIVE
        ):
            parts.append("approximate time")
        return f" [{', '.join(parts)}]" if parts else ""
