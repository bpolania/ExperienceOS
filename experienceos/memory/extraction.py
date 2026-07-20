"""Hybrid conversational memory extraction: gate, candidates, validation.

This module owns the extraction side of the hybrid pipeline:

- ``DurabilityGate``: a deterministic, provider-independent decision on
  whether an unmatched user sentence MAY contain durable experience.
- ``ExtractionRequest`` / ``MemoryCandidate`` / ``ExtractionResult``:
  the provider-independent structured extraction contract. Extractors
  return proposals only; they never touch lifecycle state.
- ``DeterministicConversationalExtractor``: reproducible offline
  extraction for conversational forms the explicit v1 rules miss
  (possessive relationship facts, affiliation verbs, additive facts,
  conversational preferences, recurring schedules, durable
  instructions, current-state corrections).
- ``CandidateValidator``: ExperienceOS-owned schema, grounding, and
  durability validation between extraction and lifecycle planning.

Everything here is deterministic and generic. No benchmark oracle data
(scenario IDs, fixture names, expected answers, answer sessions) is
referenced anywhere in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from experienceos.memory.schema import MemoryKind

EXTRACTION_SCHEMA_VERSION = "1"
DURABILITY_GATE_VERSION = "1"
GROUNDING_VALIDATOR_VERSION = "1"

DEFAULT_MAX_CANDIDATES_PER_TURN = 3
MAX_STATEMENT_LENGTH = 240
MAX_EVIDENCE_LENGTH = 240

VALID_CANDIDATE_KINDS = frozenset(
    {MemoryKind.PREFERENCE, MemoryKind.FACT, MemoryKind.INSTRUCTION}
)

# Relations a third-person pronoun may resolve to, when a bounded
# recent turn (or the same turn) mentions exactly one of them.
_RELATION_WORDS = frozenset(
    {
        "daughter", "son", "wife", "husband", "partner", "manager",
        "boss", "mom", "mother", "dad", "father", "sister", "brother",
        "roommate", "team",
    }
)
_RELATION_MENTION = re.compile(r"\bmy\s+([a-z]+(?:\s[a-z]+)?)\b", re.IGNORECASE)


def _cap(text: str) -> str:
    text = text.strip()
    return text[0].upper() + text[1:] if text else text


_TRAILING_TEMPORAL = re.compile(
    r"[\s,]+(?:now|today|these days|recently|again"
    r"|last\s+(?:year|month|week|spring|summer|fall|autumn|winter)"
    r"|a\s+(?:while|year|month)\s+(?:ago|back)"
    r"|in\s+(?:19|20)\d{2})\s*$",
    re.IGNORECASE,
)
_LEADING_ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


def _clean_value(value: str) -> str:
    value = value.strip().rstrip(".!?,;")
    previous = None
    while previous != value:
        previous = value
        value = _TRAILING_TEMPORAL.sub("", value).rstrip(".!?,;")
    return value.strip()


_WORD = re.compile(r"[a-z0-9#']+")
_GROUND_STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "on", "in", "at", "of", "to", "for"}
)


def _ground_words(text: str) -> set[str]:
    """Normalized content words for grounding comparisons."""
    words = set()
    for word in _WORD.findall(text.lower()):
        word = word.replace("'", "")
        if word in _GROUND_STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        words.add(word)
    return words


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


# --------------------------------------------------------------------------
# Durability gate
# --------------------------------------------------------------------------

# Overriding negatives: any hit rejects the sentence outright.
_OVERRIDING_NEGATIVE_CUES = (
    ("question", re.compile(r"\?\s*$")),
    (
        "greeting",
        re.compile(
            r"^(?:hi|hello|hey|thanks|thank you|good\s+(?:morning|afternoon"
            r"|evening)|bye|goodbye)\b[\w\s,]{0,20}[.!]?\s*$",
            re.IGNORECASE,
        ),
    ),
    (
        "acknowledgement",
        re.compile(
            r"^(?:ok(?:ay)?|sure|sounds good|got it|great|cool|perfect"
            r"|yes|no|nope|yep)\b[\s.!]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "current_turn_only",
        re.compile(
            r"\b(?:for th(?:is|at)\s+(?:answer|response|reply|turn|question"
            r"|message)\s+only|just th(?:is|e) once|only this time"
            r"|this time only|just for (?:now|this))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hypothetical",
        re.compile(
            r"\b(?:maybe|someday|perhaps|suppose|supposing|imagine"
            r"|hypothetically|what if|if i\s+(?:owned|had|were|was|moved"
            r"|worked|lived)|i might|i may end up|let'?s say|pretend"
            r"|i(?:'ll| will) probably|thinking about maybe)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "quoted_third_party",
        re.compile(
            r"\b(?:said|says|told me|wrote|texted|mentioned)\b[^\"']{0,30}"
            r"[\"“']",
        ),
    ),
    (
        "fictional",
        re.compile(
            r"\b(?:role-?play|in the story|in this story|fictional"
            r"|as a character|for the novel)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "brainstorm",
        re.compile(
            r"\b(?:one option would be|another option|we could either"
            r"|alternatively)\b",
            re.IGNORECASE,
        ),
    ),
)

# Transient one-off requests reject UNLESS a standing-scope or explicit
# remember cue is also present ("Remember to ..." vs "Book me a ...").
_TRANSIENT_REQUEST = re.compile(
    r"^(?:please\s+)?(?:book|find|search|look up|check|fetch|get me"
    r"|tell me|show me|what|when|where|who|which|how|can you|could you"
    r"|would you|help me|give me a hand)\b",
    re.IGNORECASE,
)
_TRANSIENT_OVERRIDE = re.compile(
    r"\b(?:remember|from now on|going forward|always|whenever"
    r"|every time)\b",
    re.IGNORECASE,
)

_POSITIVE_CUES = (
    ("explicit_remember", re.compile(r"\bremember\b", re.IGNORECASE)),
    (
        "standing_scope",
        re.compile(
            r"\b(?:from now on|going forward|always|whenever|every time"
            r"|for future\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "recurring_cue",
        re.compile(
            r"\b(?:every|usually|typically|generally|weekly|daily|monthly"
            r"|(?:mon|tues|wednes|thurs|fri|satur|sun)days?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "state_change",
        re.compile(
            r"\b(?:moved to|changed to|is now|are now|switched to)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "stable_state_verb",
        re.compile(
            r"\b(?:i|we)\s+(?:just\s+|recently\s+|now\s+"
            r"|(?:changed|switched)\s+jobs\s+and\s+(?:now\s+)?)?"
            r"(?:work for|work at|joined|live in|moved(?:\s+to)?|use|speak"
            r"|drink|study|prefer|go with|choose|drive|own)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "third_person_state",
        re.compile(
            r"\b(?:she|he|they|my\s+[a-z]+(?:\s[a-z]+)?)\s+(?:now\s+)?"
            r"(?:goes? to|works?|lives?|uses?|speaks?|attends?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "possessive_fact",
        re.compile(r"\b(?:my|our)\s+[a-z]+(?:\s[a-z]+)?'s\s+[a-z]", re.IGNORECASE),
    ),
    (
        "household_fact",
        re.compile(
            r"\b(?:my|our)\s+[a-z][a-z ]{0,40}\s+(?:is|are|uses|has)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "routing_rule",
        re.compile(r"\bsend\b[^.!?\n;]{0,80}\bto\b\s*(?:the\s+)?#?\w", re.IGNORECASE),
    ),
    (
        "preference_phrasing",
        re.compile(
            r"\bworks? better for me\b|\bwhat i drink\b|\bi tend to\b"
            r"|\bi opt for\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class GateDecision:
    """Deterministic durability screening for one unmatched sentence."""

    passed: bool
    confidence: float
    matched_cues: tuple = ()
    reason: str = ""
    version: str = DURABILITY_GATE_VERSION


class DurabilityGate:
    """Decides whether an unmatched sentence MAY hold durable experience.

    The gate never creates memory. Unclear durability rejects: the
    conversation is preserved, no auxiliary extraction runs, and the
    rejection stays visible in diagnostics.
    """

    version = DURABILITY_GATE_VERSION

    def assess(self, sentence: str) -> GateDecision:
        text = sentence.strip()
        if not text:
            return GateDecision(False, 1.0, (), "empty")

        for cue, pattern in _OVERRIDING_NEGATIVE_CUES:
            if pattern.search(text):
                return GateDecision(False, 1.0, (cue,), cue)

        if _TRANSIENT_REQUEST.search(text) and not _TRANSIENT_OVERRIDE.search(
            text
        ):
            return GateDecision(
                False, 1.0, ("transient_request",), "transient_request"
            )

        matched = tuple(
            cue for cue, pattern in _POSITIVE_CUES if pattern.search(text)
        )
        if not matched:
            return GateDecision(False, 1.0, (), "no_durable_cues")
        confidence = min(1.0, 0.7 + 0.1 * len(matched))
        return GateDecision(True, confidence, matched, "durable_cues")


# --------------------------------------------------------------------------
# Extraction contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionRequest:
    """Bounded input for one extraction attempt over one source turn.

    Never contains benchmark expected answers, answer-session IDs,
    evaluation labels, unbounded history, or inactive memories.
    """

    source_text: str
    source_ref: str
    source_role: str = "user"
    session_id: str = ""
    recent_context: tuple = ()  # bounded prior user turns, newest last
    deterministic_status: str = "rules_unmatched"
    max_candidates: int = DEFAULT_MAX_CANDIDATES_PER_TURN
    schema_version: str = EXTRACTION_SCHEMA_VERSION


@dataclass(frozen=True)
class MemoryCandidate:
    """One proposed durable memory. A proposal is not a stored memory."""

    kind: str
    statement: str
    evidence: str
    subject: str = "user"
    attribute: str = ""
    value: str = ""
    display_value: str = ""
    scope: str = "global"
    qualifiers: dict = field(default_factory=dict)
    confidence: float = 1.0
    durability_confidence: float = 1.0
    source_type: str = "user_turn"
    extraction_method: str = "deterministic_conversational"
    schema_version: str = EXTRACTION_SCHEMA_VERSION


@dataclass(frozen=True)
class ExtractionResult:
    """Extractor output: proposals plus bounded diagnostics only."""

    candidates: tuple = ()
    valid: bool = True
    status: str = "proposed"  # proposed|no_candidates|failed_safe|invalid_output
    reason: str = ""
    raw_output: str | None = None  # bounded diagnostic storage only
    parse_ok: bool = True
    elapsed_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    fallback: bool = False
    extractor_id: str = "deterministic_conversational"
    extractor_version: str = EXTRACTION_SCHEMA_VERSION


class MemoryCandidateExtractor(Protocol):
    """Provider-independent structured candidate proposal seam."""

    extractor_id: str
    extractor_version: str

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        ...


# --------------------------------------------------------------------------
# Deterministic conversational extractor
# --------------------------------------------------------------------------

_POSSESSIVE_FACT = re.compile(
    r"\b(?:my|our)\s+(?P<owner>[a-z]+(?:\s[a-z]+)?)'s\s+"
    r"(?P<attr>[a-z][a-z ]{0,40}?)\s+"
    r"(?:(?:is|are)\s+(?:now\s+)?|moved\s+to\s+|changed\s+to\s+)"
    r"(?P<value>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_OUR_FACT = re.compile(
    r"\bour\s+(?P<attr>[a-z][a-z ]{0,40}?)\s+is\s+(?:now\s+)?"
    r"(?P<value>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_EMPLOYER = re.compile(
    r"\b(?:i|we)\s+(?:just\s+|recently\s+|now\s+"
    r"|(?:changed|switched)\s+jobs\s+and\s+(?:now\s+)?)?"
    r"(?:work\s+for|joined)\s+(?P<org>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_ATTENDS = re.compile(
    r"\b(?P<who>i|we|she|he|they|my\s+[a-z]+(?:\s[a-z]+)?)\s+"
    r"(?:now\s+)?goes?\s+to\s+(?:the\s+)?(?P<place>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_RESIDENCE_MOVED = re.compile(
    r"\b(?:i|we)\s+(?:just\s+|recently\s+)?moved\s+to\s+"
    r"(?P<city>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_RESIDENCE_WE_LIVE = re.compile(
    r"\bwe\s+(?:now\s+)?live\s+(?:in|near)\s+(?P<city>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_SPEAKS = re.compile(
    r"\b(?:i|we)\s+(?:also\s+)?speak\s+(?P<langs>[^.!?\n;]+)",
    re.IGNORECASE,
)
_GROUP_USES = re.compile(
    r"\bmy\s+(?P<owner>[a-z]+)\s+uses\s+(?P<items>[^.!?\n;]+)",
    re.IGNORECASE,
)
# Capitalized product names only ("a Pixel 9"), so ordinary lowercase
# objects ("a spreadsheet") never become durable device facts.
_USES_DEVICE = re.compile(
    r"\b[Ii]\s+(?:now\s+)?use\s+(?:a|an)\s+"
    r"(?P<item>[A-Z][A-Za-z0-9-]*(?:\s+(?:[A-Z][\w-]*|\d[\w-]*)){0,2})",
)
_LEADING_SCOPE_PREF = re.compile(
    r"^for\s+(?P<scope>[^,]{3,50}),\s*i\s+"
    r"(?:usually\s+|tend\s+to\s+|generally\s+|typically\s+)?"
    r"(?:go\s+with|choose|pick|opt\s+for|prefer|use)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?P<value>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_MID_SCOPE_PREF = re.compile(
    r"\bi\s+(?:usually\s+|tend\s+to\s+|generally\s+|typically\s+)"
    r"(?:go\s+with|choose|pick|opt\s+for)\s+"
    r"(?:a\s+|an\s+|the\s+)?(?P<value>[^.!?\n;,]+?)"
    r"(?:\s+(?:for|on)\s+(?P<scope>[^.!?\n;,]+))?\s*$",
    re.IGNORECASE,
)
_WORKS_BETTER_PREF = re.compile(
    r"\b(?P<value>[\w -]{2,40}?)\s+works?\s+better\s+for\s+me"
    r"(?:\s+(?:on|for)\s+(?P<scope>[^.!?\n;,]+))?",
    re.IGNORECASE,
)
_DRINK_PREF = re.compile(
    r"\b(?P<value>[a-z][\w ]{1,30}?)\s+is\s+(?:usually\s+|typically\s+)?"
    r"what\s+i\s+drink\s+in\s+the\s+(?P<time>morning|afternoon|evening)",
    re.IGNORECASE,
)
_STUDY_PREF = re.compile(
    r"\bi\s+(?:usually\s+|generally\s+|typically\s+)?study\s+"
    r"(?P<when>(?:after|before)\s+[\w ]+|in\s+the\s+"
    r"(?:morning|afternoon|evening)|at\s+night)",
    re.IGNORECASE,
)
_SCHEDULE_MOVED = re.compile(
    r"\b(?P<what>[a-z][\w' ]{2,50}?)\s+"
    r"(?:moved\s+to|is\s+now\s+on|changed\s+to)\s+"
    r"(?P<when>(?:mon|tues|wednes|thurs|fri|satur|sun)days?"
    r"(?:\s+at\s+[\w:]+)?)",
    re.IGNORECASE,
)
_WHENEVER_INSTRUCTION = re.compile(
    r"\b(?P<action>(?:use|include|add|show|give|keep|answer|respond|reply)"
    r"\b[^.!?\n;,]*?)\s+whenever\s+(?P<clause>[^.!?\n;]+)",
    re.IGNORECASE,
)

_PRONOUNS = frozenset({"i", "we", "she", "he", "they"})

_WEEKDAY_VALUE = re.compile(
    r"^(?:mon|tues|wednes|thurs|fri|satur|sun)days?"
    r"(?:\s+at\s+[\w:]+)?$",
    re.IGNORECASE,
)


class DeterministicConversationalExtractor:
    """Reproducible offline extraction of conversational durable forms.

    Composable generic phrase patterns only: no scenario IDs, fixture
    names, expected answers, or per-case mappings. One source sentence
    may yield several independent candidates; the caller bounds the
    total per turn.
    """

    extractor_id = "deterministic_conversational"
    extractor_version = "1"

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        text = request.source_text.strip()
        candidates: list[MemoryCandidate] = []
        seen_statements: set[str] = set()

        for candidate in self._propose(text, request):
            if len(candidate.statement) > MAX_STATEMENT_LENGTH:
                continue
            key = _squash(candidate.statement)
            if key in seen_statements:
                continue
            seen_statements.add(key)
            candidates.append(candidate)
            if len(candidates) >= request.max_candidates:
                break

        if not candidates:
            return ExtractionResult(
                candidates=(),
                status="no_candidates",
                reason="no conversational pattern matched",
                extractor_id=self.extractor_id,
                extractor_version=self.extractor_version,
            )
        return ExtractionResult(
            candidates=tuple(candidates),
            status="proposed",
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
        )

    # -- pattern application -------------------------------------------------

    def _propose(self, text, request):
        yield from self._possessive_facts(text)
        yield from self._our_facts(text)
        yield from self._employer(text)
        yield from self._attends(text, request)
        yield from self._residence(text)
        yield from self._languages(text)
        yield from self._group_uses(text)
        yield from self._device(text)
        yield from self._preferences(text)
        yield from self._schedules(text)
        yield from self._instructions(text)

    def _candidate(self, match, **fields) -> MemoryCandidate:
        evidence = match.group(0).strip()[:MAX_EVIDENCE_LENGTH]
        defaults = {
            "confidence": 0.9,
            "durability_confidence": 0.9,
            "extraction_method": self.extractor_id,
        }
        defaults.update(fields)
        return MemoryCandidate(evidence=evidence, **defaults)

    def _possessive_facts(self, text):
        for match in _POSSESSIVE_FACT.finditer(text):
            owner = match.group("owner").lower().strip()
            attr = match.group("attr").lower().strip()
            value = _clean_value(match.group("value"))
            if not value or value.lower().startswith("that "):
                continue
            if _WEEKDAY_VALUE.match(value):
                value = f"on {value}"
            statement = f"{_cap(owner)}'s {attr} is {value}."
            yield self._candidate(
                match,
                kind=MemoryKind.FACT,
                statement=statement,
                subject=owner,
                attribute="_".join(f"{owner}s {attr}".split()),
                value=value.lower(),
                display_value=value,
            )

    def _our_facts(self, text):
        for match in _OUR_FACT.finditer(text):
            attr = match.group("attr").lower().strip()
            value = _clean_value(match.group("value"))
            if not value or len(attr.split()) > 4:
                continue
            statement = f"{_cap(attr)} is {value}."
            yield self._candidate(
                match,
                kind=MemoryKind.FACT,
                statement=statement,
                attribute="_".join(attr.split()),
                value=value.lower(),
                display_value=value,
            )

    def _employer(self, text):
        for match in _EMPLOYER.finditer(text):
            org = _clean_value(match.group("org"))
            if not org:
                continue
            yield self._candidate(
                match,
                kind=MemoryKind.FACT,
                statement=f"Works for {org}.",
                attribute="employer",
                value=org.lower(),
                display_value=org,
            )

    def _attends(self, text, request):
        for match in _ATTENDS.finditer(text):
            who = match.group("who").lower().strip()
            place = _clean_value(match.group("place"))
            if not place:
                continue
            qualifiers: dict = {}
            if who in ("i", "we"):
                subject, prefix = "user", ""
            elif who in _PRONOUNS:
                antecedent = _resolve_pronoun(
                    who, text[: match.start()], request.recent_context
                )
                if antecedent is None:
                    continue  # ambiguous reference: no candidate
                subject, prefix = antecedent, f"{_cap(antecedent)} "
                qualifiers["coreference"] = {
                    "pronoun": who,
                    "antecedent": antecedent,
                }
            else:  # "my daughter", "my son"
                subject = who.split(None, 1)[1]
                prefix = f"{_cap(subject)} "
            statement = (
                f"{prefix}goes to {place}."
                if prefix
                else f"Goes to {place}."
            )
            yield self._candidate(
                match,
                kind=MemoryKind.FACT,
                statement=statement,
                subject=subject,
                attribute="attends",
                value=place.lower(),
                display_value=place,
                qualifiers=qualifiers,
            )

    def _residence(self, text):
        for pattern in (_RESIDENCE_MOVED, _RESIDENCE_WE_LIVE):
            for match in pattern.finditer(text):
                city = _clean_value(match.group("city"))
                if not city or city.lower().startswith(("a ", "an ")):
                    continue
                yield self._candidate(
                    match,
                    kind=MemoryKind.FACT,
                    statement=f"Lives in {city}.",
                    attribute="residence",
                    value=city.lower(),
                    display_value=city,
                )

    def _languages(self, text):
        for match in _SPEAKS.finditer(text):
            for language in _split_additive(match.group("langs")):
                yield self._candidate(
                    match,
                    kind=MemoryKind.FACT,
                    statement=f"Speaks {language}.",
                    attribute="speaks_language",
                    value=language.lower(),
                    display_value=language,
                )

    def _group_uses(self, text):
        for match in _GROUP_USES.finditer(text):
            owner = match.group("owner").lower()
            for item in _split_additive(match.group("items")):
                yield self._candidate(
                    match,
                    kind=MemoryKind.FACT,
                    statement=f"{_cap(owner)} uses {item}.",
                    subject=owner,
                    attribute=f"{owner}_uses",
                    value=item.lower(),
                    display_value=item,
                )

    def _device(self, text):
        for match in _USES_DEVICE.finditer(text):
            item = _clean_value(match.group("item"))
            item = _LEADING_ARTICLE.sub("", item)
            if not item:
                continue
            yield self._candidate(
                match,
                kind=MemoryKind.FACT,
                statement=f"Uses a {item}.",
                attribute="uses",
                value=item.lower(),
                display_value=item,
            )

    def _preferences(self, text):
        for match in _LEADING_SCOPE_PREF.finditer(text):
            value = _clean_value(match.group("value"))
            scope = _clean_value(match.group("scope"))
            if value and scope:
                yield self._preference(match, value, scope)
        for match in _MID_SCOPE_PREF.finditer(text):
            value = _clean_value(match.group("value"))
            scope = _clean_value(match.group("scope") or "")
            if value:
                yield self._preference(match, value, scope or None)
        for match in _WORKS_BETTER_PREF.finditer(text):
            value = _clean_value(match.group("value"))
            scope = _clean_value(match.group("scope") or "")
            if value:
                yield self._preference(match, value, scope or None)
        for match in _DRINK_PREF.finditer(text):
            value = _clean_value(match.group("value"))
            time = match.group("time").lower()
            if value:
                yield self._candidate(
                    match,
                    kind=MemoryKind.PREFERENCE,
                    statement=f"Prefers {value.lower()} in the {time}.",
                    attribute="preferred_drink",
                    value=value.lower(),
                    display_value=value,
                    scope=time,
                )
        for match in _STUDY_PREF.finditer(text):
            when = _clean_value(match.group("when"))
            if when:
                yield self._candidate(
                    match,
                    kind=MemoryKind.PREFERENCE,
                    statement=f"Prefers studying {when.lower()}.",
                    attribute="study_time",
                    value=when.lower(),
                    display_value=when,
                )

    def _preference(self, match, value, scope):
        statement = (
            f"Prefers {value.lower()} for {scope.lower()}."
            if scope
            else f"Prefers {value.lower()}."
        )
        return self._candidate(
            match,
            kind=MemoryKind.PREFERENCE,
            statement=statement,
            attribute="preference",
            value=value.lower(),
            display_value=value,
            scope="_".join(scope.lower().split()) if scope else "global",
        )

    def _schedules(self, text):
        for match in _SCHEDULE_MOVED.finditer(text):
            what = match.group("what").strip()
            when = match.group("when").strip()
            low = what.lower()
            # Possessive subjects belong to the possessive-fact class;
            # emitting both would duplicate the same statement.
            if (
                low.split()[0] in _PRONOUNS
                or "'s" in low
                or low.startswith(("my ", "our "))
            ):
                continue
            yield self._candidate(
                match,
                kind=MemoryKind.FACT,
                statement=f"{_cap(what)} is on {_cap(when)}.",
                attribute="_".join(what.lower().split()),
                value=when.lower(),
                display_value=when,
            )

    def _instructions(self, text):
        for match in _WHENEVER_INSTRUCTION.finditer(text):
            action = _clean_value(match.group("action"))
            clause = _clean_value(match.group("clause"))
            if not action or not clause:
                continue
            yield self._candidate(
                match,
                kind=MemoryKind.INSTRUCTION,
                statement=f"{_cap(action)} when {clause}.",
                attribute="",
                value=action.lower(),
                display_value=action,
            )


def _split_additive(phrase: str) -> list[str]:
    """Split "Spanish and Portuguese" / "Python, Go and Rust" safely."""
    items = []
    for item in re.split(r",\s*|\s+and\s+", phrase.strip()):
        item = _clean_value(item)
        if item and len(item.split()) <= 4:
            items.append(item)
    return items


def _resolve_pronoun(
    pronoun: str, preceding_text: str, recent_context: tuple
) -> str | None:
    """Bounded, unambiguous pronoun resolution or None.

    Scans the current turn's preceding text plus the bounded recent
    user turns for "my <relation>" mentions from a small registry. The
    pronoun resolves only when exactly one distinct relation appears —
    anything else is ambiguous and yields no candidate.
    """
    relations: set[str] = set()
    for source in (preceding_text, *reversed(tuple(recent_context))):
        for match in _RELATION_MENTION.finditer(source or ""):
            relation = match.group(1).lower().split()[-1]
            if relation in _RELATION_WORDS:
                relations.add(relation)
    if len(relations) == 1:
        return next(iter(relations))
    return None


# --------------------------------------------------------------------------
# Candidate validation (ExperienceOS-owned)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationOutcome:
    accepted: bool
    stage: str  # schema|grounding|durability|accepted
    reason: str
    validator_version: str = GROUNDING_VALIDATOR_VERSION


_NEGATION = re.compile(
    r"\b(?:don'?t|do not|never|no longer|not|stopped|quit)\b", re.IGNORECASE
)
_NEGATIVE_STATEMENT = re.compile(
    r"\b(?:dislikes|no longer|not|avoids|never)\b", re.IGNORECASE
)
_QUOTED_SPAN = re.compile(r"[\"“'].{3,}?[\"”']")


class CandidateValidator:
    """Schema, grounding, and durability validation for one candidate.

    Deterministic checks only — no model validates another model's
    output here. The validator accepts or rejects proposals; duplicate
    and conflict decisions remain lifecycle-owned (planner, manager,
    engine).
    """

    version = GROUNDING_VALIDATOR_VERSION

    def validate(
        self,
        candidate: MemoryCandidate,
        request: ExtractionRequest,
        gate: GateDecision,
    ) -> ValidationOutcome:
        schema_problem = self._schema_problem(candidate, request)
        if schema_problem:
            return ValidationOutcome(False, "schema", schema_problem)
        grounding_problem = self._grounding_problem(candidate, request)
        if grounding_problem:
            return ValidationOutcome(False, "grounding", grounding_problem)
        durability_problem = self._durability_problem(candidate, gate)
        if durability_problem:
            return ValidationOutcome(False, "durability", durability_problem)
        return ValidationOutcome(True, "accepted", "validated")

    # -- schema ----------------------------------------------------------------

    @staticmethod
    def _schema_problem(candidate, request) -> str | None:
        if candidate.kind not in VALID_CANDIDATE_KINDS:
            return f"unsupported kind: {candidate.kind!r}"
        if not (candidate.statement or "").strip():
            return "empty statement"
        if len(candidate.statement) > MAX_STATEMENT_LENGTH:
            return "statement exceeds bounded length"
        if request.source_role != "user":
            return f"unsupported source role: {request.source_role!r}"
        for name in ("confidence", "durability_confidence"):
            confidence = getattr(candidate, name)
            if isinstance(confidence, bool) or not isinstance(
                confidence, (int, float)
            ):
                return f"{name} must be numeric"
            if not 0.0 <= confidence <= 1.0:
                return f"{name} out of bounds: {confidence!r}"
        if not (candidate.evidence or "").strip():
            return "missing source evidence"
        if not isinstance(candidate.qualifiers, dict):
            return "qualifiers must be a mapping"
        return None

    # -- grounding ---------------------------------------------------------------

    def _grounding_problem(self, candidate, request) -> str | None:
        source = request.source_text
        evidence = candidate.evidence.strip()
        if _squash(evidence) not in _squash(source):
            return "evidence is not a span of the source turn"
        evidence_words = _ground_words(evidence)
        if candidate.value:
            missing = _ground_words(candidate.value) - evidence_words
            if missing:
                return f"value not grounded in evidence: {sorted(missing)}"
        if candidate.scope and candidate.scope not in ("global",):
            scope_words = _ground_words(candidate.scope.replace("_", " "))
            if scope_words - evidence_words:
                return "scope qualifier not grounded in evidence"
        if not self._subject_supported(candidate, request, evidence_words):
            return f"subject not supported: {candidate.subject!r}"
        if self._inside_quotes(source, evidence):
            return "evidence is quoted third-party speech"
        if _NEGATION.search(evidence) and not _NEGATIVE_STATEMENT.search(
            candidate.statement
        ):
            return "negated source cannot ground a positive statement"
        return None

    @staticmethod
    def _subject_supported(candidate, request, evidence_words) -> bool:
        subject = (candidate.subject or "user").lower()
        if subject == "user":
            return True
        subject_words = _ground_words(subject.replace("_", " "))
        if subject_words <= evidence_words:
            return True
        coreference = candidate.qualifiers.get("coreference")
        if isinstance(coreference, dict):
            antecedent = str(coreference.get("antecedent", "")).lower()
            if antecedent and antecedent == subject:
                bounded = " ".join(
                    (request.source_text, *request.recent_context)
                ).lower()
                return f"my {antecedent}" in bounded
        return False

    @staticmethod
    def _inside_quotes(source: str, evidence: str) -> bool:
        needle = _squash(evidence)
        for span in _QUOTED_SPAN.finditer(source):
            if needle in _squash(span.group(0)):
                return True
        return False

    # -- durability ------------------------------------------------------------

    @staticmethod
    def _durability_problem(candidate, gate) -> str | None:
        if not gate.passed:
            return f"durability gate rejected: {gate.reason}"
        if candidate.durability_confidence < 0.5:
            return "durability confidence below threshold"
        return None
