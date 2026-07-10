"""External evaluation: deterministic proxies and retrieval evidence.

External metrics live in their OWN registry — they are never mixed
with the custom lifecycle registry or its aggregates. Answer-quality
metrics are deterministic PROXIES (labeled ``*_proxy``), never
official LongMemEval evaluation (official scoring uses a GPT-4o
judge). Retrieval evidence uses the official ``answer_session_ids``
relevance oracle, which the official data provides directly.

Normalization for answer proxies (documented, no hidden thresholds):
casefold, collapse whitespace, strip surrounding punctuation.
``normalized_exact_match_proxy`` is equality of normalized strings;
``answer_entity_match_proxy`` is normalized-answer substring presence
in the normalized response; ``abstention_match_proxy`` is deferred in
deterministic offline modes (an echo provider cannot abstain
meaningfully).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class ExternalMetricDefinition:
    name: str
    numerator: str
    denominator: str
    proxy: bool
    description: str

    def to_payload(self) -> dict:
        return {
            "name": self.name,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "proxy": self.proxy,
            "description": self.description,
        }


EXTERNAL_METRICS = (
    ExternalMetricDefinition(
        "answer_session_candidate_rate",
        "cases where an answer-bearing unit appeared among candidates",
        "cases with answer sessions and structured retrieval",
        False,
        "Official answer_session_ids oracle; retrieval reachability.",
    ),
    ExternalMetricDefinition(
        "answer_session_selection_rate",
        "cases where an answer-bearing unit was selected into context",
        "cases with answer sessions and structured retrieval",
        False,
        "Official answer_session_ids oracle; selection quality.",
    ),
    ExternalMetricDefinition(
        "answer_session_mrr",
        "sum of 1/rank of the best-ranked answer-bearing unit",
        "cases with answer sessions and structured retrieval",
        False,
        "Ranking quality against the official evidence sessions.",
    ),
    ExternalMetricDefinition(
        "answer_context_presence_rate",
        "cases where answer-bearing content entered supplied context",
        "cases with answer sessions",
        False,
        "Whether evidence content reached the answer model at all "
        "(full history trivially satisfies this when untruncated).",
    ),
    ExternalMetricDefinition(
        "normalized_exact_match_proxy",
        "responses exactly matching the normalized official answer",
        "evaluated non-abstention cases",
        True,
        "Deterministic proxy; NOT the official GPT-4o judge.",
    ),
    ExternalMetricDefinition(
        "answer_entity_match_proxy",
        "responses containing the normalized official answer",
        "evaluated non-abstention cases",
        True,
        "Deterministic proxy; NOT the official GPT-4o judge.",
    ),
    ExternalMetricDefinition(
        "abstention_match_proxy",
        "abstention cases with an abstaining response",
        "evaluated abstention cases",
        True,
        "Deferred in deterministic offline modes; a live labeled run "
        "is required for meaningful abstention evidence.",
    ),
    ExternalMetricDefinition(
        "external_token_reduction_vs_full_history",
        "full-history context tokens minus system context tokens",
        "full-history context tokens",
        False,
        "Same accounting method across systems within one run.",
    ),
)

_BY_NAME = {m.name: m for m in EXTERNAL_METRICS}


def external_metric(name: str) -> ExternalMetricDefinition:
    if name not in _BY_NAME:
        raise KeyError(f"unknown external metric {name!r}")
    return _BY_NAME[name]


@dataclass(frozen=True)
class ExternalContribution:
    metric: str
    numerator: float
    denominator: float
    applicable: bool = True
    undefined_reason: str | None = None
    evidence: dict = field(default_factory=dict)

    def __post_init__(self):
        external_metric(self.metric)

    def to_payload(self) -> dict:
        definition = external_metric(self.metric)
        return {
            "metric": self.metric,
            "proxy": definition.proxy,
            "applicable": self.applicable,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "undefined_reason": self.undefined_reason,
            "evidence": dict(sorted(self.evidence.items())),
        }


def normalize_answer(text: str) -> str:
    return _WS.sub(" ", text.casefold()).strip().strip(".,!?;: ")


def answer_contributions(case, response: str, structural: bool):
    """Deterministic proxy answer checks. In structural offline mode
    the deterministic echo provider cannot answer, so proxies are
    computed and recorded but flagged structural in evidence; the
    labels make them non-official either way."""
    out = []
    if case.abstention:
        out.append(
            ExternalContribution(
                "abstention_match_proxy",
                0,
                0,
                applicable=False,
                undefined_reason=(
                    "abstention verification requires a live labeled run"
                ),
            )
        )
        return out
    expected = normalize_answer(case.answer)
    actual = normalize_answer(response or "")
    out.append(
        ExternalContribution(
            "normalized_exact_match_proxy",
            1 if actual == expected else 0,
            1,
            evidence={"structural_provider": structural},
        )
    )
    out.append(
        ExternalContribution(
            "answer_entity_match_proxy",
            1 if expected and expected in actual else 0,
            1,
            evidence={"structural_provider": structural},
        )
    )
    return out


def retrieval_contributions(case, candidates, selected_texts, context_text):
    """Retrieval/selection/context evidence against the official
    answer_session_ids oracle. ``candidates`` = ordered
    (rank, session_id, selected) tuples from a structured-retrieval
    system; empty for full-history/stateless systems."""
    out = []
    answer_sessions = set(case.answer_session_ids)
    if not answer_sessions:
        return out
    if candidates:
        answer_ranked = [
            rank
            for rank, session_id, _ in candidates
            if session_id in answer_sessions
        ]
        out.append(
            ExternalContribution(
                "answer_session_candidate_rate",
                1 if answer_ranked else 0,
                1,
            )
        )
        selected_hit = any(
            session_id in answer_sessions
            for _, session_id, selected in candidates
            if selected
        )
        out.append(
            ExternalContribution(
                "answer_session_selection_rate",
                1 if selected_hit else 0,
                1,
            )
        )
        out.append(
            ExternalContribution(
                "answer_session_mrr",
                (1.0 / min(answer_ranked)) if answer_ranked else 0,
                1,
            )
        )
    else:
        for name in (
            "answer_session_candidate_rate",
            "answer_session_selection_rate",
            "answer_session_mrr",
        ):
            out.append(
                ExternalContribution(
                    name,
                    0,
                    0,
                    applicable=False,
                    undefined_reason=(
                        "no structured retrieval for this system"
                    ),
                )
            )
    # Evidence content actually reaching the model, via has_answer turns.
    evidence_texts = [
        turn.content
        for session in case.sessions
        if session.session_id in answer_sessions
        for turn in session.turns
        if turn.has_answer
    ]
    if evidence_texts:
        present = any(t in context_text for t in evidence_texts)
        out.append(
            ExternalContribution(
                "answer_context_presence_rate", 1 if present else 0, 1
            )
        )
    return out


def aggregate_external(records: list[dict]) -> dict:
    """Sum raw numerators/denominators per system and metric."""
    by_system: dict = {}
    for record in records:
        cells = by_system.setdefault(record["system_id"], {})
        for payload in record["contributions"]:
            cell = cells.setdefault(
                payload["metric"],
                {
                    "numerator": 0.0,
                    "denominator": 0.0,
                    "undefined_count": 0,
                    "sample_count": 0,
                    "proxy": payload["proxy"],
                },
            )
            if not payload["applicable"]:
                cell["undefined_count"] += 1
                continue
            cell["numerator"] += payload["numerator"]
            cell["denominator"] += payload["denominator"]
            cell["sample_count"] += 1
    # Token reduction vs full history, synthesized per case.
    fh_tokens = {
        r["question_id"]: r["context_tokens"]
        for r in records
        if r["system_id"] == "full_history"
    }
    for record in records:
        if record["system_id"] == "full_history":
            continue
        cell = by_system.setdefault(record["system_id"], {}).setdefault(
            "external_token_reduction_vs_full_history",
            {
                "numerator": 0.0,
                "denominator": 0.0,
                "undefined_count": 0,
                "sample_count": 0,
                "proxy": False,
            },
        )
        reference = fh_tokens.get(record["question_id"])
        if reference is None:
            cell["undefined_count"] += 1
            continue
        cell["numerator"] += reference - record["context_tokens"]
        cell["denominator"] += reference
        cell["sample_count"] += 1
    for system, cells in by_system.items():
        for name, cell in cells.items():
            cell["value"] = (
                cell["numerator"] / cell["denominator"]
                if cell["denominator"]
                else None
            )
            definition = external_metric(name)
            cell["numerator_definition"] = definition.numerator
            cell["denominator_definition"] = definition.denominator
    return {
        system: dict(sorted(cells.items()))
        for system, cells in sorted(by_system.items())
    }
