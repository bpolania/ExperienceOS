"""Context builder.

Selects the most relevant active memories within a budget and assembles
the context messages sent to the model provider. Selection is
deterministic: keyword overlap with the current message, then kind
priority (instructions > facts > preferences), then recency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from experienceos.context.compression import ExperienceCompressor, ExperienceSummary
from experienceos.memory.schema import ExperienceEntry, MemoryKind
from experienceos.memory.tags import TAG_ORDER, assign_tags

MEMORY_HEADER = "ExperienceOS retrieved these active user experiences:"
DEFAULT_MEMORY_BUDGET = 4

_KIND_SECTIONS = (
    (MemoryKind.PREFERENCE, "Preferences:"),
    (MemoryKind.FACT, "Facts:"),
    (MemoryKind.INSTRUCTION, "Instructions:"),
)

# Instructions guide behavior, facts anchor it, preferences flavor it.
_KIND_PRIORITY = {
    MemoryKind.INSTRUCTION: 2,
    MemoryKind.FACT: 1,
    MemoryKind.PREFERENCE: 0,
}

_SELECTION_STOPWORDS = frozenset(
    {
        "a", "an", "and", "the", "to", "of", "for", "with", "in", "on",
        "at", "is", "are", "be", "it", "me", "my", "i", "you", "we",
        "help", "please", "when", "that", "this",
    }
)


def _selection_words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in _SELECTION_STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        words.add(word)
    return words


@dataclass
class ContextSelectionRecord:
    """Why one candidate memory was selected or skipped."""

    memory_id: str
    text: str
    kind: str
    status: str
    selected: bool
    rank: int
    score: int
    matched_keywords: list[str]
    kind_priority: int
    reason: str
    tags: list[str] = field(default_factory=list)
    matched_domains: list[str] = field(default_factory=list)
    # Hybrid-retrieval extensions (empty on the default v1 path).
    component_scores: dict = field(default_factory=dict)
    exclusion_reason: str | None = None
    # Phase 11 diagnostics (None whenever the feature is disabled, so
    # earlier configurations serialize with null-valued additive keys
    # and old consumers keep working via .get()).
    semantic: dict | None = None
    fusion: dict | None = None
    gate: dict | None = None


@dataclass
class ContextBuildResult:
    """Messages plus the selection decisions behind them."""

    messages: list[dict[str, str]]
    selected_memories: list[ExperienceEntry] = field(default_factory=list)
    skipped_memories: list[ExperienceEntry] = field(default_factory=list)
    candidate_memories: list[ExperienceEntry] = field(default_factory=list)
    memory_budget: int | None = None
    selection_records: list[ContextSelectionRecord] = field(default_factory=list)
    summaries: list[ExperienceSummary] = field(default_factory=list)
    # Phase 11: bounded retrieval-level diagnostics (mode, provider,
    # fallback, gate summary, counts); empty on the legacy path and
    # for pre-Phase 11 strategies.
    retrieval_diagnostics: dict = field(default_factory=dict)


class ContextBuilder:
    """Builds provider context messages for one interaction."""

    def __init__(
        self,
        memory_budget: int = DEFAULT_MEMORY_BUDGET,
        compressor: ExperienceCompressor | None = None,
        retrieval_strategy=None,
    ):
        self.memory_budget = memory_budget
        self.compressor = compressor
        # Optional Phase 9 seam: when None (the default and every v1
        # configuration), selection below is byte-identical to Phase 8.
        self.retrieval_strategy = retrieval_strategy

    @property
    def wants_inactive_candidates(self) -> bool:
        """Whether the engine should pass superseded records too (an
        explicit temporal-retrieval capability; False on every v1 and
        earlier v2 configuration)."""
        return bool(
            getattr(self.retrieval_strategy, "includes_historical", False)
        )

    def build_context(
        self,
        user_id: str,
        session_id: str,
        message: str,
        memories: list[ExperienceEntry] | None = None,
    ) -> ContextBuildResult:
        candidates = list(memories or [])
        retrieval_diagnostics: dict = {}
        if self.retrieval_strategy is not None:
            selected, skipped, records, retrieval_diagnostics = (
                self._strategy_selection(session_id, message, candidates)
            )
        else:
            ranked = self._rank_candidates(message, candidates)
            selected = [m for m, _, _ in ranked[: self.memory_budget]]
            skipped = [m for m, _, _ in ranked[self.memory_budget :]]
            request_tags = set(assign_tags(message))
            records = [
                self._selection_record(
                    rank, memory, matched, priority, request_tags
                )
                for rank, (memory, matched, priority) in enumerate(
                    ranked, start=1
                )
            ]

        summaries: list[ExperienceSummary] = []
        compressed_ids: set[str] = set()
        if self.compressor and selected:
            # Keep only summaries that actually shrink the rendered context.
            summaries = [
                s
                for s in self.compressor.compress(selected)
                if s.compressed_chars < s.original_chars
            ]
            compressed_ids = {
                memory_id for s in summaries for memory_id in s.source_memory_ids
            }
        rendered = [m for m in selected if m.id not in compressed_ids]

        context: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "ExperienceOS is active. Use any retrieved user "
                    "experience to personalize responses."
                ),
            }
        ]
        if selected:
            annotator = getattr(
                self.retrieval_strategy, "annotate_memory", None
            )
            blocks = [s.text for s in summaries] + self._kind_sections(
                rendered, annotator
            )
            context.append(
                {"role": "system", "content": f"{MEMORY_HEADER}\n\n" + "\n\n".join(blocks)}
            )
        return ContextBuildResult(
            messages=context,
            selected_memories=selected,
            skipped_memories=skipped,
            candidate_memories=candidates,
            memory_budget=self.memory_budget,
            selection_records=records,
            summaries=summaries,
            retrieval_diagnostics=retrieval_diagnostics,
        )

    def select_memories(
        self, message: str, candidates: list[ExperienceEntry]
    ) -> tuple[list[ExperienceEntry], list[ExperienceEntry]]:
        """Deterministically rank candidates and split at the budget."""
        if self.retrieval_strategy is not None:
            selected, skipped, _, _ = self._strategy_selection(
                "", message, candidates
            )
            return selected, skipped
        ranked = [m for m, _, _ in self._rank_candidates(message, candidates)]
        return ranked[: self.memory_budget], ranked[self.memory_budget :]

    def _strategy_selection(
        self,
        session_id: str,
        message: str,
        candidates: list[ExperienceEntry],
    ) -> tuple[list, list, list]:
        """Delegate ranking to the configured retrieval strategy.

        The strategy filters lifecycle-invalid records before ranking
        and never pads the selection with zero-relevance memories; this
        method translates its audited candidates into the existing
        selection-record shape so events, benchmarks, and the dashboard
        keep working unchanged. Context assembly (compression, kind
        sections, budget semantics) stays in build_context — there is
        exactly one context path.
        """
        from experienceos.context.retrieval import RetrievalRequest

        result = self.retrieval_strategy.retrieve(
            RetrievalRequest(
                query=message,
                memories=tuple(candidates),
                k=self.memory_budget,
                session_id=session_id,
            )
        )
        selected = list(result.selected)
        skipped = [
            c.memory
            for c in result.candidates
            if not c.selected and c.status == "active"
        ]
        # Ranked candidates first (rank order); unranked (inactive,
        # zero-relevance) keep their deterministic append order —
        # never runtime IDs, which vary across runs.
        ranked = sorted(
            result.candidates, key=lambda c: (c.rank == 0, c.rank)
        )
        records = []
        display_rank = 0
        for candidate in ranked:
            display_rank += 1
            if candidate.selected:
                reason = (
                    "selected: "
                    + (
                        f"matched {', '.join(candidate.matched_tokens)}"
                        if candidate.matched_tokens
                        else "structured match"
                    )
                    + f"; score {candidate.final_score}; within budget"
                )
            else:
                reason = (
                    f"skipped: {candidate.exclusion_reason or 'not_top_k'}"
                )
            memory = candidate.memory
            tags = memory.metadata.get("tags") or assign_tags(memory.text)
            records.append(
                ContextSelectionRecord(
                    memory_id=memory.id,
                    text=memory.text,
                    kind=memory.kind,
                    status=memory.status,
                    selected=candidate.selected,
                    rank=display_rank,
                    score=candidate.final_score,
                    matched_keywords=list(candidate.matched_tokens),
                    kind_priority=candidate.kind_priority,
                    reason=reason,
                    tags=list(tags),
                    matched_domains=list(candidate.matched_domains),
                    component_scores=dict(candidate.component_scores),
                    exclusion_reason=candidate.exclusion_reason,
                    semantic=getattr(candidate, "semantic", None),
                    fusion=getattr(candidate, "fusion", None),
                    gate=getattr(candidate, "gate", None),
                )
            )
        diagnostics = {
            "strategy": getattr(result, "strategy", None),
            "retrieval_mode": (
                (result.semantic or {}).get("mode", "disabled")
                if hasattr(result, "semantic")
                else "disabled"
            ),
            "semantic": dict(getattr(result, "semantic", {}) or {}),
            "gate": dict(getattr(result, "gate", {}) or {}),
            "eligible_count": getattr(result, "active_count", None),
            "lifecycle_excluded_count": getattr(
                result, "inactive_filtered", None
            ),
            "context_token_estimate": getattr(
                result, "context_token_estimate", None
            ),
            "k": getattr(result, "k", None),
            "k_compliant": getattr(result, "k_compliant", None),
            "budget_compliant": getattr(result, "budget_compliant", None),
        }
        return selected, skipped, records, diagnostics

    @staticmethod
    def _rank_candidates(
        message: str, candidates: list[ExperienceEntry]
    ) -> list[tuple[ExperienceEntry, list[str], int]]:
        """Candidates with their matched keywords and kind priority,
        sorted by relevance, kind priority, recency, then id."""
        message_words = _selection_words(message)
        scored = [
            (
                memory,
                sorted(_selection_words(memory.text) & message_words),
                _KIND_PRIORITY.get(memory.kind, 0),
            )
            for memory in candidates
        ]
        scored.sort(
            key=lambda entry: (
                -len(entry[1]),
                -entry[2],
                -entry[0].created_at.timestamp(),
                entry[0].id,
            )
        )
        return scored

    def _selection_record(
        self,
        rank: int,
        memory: ExperienceEntry,
        matched: list[str],
        priority: int,
        request_tags: set[str],
    ) -> ContextSelectionRecord:
        selected = rank <= self.memory_budget
        tags = memory.metadata.get("tags") or assign_tags(memory.text)
        matched_domains = [t for t in TAG_ORDER if t in tags and t in request_tags]
        if selected:
            parts = [
                f"matched {', '.join(matched)}" if matched else "no keyword match"
            ]
            if matched_domains:
                parts.append(f"domains {' + '.join(matched_domains)}")
            parts.append(f"{memory.kind} priority")
            parts.append("within budget")
            reason = "selected: " + "; ".join(parts)
        else:
            if tags and not matched_domains:
                lead = (
                    f"its {tags[0]} experience was less relevant to this request"
                )
            else:
                lead = "lower relevance than selected memories"
            reason = (
                f"skipped: {lead}; budget reached after "
                f"{self.memory_budget} selected memories"
            )
        return ContextSelectionRecord(
            memory_id=memory.id,
            text=memory.text,
            kind=memory.kind,
            status=memory.status,
            selected=selected,
            rank=rank,
            score=len(matched),
            matched_keywords=matched,
            kind_priority=priority,
            reason=reason,
            tags=list(tags),
            matched_domains=matched_domains,
        )

    @staticmethod
    def _kind_sections(
        memories: list[ExperienceEntry], annotator=None
    ) -> list[str]:
        """Memories grouped under kind labels, known kinds first.
        ``annotator`` (temporal configurations only) appends concise
        bounded labels; None renders exactly the Phase 8 format."""
        known_kinds = {kind for kind, _ in _KIND_SECTIONS}
        groups = [
            *_KIND_SECTIONS,
            *(((m.kind, f"{m.kind.capitalize()}:") for m in memories
               if m.kind not in known_kinds)),
        ]

        def line(memory) -> str:
            suffix = annotator(memory) if annotator is not None else ""
            return f"- {memory.text}{suffix}"

        sections, rendered = [], set()
        for kind, label in groups:
            if kind in rendered:
                continue
            rendered.add(kind)
            group = [m for m in memories if m.kind == kind]
            if group:
                sections.append(
                    label + "\n" + "\n".join(line(m) for m in group)
                )
        return sections
