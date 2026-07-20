"""HybridMemoryPlanner: deterministic rules first, gated extraction second.

The extraction-only planning strategy:

1. The unchanged v1 ``MemoryPlanner`` runs first and stays authoritative
   for everything it detects — creation, keyed supersession, duplicate
   skipping, and forgetting.
2. Sentences the v1 rules did not match are screened by the
   deterministic ``DurabilityGate``; only durable-looking sentences
   reach the candidate extractor.
3. Extractor proposals pass per-candidate schema/grounding/durability
   validation, semantic normalization, and duplicate checks before
   becoming CREATE actions.

Isolation properties (extraction-only ablation, by construction):

- retrieval, selection K, and context budgets are untouched — this is
  a planner, and planning never reads or ranks memories for context;
- accepted candidates never supersede or forget anything: extraction
  proposes creations only, so v1 lifecycle planning is retained and
  generalized slot supersession stays out of this strategy;
- every emitted action still flows through ExperienceManager
  validation and ExperienceEngine lifecycle checks.

The planner keeps bounded per-conversation recent-turn context (for
unambiguous pronoun resolution only) and bounded extraction diagnostics
that the engine drains into audit events. It never touches storage.
"""

from __future__ import annotations

import re
from collections import deque

from experienceos.memory.extraction import (
    DEFAULT_MAX_CANDIDATES_PER_TURN,
    DURABILITY_GATE_VERSION,
    GROUNDING_VALIDATOR_VERSION,
    CandidateValidator,
    DeterministicConversationalExtractor,
    DurabilityGate,
    ExtractionRequest,
    MemoryCandidate,
)
from experienceos.memory.planner import (
    CREATE,
    _FORGET_PATTERNS,
    MemoryAction,
    MemoryPlanner,
    _normalized_text,
)
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.semantic import (
    Cardinality,
    Decision,
    METADATA_KEY,
    SemanticIdentity,
    SemanticNormalizer,
    resolve_conflicts,
)

EXTRACTION_STRATEGY = "rules_first_hybrid"
EXTRACTION_STRATEGY_VERSION = "1"

_RECENT_TURNS = 3  # bounded conversational context for coreference

_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+")

_COUNTER_KEYS = (
    "turns",
    "rules_handled_turns",
    "rules_partially_handled_turns",
    "rules_unmatched_turns",
    "unmatched_sentences",
    "gate_passed",
    "gate_rejected",
    "extractor_invocations",
    "extractor_failed_safe",
    "candidates_proposed",
    "candidates_schema_rejected",
    "candidates_grounding_rejected",
    "candidates_durability_rejected",
    "candidates_duplicate",
    "candidates_accepted",
)


class HybridMemoryPlanner(MemoryPlanner):
    """v1 rule planning plus gated, validated conversational extraction.

    Configuration is explicit and construction-time only — no global
    flags. The default extractor is the deterministic offline one; an
    optional local-model extractor may be injected where configured.
    """

    extraction_strategy = EXTRACTION_STRATEGY
    extraction_strategy_version = EXTRACTION_STRATEGY_VERSION

    def __init__(
        self,
        extractor=None,
        gate: DurabilityGate | None = None,
        validator: CandidateValidator | None = None,
        normalizer: SemanticNormalizer | None = None,
        max_candidates_per_turn: int = DEFAULT_MAX_CANDIDATES_PER_TURN,
    ):
        self.extractor = extractor or DeterministicConversationalExtractor()
        self.gate = gate or DurabilityGate()
        self.validator = validator or CandidateValidator()
        self.normalizer = normalizer or SemanticNormalizer()
        self.max_candidates_per_turn = max_candidates_per_turn
        self.counters = {key: 0 for key in _COUNTER_KEYS}
        self._recent: dict[tuple[str, str], deque] = {}
        self._pending_events: list[tuple[str, dict]] = []
        self._turn_seq = 0

    # -- diagnostics -------------------------------------------------------------

    def summary(self) -> dict:
        """Cumulative extraction counters plus configuration identity."""
        return {
            **self.counters,
            "extraction_strategy": self.extraction_strategy,
            "extraction_strategy_version": self.extraction_strategy_version,
            "durability_gate_version": self.gate.version,
            "candidate_extractor": self.extractor.extractor_id,
            "candidate_extractor_version": self.extractor.extractor_version,
            "grounding_validator_version": self.validator.version,
            "candidate_limit": self.max_candidates_per_turn,
        }

    def drain_extraction_events(self) -> list[tuple[str, dict]]:
        """Pending (event_type, payload) pairs; emptied on read. The
        engine emits these on the existing event bus."""
        drained, self._pending_events = self._pending_events, []
        return drained

    def _event(self, event_type: str, **payload) -> None:
        if len(self._pending_events) < 64:  # bounded per turn drain
            self._pending_events.append((event_type, payload))

    # -- planning -----------------------------------------------------------------

    def plan_memory_actions(
        self,
        user_id: str,
        session_id: str,
        message: str,
        existing: list[ExperienceEntry] | None = None,
    ) -> list[MemoryAction]:
        existing = existing or []
        actions = super().plan_memory_actions(
            user_id, session_id, message, existing
        )
        self._turn_seq += 1
        self.counters["turns"] += 1
        source_ref = f"{session_id}:{self._turn_seq}"
        recent = self._recent.setdefault(
            (user_id, session_id), deque(maxlen=_RECENT_TURNS)
        )

        sentences = [s.strip() for s in _SENTENCES.split(message) if s.strip()]
        unmatched = [s for s in sentences if not self._rules_match(s)]
        if not unmatched:
            self.counters["rules_handled_turns"] += 1
        elif len(unmatched) < len(sentences) or actions:
            self.counters["rules_partially_handled_turns"] += 1
        else:
            self.counters["rules_unmatched_turns"] += 1

        actions = self._extend_with_candidates(
            actions, unmatched, existing, source_ref, tuple(recent)
        )
        recent.append(message)
        return actions

    def _rules_match(self, sentence: str) -> bool:
        """Whether the v1 deterministic rules handle this sentence.

        Conservative sentence-level distinction: v1 exposes no match
        spans, so a sentence counts as handled when any v1 detector
        (preference, fact, instruction, forget) fires on it alone.
        """
        if any(p.search(sentence) for p in _FORGET_PATTERNS):
            return True
        return bool(
            self._detect_preference_texts(sentence)
            or self._detect_fact_texts(sentence)
            or self._detect_instruction_texts(sentence)
        )

    def _extend_with_candidates(
        self, actions, unmatched, existing, source_ref, recent_context
    ):
        active = [e for e in existing if e.status == MemoryStatus.ACTIVE]
        batch_texts = {
            _normalized_text(a.text)
            for a in actions
            if a.action == CREATE
        }
        accepted_this_turn = 0
        result = list(actions)

        for index, sentence in enumerate(unmatched):
            self.counters["unmatched_sentences"] += 1
            if accepted_this_turn >= self.max_candidates_per_turn:
                break
            gate = self.gate.assess(sentence)
            if not gate.passed:
                self.counters["gate_rejected"] += 1
                self._event(
                    "memory_extraction_gate_rejected",
                    source_ref=source_ref,
                    sentence_index=index,
                    reason=gate.reason,
                    gate_version=gate.version,
                )
                continue
            self.counters["gate_passed"] += 1
            self._event(
                "memory_extraction_gate_passed",
                source_ref=source_ref,
                sentence_index=index,
                matched_cues=list(gate.matched_cues),
                confidence=gate.confidence,
                gate_version=gate.version,
            )

            request = ExtractionRequest(
                source_text=sentence,
                source_ref=source_ref,
                source_role="user",
                session_id=source_ref.rsplit(":", 1)[0],
                recent_context=recent_context,
                deterministic_status="rules_unmatched",
                max_candidates=(
                    self.max_candidates_per_turn - accepted_this_turn
                ),
            )
            self.counters["extractor_invocations"] += 1
            self._event(
                "memory_extraction_invoked",
                source_ref=source_ref,
                sentence_index=index,
                extractor=self.extractor.extractor_id,
                extractor_version=self.extractor.extractor_version,
                mode="deterministic_offline",
            )
            try:
                extraction = self.extractor.extract(request)
            except Exception as exc:  # noqa: BLE001 — no fabricated fallback
                self.counters["extractor_failed_safe"] += 1
                self._event(
                    "memory_extraction_failed_safe",
                    source_ref=source_ref,
                    sentence_index=index,
                    reason=f"{type(exc).__name__}: {str(exc)[:120]}",
                )
                continue
            if extraction.status == "failed_safe" or not extraction.valid:
                self.counters["extractor_failed_safe"] += 1
                self._event(
                    "memory_extraction_failed_safe",
                    source_ref=source_ref,
                    sentence_index=index,
                    reason=extraction.reason[:120],
                    fallback=extraction.fallback,
                )
                continue

            for position, candidate in enumerate(extraction.candidates):
                if accepted_this_turn >= self.max_candidates_per_turn:
                    break
                self.counters["candidates_proposed"] += 1
                self._event(
                    "memory_candidate_proposed",
                    source_ref=source_ref,
                    candidate_index=position,
                    kind=candidate.kind,
                    statement=candidate.statement[:120],
                    confidence=candidate.confidence,
                )
                action = self._accept_candidate(
                    candidate, request, gate, active, batch_texts,
                    source_ref, position,
                )
                if action is not None:
                    result.append(action)
                    batch_texts.add(_normalized_text(action.text))
                    accepted_this_turn += 1
        return result

    def _accept_candidate(
        self, candidate, request, gate, active, batch_texts,
        source_ref, position,
    ) -> MemoryAction | None:
        outcome = self.validator.validate(candidate, request, gate)
        if not outcome.accepted:
            self.counters[f"candidates_{outcome.stage}_rejected"] += 1
            self._event(
                "memory_candidate_rejected",
                source_ref=source_ref,
                candidate_index=position,
                stage=outcome.stage,
                reason=outcome.reason[:120],
                validator_version=outcome.validator_version,
            )
            return None

        if _normalized_text(candidate.statement) in batch_texts or any(
            entry.kind == candidate.kind
            and _normalized_text(entry.text)
            == _normalized_text(candidate.statement)
            for entry in active
        ):
            return self._duplicate(candidate, source_ref, position, "exact text")

        identity = self._identity_for(candidate)
        if identity is not None:
            duplicates = [
                d
                for d in resolve_conflicts(identity, active, self.normalizer)
                if d.decision == Decision.DUPLICATE
            ]
            if duplicates:
                return self._duplicate(
                    candidate, source_ref, position, duplicates[0].reason
                )

        self.counters["candidates_accepted"] += 1
        self._event(
            "memory_candidate_accepted",
            source_ref=source_ref,
            candidate_index=position,
            kind=candidate.kind,
            statement=candidate.statement[:120],
            attribute=identity.attribute if identity else None,
            scope=identity.scope if identity else None,
            confidence=candidate.confidence,
        )
        metadata: dict = {
            "extraction": {
                "method": candidate.extraction_method,
                "extractor": self.extractor.extractor_id,
                "extractor_version": self.extractor.extractor_version,
                "gate_version": DURABILITY_GATE_VERSION,
                "validator_version": GROUNDING_VALIDATOR_VERSION,
                "source_ref": source_ref,
                "evidence": candidate.evidence[:160],
                "source_type": candidate.source_type,
            }
        }
        if identity is not None:
            metadata[METADATA_KEY] = identity.to_metadata()
        return MemoryAction(
            action=CREATE,
            kind=candidate.kind,
            text=candidate.statement,
            reason="hybrid extraction: gated durable conversational content",
            metadata=metadata,
        )

    def _duplicate(self, candidate, source_ref, position, reason):
        self.counters["candidates_duplicate"] += 1
        self._event(
            "memory_candidate_rejected",
            source_ref=source_ref,
            candidate_index=position,
            stage="duplicate",
            reason=f"duplicate: {reason}"[:120],
        )
        return None

    def _identity_for(
        self, candidate: MemoryCandidate
    ) -> SemanticIdentity | None:
        """Semantic identity for an accepted candidate.

        The slot registry normalizer is authoritative when it
        recognizes the stored statement (full confidence, known
        cardinality). Otherwise a conservative generic identity is
        built from the candidate's own structured fields — unknown
        cardinality and sub-1.0 confidence, so slot conflict rules
        can never supersede on it, only deduplicate and coexist.
        """
        identity = self.normalizer.normalize(
            candidate.kind, candidate.statement
        )
        if identity is not None:
            return identity
        if not candidate.attribute or not candidate.value:
            return None
        return SemanticIdentity(
            subject=candidate.subject or "user",
            attribute=candidate.attribute,
            value=candidate.value.strip().lower(),
            display_value=candidate.display_value or candidate.value,
            scope=candidate.scope or "global",
            qualifiers=dict(candidate.qualifiers),
            cardinality=Cardinality.UNKNOWN,
            confidence=min(candidate.confidence, 0.95),
            extraction_method=f"hybrid:{candidate.extraction_method}",
        )
