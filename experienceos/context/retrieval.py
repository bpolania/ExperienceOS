"""Lifecycle-aware hybrid retrieval: broad lexical recall, filtered.

The Phase 9 retrieval strategy seam. Naive retrieval finds text;
ExperienceOS retrieves current, valid, scoped experience:

    query
    → broad lexical candidate generation (BM25-style IDF weighting,
      phrase/entity overlap, a small transparent alias registry)
    → structured semantic signals (Prompt 2 identity fields: attribute,
      value, scope; Prompt 3 extraction confidence)
    → active-state lifecycle filtering (forgotten/superseded records
      are excluded before ranking and can never enter context)
    → query-aware scoring with explicit versioned weights
    → deterministic top-K selection with documented tie-breaking
    → auditable per-candidate score explanations

The strategy selects existing memories only. It never creates,
updates, supersedes, or forgets memories, never changes lifecycle
status, and never alters provenance. Coverage-aware/diversity-aware
final composition is deliberately out of scope (Prompt 5), as is
temporal/historical query reasoning (Prompt 6): current queries use
active memories only, and no historical mode is implemented because
the repository has none to preserve.

No benchmark oracle data (scenario IDs, expected answers, answer
sessions) is referenced anywhere in this module.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

from experienceos.memory.schema import ExperienceEntry, MemoryKind, MemoryStatus
from experienceos.memory.semantic import METADATA_KEY
from experienceos.memory.tags import TAG_ORDER, assign_tags

RETRIEVAL_STRATEGY_VERSION = "1"
LEXICAL_SCORING_VERSION = "1"
CANDIDATE_GENERATION_STRATEGY = "lexical+structured_semantic"

# Explicit, versioned, provider-independent, scenario-agnostic weights.
# Tuned on the phase9_dev fixtures only — never on frozen scenario IDs.
SCORING_WEIGHTS = {
    "lexical": 1.0,  # summed IDF of matched normalized tokens
    "phrase": 1.5,  # exact multi-word phrase overlap
    "entity": 2.0,  # named entity / model-number overlap
    "attribute": 1.2,  # semantic-identity attribute ∩ expanded query
    "value": 1.5,  # semantic-identity value ∩ query tokens
    "scope": 0.8,  # semantic-identity scope ∩ query tokens
    "domain": 0.6,  # existing tag/domain overlap
    "kind": 0.15,  # instruction > fact > preference
    "confidence": 0.1,  # identity/extraction confidence
}

_KIND_PRIORITY = {
    MemoryKind.INSTRUCTION: 2,
    MemoryKind.FACT: 1,
    MemoryKind.PREFERENCE: 0,
}

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "the", "to", "of", "for", "with", "in", "on",
        "at", "is", "are", "be", "it", "me", "my", "i", "you", "we",
        "do", "does", "did", "have", "has", "had", "what", "which",
        "who", "when", "where", "how", "should", "would", "could",
        "can", "will", "please", "help", "that", "this", "your", "our",
        "am", "was", "were", "remember", "know", "tell", "give",
    }
)

# Small transparent alias registry: deterministic, general classes only
# (never derived from benchmark answers). Members are normalized with
# the same token rules at module load so both sides match consistently.
_RAW_ALIAS_CLASSES = (
    ("employer", "work", "works", "company", "employs", "employer", "job"),
    ("phone", "mobile", "device", "handset", "use", "uses"),
    ("residence", "live", "lives", "city", "home", "moved", "based"),
    ("seat", "seats", "aisle", "window", "seating"),
    ("school", "attends", "goes", "studies"),
    ("language", "languages", "speak", "speaks"),
    ("send", "route", "routing", "channel", "deliver"),
    ("weather", "forecast", "temperature"),
    ("drink", "drinks", "coffee", "tea", "beverage"),
    (
        "food", "meal", "meals", "recipe", "snack", "snacks", "eat",
        "eating", "dish", "cake", "dinner", "lunch", "breakfast",
        "cooking",
    ),
)

# Safe morphological prefix matching: "commit" matches "committing",
# "book" does NOT match "bookshelf" (prefix must be >= 5 chars). Value
# distinctions survive: model numbers, weekdays, aisle/window, units
# never relate by prefix.
_MIN_PREFIX = 5


def tokens_match(query_token: str, memory_token: str) -> bool:
    if query_token == memory_token:
        return True
    shorter, longer = sorted((query_token, memory_token), key=len)
    return len(shorter) >= _MIN_PREFIX and longer.startswith(shorter)


def _normalize_token(word: str) -> str:
    word = word.replace("'", "")
    if (
        len(word) > 3
        and word.endswith("s")
        and not word.endswith(("ss", "us", "is"))
    ):
        word = word[:-1]  # safe singular/plural folding only
    return word


_TOKEN_RE = re.compile(r"[a-z0-9#][a-z0-9#'-]*")

# Named entities and model numbers: capitalized word runs optionally
# followed by numbers ("Pixel 9", "Lincoln Middle School", "Globex").
_ENTITY_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9-]*(?:\s+(?:[A-Z][A-Za-z0-9-]*|\d[\w-]*))*\b"
)
# Lowercase word+number model phrases ("pixel 9") stay distinct too.
_MODEL_RE = re.compile(r"\b([a-z][a-z-]+\s+\d[\w-]*)\b")


def tokenize(text: str) -> set[str]:
    """Deterministic normalized content tokens.

    Unicode NFKC, case folding, punctuation removal, possessive
    normalization, safe plural folding, stopword removal. Distinct
    values stay distinct: pixel 6 vs pixel 9, aisle vs window,
    celsius vs fahrenheit (-us endings are never stripped).
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    tokens = set()
    for word in _TOKEN_RE.findall(folded):
        token = _normalize_token(word)
        if token and token not in _STOPWORDS:
            tokens.add(token)
    return tokens


def phrases(text: str) -> set[str]:
    """Normalized multi-word entity/model phrases from original text."""
    found = set()
    for match in _ENTITY_RE.finditer(text):
        phrase = " ".join(
            _normalize_token(w)
            for w in match.group(0).casefold().split()
        )
        if " " in phrase:
            found.add(phrase)
    for match in _MODEL_RE.finditer(text.casefold()):
        found.add(
            " ".join(_normalize_token(w) for w in match.group(1).split())
        )
    return found


def entities(text: str) -> set[str]:
    """Normalized named entities (single- or multi-word)."""
    found = set()
    for match in _ENTITY_RE.finditer(text):
        words = match.group(0).casefold().split()
        normalized = " ".join(_normalize_token(w) for w in words)
        if normalized and normalized not in _STOPWORDS:
            found.add(normalized)
    return found


ALIAS_CLASSES = tuple(
    frozenset(
        token
        for raw in klass
        for token in [_normalize_token(raw.casefold())]
        if token
    )
    for klass in _RAW_ALIAS_CLASSES
)

# Canonical name per alias class (its first declared member), so
# downstream facet extraction can name the concept a query touches.
ALIAS_CANONICAL = {
    tokens: _normalize_token(raw[0].casefold())
    for raw, tokens in zip(_RAW_ALIAS_CLASSES, ALIAS_CLASSES)
}


def expand_query_tokens(tokens: set[str]) -> set[str]:
    """Query tokens plus their alias classes (query side only)."""
    expanded = set(tokens)
    for klass in ALIAS_CLASSES:
        if tokens & klass:
            expanded |= klass
    return expanded


@dataclass(frozen=True)
class QueryProfile:
    """Deterministic normalization of one query."""

    text: str
    tokens: frozenset
    expanded_tokens: frozenset
    phrases: frozenset
    entities: frozenset
    tags: tuple


def normalize_query(text: str) -> QueryProfile:
    tokens = tokenize(text)
    return QueryProfile(
        text=text,
        tokens=frozenset(tokens),
        expanded_tokens=frozenset(expand_query_tokens(tokens)),
        phrases=frozenset(phrases(text)),
        entities=frozenset(entities(text)),
        tags=tuple(assign_tags(text)),
    )


# --------------------------------------------------------------------------
# Retrieval contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalRequest:
    """Bounded retrieval input. Never carries benchmark expected
    answers, answer-session oracles, scenario IDs, or inactive records
    presented as active truth."""

    query: str
    memories: tuple  # candidate ExperienceEntry records
    k: int
    session_id: str = ""
    token_budget: int | None = None  # optional; None preserves v1 rules
    historical_mode: bool = False  # unsupported: Prompt 6 owns temporal
    strategy_version: str = RETRIEVAL_STRATEGY_VERSION


@dataclass
class RetrievalCandidate:
    """One scored (or excluded) memory with auditable evidence."""

    memory: ExperienceEntry
    status: str
    normalized_tokens: tuple = ()
    matched_tokens: tuple = ()
    matched_phrases: tuple = ()
    matched_entities: tuple = ()
    matched_domains: tuple = ()
    component_scores: dict = field(default_factory=dict)
    final_score: float = 0.0
    kind_priority: int = 0
    confidence: float = 1.0
    token_estimate: int = 0
    rank: int = 0  # 1-based over ranked candidates; 0 = never ranked
    selected: bool = False
    exclusion_reason: str | None = None  # inactive_*, zero_relevance,
    # not_top_k, token_budget


@dataclass
class RetrievalResult:
    """Selected memories plus complete audit evidence."""

    selected: list = field(default_factory=list)  # ExperienceEntry
    candidates: list = field(default_factory=list)  # RetrievalCandidate
    active_count: int = 0
    inactive_filtered: int = 0
    lexical_candidates: int = 0
    zero_relevance_excluded: int = 0
    skipped_not_top_k: int = 0
    skipped_token_budget: int = 0
    unresolved_conflict_pairs: int = 0
    k: int = 0
    k_compliant: bool = True
    budget_compliant: bool = True
    context_token_estimate: int = 0
    latency_ms: float = 0.0
    strategy: str = "hybrid_retrieval"
    strategy_version: str = RETRIEVAL_STRATEGY_VERSION
    warnings: tuple = ()
    coverage: dict = field(default_factory=dict)  # Prompt 5 evidence


class RetrievalStrategy(Protocol):
    """Provider-independent retrieval seam."""

    strategy: str
    strategy_version: str

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        ...


def _token_estimate(text: str) -> int:
    return -(-len(text) // 4)  # ceil(chars / 4), suite convention


def _identity_metadata(entry: ExperienceEntry) -> dict:
    stored = entry.metadata.get(METADATA_KEY)
    return stored if isinstance(stored, dict) else {}


def _entry_confidence(entry: ExperienceEntry, identity: dict) -> float:
    confidence = identity.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(
        confidence, bool
    ):
        return float(confidence)
    return 1.0


class HybridRetrievalStrategy:
    """Broad lexical + structured-semantic retrieval, lifecycle-first.

    Deterministic tie-breaking (documented order):

    1. final score, descending
    2. phrase+entity score, descending (direct-match preference)
    3. memory-kind priority (instruction > fact > preference)
    4. confidence, descending
    5. recency (created_at), descending
    6. memory ID, ascending (stable)

    Repeated runs over the same inputs produce identical rankings.
    """

    strategy = "hybrid_retrieval"
    strategy_version = RETRIEVAL_STRATEGY_VERSION
    lexical_scoring_version = LEXICAL_SCORING_VERSION
    candidate_generation = CANDIDATE_GENERATION_STRATEGY

    def __init__(
        self,
        weights: dict | None = None,
        candidate_limit: int | None = None,
        selection_strategy=None,
        temporal_policy=None,
    ):
        self.weights = dict(weights or SCORING_WEIGHTS)
        # Candidate limit bounds scored candidates when populations are
        # large; it is always >= K at selection time and never padded.
        self.candidate_limit = candidate_limit
        # Optional Phase 9 Prompt 5 seam: when None (the default and
        # every Prompt 4 configuration), final selection below is the
        # unchanged deterministic top-K loop.
        self.selection_strategy = selection_strategy
        # Optional Phase 9 Prompt 6 seam: when None (the default and
        # every earlier configuration), admission, scoring, and
        # rendering below are byte-identical to Prompt 4/5.
        self.temporal_policy = temporal_policy
        self.counters = {
            "retrievals": 0,
            "active_memories": 0,
            "inactive_filtered": 0,
            "lexical_candidates": 0,
            "zero_relevance_excluded": 0,
            "selected_total": 0,
            "skipped_not_top_k": 0,
            "skipped_token_budget": 0,
            "k_compliant_retrievals": 0,
            "budget_compliant_retrievals": 0,
            "unresolved_conflict_retrievals": 0,
            "latency_ms_total": 0.0,
        }

    @property
    def includes_historical(self) -> bool:
        """Whether the memory pool should include superseded records
        (explicit historical/as-of retrieval; forgotten never)."""
        return self.temporal_policy is not None

    # -- diagnostics -----------------------------------------------------------

    def summary(self) -> dict:
        # Measured latency stays out of the summary: it lands in
        # digested benchmark evidence and would break deterministic
        # rerun comparison. Read counters["latency_ms_total"] directly
        # for local timing reports.
        return {
            **{
                k: v
                for k, v in self.counters.items()
                if k != "latency_ms_total"
            },
            "retrieval_strategy": self.strategy,
            "retrieval_strategy_version": self.strategy_version,
            "lexical_scoring_version": self.lexical_scoring_version,
            "candidate_generation_strategy": self.candidate_generation,
            "candidate_limit": self.candidate_limit,
            "semantic_scoring_enabled": True,  # structured identity fields
            "embedding_scoring_enabled": False,  # deferred (see docs)
            "historical_mode_support": False,  # Prompt 6 owns temporal
            "lifecycle_filtering": "active_only_before_ranking",
            "scoring_weights_version": LEXICAL_SCORING_VERSION,
        }

    # -- retrieval ---------------------------------------------------------------

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        started = time.perf_counter()
        result = RetrievalResult(
            k=request.k,
            strategy=self.strategy,
            strategy_version=self.strategy_version,
        )
        if request.historical_mode:
            # No historical retrieval exists to preserve; current
            # active experience only (Prompt 6 owns temporal queries).
            result.warnings = (
                "historical_mode unsupported: using current active "
                "experience only",
            )

        query = normalize_query(request.query)
        intent = None
        if self.temporal_policy is not None:
            intent = self.temporal_policy.interpret(
                request.query, historical_flag=request.historical_mode
            )
            self._last_by_id = {e.id: e for e in request.memories}

        # 1. Lifecycle filtering BEFORE ranking: inactive records are
        # excluded, audited, and can never reach context or compression.
        # A temporal policy may ADMIT superseded records for explicit
        # historical/as-of/timeline intents (forgotten records never),
        # and may HOLD active records that are not yet valid or are
        # historical-only for current queries.
        active: list[ExperienceEntry] = []
        for entry in request.memories:
            if intent is not None:
                reason = self.temporal_policy.admit(entry, intent)
                if reason is None:
                    active.append(entry)
                    continue
            elif entry.status == MemoryStatus.ACTIVE:
                active.append(entry)
                continue
            else:
                reason = f"inactive_{entry.status}"
            result.candidates.append(
                RetrievalCandidate(
                    memory=entry,
                    status=entry.status,
                    exclusion_reason=reason,
                )
            )
            result.inactive_filtered += 1
        result.active_count = len(active)

        # 2. Corpus statistics for BM25-style IDF over active memories.
        doc_tokens = {e.id: tokenize(e.text) for e in active}
        doc_count = len(active)
        doc_frequency: dict[str, int] = {}
        for tokens in doc_tokens.values():
            for token in tokens:
                doc_frequency[token] = doc_frequency.get(token, 0) + 1

        def idf(token: str) -> float:
            df = doc_frequency.get(token, 0)
            return math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))

        # 3. Score every admitted memory (bounded population).
        by_id = {e.id: e for e in request.memories}
        scored: list[RetrievalCandidate] = []
        for entry in active:
            candidate = self._score(entry, query, doc_tokens[entry.id], idf)
            if candidate.final_score <= 0.0:
                candidate.exclusion_reason = "zero_relevance"
                result.zero_relevance_excluded += 1
                result.candidates.append(candidate)
                continue
            if intent is not None:
                # Temporal fit and provenance trust REFINE candidates
                # that are already relevant; they never create
                # relevance (zero-relevance exclusion happened above).
                components, bonus = self.temporal_policy.score(
                    entry, intent, by_id
                )
                candidate.component_scores.update(components)
                candidate.final_score = round(
                    candidate.final_score + bonus, 6
                )
            scored.append(candidate)
        result.lexical_candidates = len(scored)

        # 4. Deterministic ranking (documented tie-break order).
        scored.sort(
            key=lambda c: (
                -c.final_score,
                -(
                    c.component_scores.get("phrase_score", 0.0)
                    + c.component_scores.get("entity_score", 0.0)
                ),
                -c.kind_priority,
                -c.confidence,
                -c.memory.created_at.timestamp(),
                c.memory.id,
            )
        )
        if self.candidate_limit is not None:
            limit = max(self.candidate_limit, request.k)
            for candidate in scored[limit:]:
                candidate.exclusion_reason = "below_candidate_limit"
                result.candidates.append(candidate)
            scored = scored[:limit]

        # 5. Final selection with optional token-budget enforcement.
        # K never grows; zero-relevance records never pad the context.
        budget = request.token_budget
        for index, candidate in enumerate(scored, start=1):
            candidate.rank = index
        if self.selection_strategy is not None:
            used_tokens = self._coverage_selection(
                request, query, scored, result
            )
        else:
            used_tokens = 0
            for candidate in scored:
                if len(result.selected) >= request.k:
                    candidate.exclusion_reason = "not_top_k"
                    result.skipped_not_top_k += 1
                elif (
                    budget is not None
                    and used_tokens + candidate.token_estimate > budget
                ):
                    candidate.exclusion_reason = "token_budget"
                    result.skipped_token_budget += 1
                else:
                    candidate.selected = True
                    used_tokens += candidate.token_estimate
                    result.selected.append(candidate.memory)
                result.candidates.append(candidate)

        result.context_token_estimate = used_tokens
        result.k_compliant = len(result.selected) <= request.k
        result.budget_compliant = budget is None or used_tokens <= budget
        result.unresolved_conflict_pairs = self._conflict_pairs(
            [c for c in result.candidates if c.selected]
        )
        result.latency_ms = (time.perf_counter() - started) * 1000.0

        self._count(result)
        return result

    def _coverage_selection(self, request, query, scored, result) -> int:
        """Delegate final selection to the configured Prompt 5 strategy.

        The strategy receives the full positive-relevance active pool
        (Prompt 4 ranks preserved) and returns a bounded subset in
        final context order plus per-candidate skip reasons. Retrieval
        component scores stay untouched; coverage evidence rides
        ``result.coverage`` keyed by memory ID.
        """
        from experienceos.context.selection import SelectionRequest

        intent = (
            self.temporal_policy.last_intent
            if self.temporal_policy is not None
            else None
        )
        selection = self.selection_strategy.select(
            SelectionRequest(
                query=query,
                candidates=tuple(scored),
                k=request.k,
                token_budget=request.token_budget,
                session_id=request.session_id,
                temporal_mode=intent.mode if intent else "current",
            )
        )
        selected_ids = {c.memory.id for c in selection.selected}
        used_tokens = selection.selected_token_estimate
        for candidate in selection.selected:  # final context order
            candidate.selected = True
            result.selected.append(candidate.memory)
        for candidate in scored:
            if candidate.memory.id not in selected_ids:
                reason = selection.skipped.get(
                    candidate.memory.id, "not_selected_by_coverage"
                )
                candidate.exclusion_reason = reason
                if reason == "not_top_k":
                    result.skipped_not_top_k += 1
                elif reason == "token_budget":
                    result.skipped_token_budget += 1
            result.candidates.append(candidate)
        result.coverage = {
            "strategy": selection.strategy,
            "strategy_version": selection.strategy_version,
            "weights_version": selection.weights_version,
            "query_facets": len(selection.query_facets),
            "covered_facets": len(selection.covered_facets),
            "stopped_reason": selection.stopped_reason,
            "conflict_warnings": selection.conflict_groups,
            "steps": [
                {
                    "memory_id": s.memory_id,
                    "step": s.step,
                    "retrieval_rank": s.retrieval_rank,
                    "utility": s.utility,
                    "new_facets": list(s.new_facets),
                    "redundancy_penalty": s.redundancy_penalty,
                    "source_diversity_gain": s.source_diversity_gain,
                    "conflict_warning": s.conflict_warning,
                    "reason": s.reason,
                }
                for s in selection.steps
            ],
        }
        return used_tokens

    def annotate_memory(self, memory) -> str:
        """Concise temporal/provenance label for rendered context.
        Empty (and never invoked by the builder) without a temporal
        policy, so earlier systems render byte-identical context."""
        if self.temporal_policy is None:
            return ""
        return self.temporal_policy.annotate(
            memory, getattr(self, "_last_by_id", {})
        )

    # -- scoring ------------------------------------------------------------------

    def _score(self, entry, query, memory_tokens, idf) -> RetrievalCandidate:
        identity = _identity_metadata(entry)
        exact = memory_tokens & query.expanded_tokens
        prefix_eligible = [
            t for t in query.expanded_tokens
            if len(t) >= _MIN_PREFIX and t not in exact
        ]
        matched_tokens = sorted(
            exact
            | {
                m
                for m in memory_tokens - exact
                if any(tokens_match(q, m) for q in prefix_eligible)
            }
        )
        lexical = sum(idf(token) for token in matched_tokens)

        memory_phrases = phrases(entry.text)
        matched_phrases = sorted(
            memory_phrases & (query.phrases | query.entities)
        )
        phrase_score = float(len(matched_phrases))

        memory_entities = entities(entry.text)
        matched_entities = sorted(memory_entities & query.entities)
        entity_score = float(len(matched_entities))

        attribute_tokens = tokenize(
            str(identity.get("attribute", "")).replace("_", " ")
        )
        attribute_score = float(
            bool(attribute_tokens & query.expanded_tokens)
        )
        value_tokens = tokenize(str(identity.get("value", "")))
        value_score = float(bool(value_tokens and value_tokens <= query.tokens)) + 0.5 * float(
            bool(value_tokens & query.tokens)
        )
        scope = str(identity.get("scope", "") or "")
        scope_tokens = (
            tokenize(scope.replace("_", " ")) if scope != "global" else set()
        )
        scope_score = float(bool(scope_tokens & query.tokens))

        tags = entry.metadata.get("tags") or assign_tags(entry.text)
        matched_domains = [
            t for t in TAG_ORDER if t in tags and t in query.tags
        ]
        domain_score = float(len(matched_domains))

        kind_priority = _KIND_PRIORITY.get(entry.kind, 0)
        confidence = _entry_confidence(entry, identity)

        relevance = (
            self.weights["lexical"] * lexical
            + self.weights["phrase"] * phrase_score
            + self.weights["entity"] * entity_score
            + self.weights["attribute"] * attribute_score
            + self.weights["value"] * value_score
            + self.weights["scope"] * scope_score
            + self.weights["domain"] * domain_score
        )
        # Kind priority and confidence refine ranking but never create
        # relevance on their own — zero-signal memories stay excluded.
        final_score = (
            relevance
            + self.weights["kind"] * kind_priority
            + self.weights["confidence"] * confidence
            if relevance > 0.0
            else 0.0
        )
        return RetrievalCandidate(
            memory=entry,
            status=entry.status,
            normalized_tokens=tuple(sorted(memory_tokens)),
            matched_tokens=tuple(matched_tokens),
            matched_phrases=tuple(matched_phrases),
            matched_entities=tuple(matched_entities),
            matched_domains=tuple(matched_domains),
            component_scores={
                "lexical_score": round(lexical, 6),
                "phrase_score": phrase_score,
                "entity_score": entity_score,
                "attribute_score": attribute_score,
                "value_score": value_score,
                "scope_score": scope_score,
                "domain_score": domain_score,
                "kind_priority": float(kind_priority),
                "confidence_score": round(confidence, 6),
            },
            final_score=round(final_score, 6),
            kind_priority=kind_priority,
            confidence=confidence,
            token_estimate=_token_estimate(entry.text),
        )

    @staticmethod
    def _conflict_pairs(selected: list) -> int:
        """Unresolved active conflicts among SELECTED records: two
        selected memories occupying the same semantic slot with
        different values. Recorded as diagnostics, never silently
        resolved — extraction-only configurations leave these visible
        by design."""
        slots: dict[tuple, set] = {}
        for candidate in selected:
            identity = _identity_metadata(candidate.memory)
            attribute = identity.get("attribute")
            if not attribute:
                continue
            if identity.get("cardinality") == "multi":
                continue  # additive facts (languages, tools) never conflict
            slot = (
                identity.get("subject", "user"),
                attribute,
                identity.get("scope", "global"),
            )
            slots.setdefault(slot, set()).add(identity.get("value", ""))
        return sum(1 for values in slots.values() if len(values) > 1)

    def _count(self, result: RetrievalResult) -> None:
        counters = self.counters
        counters["retrievals"] += 1
        counters["active_memories"] += result.active_count
        counters["inactive_filtered"] += result.inactive_filtered
        counters["lexical_candidates"] += result.lexical_candidates
        counters["zero_relevance_excluded"] += result.zero_relevance_excluded
        counters["selected_total"] += len(result.selected)
        counters["skipped_not_top_k"] += result.skipped_not_top_k
        counters["skipped_token_budget"] += result.skipped_token_budget
        counters["k_compliant_retrievals"] += int(result.k_compliant)
        counters["budget_compliant_retrievals"] += int(
            result.budget_compliant
        )
        counters["unresolved_conflict_retrievals"] += int(
            result.unresolved_conflict_pairs > 0
        )
        counters["latency_ms_total"] += result.latency_ms
