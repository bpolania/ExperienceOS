"""Deterministic grounded extraction controller.

A rule-based, provider-independent implementation of the
``ExtractionController`` protocol that answers one narrow question:
does the current interaction contain ONE durable, user-grounded
experience candidate? If yes, it proposes exactly one candidate with
an exact evidence span and a conservative normalization, validated
through ``GroundedCandidateValidator`` before anything leaves the
controller. If no, it returns none with a bounded abstention reason.

Authority: proposal-only. No store, manager, engine, provider, model,
network, or lifecycle access exists here; ``canonical_effect`` is
false in every diagnostic, and the canonical extraction path
(``HybridMemoryPlanner``) is untouched — this controller is directly
invokable only and is not wired into memory creation.

Design constraints inherited from the grounding validator: emitted
normalizations stay within the cited span's vocabulary (no synonym
rewriting), spans are exact slices of the unmodified source
(``source[start:end] == evidence``), and the smallest complete
supporting clause is preferred over whole-message evidence. Rules are
bounded English patterns for explicit and semi-natural durable
statements — deliberately conservative, not a general parser.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from experienceos.controllers.extraction import (
    ExtractionEvidence,
    ExtractionProposal,
    ProposedMemoryCandidate,
)
from experienceos.controllers.base import EvidenceSpan
from experienceos.memory.grounding import (
    ApprovedSource,
    GroundedCandidateValidator,
)

GROUNDED_EXTRACTION_CONTROLLER_ID = "grounded_rules-1"
GROUNDED_EXTRACTION_VERSION = "1"

ABSTENTION_REASONS = (
    "no_rule_match",
    "question",
    "hypothetical",
    "invalid_grounding",
    "empty_source",
    "invalid_provenance",
)

# Sentence-level pre-screens: no rule fires inside interrogative or
# hypothetical sentences, regardless of what else the sentence says.
_SENTENCE_QUESTION = re.compile(
    r"\?\s*$"
    r"|^(?:should|could|would|can|do|does|did|am|is|are|will|shall)\s+"
    r"(?:i|we|you|it|there)\b"
    r"|\bi wonder\b|\bwondering (?:if|whether)\b",
    re.IGNORECASE,
)
_SENTENCE_HYPOTHETICAL = re.compile(
    r"\b(?:if (?:i|we)\b|i might|we might|i would|we would|suppose"
    r"|supposing|imagine|hypothetically|what if|were (?:i|we) to)\b",
    re.IGNORECASE,
)
_SENTENCE_TEMPORAL = re.compile(
    r"\b(?:today|tonight|tomorrow|right now|for now|just this once"
    r"|this (?:week|weekend|month|year|time|trip|session|morning"
    r"|afternoon|evening)|until (?:mon|tues|wednes|thurs|fri|satur"
    r"|sun)[a-z]*)\b",
    re.IGNORECASE,
)
_TRAILING_FILLER = re.compile(
    r"\s+(?:anyway|though|actually|honestly|after all)$",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"[^.!?]*[.!?]?")


def _conjugate(verb: str) -> str:
    """First-person verb -> third-person singular, bounded rules."""
    lowered = verb.lower()
    if lowered.endswith("y") and len(lowered) > 2 and (
        lowered[-2] not in "aeiou"
    ):
        return lowered[:-1] + "ies"
    if lowered.endswith(("o", "s", "x", "z", "ch", "sh")):
        return lowered + "es"
    return lowered + "s"


def _sentence_case(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def _finish(text: str) -> str:
    text = _sentence_case(text.strip().rstrip(","))
    return text if text.endswith((".", "!", "?")) else text + "."


@dataclass(frozen=True)
class _RawCandidate:
    rule_id: str
    family: str
    tier: int
    kind: str
    normalized: str
    start: int
    end: int
    confidence: float


class DeterministicGroundedExtractionController:
    """One durable user-grounded candidate, or none."""

    controller_id = GROUNDED_EXTRACTION_CONTROLLER_ID
    version = GROUNDED_EXTRACTION_VERSION

    def __init__(self, validator: GroundedCandidateValidator | None = None):
        self.validator = validator or GroundedCandidateValidator()

    # -- protocol ----------------------------------------------------------------

    def extract(self, evidence: ExtractionEvidence) -> ExtractionProposal:
        started = time.perf_counter()
        source_text = evidence.user_text or ""
        provenance = evidence.provenance_label or "user_asserted"
        source_id = str(
            evidence.metadata.get("source_id", "user-message")
        )
        if not source_text.strip():
            return self._abstain(
                "empty_source", started, raw=0, valid=0
            )

        raw_candidates = self._discover(source_text)
        if not raw_candidates:
            reason = "no_rule_match"
            sentences = list(self._sentences(source_text))
            if sentences and all(
                _SENTENCE_QUESTION.search(s.strip())
                for s, _ in sentences if s.strip()
            ):
                reason = "question"
            elif any(
                _SENTENCE_HYPOTHETICAL.search(s)
                for s, _ in sentences
            ):
                reason = "hypothetical"
            return self._abstain(reason, started, raw=0, valid=0)

        source = ApprovedSource(
            source_id=source_id, text=source_text, provenance=provenance
        )
        validated = []
        rejected = []
        for raw in raw_candidates:
            candidate = ProposedMemoryCandidate(
                kind=raw.kind,
                text=raw.normalized,
                grounded=True,
                confidence=raw.confidence,
                evidence_spans=(
                    EvidenceSpan(
                        source="user",
                        start=raw.start,
                        end=raw.end,
                        excerpt=source_text[raw.start:raw.end],
                    ),
                ),
            )
            result = self.validator.validate(candidate, source)
            if result.valid:
                validated.append((raw, candidate, result))
            else:
                rejected.append((raw.rule_id, result.code))

        if not validated:
            return self._abstain(
                "invalid_grounding", started,
                raw=len(raw_candidates), valid=0,
                rejected=rejected,
            )

        # Deterministic arbitration: tier, confidence, narrower span,
        # earlier offset, stable rule ID.
        validated.sort(
            key=lambda item: (
                item[0].tier,
                -item[0].confidence,
                item[0].end - item[0].start,
                item[0].start,
                item[0].rule_id,
            )
        )
        raw, candidate, result = validated[0]
        skipped = [
            {"rule_id": other.rule_id, "reason": "lower_priority"}
            for other, _, _ in validated[1:5]
        ] + [
            {"rule_id": rule_id, "reason": f"rejected:{code}"}
            for rule_id, code in rejected[:5]
        ]
        diagnostics = {
            "controller_id": self.controller_id,
            "controller_version": self.version,
            "source_id": source_id,
            "source_provenance": provenance,
            "matched_rule": raw.rule_id,
            "rule_family": raw.family,
            "raw_candidate_count": len(raw_candidates),
            "valid_candidate_count": len(validated),
            "skipped_candidates": skipped,
            "evidence_start": raw.start,
            "evidence_end": raw.end,
            "validation": result.diagnostics,
            "canonical_effect": False,
            "evaluation": {
                "elapsed_ms": round(
                    (time.perf_counter() - started) * 1000.0, 3
                )
            },
        }
        return ExtractionProposal(
            recommendation="candidate",
            candidate=candidate,
            score=raw.confidence,
            confidence=raw.confidence,
            reason=(
                f"durable {raw.family} matched by {raw.rule_id}; "
                "exact-span grounded and validated"
            ),
            controller_id=self.controller_id,
            diagnostics=diagnostics,
        )

    # -- abstention --------------------------------------------------------------

    def _abstain(self, reason, started, raw, valid, rejected=None):
        diagnostics = {
            "controller_id": self.controller_id,
            "controller_version": self.version,
            "abstention_reason": reason,
            "raw_candidate_count": raw,
            "valid_candidate_count": valid,
            "canonical_effect": False,
            "evaluation": {
                "elapsed_ms": round(
                    (time.perf_counter() - started) * 1000.0, 3
                )
            },
        }
        if rejected:
            diagnostics["rejected_candidates"] = [
                {"rule_id": rule_id, "code": code}
                for rule_id, code in rejected[:8]
            ]
        return ExtractionProposal(
            recommendation="none",
            candidate=None,
            score=0.0,
            confidence=0.0,
            reason=f"no durable user-grounded candidate: {reason}",
            controller_id=self.controller_id,
            diagnostics=diagnostics,
        )

    # -- discovery ---------------------------------------------------------------

    @staticmethod
    def _sentences(text: str):
        position = 0
        for match in _SENTENCE_SPLIT.finditer(text):
            sentence = match.group(0)
            if sentence.strip():
                yield sentence, match.start()
            position = match.end()
            if position >= len(text):
                break

    def _discover(self, text: str) -> list:
        candidates: list = []
        for sentence, offset in self._sentences(text):
            stripped = sentence.strip()
            if _SENTENCE_QUESTION.search(stripped):
                continue
            if _SENTENCE_HYPOTHETICAL.search(stripped):
                continue
            for rule in _RULES:
                raw = rule(self, sentence, offset, text)
                if raw is not None:
                    candidates.append(raw)
        return candidates

    def _span(self, text, match_start, match_end, source,
              sentence_offset):
        """Trim trailing filler; include the terminal period only when
        the match both starts its sentence and reaches sentence end."""
        segment = source[match_start:match_end]
        trimmed = _TRAILING_FILLER.sub("", segment.rstrip())
        end = match_start + len(trimmed)
        sentence_start = sentence_offset + (
            len(source[sentence_offset:]) - len(
                source[sentence_offset:].lstrip()
            )
        )
        if (
            match_start == sentence_start
            and end < len(source)
            and source[end] == "."
        ):
            end += 1
        return match_start, end


# -- rule implementations (bounded, ordered, feature-named) ----------------------
# Each rule returns a _RawCandidate or None. Tier 1 = current
# replacement / standing instructions, then explicit statements, then
# habitual and scoped forms, then conversational facts.


def _rule_from_now_on(ctl, sentence, offset, source):
    match = re.match(
        r"^\s*From now on, ([a-z][^.!?]*)", sentence, re.IGNORECASE
    )
    if not match:
        return None
    body = match.group(1)
    if ", not " in body:
        return None  # the contrast-instruction rule cites the clause
    start = offset + match.start(0) + len(match.group(0)) - len(
        match.group(0).lstrip()
    )
    start, end = ctl._span(
        sentence, offset + sentence.index("From now on"),
        offset + len(sentence.rstrip()), source, offset
    )
    normalized = _finish(
        body.replace(" my ", " the ").rstrip(".") + " from now on"
    )
    return _RawCandidate(
        "replacement-from-now-on", "current_replacement", 1,
        "instruction", normalized, start, end, 0.9,
    )


def _rule_contrast_instruction(ctl, sentence, offset, source):
    match = re.search(
        r"\b((?:send|include|use|keep|put|add) me [^.!?]*, not [^.!?,]+"
        r"|(?:send|include|use|keep|put|add) [^.!?]*, not [^.!?,]+)",
        sentence, re.IGNORECASE,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    normalized = _finish(re.sub(r"^(\w+) me ", r"\1 ", body, count=1))
    return _RawCandidate(
        "instruction-with-contrast", "standing_instruction", 1,
        "instruction", normalized, start, end, 0.9,
    )


def _rule_when_clause_instruction(ctl, sentence, offset, source):
    match = re.match(
        r"^\s*(When [^,]+, (?:always |never )?[a-z][^.!?]*)",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    return _RawCandidate(
        "instruction-when-clause", "standing_instruction", 1,
        "instruction", _finish(source[start:end].rstrip(".")),
        start, end, 0.9,
    )


def _rule_negated_standing_instruction(ctl, sentence, offset, source):
    match = re.match(
        r"^\s*(Do n[o']?t \w+ [^.!?]*\bmy [\w-]+ "
        r"(?:plans|trips|emails|reports|itineraries)\b[^.!?]*)",
        sentence, re.IGNORECASE,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    normalized = _finish(body.replace(" my ", " "))
    return _RawCandidate(
        "instruction-negated-standing", "standing_instruction", 1,
        "instruction", normalized, start, end, 0.9,
    )


def _rule_now_replacement(ctl, sentence, offset, source):
    match = re.search(
        r"\b(now I (\w+) [^.!?,]+)", sentence
    )
    if not match or "used to" not in sentence.lower() and (
        "but now" not in sentence.lower()
    ):
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    verb = match.group(2)
    rest = source[start:end][len(f"now I {verb}"):].strip()
    normalized = _finish(f"Now {_conjugate(verb)} {rest}")
    return _RawCandidate(
        "preference-now-replacement", "current_replacement", 1,
        "preference", normalized, start, end, 0.9,
    )


def _rule_make_it_contrast(ctl, sentence, offset, source):
    match = re.search(
        r"\b(make it ([\w-]+) (\w+), not ([\w-]+))\b",
        sentence, re.IGNORECASE,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    qualifier, noun, alternative = (
        match.group(2), match.group(3), match.group(4)
    )
    normalized = _finish(
        f"{noun.capitalize()} is {qualifier}, not {alternative}"
    )
    return _RawCandidate(
        "preference-change-contrast", "current_replacement", 1,
        "preference", normalized, start, end, 0.85,
    )


def _rule_explicit_preference(ctl, sentence, offset, source):
    match = re.search(
        r"\b(I (?:always |usually |normally )?"
        r"(prefer|like|want|love) [^.!?;,\-]+)",
        sentence,
    )
    if not match:
        return None
    if re.search(r"[Ff]or [\w ]+?,? $", sentence[:match.start(1)]):
        return None  # scope-carrying clause: the scoped rule owns it
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    adverb_match = re.match(
        r"I (always|usually|normally) (\w+) (.+)", body
    )
    if adverb_match:
        adverb, verb, rest = adverb_match.groups()
        normalized = _finish(
            f"{adverb.capitalize()} {_conjugate(verb)} {rest}"
        )
        confidence = 0.85
    else:
        plain = re.match(r"I (\w+) (.+)", body)
        verb, rest = plain.groups()
        normalized = _finish(f"{_conjugate(verb).capitalize()} {rest}")
        confidence = 0.9
    return _RawCandidate(
        "preference-explicit", "explicit_preference", 3,
        "preference", normalized, start, end, confidence,
    )


def _rule_negated_preference(ctl, sentence, offset, source):
    match = re.search(
        r"\b(I do n[o']?t (prefer|like|want|use|drink|choose) "
        r"[^.!?;,]+)",
        sentence, re.IGNORECASE,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    normalized = _finish(
        re.sub(r"^I do (n[o']?t)", lambda m: f"Does {m.group(1)}",
               body, count=1)
    )
    return _RawCandidate(
        "preference-negated", "explicit_preference", 3,
        "preference", normalized, start, end, 0.9,
    )


def _rule_possessive_fact(ctl, sentence, offset, source):
    match = re.search(
        r"\b([Mm]y [a-z][a-z ]{0,30} is [A-Za-z0-9][\w -]*)",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    normalized = _finish(re.sub(r"^[Mm]y ", "", body, count=1))
    return _RawCandidate(
        "fact-possessive", "durable_fact", 4, "fact",
        normalized, start, end, 0.9,
    )


def _rule_stable_state_fact(ctl, sentence, offset, source):
    match = re.search(
        r"\b(I (work (?:at|for)|live in) [^.!?;,]+)", sentence
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    normalized = _finish(
        re.sub(r"^I (work|live)", lambda m: _conjugate(
            m.group(1)
        ).capitalize(), body, count=1)
    )
    return _RawCandidate(
        "fact-stable-state", "durable_fact", 4, "fact",
        normalized, start, end, 0.9,
    )


def _rule_has_become_fact(ctl, sentence, offset, source):
    match = re.search(
        r"\b([A-Z][\w-]*) has become my ([a-z][a-z ]{0,40}?)"
        r"(?=[.!?,;]|$)",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(0), offset + match.end(0),
        source, offset,
    )
    normalized = _finish(
        f"{match.group(2).strip().capitalize()} is {match.group(1)}"
    )
    return _RawCandidate(
        "fact-has-become", "conversational_fact", 7, "fact",
        normalized, start, end, 0.8,
    )


def _rule_acquired_fact(ctl, sentence, offset, source):
    match = re.search(
        r"\b(I (?:finally |recently |just )?got my "
        r"([a-z][a-z ]{0,40}?))(?=[.!?,;]| so\b|$)",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    normalized = _finish(f"Got a {match.group(2).strip()}")
    return _RawCandidate(
        "fact-acquired", "conversational_fact", 7, "fact",
        normalized, start, end, 0.8,
    )


def _rule_copular_fact(ctl, sentence, offset, source):
    if _SENTENCE_TEMPORAL.search(sentence):
        return None
    match = re.search(
        r"\b(I'm ((?:lactose|gluten) intolerant|allergic to [\w ]+"
        r"|vegetarian|vegan))",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    normalized = _finish(f"Is {match.group(2)}")
    return _RawCandidate(
        "fact-copular", "conversational_fact", 7, "fact",
        normalized, start, end, 0.8,
    )


def _rule_habitual(ctl, sentence, offset, source):
    match = re.search(
        r"\b(I (usually|normally|generally|always) "
        r"(?!prefer|like|want|love)(\w+) [^.!?;\-]+)",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    parts = re.match(r"I (\w+) (\w+) (.+)", body)
    adverb, verb, rest = parts.groups()
    normalized = _finish(
        f"{adverb.capitalize()} {_conjugate(verb)} {rest}"
    )
    return _RawCandidate(
        "preference-habitual", "habitual_preference", 6,
        "preference", normalized, start, end, 0.8,
    )


def _rule_leading_adverb_habit(ctl, sentence, offset, source):
    match = re.search(
        r"\b((?:normally|usually) I (\w+) [^.!?;\-]+)",
        sentence, re.IGNORECASE,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    parts = re.match(r"(\w+) I (\w+) (.+)", body, re.IGNORECASE)
    adverb, verb, rest = parts.groups()
    normalized = _finish(
        f"{adverb.capitalize()} {_conjugate(verb)} {rest}"
    )
    return _RawCandidate(
        "preference-leading-adverb", "habitual_preference", 6,
        "preference", normalized, start, end, 0.8,
    )


def _rule_do_all_my(ctl, sentence, offset, source):
    match = re.search(r"\b(I do all my [^.!?;,]+)", sentence)
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    normalized = _finish(
        re.sub(r"^I do all my ", "Does all ", body, count=1)
    )
    return _RawCandidate(
        "preference-do-all", "habitual_preference", 6,
        "preference", normalized, start, end, 0.8,
    )


def _rule_recurring_period(ctl, sentence, offset, source):
    match = re.search(
        r"\b(I (\w+) [^.!?;,]*\bmost "
        r"(?:weeks|days|months|mornings|trips)\b)",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    verb = match.group(2)
    rest = body[len(f"I {verb}"):].strip()
    normalized = _finish(f"{_conjugate(verb).capitalize()} {rest}")
    return _RawCandidate(
        "preference-recurring-period", "habitual_preference", 6,
        "preference", normalized, start, end, 0.8,
    )


def _rule_scoped_preference(ctl, sentence, offset, source):
    match = re.search(
        r"\b([Ff]or [\w -]+?,? I (usually|normally) (\w+) "
        r"[^.!?;\-]+)",
        sentence,
    )
    if not match:
        return None
    start, end = ctl._span(
        sentence, offset + match.start(1), offset + match.end(1),
        source, offset,
    )
    body = source[start:end].rstrip(".")
    parts = re.match(
        r"[Ff]or ([\w -]+?),? I (usually|normally) (\w+) (.+)", body
    )
    scope, adverb, verb, rest = parts.groups()
    normalized = _finish(
        f"{adverb.capitalize()} {_conjugate(verb)} {rest} for {scope}"
    )
    return _RawCandidate(
        "preference-scoped", "scoped_preference", 5,
        "preference", normalized, start, end, 0.8,
    )


_RULES = (
    _rule_from_now_on,
    _rule_contrast_instruction,
    _rule_when_clause_instruction,
    _rule_negated_standing_instruction,
    _rule_now_replacement,
    _rule_make_it_contrast,
    _rule_negated_preference,
    _rule_explicit_preference,
    _rule_possessive_fact,
    _rule_stable_state_fact,
    _rule_has_become_fact,
    _rule_acquired_fact,
    _rule_copular_fact,
    _rule_scoped_preference,
    _rule_leading_adverb_habit,
    _rule_do_all_my,
    _rule_recurring_period,
    _rule_habitual,
)
