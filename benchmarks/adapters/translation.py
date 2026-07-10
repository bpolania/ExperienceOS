"""Deterministic translation from ExperienceOS lifecycle events to
benchmark evidence records.

The adapter observes the public event stream and translates; it never
reconstructs lifecycle decisions from response text and never invents
values production events omit (absent fields stay None/empty per the
contract). Event order is preserved as emitted.
"""

from __future__ import annotations

from datetime import datetime

from benchmarks.contract import (
    AppliedActionRecord,
    CandidateRecord,
    ContextAccounting,
    FallbackRecord,
    LatencyRecord,
    ProposalRecord,
    RejectedActionRecord,
    TurnEvidence,
)

APPROXIMATION_METHOD = "approximation"


def _tokens(chars: int) -> int:
    return -(-chars // 4)  # ceil(chars / 4)


def _ts(event) -> datetime:
    return event.timestamp


def _stage_ms(events_by_type, start_type, end_type) -> float | None:
    start = events_by_type.get(start_type)
    end = events_by_type.get(end_type)
    if start is None or end is None:
        return None
    return (_ts(end) - _ts(start)).total_seconds() * 1000.0


def translate_turn(
    *,
    turn_index: int,
    session_id: str,
    message: str,
    response: str,
    events: list,
    end_to_end_ms: float,
) -> tuple[TurnEvidence, ContextAccounting]:
    """Translate one chat turn's event slice into TurnEvidence plus
    the turn's context accounting."""
    proposals: list[ProposalRecord] = []
    applied: list[AppliedActionRecord] = []
    rejected: list[RejectedActionRecord] = []
    fallbacks: list[FallbackRecord] = []
    candidates: list[CandidateRecord] = []
    context_contents: list[str] = []
    compressed_summaries: list[dict] = []
    first_by_type: dict = {}

    for event in events:
        event_type = str(event.type)
        first_by_type.setdefault(event_type, event)
        payload = event.payload or {}

        if event_type == "context_built":
            context_contents = [
                m.get("content", "") for m in payload.get("context_messages", [])
            ]
            compressed_summaries = list(payload.get("compressed_summaries", []))
            for record in payload.get("selection_records", []):
                candidates.append(
                    CandidateRecord(
                        memory_id=record.get("memory_id", ""),
                        text=record.get("text", ""),
                        rank=int(record.get("rank", 0)),
                        score=float(record.get("score", 0)),
                        selected=bool(record.get("selected", False)),
                        reason=record.get("reason", "") or "",
                    )
                )
        elif event_type == "memory_action_planned":
            for action in payload.get("planned_actions", []):
                proposals.append(
                    ProposalRecord(
                        action=action.get("action", ""),
                        kind=action.get("kind"),
                        text=action.get("text"),
                        target_memory_id=action.get("memory_id"),
                        replaces=action.get("replaces"),
                        confidence=action.get("confidence"),
                        explanation=action.get("explanation") or None,
                        decision_source=action.get("decision_source"),
                    )
                )
            for action in payload.get("rejected_actions", []):
                rejected.append(
                    RejectedActionRecord(
                        action=action.get("action", ""),
                        rejected_reason=action.get(
                            "rejected_reason", "unknown"
                        ),
                        text=action.get("text"),
                        target_memory_id=action.get("memory_id"),
                    )
                )
            policy = payload.get("policy") or {}
            if policy.get("fallback_used"):
                fallbacks.append(
                    FallbackRecord(
                        reason=policy.get("fallback_reason") or "unknown",
                        turn_index=turn_index,
                    )
                )
        elif event_type == "memory_created":
            applied.append(
                AppliedActionRecord(
                    action="create",
                    memory_id=payload.get("memory_id", ""),
                    kind=payload.get("kind"),
                    text=payload.get("text"),
                    replaces=payload.get("replaces"),
                )
            )
        elif event_type == "memory_superseded":
            applied.append(
                AppliedActionRecord(
                    action="supersede",
                    memory_id=payload.get("memory_id", ""),
                    kind=payload.get("kind"),
                    text=payload.get("text"),
                )
            )
        elif event_type == "memory_forgotten":
            applied.append(
                AppliedActionRecord(
                    action="forget",
                    memory_id=payload.get("memory_id", ""),
                    kind=payload.get("kind"),
                    text=payload.get("text"),
                )
            )

    # The provider receives the built context plus the user message.
    provider_messages = [*context_contents, message]
    # Message 0 is the static system instruction; everything else in
    # the built context is rendered experience (memory context).
    memory_chars = sum(len(c) for c in context_contents[1:])
    total_chars = sum(len(c) for c in provider_messages)

    accounting = ContextAccounting(
        method=APPROXIMATION_METHOD,
        total_context_tokens=_tokens(total_chars),
        memory_context_tokens=_tokens(memory_chars),
        total_context_chars=total_chars,
        memory_context_chars=memory_chars,
        selected_memory_count=sum(1 for c in candidates if c.selected),
        candidate_memory_count=len(candidates),
        context_budget=0,  # filled by the adapter, which knows the case
        compressed_summary_count=len(compressed_summaries),
        compression_saved_chars=sum(
            int(s.get("saved_chars", 0)) for s in compressed_summaries
        ),
    )

    latencies = [LatencyRecord("end_to_end", end_to_end_ms)]
    for stage, start_type, end_type in (
        ("retrieval", "context_requested", "context_built"),
        ("memory_decision", "context_built", "memory_action_planned"),
        ("response", "memory_action_planned", "response_returned"),
    ):
        value = _stage_ms(first_by_type, start_type, end_type)
        if value is not None:
            latencies.append(LatencyRecord(stage, value))

    evidence = TurnEvidence(
        turn_index=turn_index,
        session_id=session_id,
        message=message,
        proposals=tuple(proposals),
        applied_actions=tuple(applied),
        rejected_actions=tuple(rejected),
        fallbacks=tuple(fallbacks),
        candidates=tuple(candidates),
        context_messages=tuple(provider_messages),
        response=response,
        latencies=tuple(latencies),
    )
    return evidence, accounting
