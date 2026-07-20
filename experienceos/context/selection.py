"""Coverage-aware context selection over scored retrieval candidates.

The final-selection layer. Retrieval generates and scores
lifecycle-filtered active candidates; this module chooses the final
bounded subset so the same K and token budget carry complementary,
non-redundant, source-diverse experience instead of several copies of
the strongest facet:

    query facets (deterministic, from the query and structured
    metadata only)
    → candidate facet projection (matched evidence + semantic identity
      + domain + kind + source session)
    → iterative maximal-marginal-relevance-style utility
      (base relevance + coverage gains − redundancy/conflict penalties)
    → deterministic bounded selection with documented tie-breaking

Principles: retrieval relevance stays the
foundation of utility; the strongest direct match normally stays
first; diversity without relevance earns nothing; source-session
diversity is a bounded bonus, never a quota; multi-valued facts are
complementary while paraphrases are redundant; unresolved active
conflicts are warned about, never presented as diversity; selection
never pads with zero-value memories, never exceeds K or the token
budget, and never mutates memory state.

No benchmark oracle data (scenario IDs, expected answers, answer
sessions, gold relevance) is referenced anywhere in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from experienceos.context.retrieval import (
    ALIAS_CANONICAL,
    ALIAS_CLASSES,
    QueryProfile,
)
from experienceos.memory.schema import MemoryKind
from experienceos.memory.semantic import METADATA_KEY

SELECTION_STRATEGY_VERSION = "1"
FACET_EXTRACTOR_VERSION = "1"
COVERAGE_WEIGHTS_VERSION = "1"

# Explicit, versioned, provider-independent, scenario-agnostic weights.
# Tuned on phase9_dev fixtures only — never on frozen scenario IDs.
COVERAGE_WEIGHTS = {
    "base_relevance": 1.0,  # retrieval final score, untouched
    "facet_gain": 0.6,  # per newly covered query-relevant facet
    "attribute_gain": 0.8,  # first coverage of a semantic attribute
    "entity_gain": 0.5,  # first coverage of a matched entity
    "value_complement": 0.7,  # new value under a multi-valued attribute
    "source_diversity": 0.4,  # new session adding new facets (bounded)
    "instruction_gain": 0.3,  # durable instruction applicable to query
    "confidence_gain": 0.1,
    "token_efficiency": 0.15,  # small; never overwhelms relevance
    "redundancy_penalty": 1.2,  # per redundancy signal (bounded below)
    "conflict_penalty": 2.0,  # unresolved same-slot conflict vs selected
}

_MULTI_FACET_CUES = re.compile(
    r"\b(?:and|also|plus|as well as|everything|all of)\b"
    r"|\bwhat do you know\b|\btell me about me\b",
    re.IGNORECASE,
)
_MULTI_VALUE_CUES = re.compile(
    r"\b(?:which|what|list)\b.*\b(?:languages|preferences|things|tools"
    r"|facts|memories|details)\b",
    re.IGNORECASE,
)

_NEAR_DUPLICATE_JACCARD = 0.8


# --------------------------------------------------------------------------
# Query facets
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryFacets:
    """Deterministic representation of what a query appears to request."""

    facets: tuple  # ordered "type:value" strings
    multi_facet: bool
    multi_valued: bool
    version: str = FACET_EXTRACTOR_VERSION


def extract_query_facets(query: QueryProfile) -> QueryFacets:
    """Facets from the query text and the transparent alias registry
    only — never from benchmark answers or scenario metadata. A query
    with one clear request yields one or few facets."""
    facets: list[str] = []
    for token in sorted(query.tokens):
        facets.append(f"token:{token}")
    for phrase in sorted(query.phrases | query.entities):
        facets.append(f"entity:{phrase}")
    for klass in ALIAS_CLASSES:
        if query.tokens & klass:
            facets.append(f"attribute:{ALIAS_CANONICAL[klass]}")
    for tag in query.tags:
        facets.append(f"domain:{tag}")
    attribute_count = sum(1 for f in facets if f.startswith("attribute:"))
    entity_count = sum(1 for f in facets if f.startswith("entity:"))
    multi_facet = bool(
        _MULTI_FACET_CUES.search(query.text)
        or attribute_count >= 2
        or entity_count >= 2
    )
    multi_valued = bool(_MULTI_VALUE_CUES.search(query.text))
    return QueryFacets(
        facets=tuple(facets),
        multi_facet=multi_facet,
        multi_valued=multi_valued,
    )


# --------------------------------------------------------------------------
# Candidate facets
# --------------------------------------------------------------------------


def _identity(candidate) -> dict:
    stored = candidate.memory.metadata.get(METADATA_KEY)
    return stored if isinstance(stored, dict) else {}


def candidate_facets(candidate) -> tuple:
    """Facets a candidate can cover, grounded in the query evidence it
    matched and its own structured metadata."""
    facets: list[str] = []
    for token in candidate.matched_tokens:
        facets.append(f"token:{token}")
    for phrase in sorted(
        set(candidate.matched_phrases) | set(candidate.matched_entities)
    ):
        facets.append(f"entity:{phrase}")
    identity = _identity(candidate)
    attribute = identity.get("attribute")
    if attribute:
        facets.append(f"attribute:{attribute}")
        value = identity.get("value")
        if value:
            facets.append(f"value:{attribute}={value}")
    scope = identity.get("scope")
    if scope and scope != "global":
        facets.append(f"scope:{scope}")
    for domain in candidate.matched_domains:
        facets.append(f"domain:{domain}")
    facets.append(f"kind:{candidate.memory.kind}")
    return tuple(facets)


def _slot(candidate) -> tuple | None:
    identity = _identity(candidate)
    attribute = identity.get("attribute")
    if not attribute:
        return None
    return (
        identity.get("subject", "user"),
        attribute,
        identity.get("scope", "global"),
    )


def _source_session(candidate) -> str:
    return candidate.memory.source_session_id or ""


def redundancy_signals(candidate, selected: list) -> tuple:
    """Deterministic redundancy signals of a candidate against the
    already-selected set. Multi-valued same-attribute values are
    complementary, never redundant."""
    signals: list[str] = []
    identity = _identity(candidate)
    tokens = set(candidate.normalized_tokens)
    evidence = set(candidate.matched_tokens)
    for chosen in selected:
        chosen_identity = _identity(chosen)
        # Same semantic slot and value: near-certain paraphrase.
        slot, chosen_slot = _slot(candidate), _slot(chosen)
        if slot is not None and slot == chosen_slot:
            if identity.get("cardinality") == "multi" and identity.get(
                "value"
            ) != chosen_identity.get("value"):
                continue  # complementary multi-valued fact
            if identity.get("value") == chosen_identity.get("value"):
                signals.append("same_slot_value")
                continue
            signals.append("conflicting_slot")  # handled as conflict
            continue
        chosen_tokens = set(chosen.normalized_tokens)
        union = tokens | chosen_tokens
        if union:
            jaccard = len(tokens & chosen_tokens) / len(union)
            if jaccard >= _NEAR_DUPLICATE_JACCARD:
                signals.append("near_duplicate_text")
                continue
        if evidence and evidence == set(chosen.matched_tokens):
            signals.append("same_matched_evidence")
    return tuple(signals)


# --------------------------------------------------------------------------
# Selection contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionRequest:
    """Bounded final-selection input: the scored ACTIVE
    candidate pool only. Never carries expected answers, answer-session
    IDs, scenario IDs, categories, or inactive records."""

    query: QueryProfile
    candidates: tuple  # positive-relevance RetrievalCandidate, ranked
    k: int
    token_budget: int | None = None
    session_id: str = ""
    temporal_mode: str = "current"  # current|historical|as_of|timeline
    strategy_version: str = SELECTION_STRATEGY_VERSION


@dataclass
class SelectionStep:
    """Audit record for one selected candidate."""

    memory_id: str
    retrieval_rank: int
    base_score: float
    step: int
    utility: float
    new_facets: tuple
    redundancy_penalty: float
    source_diversity_gain: float
    instruction_gain: float
    confidence_gain: float
    token_efficiency_gain: float
    conflict_warning: bool
    reason: str


@dataclass
class SelectionResult:
    selected: list = field(default_factory=list)  # RetrievalCandidate
    steps: list = field(default_factory=list)  # SelectionStep
    skipped: dict = field(default_factory=dict)  # memory_id -> reason
    covered_facets: tuple = ()
    query_facets: tuple = ()
    conflict_groups: int = 0
    stopped_reason: str = "k_reached"
    selected_token_estimate: int = 0
    k: int = 0
    k_compliant: bool = True
    budget_compliant: bool = True
    strategy: str = "coverage_selection"
    strategy_version: str = SELECTION_STRATEGY_VERSION
    weights_version: str = COVERAGE_WEIGHTS_VERSION


class ContextSelectionStrategy(Protocol):
    """Provider-independent final-selection seam."""

    strategy: str
    strategy_version: str

    def select(self, request: SelectionRequest) -> SelectionResult:
        ...


# --------------------------------------------------------------------------
# Coverage-aware iterative selection
# --------------------------------------------------------------------------


class CoverageSelectionStrategy:
    """Deterministic MMR-style selection over scored active candidates.

    Tie-breaking (documented order):

    1. coverage utility, descending
    2. newly covered facet count, descending
    3. base retrieval score, descending
    4. phrase+entity score, descending
    5. memory-kind priority (instruction > fact > preference)
    6. confidence, descending
    7. token estimate, ascending
    8. retrieval rank, ascending (stable creation-ordered)

    Rank is unique per candidate, so ordering never depends on runtime
    UUIDs, wall-clock values, or dict ordering. Repeated runs produce
    identical selections and diagnostics.
    """

    strategy = "coverage_selection"
    strategy_version = SELECTION_STRATEGY_VERSION

    def __init__(self, weights: dict | None = None):
        self.weights = dict(weights or COVERAGE_WEIGHTS)
        self.counters = {
            "selections": 0,
            "candidates_considered": 0,
            "selected_total": 0,
            "selected_redundant": 0,
            "selected_with_conflict_warning": 0,
            "skipped_redundant": 0,
            "skipped_no_new_coverage": 0,
            "skipped_not_top_k": 0,
            "skipped_token_budget": 0,
            "stopped_no_positive_utility": 0,
            "query_facets_total": 0,
            "query_facets_covered": 0,
            "distinct_source_sessions_selected": 0,
            "multi_facet_queries": 0,
        }

    def summary(self) -> dict:
        return {
            **self.counters,
            "selection_strategy": self.strategy,
            "selection_strategy_version": self.strategy_version,
            "coverage_weights_version": COVERAGE_WEIGHTS_VERSION,
            "facet_extractor_version": FACET_EXTRACTOR_VERSION,
            "redundancy_strategy": "slot_value+jaccard+evidence",
            "source_diversity_enabled": True,
            "zero_value_padding": False,
        }

    # -- selection ----------------------------------------------------------------

    def select(self, request: SelectionRequest) -> SelectionResult:
        weights = self.weights
        # Chronology modes: same-slot different-value records are
        # TIMELINE VARIANTS (requested history), not redundancy or
        # concealable conflicts. Current mode keeps coverage behavior.
        self._timeline_mode = request.temporal_mode in (
            "timeline", "historical", "as_of"
        )
        query_facets = extract_query_facets(request.query)
        result = SelectionResult(
            k=request.k, query_facets=query_facets.facets
        )
        remaining = list(request.candidates)
        facet_map = {
            c.memory.id: candidate_facets(c) for c in remaining
        }
        query_facet_set = set(query_facets.facets)
        covered: set[str] = set()
        covered_attributes: set[str] = set()
        selected_sessions: set[str] = set()
        used_tokens = 0
        conflict_slots: set[tuple] = set()

        step = 0
        while remaining and len(result.selected) < request.k:
            best = None
            best_key = None
            best_evidence = None
            for candidate in remaining:
                evidence = self._utility(
                    candidate,
                    facet_map[candidate.memory.id],
                    query_facets,
                    query_facet_set,
                    covered,
                    covered_attributes,
                    selected_sessions,
                    result.selected,
                    weights,
                )
                key = (
                    -evidence["utility"],
                    -len(evidence["new_facets"]),
                    -candidate.final_score,
                    -(
                        candidate.component_scores.get("phrase_score", 0.0)
                        + candidate.component_scores.get("entity_score", 0.0)
                    ),
                    -candidate.kind_priority,
                    -candidate.confidence,
                    candidate.token_estimate,
                    candidate.rank,
                )
                if best_key is None or key < best_key:
                    best, best_key, best_evidence = candidate, key, evidence
            if best is None or best_evidence["utility"] <= 0.0:
                result.stopped_reason = "no_positive_utility"
                self.counters["stopped_no_positive_utility"] += 1
                for candidate in remaining:
                    result.skipped[candidate.memory.id] = (
                        "non_positive_utility"
                        if candidate is best
                        else "not_selected_by_coverage"
                    )
                break
            if (
                request.token_budget is not None
                and used_tokens + best.token_estimate > request.token_budget
            ):
                remaining.remove(best)
                result.skipped[best.memory.id] = "token_budget"
                self.counters["skipped_token_budget"] += 1
                continue

            step += 1
            remaining.remove(best)
            result.selected.append(best)
            used_tokens += best.token_estimate
            covered |= set(best_evidence["new_facets"])
            identity = _identity(best)
            if identity.get("attribute"):
                covered_attributes.add(identity["attribute"])
            slot = _slot(best)
            if slot is not None:
                conflict_slots.add(slot)
            session = _source_session(best)
            if session:
                selected_sessions.add(session)
            if best_evidence["redundancy_penalty"] > 0:
                self.counters["selected_redundant"] += 1
            if best_evidence["conflict_warning"]:
                self.counters["selected_with_conflict_warning"] += 1
            result.steps.append(
                SelectionStep(
                    memory_id=best.memory.id,
                    retrieval_rank=best.rank,
                    base_score=best.final_score,
                    step=step,
                    utility=round(best_evidence["utility"], 6),
                    new_facets=tuple(sorted(best_evidence["new_facets"])),
                    redundancy_penalty=round(
                        best_evidence["redundancy_penalty"], 6
                    ),
                    source_diversity_gain=best_evidence["source_gain"],
                    instruction_gain=best_evidence["instruction_gain"],
                    confidence_gain=round(
                        best_evidence["confidence_gain"], 6
                    ),
                    token_efficiency_gain=round(
                        best_evidence["token_gain"], 6
                    ),
                    conflict_warning=best_evidence["conflict_warning"],
                    reason=best_evidence["reason"],
                )
            )

        if len(result.selected) >= request.k:
            for candidate in remaining:
                result.skipped[candidate.memory.id] = "not_top_k"
                self.counters["skipped_not_top_k"] += 1

        # Conflict visibility: an unselected candidate that conflicts
        # with a selected same-slot value is CONTAINED, not merely
        # skipped — the warning must survive even when the penalty kept
        # it out of context. Never concealed, never resolved silently.
        # Chronology modes exempt timeline variants (requested history).
        contained = 0
        if not self._timeline_mode:
            for candidate in request.candidates:
                if candidate in result.selected:
                    continue
                if "conflicting_slot" in redundancy_signals(
                    candidate, result.selected
                ):
                    result.skipped[candidate.memory.id] = (
                        "conflict_contained"
                    )
                    contained += 1
        if contained:
            self.counters["selected_with_conflict_warning"] += 1

        if self._timeline_mode and len(result.selected) > 1:
            # Timeline context order is chronological: derived validity
            # start, then creation order — deterministic.
            def chronology(candidate):
                temporal = candidate.memory.metadata.get("temporal") or {}
                start = (
                    temporal.get("valid_from")
                    or temporal.get("event_time")
                    or ""
                )
                return (start, candidate.memory.created_at.isoformat())

            result.selected.sort(key=chronology)

        result.covered_facets = tuple(sorted(covered))
        result.selected_token_estimate = used_tokens
        result.k_compliant = len(result.selected) <= request.k
        result.budget_compliant = (
            request.token_budget is None
            or used_tokens <= request.token_budget
        )
        result.conflict_groups = (
            sum(1 for s in result.steps if s.conflict_warning)
            + sum(
                1
                for reason in result.skipped.values()
                if reason == "conflict_contained"
            )
        )

        counters = self.counters
        counters["selections"] += 1
        counters["candidates_considered"] += len(request.candidates)
        counters["selected_total"] += len(result.selected)
        counters["multi_facet_queries"] += int(query_facets.multi_facet)
        counters["query_facets_total"] += len(query_facet_set)
        counters["query_facets_covered"] += len(
            query_facet_set
            & {
                f
                for c in result.selected
                for f in facet_map[c.memory.id]
            }
        )
        counters["distinct_source_sessions_selected"] += len(
            selected_sessions
        )
        return result

    # -- utility ------------------------------------------------------------------

    def _utility(
        self,
        candidate,
        facets,
        query_facets,
        query_facet_set,
        covered,
        covered_attributes,
        selected_sessions,
        selected,
        weights,
    ) -> dict:
        new_facets = [f for f in facets if f not in covered]
        new_query_facets = [f for f in new_facets if f in query_facet_set]

        identity = _identity(candidate)
        attribute = identity.get("attribute")
        attribute_gain = (
            weights["attribute_gain"]
            if attribute and attribute not in covered_attributes
            else 0.0
        )
        value_complement = (
            weights["value_complement"]
            if attribute
            and attribute in covered_attributes
            and identity.get("cardinality") == "multi"
            and f"value:{attribute}={identity.get('value')}" not in covered
            else 0.0
        )
        entity_gain = weights["entity_gain"] * sum(
            1
            for f in new_facets
            if f.startswith("entity:")
        )

        signals = redundancy_signals(candidate, selected)
        if getattr(self, "_timeline_mode", False):
            # Distinct same-slot values across time are the requested
            # chronology; only exact duplicates stay redundant.
            signals = tuple(
                s for s in signals if s != "conflicting_slot"
            )
        conflict = "conflicting_slot" in signals
        redundancy = weights["redundancy_penalty"] * min(
            2, sum(1 for s in signals if s != "conflicting_slot")
        )
        conflict_penalty = weights["conflict_penalty"] if conflict else 0.0

        session = _source_session(candidate)
        source_gain = 0.0
        if (
            query_facets.multi_facet
            and session
            and session not in selected_sessions
            and new_query_facets
            and not conflict
            and not signals
        ):
            source_gain = weights["source_diversity"]

        instruction_gain = (
            weights["instruction_gain"]
            if candidate.memory.kind == MemoryKind.INSTRUCTION
            and new_facets
            else 0.0
        )
        confidence_gain = weights["confidence_gain"] * candidate.confidence
        token_gain = (
            weights["token_efficiency"] / (1.0 + candidate.token_estimate / 20.0)
            if new_query_facets
            else 0.0
        )

        utility = (
            weights["base_relevance"] * candidate.final_score
            + weights["facet_gain"] * len(new_query_facets)
            + attribute_gain
            + value_complement
            + entity_gain
            + source_gain
            + instruction_gain
            + confidence_gain
            + token_gain
            - redundancy
            - conflict_penalty
        )
        reason_parts = [f"utility {round(utility, 3)}"]
        if new_query_facets:
            reason_parts.append(f"{len(new_query_facets)} new facets")
        if value_complement:
            reason_parts.append("multi-value complement")
        if source_gain:
            reason_parts.append("new source session")
        if redundancy:
            reason_parts.append("redundant evidence")
        if conflict:
            reason_parts.append("UNRESOLVED CONFLICT with selected value")
        return {
            "utility": utility,
            "new_facets": new_facets,
            "redundancy_penalty": redundancy + conflict_penalty,
            "source_gain": source_gain,
            "instruction_gain": instruction_gain,
            "confidence_gain": confidence_gain,
            "token_gain": token_gain,
            "conflict_warning": conflict,
            "reason": "; ".join(reason_parts),
        }
