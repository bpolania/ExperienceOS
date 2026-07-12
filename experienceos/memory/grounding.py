"""Grounded candidate validation.

Deterministic, provider-independent validation for proposed durable
memory candidates (`ProposedMemoryCandidate` +
`EvidenceSpan`): structural schema, canonical kind, source identity
and provenance, exact evidence-span matching, source-form rejection
(questions, hypotheticals, temporary state, one-off requests,
third-party ownership), durability, and conservative normalized-text
support checks.

The validator approves or rejects a proposal for LATER lifecycle
consideration. It never creates, updates, supersedes, forgets,
retrieves, or ranks memories; it receives no store handle and calls no
provider or model. It is not integrated into canonical extraction —
``canonical_effect`` is false in every diagnostic it emits.

Composition rule with the existing durability gate
(``experienceos.memory.extraction.DurabilityGate``): the gate's
NEGATIVE decisions (question, hypothetical, transient request, quoted
third-party speech, greeting, fiction, brainstorm) are authoritative
and reject here too. When the gate finds no positive cue
(``no_durable_cues``) this validator may still accept through a
supplementary durable-assertion cue set — externally produced
proposals cover phrasings the rules-first extractor never emits (e.g.
"has become", copular self-description, change-with-contrast) — after
every form-rejection guard has already run. This widens acceptance for
proposal validation only; canonical extraction behavior is unchanged.

Support checking is conservative and deterministic — lexical
containment with bounded morphology, polarity, frequency-strength, and
universalizer rules. It rejects clear expansions and inversions; it is
NOT general semantic entailment. Where support cannot be established
deterministically the result is ``indeterminate_support`` and the
proposal FAILS CLOSED (invalid) — a stronger repository-owned rule may
later re-establish support, but this validator never guesses.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from experienceos.controllers.extraction import ProposedMemoryCandidate
from experienceos.memory.extraction import (
    _NEGATION,
    DurabilityGate,
    MAX_EVIDENCE_LENGTH,
    VALID_CANDIDATE_KINDS,
)

GROUNDED_VALIDATOR_ID = "grounded_candidate_validator"
GROUNDED_VALIDATOR_VERSION = "1"

VALID = "valid"
REJECTION_CODES = (
    "malformed_proposal",
    "invalid_memory_kind",
    "missing_source",
    "source_mismatch",
    "invalid_source_type",
    "assistant_only_source",
    "empty_evidence",
    "invalid_offsets",
    "evidence_mismatch",
    "question_derived",
    "hypothetical_derived",
    "temporary_state",
    "one_off_request",
    "unsupported_ownership",
    "unsupported_normalization",
    "non_durable",
    "indeterminate_support",
)

DEFAULT_ALLOWED_PROVENANCE = frozenset({"user_asserted"})
# Grantable only through the existing validated policy paths (the
# confirmation flow and the tool-result flow); never default.
CONFIRMABLE_PROVENANCE = frozenset({"jointly_confirmed", "tool_verified"})

_STAGES = (
    "schema", "kind", "provenance", "span_structure", "exact_match",
    "source_form", "durability", "normalized_support",
)

# -- source-form guards (evaluated on the CITED SPAN text) ----------------------

# A question is: any question mark in the span, an auxiliary+subject
# question opening, or an explicit wondering construction. A bare
# interrogative word is NOT enough — "When planning work trips, ..."
# is a subordinate clause, not a question.
_QUESTION = re.compile(
    r"\?"
    r"|^(?:should|could|would|can|do|does|did|am|is|are|will|shall)\s+"
    r"(?:i|we|you|it|there)\b"
    r"|\bi wonder\b|\bwondering (?:if|whether)\b",
    re.IGNORECASE,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:if (?:i|we)\b|i might|we might|i would|we would|i could see"
    r"|were (?:i|we) to|imagine|suppose|supposing|hypothetically"
    r"|what if|maybe someday|might end up)\b",
    re.IGNORECASE,
)
_ONE_OFF = re.compile(
    r"^(?:please\s+)?(?:book|order|reserve|find|search|look up|check"
    r"|fetch|get me|grab|schedule)\b",
    re.IGNORECASE,
)
_STANDING_OVERRIDE = re.compile(
    r"\b(?:remember|from now on|going forward|always|whenever"
    r"|every time)\b",
    re.IGNORECASE,
)
_TEMPORARY = re.compile(
    r"\b(?:today|tonight|tomorrow|right now|for now|just this once"
    r"|this (?:week|weekend|month|year|time|trip|session|morning"
    r"|afternoon|evening)|until (?:mon|tues|wednes|thurs|fri|satur"
    r"|sun)[a-z]*|until (?:next|the end of)\b)",
    re.IGNORECASE,
)
_THIRD_PARTY_PREFERENCE = re.compile(
    r"\bmy\s+(?:manager|boss|partner|wife|husband|friend|colleague"
    r"|coworker|co-worker|mother|father|mom|dad|sister|brother|team"
    r"|teammate|client|roommate)\b[^.!?\n]{0,40}\b(?:prefers?|likes?"
    r"|wants?|keeps? saying|insists?|swears? by)\b",
    re.IGNORECASE,
)

# -- supplementary durable-assertion cues (validator-only; see module
# docstring) --------------------------------------------------------------------

_SUPPLEMENTARY_DURABLE_CUES = (
    ("state_become", re.compile(
        r"\b(?:has|have) become\b|\bbecame\b", re.IGNORECASE)),
    ("copular_self_description", re.compile(
        r"\bi\s*(?:'m| am)\b", re.IGNORECASE)),
    ("acquired_possession", re.compile(
        r"\bi (?:finally |recently |just )?(?:got|earned|received) my\b",
        re.IGNORECASE)),
    ("change_with_contrast", re.compile(
        r"\bmake it\b[^.!?\n]{0,60},?\s*\bnot\b", re.IGNORECASE)),
    ("imperative_instruction", re.compile(
        r"^(?:always |never |do not |don'?t )?(?:send|include|use|keep"
        r"|exclude|avoid|add|put)\b",
        re.IGNORECASE)),
    ("habitual_adverb", re.compile(
        r"\b(?:normally|often|generally|by default)\b", re.IGNORECASE)),
    ("habitual_do", re.compile(
        r"\bi do all my\b", re.IGNORECASE)),
    ("recurring_period", re.compile(
        r"\bmost (?:weeks|days|months|mornings|evenings|trips)\b",
        re.IGNORECASE)),
    ("negated_preference", re.compile(
        r"\b(?:i|we) (?:do not|don'?t|never) (?:prefer|like|want|use"
        r"|drink|choose|include)\b",
        re.IGNORECASE)),
)

# -- normalized-support lexical rules --------------------------------------------

_UNIVERSALIZERS = frozenset(
    {"all", "every", "any", "everywhere", "everything", "anywhere"}
)
_FREQUENCY_STRENGTH = {
    "always": 3, "never": 3, "requires": 3,
    "usually": 2, "normally": 2, "often": 2, "generally": 2,
    "typically": 2, "most": 2, "default": 2,
    "sometimes": 1, "occasionally": 1, "tend": 1, "tends": 1,
}
_SUPPORT_STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "was", "were", "be", "been",
     "for", "in", "on", "at", "as", "to", "of", "with", "and", "or",
     "but", "not", "no", "it", "its", "this", "that", "these",
     "when", "while", "from", "into", "out", "so", "my", "our",
     "their", "his", "her", "me", "we", "i", "you"}
)
_TOKEN = re.compile(r"[a-z0-9#'\-]+")


def _support_tokens(text: str) -> list:
    return [t.strip("'-") for t in _TOKEN.findall(text.lower())
            if t.strip("'-")]


def _same_lexeme(a: str, b: str) -> bool:
    """Bounded morphology: exact, plural/verb -s/-es, ies<->y, or a
    shared prefix of 5+ characters (the repository's safe-prefix
    convention)."""
    if a == b:
        return True
    for x, y in ((a, b), (b, a)):
        if x == y + "s" or x == y + "es":
            return True
        if x.endswith("ies") and len(x) > 4 and y == x[:-3] + "y":
            return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 5 and longer.startswith(shorter)


@dataclass(frozen=True)
class ApprovedSource:
    """Caller-supplied source of record for one validation.

    Provenance comes from HERE — never from the proposal. A proposal
    cannot upgrade its own trust by claiming a different provenance.
    """

    source_id: str
    text: str
    provenance: str = "user_asserted"


@dataclass(frozen=True)
class GroundingValidation:
    """Bounded validation result; carries no mutation authority."""

    valid: bool
    code: str  # "valid" or one of REJECTION_CODES
    stages: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    candidate: ProposedMemoryCandidate | None = None
    explanation: str = ""


class GroundedCandidateValidator:
    """Composing validator for externally produced memory proposals."""

    validator_id = GROUNDED_VALIDATOR_ID
    version = GROUNDED_VALIDATOR_VERSION

    def __init__(self, durability_gate=None,
                 accepted_confirmed_provenance=frozenset()):
        extra = frozenset(accepted_confirmed_provenance)
        unknown = extra - CONFIRMABLE_PROVENANCE
        if unknown:
            raise ValueError(
                f"provenance {sorted(unknown)} cannot be accepted; "
                f"only {sorted(CONFIRMABLE_PROVENANCE)} are grantable"
            )
        self.allowed_provenance = DEFAULT_ALLOWED_PROVENANCE | extra
        self.gate = durability_gate or DurabilityGate()

    # -- public API --------------------------------------------------------------

    def validate(self, candidate, source: ApprovedSource
                 ) -> GroundingValidation:
        started = time.perf_counter()
        stages: dict = {name: "skipped" for name in _STAGES}
        outcome = self._run(candidate, source, stages)
        code, explanation = outcome
        valid = code == VALID
        diagnostics = self._diagnostics(
            candidate, source, stages, code, started
        )
        return GroundingValidation(
            valid=valid,
            code=code,
            stages=stages,
            diagnostics=diagnostics,
            candidate=candidate if valid else None,
            explanation=explanation,
        )

    # -- pipeline ----------------------------------------------------------------

    def _run(self, candidate, source, stages):
        # 1. schema
        problem = self._schema_problem(candidate, source)
        if problem:
            stages["schema"] = "failed"
            return problem
        stages["schema"] = "passed"

        # 2. kind
        if candidate.kind not in VALID_CANDIDATE_KINDS:
            stages["kind"] = "failed"
            return ("invalid_memory_kind",
                    f"kind {candidate.kind!r} is not canonical")
        stages["kind"] = "passed"

        # 3. source identity + provenance (approved metadata only)
        problem = self._provenance_problem(candidate, source)
        if problem:
            stages["provenance"] = "failed"
            return problem
        stages["provenance"] = "passed"

        span = candidate.evidence_spans[0]
        evidence = span.excerpt

        # 4. span structure
        problem = self._structure_problem(span, source)
        if problem:
            stages["span_structure"] = "failed"
            return problem
        stages["span_structure"] = "passed"

        # 5. exact match (never repaired)
        if source.text[span.start:span.end] != evidence:
            stages["exact_match"] = "failed"
            return ("evidence_mismatch",
                    "evidence text does not equal the exact source "
                    "slice")
        stages["exact_match"] = "passed"

        # 6. source-form rejection on the cited span
        problem = self._form_problem(evidence)
        if problem:
            stages["source_form"] = "failed"
            return problem
        stages["source_form"] = "passed"

        # 7. durability (gate negatives authoritative; supplementary
        # cues may recover only from "no_durable_cues")
        problem = self._durability_problem(evidence, stages)
        if problem:
            stages["durability"] = "failed"
            return problem
        stages["durability"] = "passed"

        # 8. normalized-text support
        problem = self._support_problem(candidate.text, evidence)
        if problem:
            stages["normalized_support"] = "failed"
            return problem
        stages["normalized_support"] = "passed"
        return (VALID, "validated")

    # -- stages ------------------------------------------------------------------

    @staticmethod
    def _schema_problem(candidate, source):
        if not isinstance(candidate, ProposedMemoryCandidate):
            return ("malformed_proposal",
                    "candidate is not a ProposedMemoryCandidate")
        if not isinstance(source, ApprovedSource):
            return ("malformed_proposal",
                    "source is not an ApprovedSource")
        if not (candidate.text or "").strip():
            return ("malformed_proposal", "empty candidate text")
        if not candidate.evidence_spans:
            return ("malformed_proposal",
                    "positive proposal cites no evidence span")
        confidence = candidate.confidence
        if isinstance(confidence, bool) or not isinstance(
            confidence, (int, float)
        ) or not 0.0 <= float(confidence) <= 1.0:
            return ("malformed_proposal", "confidence out of bounds")
        return None

    def _provenance_problem(self, candidate, source):
        if not (source.source_id or "").strip():
            return ("missing_source", "approved source has no identity")
        if not source.text:
            return ("missing_source", "approved source has no text")
        if source.provenance not in self.allowed_provenance:
            if source.provenance in CONFIRMABLE_PROVENANCE:
                return ("invalid_source_type",
                        f"{source.provenance!r} not granted for this "
                        "validation")
            if source.provenance in ("assistant_derived",):
                return ("assistant_only_source",
                        "unconfirmed assistant-derived source")
            return ("invalid_source_type",
                    f"unknown provenance {source.provenance!r}")
        for span in candidate.evidence_spans:
            if span.source == "assistant":
                return ("assistant_only_source",
                        "cited span comes from assistant text")
            if span.source != "user":
                return ("source_mismatch",
                        f"span source {span.source!r} is not the "
                        "approved source")
        return None

    @staticmethod
    def _structure_problem(span, source):
        if not isinstance(span.start, int) or not isinstance(
            span.end, int
        ):
            return ("invalid_offsets", "offsets must be integers")
        if span.start < 0 or span.end <= span.start:
            return ("invalid_offsets",
                    "offsets must satisfy 0 <= start < end")
        if span.end > len(source.text):
            return ("invalid_offsets",
                    "end offset exceeds the source length")
        if not (span.excerpt or "").strip():
            return ("empty_evidence", "evidence text is empty")
        if len(span.excerpt) > MAX_EVIDENCE_LENGTH:
            return ("invalid_offsets",
                    "evidence exceeds the bounded length")
        return None

    @staticmethod
    def _form_problem(evidence):
        text = evidence.strip()
        if _QUESTION.search(text):
            return ("question_derived",
                    "cited span expresses a question, not an assertion")
        if _HYPOTHETICAL.search(text):
            return ("hypothetical_derived",
                    "cited span is hypothetical or counterfactual")
        if _ONE_OFF.search(text) and not _STANDING_OVERRIDE.search(text):
            return ("one_off_request",
                    "cited span is a one-off request")
        if _TEMPORARY.search(text):
            return ("temporary_state",
                    "cited span is bounded to a temporary period")
        if _THIRD_PARTY_PREFERENCE.search(text):
            return ("unsupported_ownership",
                    "cited span states another person's preference")
        return None

    def _durability_problem(self, evidence, stages):
        decision = self.gate.assess(evidence)
        stages["durability_gate_reason"] = decision.reason
        if decision.passed:
            return None
        if decision.reason == "question":
            return ("question_derived", "durability gate: question")
        if decision.reason == "hypothetical":
            return ("hypothetical_derived",
                    "durability gate: hypothetical")
        if decision.reason == "transient_request":
            return ("one_off_request",
                    "durability gate: transient request")
        if decision.reason == "current_turn_only":
            return ("temporary_state",
                    "durability gate: current turn only")
        if decision.reason == "quoted_third_party":
            return ("unsupported_ownership",
                    "durability gate: quoted third-party speech")
        if decision.reason == "no_durable_cues":
            for cue, pattern in _SUPPLEMENTARY_DURABLE_CUES:
                if pattern.search(evidence):
                    stages["durability_gate_reason"] = (
                        f"supplementary:{cue}"
                    )
                    return None
            return ("non_durable",
                    "no durable-assertion cue in the cited span")
        return ("non_durable", f"durability gate: {decision.reason}")

    def _support_problem(self, normalized, evidence):
        normalized_tokens = _support_tokens(normalized)
        evidence_tokens = _support_tokens(evidence)
        if not normalized_tokens:
            return ("malformed_proposal", "empty normalized text")

        # Polarity must survive in both directions.
        evidence_negated = bool(_NEGATION.search(evidence))
        normalized_negated = bool(_NEGATION.search(normalized))
        if evidence_negated != normalized_negated:
            return ("unsupported_normalization",
                    "polarity differs between evidence and candidate")

        # Frequency/certainty must not strengthen.
        def strength(tokens):
            return max(
                (_FREQUENCY_STRENGTH.get(t, 0) for t in tokens),
                default=0,
            )
        if strength(normalized_tokens) > strength(evidence_tokens):
            return ("unsupported_normalization",
                    "candidate strengthens frequency or certainty")

        # Universalizers must come from the evidence itself.
        evidence_set = set(evidence_tokens)
        for token in normalized_tokens:
            if token in _UNIVERSALIZERS and token not in evidence_set:
                return ("unsupported_normalization",
                        f"unsupported universal scope {token!r}")

        # Content containment with bounded morphology. Unknown content
        # introduces information the evidence never stated: entities,
        # numbers, and universal words are clear inventions; other
        # unknown words leave support indeterminate (fail closed).
        unknown = []
        for token in normalized_tokens:
            if token in _SUPPORT_STOPWORDS:
                continue
            if any(_same_lexeme(token, known)
                   for known in evidence_tokens):
                continue
            unknown.append(token)
        if unknown:
            # Clear inventions: numbers, or entity-like tokens (words
            # that appear capitalized mid-sentence or fully uppercased
            # in the normalized text) that the evidence never states.
            words = re.findall(r"[A-Za-z][\w\-']*", normalized)
            entity_like = {
                w.lower()
                for index, w in enumerate(words)
                if (w.isupper() and len(w) >= 2)
                or (w[:1].isupper() and index > 0)
            }
            invented = [
                t for t in unknown
                if any(c.isdigit() for c in t) or t in entity_like
            ]
            if invented:
                return ("unsupported_normalization",
                        f"unsupported details: {sorted(set(invented))}")
            return ("indeterminate_support",
                    "support cannot be established deterministically "
                    f"for: {sorted(set(unknown))}")
        return None

    # -- diagnostics -------------------------------------------------------------

    def _diagnostics(self, candidate, source, stages, code, started):
        span = None
        if isinstance(candidate, ProposedMemoryCandidate) and (
            candidate.evidence_spans
        ):
            span = candidate.evidence_spans[0]
        payload = {
            "validator_id": self.validator_id,
            "validator_version": self.version,
            "source_id": getattr(source, "source_id", None),
            "source_provenance": getattr(source, "provenance", None),
            "proposed_kind": getattr(candidate, "kind", None),
            "candidate_text": (
                str(getattr(candidate, "text", ""))[:240] or None
            ),
            "evidence_start": span.start if span else None,
            "evidence_end": span.end if span else None,
            "evidence_length": (
                len(span.excerpt) if span and span.excerpt else None
            ),
            "stages": dict(stages),
            "valid": code == VALID,
            "code": code,
            "canonical_effect": False,
            "evaluation": {
                "elapsed_ms": round(
                    (time.perf_counter() - started) * 1000.0, 3
                )
            },
        }
        json.dumps(payload)  # deterministic serialization guarantee
        return payload
