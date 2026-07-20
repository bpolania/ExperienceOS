"""Lifecycle-aware hybrid retrieval: broad lexical recall, filtered.

The retrieval strategy seam. Naive retrieval finds text;
ExperienceOS retrieves current, valid, scoped experience:

    query
    → broad lexical candidate generation (BM25-style IDF weighting,
      phrase/entity overlap, a small transparent alias registry)
    → structured semantic signals (identity fields: attribute,
      value, scope; extraction confidence)
    → active-state lifecycle filtering (forgotten/superseded records
      are excluded before ranking and can never enter context)
    → query-aware scoring with explicit versioned weights
    → deterministic top-K selection with documented tie-breaking
    → auditable per-candidate score explanations

The strategy selects existing memories only. It never creates,
updates, supersedes, or forgets memories, never changes lifecycle
status, and never alters provenance. Coverage-aware/diversity-aware
final composition is deliberately out of scope, as is
temporal/historical query reasoning: current queries use
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
    historical_mode: bool = False  # unsupported: temporal queries owned elsewhere
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
    # not_top_k, token_budget, below_semantic_floor
    semantic: dict | None = None  # vector-free semantic
    # evidence; None whenever semantic retrieval is disabled
    fusion: dict | None = None  # reconstructable
    # fusion breakdown; None outside fused mode
    gate: dict | None = None  # shadow-gate
    # proposal evidence; None whenever no gate is configured


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
    coverage: dict = field(default_factory=dict)  # coverage evidence
    semantic: dict = field(default_factory=dict)  # semantic summary;
    # empty whenever semantic retrieval is disabled
    gate: dict = field(default_factory=dict)  # shadow-gate
    # summary; empty whenever no gate is configured


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
        semantic_generator=None,
        semantic_mode: str = "disabled",
        semantic_strict: bool = False,
        fusion_profile=None,
        memory_gate=None,
        gate_strict: bool = False,
    ):
        self.weights = dict(weights or SCORING_WEIGHTS)
        # Candidate limit bounds scored candidates when populations are
        # large; it is always >= K at selection time and never padded.
        self.candidate_limit = candidate_limit
        # Optional coverage-selection seam: when None (the default and
        # every fusion configuration), final selection below is the
        # unchanged deterministic top-K loop.
        self.selection_strategy = selection_strategy
        # Optional temporal-policy seam: when None (the default and
        # every earlier configuration), admission, scoring, and
        # rendering below are byte-identical to the fusion/coverage path.
        self.temporal_policy = temporal_policy
        # Optional semantic-scoring seam: mode is explicit, fixed per
        # strategy instance, and never chosen from query content. With
        # the default "disabled" mode (and every earlier
        # configuration) no provider is invoked, no cache exists, and
        # retrieval below is byte-identical to the lexical path.
        from experienceos.context.semantic import SEMANTIC_MODES

        if semantic_mode not in SEMANTIC_MODES:
            raise ValueError(
                f"unknown semantic_mode {semantic_mode!r}; expected one "
                f"of {SEMANTIC_MODES}"
            )
        # Fusion seam: an explicit, versioned fusion profile
        # applies only in "fused" mode. The lexical_reference profile
        # bypasses fusion entirely and routes through the unchanged
        # lexical path (the zero-semantic-weight equivalence design).
        if semantic_mode == "fused":
            from experienceos.context.fusion import resolve_fusion_profile

            self.fusion_profile = resolve_fusion_profile(fusion_profile)
        else:
            if fusion_profile is not None:
                raise ValueError(
                    "fusion_profile is only valid with "
                    "semantic_mode='fused'"
                )
            self.fusion_profile = None
        from experienceos.context.fusion import REFERENCE_PROFILE_ID

        self._reference_bypass = (
            semantic_mode == "fused"
            and self.fusion_profile.profile_id == REFERENCE_PROFILE_ID
        )
        if (
            semantic_mode != "disabled"
            and not self._reference_bypass
            and semantic_generator is None
        ):
            raise ValueError(
                "semantic_mode requires a configured semantic_generator"
            )
        self.semantic_generator = semantic_generator
        self.semantic_mode = semantic_mode
        self.semantic_strict = semantic_strict
        # Optional shadow-gate seam: a shadow-only MemoryGate
        # evaluated strictly AFTER canonical selection and budget
        # enforcement. It observes the finished result and attaches
        # additive diagnostics; it can never alter it. Default None:
        # no gate, no diagnostics, byte-identical earlier behavior.
        self.memory_gate = memory_gate
        self.gate_strict = gate_strict
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
            "historical_mode_support": False,  # temporal queries owned elsewhere
            "lifecycle_filtering": "active_only_before_ranking",
            "scoring_weights_version": LEXICAL_SCORING_VERSION,
            # Additive semantic block, present only when configured so
            # every earlier configuration's summary stays identical.
            **(
                {"semantic_retrieval": self._semantic_summary()}
                if self.semantic_mode != "disabled"
                else {}
            ),
        }

    def _semantic_summary(self) -> dict:
        block = {
            "mode": self.semantic_mode,
            "strict": self.semantic_strict,
        }
        if self.semantic_generator is not None:
            block.update(
                relevance_floor=self.semantic_generator.relevance_floor,
                provider_id=self.semantic_generator.provider.provider_id,
                model_id=self.semantic_generator.provider.model_id,
                cache=self.semantic_generator.cache.summary(),
            )
        if self.fusion_profile is not None:
            block["fusion_profile"] = self.fusion_profile.to_metadata()
            block["reference_bypass"] = self._reference_bypass
        return block

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
            # active experience only (temporal queries owned elsewhere).
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

        # Semantic scoring runs strictly AFTER the
        # lifecycle filter above — only admitted entries are ever
        # embedded, so similarity can never widen admission. Provider
        # failure or unavailability falls back to the unchanged
        # lexical path (recorded in ``result.semantic``).
        semantic_outcome = None
        if self.semantic_mode != "disabled" and not self._reference_bypass:
            semantic_outcome = self._semantic_outcome(
                request, tuple(active), result
            )
            for candidate in result.candidates:
                # Lifecycle-excluded records were never embedded.
                candidate.semantic = {"considered": False}

        if semantic_outcome is not None and (
            self.semantic_mode == "semantic_only"
            or (
                self.semantic_mode == "fused"
                and self.fusion_profile.component_weights.get("semantic")
                == 1.0
                and len(self.fusion_profile.component_weights) == 1
            )
        ):
            # semantic_only mode, and the embedding_only fused profile,
            # share one implementation: semantic evidence plus
            # non-relevance refiners, lexical never mixed in.
            scored = self._semantic_candidates(
                active, semantic_outcome, result
            )
        elif self.semantic_mode == "fused" and semantic_outcome is not None:
            scored = self._fused_candidates(
                request, query, active, intent, result, semantic_outcome
            )
        else:
            # disabled mode, the lexical_reference profile, score_only
            # mode, and every semantic/fused fallback: the unchanged
            # lexical path.
            scored = self._lexical_scored(
                request, query, active, intent, result
            )
            if semantic_outcome is not None:  # score_only diagnostics
                self._attach_semantic_diagnostics(
                    scored, result, semantic_outcome
                )

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
        if result.semantic.get("fusion") is not None:
            result.semantic["fusion"]["post_limit_count"] = len(scored)

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

        # Shadow-gate evaluation of the FINISHED
        # canonical result — selection, ordering, reasons, and budgets
        # above are final; the gate can only attach diagnostics.
        if self.memory_gate is not None:
            from experienceos.context.gating import evaluate_shadow_gate

            evaluate_shadow_gate(
                self.memory_gate,
                result,
                query=request.query,
                retrieval_mode=self.semantic_mode,
                fusion_profile_id=(
                    self.fusion_profile.profile_id
                    if self.fusion_profile is not None
                    else None
                ),
                strict=self.gate_strict,
            )
        return result

    def _lexical_scored(
        self, request, query, active, intent, result
    ) -> list[RetrievalCandidate]:
        """Steps 2-3 of the lexical pipeline, moved verbatim: corpus
        statistics plus lexical/structured scoring of every admitted
        memory. Behavior is unchanged from the lexical path."""
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
        return scored

    def _semantic_outcome(self, request, active, result):
        """Score admitted entries semantically, or record a fallback.

        Returns the scoring outcome, or ``None`` after recording a
        deterministic fallback to the lexical path. Only typed
        embedding errors are contained; programming errors propagate.
        """
        from experienceos.embeddings.base import EmbeddingProviderError

        def _fallback(reason: str) -> None:
            result.semantic = {
                "mode": self.semantic_mode,
                "enabled": True,
                "provider_available": False,
                "provider_id": self.semantic_generator.provider.provider_id,
                "model_id": self.semantic_generator.provider.model_id,
                "fallback_used": True,
                "fallback_reason": reason,
            }
            if self.fusion_profile is not None:
                # A fused profile falls back to the exact lexical
                # reference path, recorded here.
                result.semantic["fusion_profile_id"] = (
                    self.fusion_profile.profile_id
                )
                result.semantic["fallback_path"] = "lexical_reference"

        try:
            outcome = self.semantic_generator.score_memories(
                request.query, active
            )
        except EmbeddingProviderError as exc:
            if self.semantic_strict:
                raise
            availability = getattr(exc, "availability", None)
            _fallback(
                availability.reason
                if availability is not None and availability.reason
                else type(exc).__name__
            )
            return None
        result.semantic = {
            "mode": self.semantic_mode,
            "enabled": True,
            "provider_available": True,
            "provider_id": outcome.provider_id,
            "model_id": outcome.model_id,
            "dimensions": outcome.dimensions,
            "relevance_floor": outcome.relevance_floor,
            "query_zero_vector": outcome.query_zero_vector,
            "eligible_count": outcome.eligible_count,
            "scored_count": len(outcome.scores),
            "semantic_candidate_count": outcome.above_floor_count,
            "query_embedding": outcome.query_embedding,
            "memory_embedding": outcome.memory_embedding,
            "cache": outcome.cache,
            "fallback_used": False,
            "fallback_reason": None,
        }
        if self.fusion_profile is not None:
            result.semantic["fusion_profile_id"] = (
                self.fusion_profile.profile_id
            )
        return outcome

    def _semantic_candidates(
        self, active, outcome, result
    ) -> list[RetrievalCandidate]:
        """Semantic-only candidate generation over admitted entries.

        Ranking is semantic score first; lexical scores are never
        mixed in (fusion is a separate stage). Entries at or below the
        relevance floor are excluded as ``below_semantic_floor`` —
        never padded toward K. The shared step-4 sort then orders
        candidates by (-final_score, -(phrase+entity)=0, -kind
        priority, -confidence, -created_at, id): the documented
        semantic tie-break tuple.
        """
        scored: list[RetrievalCandidate] = []
        for entry in active:
            score = outcome.scores[entry.id]
            identity = _identity_metadata(entry)
            candidate = RetrievalCandidate(
                memory=entry,
                status=entry.status,
                component_scores={
                    "semantic_score": score.score,
                    "semantic_raw_cosine": score.raw_cosine,
                },
                final_score=score.score,
                kind_priority=_KIND_PRIORITY.get(entry.kind, 0),
                confidence=_entry_confidence(entry, identity),
                token_estimate=_token_estimate(entry.text),
                semantic=self._semantic_evidence(score, outcome),
            )
            if not score.above_floor:
                candidate.exclusion_reason = "below_semantic_floor"
                result.candidates.append(candidate)
                continue
            scored.append(candidate)
        return scored

    def _attach_semantic_diagnostics(self, scored, result, outcome) -> None:
        """score_only mode: semantic evidence rides along as
        diagnostics on the lexically-scored candidates; final scores
        and ranking are untouched (fusion is a separate stage)."""
        for candidate in scored:
            score = outcome.scores.get(candidate.memory.id)
            if score is not None:
                candidate.semantic = self._semantic_evidence(score, outcome)
        for candidate in result.candidates:
            score = outcome.scores.get(candidate.memory.id)
            if score is not None and candidate.semantic is None:
                candidate.semantic = self._semantic_evidence(score, outcome)

    def _fused_candidates(
        self, request, query, active, intent, result, outcome
    ) -> list[RetrievalCandidate]:
        """Fused candidate pool: the union of lexical-evidence and
        above-floor semantic-evidence candidates over the already
        lifecycle-admitted entries (contract §6/§13 rules).

        A memory enters through positive lexical/structured relevance,
        a semantic score above the relevance floor, or both. For a
        lexically relevant memory, a below-floor semantic score still
        contributes to fusion (it refines an already-relevant
        candidate); a memory without lexical relevance needs an
        above-floor semantic score. Kind, confidence, recency, and
        temporal bonus never create eligibility. Zero-evidence
        memories are excluded as ``no_fused_evidence`` — never padded.
        """
        from experienceos.context.fusion import (
            fuse_components,
            structured_aggregate,
        )

        profile = self.fusion_profile
        doc_tokens = {e.id: tokenize(e.text) for e in active}
        doc_count = len(active)
        doc_frequency: dict[str, int] = {}
        for tokens in doc_tokens.values():
            for token in tokens:
                doc_frequency[token] = doc_frequency.get(token, 0) + 1

        def idf(token: str) -> float:
            df = doc_frequency.get(token, 0)
            return math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))

        by_id = {e.id: e for e in request.memories}
        sort_key = self._ranking_key
        fused: list[RetrievalCandidate] = []
        lexical_positive: list[tuple[RetrievalCandidate, float]] = []
        counts = {"lexical": 0, "semantic": 0, "overlap": 0,
                  "lexical_only": 0, "semantic_only": 0}
        for entry in active:
            candidate = self._score(entry, query, doc_tokens[entry.id], idf)
            lexical_final = candidate.final_score  # pre-fusion ranking
            if intent is not None:
                components, bonus = self.temporal_policy.score(
                    entry, intent, by_id
                )
                candidate.component_scores.update(components)
                raw_temporal = bonus
            else:
                raw_temporal = 0.0
            score = outcome.scores[entry.id]
            candidate.semantic = self._semantic_evidence(score, outcome)
            lexical_evidence = lexical_final > 0.0
            semantic_evidence = score.above_floor
            if not lexical_evidence and not semantic_evidence:
                candidate.exclusion_reason = "no_fused_evidence"
                result.candidates.append(candidate)
                continue
            counts["lexical"] += int(lexical_evidence)
            counts["semantic"] += int(semantic_evidence)
            if lexical_evidence and semantic_evidence:
                counts["overlap"] += 1
                evidence_source = "lexical_and_semantic"
            elif lexical_evidence:
                counts["lexical_only"] += 1
                evidence_source = "lexical_only"
            else:
                counts["semantic_only"] += 1
                evidence_source = "semantic_only"
            breakdown = fuse_components(
                profile,
                {
                    "lexical": candidate.component_scores["lexical_score"],
                    "structured": structured_aggregate(
                        candidate.component_scores, self.weights
                    ),
                    "semantic": score.score,
                    "temporal": raw_temporal,
                },
            )
            candidate.fusion = {
                "profile_id": profile.profile_id,
                "profile_version": profile.version,
                "normalization_id": profile.normalization_id,
                "raw": breakdown.raw,
                "normalized": breakdown.normalized,
                "weights": breakdown.weights,
                "contributions": breakdown.contributions,
                "fused_score": breakdown.fused_score,
                "evidence_source": evidence_source,
                "semantic_rank": score.rank,
                "lexical_rank": None,  # filled below
                "fused_rank": None,  # filled below
                "rank_delta": None,
            }
            candidate.final_score = breakdown.fused_score
            fused.append(candidate)
            if lexical_evidence:
                lexical_positive.append((candidate, lexical_final))

        # Pre-fusion lexical ranks (existing tuple over pre-fusion
        # scores) and prospective fused ranks: the same key the shared
        # step-4 sort applies, so these equal the final ranks.
        lexical_order = sorted(
            lexical_positive,
            key=lambda item: sort_key(item[0], final=item[1]),
        )
        for rank, (candidate, _) in enumerate(lexical_order, start=1):
            candidate.fusion["lexical_rank"] = rank
        demoted = 0
        for rank, candidate in enumerate(
            sorted(fused, key=sort_key), start=1
        ):
            candidate.fusion["fused_rank"] = rank
            lexical_rank = candidate.fusion["lexical_rank"]
            if lexical_rank is not None:
                candidate.fusion["rank_delta"] = lexical_rank - rank
                demoted += int(rank > lexical_rank)
        result.semantic["fusion"] = {
            "profile": profile.to_metadata(),
            "eligible_count": len(active),
            "lexical_candidate_count": counts["lexical"],
            "semantic_candidate_count": counts["semantic"],
            "overlap_count": counts["overlap"],
            "lexical_only_count": counts["lexical_only"],
            "semantic_only_count": counts["semantic_only"],
            "union_count": len(fused),
            "promoted_by_semantic": counts["semantic_only"],
            "demoted_after_fusion": demoted,
        }
        return fused

    def _ranking_key(self, candidate, final=None):
        """The shared deterministic step-4 ranking tuple."""
        score = candidate.final_score if final is None else final
        return (
            -score,
            -(
                candidate.component_scores.get("phrase_score", 0.0)
                + candidate.component_scores.get("entity_score", 0.0)
            ),
            -candidate.kind_priority,
            -candidate.confidence,
            -candidate.memory.created_at.timestamp(),
            candidate.memory.id,
        )

    @staticmethod
    def _semantic_evidence(score, outcome) -> dict:
        return {
            "considered": True,
            "score": score.score,
            "raw_cosine": score.raw_cosine,
            "rank": score.rank,
            "above_floor": score.above_floor,
            "cache_status": score.cache_status,
            "relevance_floor": outcome.relevance_floor,
            "provider_id": outcome.provider_id,
            "model_id": outcome.model_id,
            "dimensions": outcome.dimensions,
        }

    def _coverage_selection(self, request, query, scored, result) -> int:
        """Delegate final selection to the configured coverage strategy.

        The strategy receives the full positive-relevance active pool
        (fusion ranks preserved) and returns a bounded subset in
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
