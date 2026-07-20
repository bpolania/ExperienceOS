"""Forget-intent detection and conservative target resolution.

Forget intent and forget target resolution are
SEPARATE components:

- ``ForgetIntentDetector``: deterministic detection of durable forget
  requests, with guards for negation ("don't forget"), questions,
  hypotheticals, quoted speech, current-turn-only instructions, and
  bulk requests ("forget everything" → structured unsupported result,
  never fuzzy mass deletion).
- ``describe_target``: a structured description of what the user wants
  forgotten (tokens, entities, attribute hints via the transparent
  alias registry, kind hints, historical qualifiers).
- ``ForgetTargetResolver``: deterministic scoring of ACTIVE candidates
  only (forgotten/superseded records are never targets), with explicit
  versioned weights, confidence and margin thresholds, and outcomes
  that reject ambiguity instead of guessing.

The resolver proposes; ExperienceManager validation and the
ExperienceEngine forget transition stay authoritative. Nothing here
mutates storage.

No benchmark oracle data is referenced anywhere in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from experienceos.context.retrieval import (
    ALIAS_CANONICAL,
    ALIAS_CLASSES,
    entities as extract_entities,
    tokenize,
    tokens_match,
)
from experienceos.memory.planner import _content_words
from experienceos.memory.semantic import METADATA_KEY

FORGET_RESOLVER_VERSION = "1"

# Explicit, versioned, scenario-agnostic weights (fixture-tuned only).
FORGET_WEIGHTS = {
    "exact_text": 5.0,
    "attribute": 2.0,
    "value": 1.5,
    "scope": 1.0,
    "entity": 2.0,
    "kind": 0.5,
    "lexical": 0.6,  # per matched content token (prefix-aware)
    "full_coverage": 1.5,  # every description content token matched
}
MIN_SCORE = 1.0
MIN_MARGIN = 0.5
MAX_TARGETS = 3

# --- Intent detection -------------------------------------------------------

_NEGATED = re.compile(
    r"\b(?:don'?t|do not|never|please don'?t)\s+forget\b", re.IGNORECASE
)
_QUESTION = re.compile(
    r"^(?:did|do|does|would|will|can|could|what|have)\b.*\bforg[eo]t"
    r"|forg[eo]t\b[^.!]*\?\s*$",
    re.IGNORECASE,
)
_HYPOTHETICAL = re.compile(
    r"\bwhat would happen\b|\bif i asked\b|\bmaybe\b.*\bforget\b"
    r"|\bforget\b.*\b(?:later|someday)\b|\bsuppose\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(
    r"\b(?:said|says|told me|wrote)\b[^\"']{0,30}[\"'].*forget",
    re.IGNORECASE,
)
_CURRENT_TURN_ONLY = re.compile(
    r"\bfor th(?:is|at)\s+(?:answer|response|reply|question|message)\b"
    r"|\bjust th(?:is|e) once\b|\bignore\b.*\bfor now\b",
    re.IGNORECASE,
)
_BULK = re.compile(
    r"\b(?:forget|erase|delete|remove|clear|wipe)\s+"
    r"(?:everything|it all|all\s+(?:my\s+)?"
    r"(?:memories|preferences|facts|instructions|experience)"
    r"|all of it)\b",
    re.IGNORECASE,
)
_POSITIVE_PATTERNS = (
    re.compile(
        r"\b(?:forget|erase|remove|delete)\s+"
        r"(?:that\s+|the\s+(?:memory|fact|instruction|preference|rule|"
        r"detail)\s+(?:that\s+|about\s+|of\s+|for\s+)?"
        r"|what\s+i\s+said\s+about\s+|my\s+)?"
        r"(?P<target>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bstop\s+remembering\s+(?:that\s+|my\s+)?(?P<target>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:don'?t|do not)\s+remember\s+(?:my\s+)?"
        r"(?P<target>[^.!?\n;]+?)\s+any\s?more\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bno\s+longer\s+(?:keep|need|remember)\s+"
        r"(?:the\s+|my\s+)?(?P<target>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi\s+(?:do\s+not|don'?t)\s+care\s+about\s+"
        r"(?:my\s+)?(?P<target>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi\s+no\s+longer\s+(?:want|need|prefer|like|care\s+about)\s+"
        r"(?:you\s+to\s+remember\s+)?(?:my\s+)?(?P<target>[^.!?\n;]+)",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class ForgetIntent:
    detected: bool
    confidence: float = 0.0
    target_text: str = ""
    span: tuple = (0, 0)
    current_turn_only: bool = False
    bulk: bool = False
    negated: bool = False
    ambiguity_reason: str | None = None
    version: str = FORGET_RESOLVER_VERSION


class ForgetIntentDetector:
    """Deterministic durable-forget intent. Never mutates state."""

    version = FORGET_RESOLVER_VERSION

    def detect(self, message: str) -> ForgetIntent:
        if _NEGATED.search(message):
            return ForgetIntent(
                False, negated=True, ambiguity_reason="negated forget"
            )
        if _QUESTION.search(message):
            return ForgetIntent(
                False, ambiguity_reason="question about forgetting"
            )
        if _HYPOTHETICAL.search(message):
            return ForgetIntent(
                False, ambiguity_reason="hypothetical forget"
            )
        if _QUOTED.search(message):
            return ForgetIntent(
                False, ambiguity_reason="quoted third-party forget"
            )
        if _CURRENT_TURN_ONLY.search(message):
            return ForgetIntent(
                False,
                current_turn_only=True,
                ambiguity_reason="current-turn-only instruction",
            )
        if _BULK.search(message):
            return ForgetIntent(
                True, confidence=1.0, bulk=True,
                ambiguity_reason="bulk request unsupported",
            )
        for pattern in _POSITIVE_PATTERNS:
            match = pattern.search(message)
            if match:
                target = match.group("target").strip().rstrip(".!?,")
                target = re.sub(
                    r"\s+(?:entirely|completely|now|please|any\s?more"
                    r"|any\s+longer)$",
                    "", target, flags=re.IGNORECASE,
                ).strip()
                if not target:
                    continue
                return ForgetIntent(
                    True, confidence=1.0, target_text=target,
                    span=match.span(),
                )
        return ForgetIntent(False)


# --- Target description --------------------------------------------------------

_KIND_HINTS = {
    "preference": "preference",
    "instruction": "instruction",
    "rule": "instruction",
    "fact": "fact",
}
_HISTORICAL_QUALIFIER = re.compile(
    r"\b(?:old|previous|former|earlier)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ForgetTargetDescription:
    raw: str
    tokens: frozenset
    entities: frozenset
    attribute_hints: frozenset  # alias-class canonical names
    kind_hint: str | None
    historical: bool
    version: str = FORGET_RESOLVER_VERSION


def describe_target(target_text: str) -> ForgetTargetDescription:
    # The planner's forget-topic stopwords strip lifecycle vocabulary
    # ("don't", "like", "preference", …) so only content words remain;
    # fall back to plain tokenization if nothing survives.
    tokens = _content_words(target_text) or tokenize(target_text)
    hints = frozenset(
        ALIAS_CANONICAL[klass]
        for klass in ALIAS_CLASSES
        if tokens & klass
    )
    kind_hint = next(
        (kind for word, kind in _KIND_HINTS.items()
         if word in target_text.lower()),
        None,
    )
    return ForgetTargetDescription(
        raw=target_text,
        tokens=frozenset(tokens),
        entities=frozenset(extract_entities(target_text)),
        attribute_hints=hints,
        kind_hint=kind_hint,
        historical=bool(_HISTORICAL_QUALIFIER.search(target_text)),
    )


# --- Target resolution -----------------------------------------------------------


class ForgetOutcome:
    RESOLVED = "resolved"
    NO_INTENT = "no_intent"
    NO_ACTIVE_CANDIDATES = "no_active_candidates"
    BELOW_THRESHOLD = "below_threshold"
    AMBIGUOUS = "ambiguous"
    BULK_UNSUPPORTED = "bulk_request_unsupported"
    INACTIVE_TARGET_ONLY = "inactive_target_only"
    NEGATED_OR_NON_DURABLE = "negated_or_non_durable"


@dataclass
class ForgetCandidateScore:
    entry: object
    score: float
    components: dict = field(default_factory=dict)


@dataclass
class ForgetResolutionResult:
    outcome: str
    targets: list = field(default_factory=list)  # resolved entries
    scores: list = field(default_factory=list)  # ForgetCandidateScore
    reason: str = ""
    version: str = FORGET_RESOLVER_VERSION


def _identity(entry) -> dict:
    stored = entry.metadata.get(METADATA_KEY)
    return stored if isinstance(stored, dict) else {}


class ForgetTargetResolver:
    """Deterministic active-only target resolution.

    Auto-resolves only when the top candidate clears MIN_SCORE and
    beats the runner-up by MIN_MARGIN with no incompatible ambiguity.
    Tie-breaking: score descending, recency descending, memory ID
    ascending — fully deterministic.
    """

    version = FORGET_RESOLVER_VERSION

    def __init__(self, weights: dict | None = None,
                 min_score: float = MIN_SCORE,
                 min_margin: float = MIN_MARGIN,
                 max_targets: int = MAX_TARGETS):
        self.weights = dict(weights or FORGET_WEIGHTS)
        self.min_score = min_score
        self.min_margin = min_margin
        self.max_targets = max_targets

    def resolve(
        self, intent: ForgetIntent, memories: list
    ) -> ForgetResolutionResult:
        if not intent.detected:
            reason = intent.ambiguity_reason or "no forget intent"
            outcome = (
                ForgetOutcome.NEGATED_OR_NON_DURABLE
                if intent.negated or intent.current_turn_only
                or intent.ambiguity_reason
                else ForgetOutcome.NO_INTENT
            )
            return ForgetResolutionResult(outcome=outcome, reason=reason)
        if intent.bulk:
            return ForgetResolutionResult(
                outcome=ForgetOutcome.BULK_UNSUPPORTED,
                reason="bulk forgetting requires explicit per-memory "
                       "requests; no mass action taken",
            )

        active = [m for m in memories if m.status == "active"]
        inactive = [m for m in memories if m.status != "active"]

        # Explicit multi-target requests ("X and Y") resolve each part
        # independently; plural wording alone never widens the action.
        parts = self._split_targets(intent.target_text)
        resolved: list = []
        all_scores: list = []
        for part in parts[: self.max_targets]:
            result = self._resolve_one(part, active, inactive, resolved)
            all_scores.extend(result.scores)
            if result.outcome != ForgetOutcome.RESOLVED:
                if len(parts) == 1:
                    return result
                continue  # explicit part that fails stays unresolved
            resolved.extend(result.targets)
        if not resolved:
            return ForgetResolutionResult(
                outcome=ForgetOutcome.BELOW_THRESHOLD,
                scores=all_scores,
                reason="no target part resolved above threshold",
            )
        return ForgetResolutionResult(
            outcome=ForgetOutcome.RESOLVED,
            targets=resolved,
            scores=all_scores,
            reason=f"{len(resolved)} target(s) resolved",
        )

    @staticmethod
    def _split_targets(target_text: str) -> list:
        parts = [
            p.strip()
            for p in re.split(r"\s+and\s+", target_text)
            if len(p.strip()) >= 3
        ]
        return parts or [target_text]

    def _resolve_one(self, part, active, inactive, already):
        description = describe_target(part)
        scored = sorted(
            (
                self._score(entry, description)
                for entry in active
                if entry not in already
            ),
            key=lambda c: (
                -c.score,
                -c.entry.created_at.timestamp(),
                c.entry.id,
            ),
        )
        positive = [c for c in scored if c.score > 0]
        if not positive:
            # Only inactive records would match: never a target.
            if any(
                self._score(entry, description).score >= self.min_score
                for entry in inactive
            ):
                return ForgetResolutionResult(
                    outcome=ForgetOutcome.INACTIVE_TARGET_ONLY,
                    reason="only inactive (superseded/forgotten) records "
                           "match; forget targets must be active",
                )
            return ForgetResolutionResult(
                outcome=ForgetOutcome.NO_ACTIVE_CANDIDATES,
                reason=f"no active memory matches {part!r}",
            )
        top = positive[0]
        if top.score < self.min_score:
            return ForgetResolutionResult(
                outcome=ForgetOutcome.BELOW_THRESHOLD,
                scores=positive[:3],
                reason=f"top score {top.score:.2f} below "
                       f"{self.min_score}",
            )
        if len(positive) > 1:
            second = positive[1]
            if top.score - second.score < self.min_margin:
                return ForgetResolutionResult(
                    outcome=ForgetOutcome.AMBIGUOUS,
                    scores=positive[:3],
                    reason="two candidates within the ambiguity margin; "
                           "rejecting rather than guessing",
                )
        return ForgetResolutionResult(
            outcome=ForgetOutcome.RESOLVED,
            targets=[top.entry],
            scores=positive[:3],
        )

    def _score(self, entry, description) -> ForgetCandidateScore:
        weights = self.weights
        entry_tokens = tokenize(entry.text)
        identity = _identity(entry)
        components: dict = {}

        exact = float(
            " ".join(sorted(description.tokens))
            == " ".join(sorted(entry_tokens))
        )
        components["exact_text_score"] = exact * weights["exact_text"]

        attribute = str(identity.get("attribute", ""))
        attribute_tokens = tokenize(attribute.replace("_", " "))
        attribute_hit = 0.0
        if attribute:
            canonical_hits = {
                hint
                for hint in description.attribute_hints
                if any(
                    tokens_match(hint, t) for t in attribute_tokens
                )
            }
            direct = any(
                tokens_match(d, a)
                for d in description.tokens
                for a in attribute_tokens
            )
            # Attribute matches via the alias registry ("drink
            # preference" → preferred_drink) or direct wording.
            if canonical_hits or direct:
                attribute_hit = 1.0
            # Alias-class hint matching the identity VALUE also links
            # ("morning drink" ↔ value "coffee" via the drink class).
            elif description.attribute_hints:
                value_tokens = tokenize(str(identity.get("value", "")))
                for klass in ALIAS_CLASSES:
                    if (
                        ALIAS_CANONICAL[klass] in description.attribute_hints
                        and value_tokens & klass
                    ):
                        attribute_hit = 1.0
                        break
        components["attribute_score"] = attribute_hit * weights["attribute"]

        value_tokens = tokenize(str(identity.get("value", "")))
        value_hit = float(
            bool(value_tokens)
            and any(
                tokens_match(d, v)
                for d in description.tokens
                for v in value_tokens
            )
        )
        components["value_score"] = value_hit * weights["value"]

        scope = str(identity.get("scope", "") or "")
        scope_tokens = (
            tokenize(scope.replace("_", " ")) if scope != "global" else set()
        )
        scope_hit = float(
            bool(scope_tokens)
            and any(
                tokens_match(d, s)
                for d in description.tokens
                for s in scope_tokens
            )
        )
        components["scope_score"] = scope_hit * weights["scope"]

        entity_hits = sum(
            1
            for e in description.entities
            if any(e in t or t in e for t in
                   extract_entities(entry.text) | entry_tokens)
        )
        components["entity_score"] = entity_hits * weights["entity"]

        kind_hit = float(
            description.kind_hint is not None
            and entry.kind == description.kind_hint
        )
        components["kind_score"] = kind_hit * weights["kind"]

        lexical_hits = sum(
            1
            for d in description.tokens
            if any(tokens_match(d, t) for t in entry_tokens)
        )
        components["lexical_score"] = lexical_hits * weights["lexical"]
        # Full coverage: every content token of the request matched
        # this memory — a strong, generic signal for short requests.
        components["full_coverage_score"] = (
            weights["full_coverage"]
            if description.tokens and lexical_hits == len(description.tokens)
            else 0.0
        )

        return ForgetCandidateScore(
            entry=entry,
            score=round(sum(components.values()), 6),
            components=components,
        )
