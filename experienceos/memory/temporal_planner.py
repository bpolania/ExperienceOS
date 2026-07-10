"""TemporalMemoryPlanner: temporal + provenance metadata on planning.

Phase 9 Prompt 6 planning strategy. Extends the Prompt 2
``SemanticMemoryPlanner`` (rules extraction + conservative semantic
supersession — required so corrections produce validity transitions)
and adds:

- temporal normalization of the SOURCE message (the raw wording holds
  the temporal expressions that stored text may lose), attached as
  additive ``metadata["temporal"]``;
- provenance classification (``metadata["provenance"]``): the standard
  chat path is ``user_asserted``; narrow feature-flagged eligibility
  admits tool-verified results, jointly-confirmed decisions, and
  deterministic derivations — never unconfirmed assistant content;
- historical containment: a historical statement never supersedes a
  current fact (semantic supersedes emitted for a historical-scoped
  create are vetoed so both coexist);
- deterministic reference time: supplied by the runtime via
  ``set_reference_time`` (e.g. a session date) — never a wall clock.

The planner proposes; ExperienceManager validation and the
ExperienceEngine lifecycle stay authoritative. Validity intervals are
derived at read time from supersession links (see
``experienceos.memory.temporal.resolve_validity``) — no store
mutation, no background workers.
"""

from __future__ import annotations

import re
from dataclasses import replace as dc_replace

from experienceos.memory.planner import CREATE, SUPERSEDE, MemoryAction
from experienceos.memory.schema import ExperienceEntry, MemoryKind
from experienceos.memory.semantic_planner import SemanticMemoryPlanner
from experienceos.memory.temporal import (
    PROVENANCE_KEY,
    PROVENANCE_VERSION,
    TEMPORAL_KEY,
    TEMPORAL_VERSION,
    ProvenanceMetadata,
    SourceType,
    TemporalMetadata,
    TemporalNormalizer,
    TemporalScope,
)

ASSISTANT_INGESTION_POLICY = (
    "explicit_confirmation_or_tool_or_deterministic_derivation-1"
)

# Narrow, auditable confirmation patterns. Ambiguity means no memory.
_CONFIRMATION = re.compile(
    r"^(?:yes|yep|confirmed|sounds good|ok(?:ay)?|great|perfect"
    r"|that works)[,.! ]*"
    r"(?:book|do|go with|use|schedule|that|it|please)?[,.! ]*"
    r"(?:that|it|one)?[.! ]*$",
    re.IGNORECASE,
)
_ASSISTANT_PROPOSAL = re.compile(
    r"\b(?:we(?:'|w)?ll|we will|i(?:'|w)?ll|let'?s|i suggest we|how about we)\s+"
    r"(?:use|book|take|go with|schedule|plan on)\s+"
    r"(?P<what>[^.!?\n;]+)",
    re.IGNORECASE,
)
_AMBIGUOUS_PROPOSAL = re.compile(r"\bor\b|\boption\b|\beither\b", re.IGNORECASE)

# Deterministic derivation: explicit start date + explicit duration.
_TRIP_DERIVATION = re.compile(
    r"\b(?P<subject>trip|conference|visit|stay)\s+"
    r"(?:begins|starts)\s+(?:on\s+)?(?P<start>\w+\s+\d{1,2}(?:,\s*\d{4})?)"
    r"\b.*?\blasts?\s+(?P<count>\w+)\s+days?\b",
    re.IGNORECASE,
)
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Narrow historical-fact forms (v1 extracts present tense only; past
# state is a temporal need). Stored past-tense text never matches the
# semantic registry's current-fact patterns, so historical statements
# structurally coexist with current facts.
_HISTORICAL_FACT = re.compile(
    r"\bmy\s+(?P<subject>[a-z][a-z ]{0,40}?)\s+(?:was|used to be)\s+"
    r"(?P<value>[^.!?\n;]+)",
    re.IGNORECASE,
)
_HISTORICAL_LIVED = re.compile(
    r"\bi\s+used\s+to\s+live\s+(?:in|near)\s+(?P<city>[^.!?\n;,]+)",
    re.IGNORECASE,
)
_TRAILING_TIME = re.compile(
    r"[\s,]*(?:back\s+)?(?:in|during)\s+(?:19|20)\d{2}\s*$"
    r"|[\s,]*(?:a few|several)\s+years\s+ago\s*$",
    re.IGNORECASE,
)


class TemporalMemoryPlanner(SemanticMemoryPlanner):
    """Semantic planning plus temporal/provenance metadata."""

    temporal_version = TEMPORAL_VERSION
    provenance_version = PROVENANCE_VERSION

    def __init__(
        self,
        normalizer=None,
        temporal_normalizer: TemporalNormalizer | None = None,
        assistant_ingestion: bool = False,
    ):
        super().__init__(normalizer=normalizer)
        self.temporal_normalizer = temporal_normalizer or TemporalNormalizer()
        self.assistant_ingestion = assistant_ingestion
        self.reference_time: str | None = None
        self._turn_seq = 0
        self._last_assistant: dict[tuple, str] = {}
        self._queued_tool_results: list[tuple] = []
        self._pending_events: list[tuple] = []
        self.counters = {
            "turns": 0,
            "creates_with_temporal": 0,
            "creates_with_provenance": 0,
            "temporal_expressions_detected": 0,
            "temporal_expressions_unresolved": 0,
            "historical_supersede_vetoes": 0,
            "future_memories_created": 0,
            "tool_verified_accepted": 0,
            "jointly_confirmed_accepted": 0,
            "derivations_created": 0,
            "assistant_candidates_rejected": 0,
            "assistant_notes_seen": 0,
        }

    # -- runtime seams --------------------------------------------------------

    def set_reference_time(self, reference: str | None) -> None:
        """Deterministic runtime reference date (ISO); never wall clock."""
        self.reference_time = reference

    def note_assistant_message(self, user_id, session_id, text) -> None:
        """Bounded assistant context for later explicit confirmation.
        A no-op unless assistant ingestion is enabled."""
        if not self.assistant_ingestion:
            return
        self.counters["assistant_notes_seen"] += 1
        self._last_assistant[(user_id, session_id)] = text[:500]

    def queue_tool_result(self, tool: str, payload: dict) -> None:
        """Structured trusted tool result for the next planning turn.
        Requires ``fact`` text grounded in the payload; free-form
        assistant paraphrase is not eligible."""
        self._queued_tool_results.append((tool, dict(payload)))

    def drain_extraction_events(self):
        drained, self._pending_events = self._pending_events, []
        return drained

    def _event(self, event_type, **payload):
        if len(self._pending_events) < 64:
            self._pending_events.append((event_type, payload))

    def summary(self) -> dict:
        return {
            **self.counters,
            "temporal_metadata_version": TEMPORAL_VERSION,
            "provenance_version": PROVENANCE_VERSION,
            "assistant_ingestion_enabled": self.assistant_ingestion,
            "assistant_ingestion_policy": ASSISTANT_INGESTION_POLICY,
        }

    # -- planning ---------------------------------------------------------------

    def plan_memory_actions(self, user_id, session_id, message, existing=None):
        existing = existing or []
        self._turn_seq += 1
        self.counters["turns"] += 1
        source_ref = f"{session_id}:{self._turn_seq}"

        actions = super().plan_memory_actions(
            user_id, session_id, message, existing
        )
        actions = self._apply_temporal(actions, message, source_ref)
        actions.extend(self._tool_actions(source_ref, session_id))
        confirmation = self._confirmation_action(
            user_id, session_id, message, source_ref
        )
        if confirmation is not None:
            actions.append(confirmation)
        derivation = self._derivation_action(message, source_ref, session_id)
        if derivation is not None:
            actions.append(derivation)
        actions.extend(
            self._historical_fact_actions(
                message, source_ref, existing, actions
            )
        )
        return actions

    # -- temporal + provenance on ordinary creates --------------------------------

    def _apply_temporal(self, actions, message, source_ref):
        temporal = self.temporal_normalizer.normalize(
            message, self.reference_time
        )
        if temporal is None and self.reference_time is not None:
            # No temporal expression, but the observation date itself
            # is known and auditable — record it, nothing more.
            temporal = TemporalMetadata(
                source_session_date=self.reference_time,
                reference_time=self.reference_time,
            )
        if temporal is not None and (
            temporal.time_expression
            or temporal.temporal_scope != TemporalScope.UNKNOWN
        ):
            self.counters["temporal_expressions_detected"] += 1
            if temporal.uncertainty_reason:
                self.counters["temporal_expressions_unresolved"] += 1
                self._event(
                    "memory_temporal_unresolved",
                    source_ref=source_ref,
                    expression=temporal.time_expression,
                    reason=temporal.uncertainty_reason,
                )
            else:
                self._event(
                    "memory_temporal_detected",
                    source_ref=source_ref,
                    expression=temporal.time_expression,
                    event_time=temporal.event_time,
                    precision=temporal.time_precision,
                    scope=temporal.temporal_scope,
                    reference=self.reference_time,
                )
        historical = (
            temporal is not None
            and temporal.temporal_scope == TemporalScope.HISTORICAL
        )
        vetoed_targets = set()
        result = []
        for action in actions:
            if action.action == CREATE:
                metadata = dict(action.metadata or {})
                if temporal is not None:
                    metadata[TEMPORAL_KEY] = temporal.to_metadata()
                    self.counters["creates_with_temporal"] += 1
                    if temporal.temporal_scope == TemporalScope.FUTURE:
                        self.counters["future_memories_created"] += 1
                metadata[PROVENANCE_KEY] = ProvenanceMetadata(
                    source_type=SourceType.USER_ASSERTED,
                    source_role="user",
                    source_message_ref=source_ref,
                    source_session_id=source_ref.rsplit(":", 1)[0],
                    source_session_date=self.reference_time,
                ).to_metadata()
                self.counters["creates_with_provenance"] += 1
                if historical and action.replaces:
                    # A historical statement coexists; it never
                    # replaces the current fact.
                    vetoed_targets.add(action.replaces)
                    action = dc_replace(action, replaces=None, reason=None)
                    self.counters["historical_supersede_vetoes"] += 1
                result.append(dc_replace(action, metadata=metadata))
            else:
                result.append(action)
        if vetoed_targets:
            result = [
                a for a in result
                if not (
                    a.action == SUPERSEDE and a.memory_id in vetoed_targets
                )
            ]
            self._event(
                "memory_historical_coexistence",
                source_ref=source_ref,
                vetoed_targets=len(vetoed_targets),
            )
        return result

    # -- historical facts (past state, coexists with current) ---------------------------

    def _historical_fact_actions(
        self, message, source_ref, existing, planned
    ):
        statements = []
        for match in _HISTORICAL_FACT.finditer(message):
            subject = match.group("subject").strip()
            value = _TRAILING_TIME.sub(
                "", match.group("value").strip().rstrip(".!?,")
            ).strip()
            if value and len(subject.split()) <= 4:
                statements.append(
                    f"{subject[0].upper()}{subject[1:]} was {value}."
                )
        for match in _HISTORICAL_LIVED.finditer(message):
            city = _TRAILING_TIME.sub(
                "", match.group("city").strip().rstrip(".!?,")
            ).strip()
            if city:
                statements.append(f"Lived in {city}.")
        if not statements:
            return []
        temporal = self.temporal_normalizer.normalize(
            message, self.reference_time
        ) or TemporalMetadata()
        temporal = dc_replace(
            temporal,
            temporal_scope=TemporalScope.HISTORICAL,
            source_session_date=self.reference_time,
            reference_time=self.reference_time,
        )
        known = {a.text for a in planned if a.action == CREATE}
        known |= {e.text for e in existing}
        actions = []
        for statement in statements:
            if statement in known:
                continue
            known.add(statement)
            self.counters["creates_with_temporal"] += 1
            self.counters["creates_with_provenance"] += 1
            actions.append(
                MemoryAction(
                    action=CREATE, kind=MemoryKind.FACT, text=statement,
                    reason="historical statement (coexists with current)",
                    metadata={
                        TEMPORAL_KEY: temporal.to_metadata(),
                        PROVENANCE_KEY: ProvenanceMetadata(
                            source_type=SourceType.USER_ASSERTED,
                            source_message_ref=source_ref,
                            source_session_id=source_ref.rsplit(":", 1)[0],
                            source_session_date=self.reference_time,
                        ).to_metadata(),
                    },
                )
            )
        return actions

    # -- tool-verified path -----------------------------------------------------------

    def _tool_actions(self, source_ref, session_id):
        actions = []
        queued, self._queued_tool_results = self._queued_tool_results, []
        for tool, payload in queued:
            fact = payload.get("fact")
            if not self.assistant_ingestion or not isinstance(fact, str) \
                    or not fact.strip():
                self.counters["assistant_candidates_rejected"] += 1
                self._event(
                    "memory_tool_result_rejected",
                    source_ref=source_ref, tool=tool,
                    reason="ingestion disabled or unstructured payload",
                )
                continue
            # Grounding: the fact must be composed of OTHER payload
            # values — a free-text fact never grounds itself.
            grounding = " ".join(
                str(v)
                for k, v in payload.items()
                if k != "fact" and isinstance(v, (str, int))
            ).lower()
            content_words = [
                w for w in re.findall(r"[a-z0-9]+", fact.lower())
                if len(w) > 3
            ]
            if not all(w in grounding for w in content_words):
                self.counters["assistant_candidates_rejected"] += 1
                self._event(
                    "memory_tool_result_rejected",
                    source_ref=source_ref, tool=tool,
                    reason="fact not grounded in tool payload",
                )
                continue
            temporal = self.temporal_normalizer.normalize(
                fact, self.reference_time
            )
            metadata = {
                PROVENANCE_KEY: ProvenanceMetadata(
                    source_type=SourceType.TOOL_VERIFIED,
                    source_role="tool",
                    source_message_ref=source_ref,
                    source_session_id=session_id,
                    source_session_date=self.reference_time,
                    confirmation_status="confirmed",
                    confirmed_by="tool",
                    source_tool=tool,
                    source_tool_result_ref=str(
                        payload.get("result_ref", "")
                    ) or None,
                ).to_metadata(),
            }
            if temporal is not None:
                metadata[TEMPORAL_KEY] = temporal.to_metadata()
            self.counters["tool_verified_accepted"] += 1
            self._event(
                "memory_tool_result_accepted",
                source_ref=source_ref, tool=tool, fact=fact[:120],
            )
            actions.append(
                MemoryAction(
                    action=CREATE, kind=MemoryKind.FACT, text=fact.strip(),
                    reason=f"tool-verified result from {tool}",
                    metadata=metadata,
                )
            )
        return actions

    # -- jointly-confirmed path ---------------------------------------------------------

    def _confirmation_action(self, user_id, session_id, message, source_ref):
        if not self.assistant_ingestion:
            return None
        if not _CONFIRMATION.match(message.strip()):
            return None
        proposal = self._last_assistant.get((user_id, session_id))
        if not proposal:
            return None
        match = _ASSISTANT_PROPOSAL.search(proposal)
        if not match or _AMBIGUOUS_PROPOSAL.search(proposal):
            # Two options, hedged phrasing, or no recognizable
            # proposal: ambiguous confirmation creates no memory.
            self.counters["assistant_candidates_rejected"] += 1
            self._event(
                "memory_confirmation_rejected",
                source_ref=source_ref,
                reason="ambiguous or unrecognized proposal",
            )
            return None
        what = match.group("what").strip().rstrip(".!?")
        temporal = self.temporal_normalizer.normalize(
            proposal, self.reference_time
        )
        metadata = {
            PROVENANCE_KEY: ProvenanceMetadata(
                source_type=SourceType.JOINTLY_CONFIRMED,
                source_role="assistant",
                source_message_ref=source_ref,
                source_session_id=session_id,
                source_session_date=self.reference_time,
                derivation_refs=(
                    f"{session_id}:assistant", source_ref,
                ),
                confirmation_status="confirmed",
                confirmed_by="user",
            ).to_metadata(),
        }
        if temporal is not None:
            metadata[TEMPORAL_KEY] = temporal.to_metadata()
        self.counters["jointly_confirmed_accepted"] += 1
        self._event(
            "memory_confirmation_linked",
            source_ref=source_ref, decision=what[:120],
        )
        self._last_assistant.pop((user_id, session_id), None)
        return MemoryAction(
            action=CREATE, kind=MemoryKind.FACT,
            text=f"Confirmed plan: {what}.",
            reason="assistant proposal explicitly confirmed by user",
            metadata=metadata,
        )

    # -- deterministic derivation ----------------------------------------------------------

    def _derivation_action(self, message, source_ref, session_id):
        match = _TRIP_DERIVATION.search(message)
        if not match:
            return None
        start = self.temporal_normalizer.normalize(
            match.group("start"), self.reference_time
        )
        if start is None or start.event_time is None or len(
            start.event_time
        ) != 10:
            return None  # day precision required; never invent it
        count = _NUM_WORDS.get(match.group("count").lower())
        if count is None:
            try:
                count = int(match.group("count"))
            except ValueError:
                return None
        from datetime import date, timedelta

        end = (
            date.fromisoformat(start.event_time) + timedelta(days=count)
        ).isoformat()
        subject = match.group("subject").lower()
        metadata = {
            TEMPORAL_KEY: TemporalMetadata(
                event_time=end,
                valid_from=start.event_time,
                valid_until=end,
                temporal_scope=TemporalScope.FUTURE,
                source_session_date=self.reference_time,
                time_precision="day",
                time_expression=match.group(0)[:80],
                reference_time=self.reference_time,
            ).to_metadata(),
            PROVENANCE_KEY: ProvenanceMetadata(
                source_type=SourceType.SYSTEM_OBSERVED,
                source_role="system",
                source_message_ref=source_ref,
                source_session_id=session_id,
                source_session_date=self.reference_time,
                derivation_refs=(source_ref,),
                confirmation_status="derived",
                confirmed_by=None,
            ).to_metadata(),
        }
        self.counters["derivations_created"] += 1
        self._event(
            "memory_derivation_created",
            source_ref=source_ref, derived_end=end,
        )
        return MemoryAction(
            action=CREATE, kind=MemoryKind.FACT,
            text=f"{subject.capitalize()} ends on {end}.",
            reason="deterministic derivation from user-provided dates",
            metadata=metadata,
        )
