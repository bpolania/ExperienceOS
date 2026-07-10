"""Official LongMemEval record schema and external-case normalization.

Source (verified 2026-07-10 against the official repository
github.com/xiaowu0162/LongMemEval and the official dataset
huggingface.co/datasets/xiaowu0162/longmemeval-cleaned, revision
98d7416c24c778c2fee6e6f3006e7a073259d48f, both MIT-licensed):

Each of the 500 official instances carries: question_id,
question_type (single-session-user / single-session-assistant /
single-session-preference / temporal-reasoning / knowledge-update /
multi-session), question, answer, question_date,
haystack_session_ids, haystack_dates, haystack_sessions (ordered
user/assistant turns, evidence turns optionally marked
has_answer=true), and answer_session_ids (evidence sessions).
Abstention instances are marked by an ``_abs`` suffix on question_id.

External cases are normalized into a separate representation — never
into custom lifecycle scenarios — preserving session boundaries, turn
order, timestamps, categories, answers, and abstention.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BENCHMARK_NAME = "longmemeval"
REQUIRED_DISPLAY_LABEL = "LongMemEval 50-case stratified subset"

DATASET_VARIANTS = ("oracle", "s_cleaned", "m_cleaned", "synthetic")

OFFICIAL_TYPES = frozenset(
    (
        "single-session-user",
        "single-session-assistant",
        "single-session-preference",
        "temporal-reasoning",
        "knowledge-update",
        "multi-session",
    )
)

REQUIRED_FIELDS = (
    "question_id",
    "question_type",
    "question",
    "answer",
    "question_date",
    "haystack_session_ids",
    "haystack_dates",
    "haystack_sessions",
    "answer_session_ids",
)


class InvalidExternalRecord(ValueError):
    """Raised when an official-shape record fails validation."""


@dataclass(frozen=True)
class ExternalTurn:
    role: str
    content: str
    has_answer: bool = False


@dataclass(frozen=True)
class ExternalSession:
    session_id: str
    date: str
    turns: tuple[ExternalTurn, ...]


@dataclass(frozen=True)
class ExternalCase:
    """Normalized external benchmark case (separate from the custom
    lifecycle schema; no lifecycle oracle fields are fabricated)."""

    benchmark: str
    question_id: str
    category: str  # subset category, not the raw official type
    official_type: str
    question: str
    question_date: str
    answer: str
    abstention: bool
    sessions: tuple[ExternalSession, ...]
    answer_session_ids: tuple[str, ...]
    dataset_variant: str
    notes: str = ""

    @property
    def history_turn_count(self) -> int:
        return sum(len(s.turns) for s in self.sessions)


def is_abstention(question_id: str) -> bool:
    return str(question_id).endswith("_abs")


def validate_official_record(record: dict, index: int = -1) -> None:
    if not isinstance(record, dict):
        raise InvalidExternalRecord(
            f"record {index}: expected object, got {type(record).__name__}"
        )
    label = record.get("question_id", f"<record {index}>")
    for field_name in REQUIRED_FIELDS:
        if field_name not in record:
            raise InvalidExternalRecord(
                f"{label}: missing official field {field_name!r}"
            )
    if record["question_type"] not in OFFICIAL_TYPES:
        raise InvalidExternalRecord(
            f"{label}: unknown question_type {record['question_type']!r}"
        )
    sessions = record["haystack_sessions"]
    session_ids = record["haystack_session_ids"]
    dates = record["haystack_dates"]
    if not isinstance(sessions, list) or not sessions:
        raise InvalidExternalRecord(f"{label}: haystack_sessions missing")
    if len(sessions) != len(session_ids) or len(sessions) != len(dates):
        raise InvalidExternalRecord(
            f"{label}: session/id/date arity mismatch "
            f"({len(sessions)}/{len(session_ids)}/{len(dates)})"
        )
    for turn_list in sessions:
        if not isinstance(turn_list, list):
            raise InvalidExternalRecord(
                f"{label}: session must be a list of turns"
            )
        for turn in turn_list:
            if not isinstance(turn, dict) or "role" not in turn or (
                "content" not in turn
            ):
                raise InvalidExternalRecord(
                    f"{label}: malformed turn (role/content required)"
                )


def normalize_record(
    record: dict, category: str, dataset_variant: str
) -> ExternalCase:
    """Official record -> ExternalCase; preserves order, timestamps,
    categories, answers, and abstention. Never mutates the source."""
    validate_official_record(record)
    sessions = []
    for session_id, date, turns in zip(
        record["haystack_session_ids"],
        record["haystack_dates"],
        record["haystack_sessions"],
    ):
        sessions.append(
            ExternalSession(
                session_id=str(session_id),
                date=str(date),
                turns=tuple(
                    ExternalTurn(
                        role=turn["role"],
                        content=turn["content"],
                        has_answer=bool(turn.get("has_answer", False)),
                    )
                    for turn in turns
                ),
            )
        )
    return ExternalCase(
        benchmark=BENCHMARK_NAME,
        question_id=str(record["question_id"]),
        category=category,
        official_type=record["question_type"],
        question=record["question"],
        question_date=str(record["question_date"]),
        answer=str(record["answer"]),
        abstention=is_abstention(record["question_id"]),
        sessions=tuple(sessions),
        answer_session_ids=tuple(
            str(s) for s in record["answer_session_ids"]
        ),
        dataset_variant=dataset_variant,
    )
