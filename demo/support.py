"""Support logic for the demo dashboard.

Kept free of Streamlit imports so provider selection, agent creation,
and event display logic stay testable without the demo extra installed.
"""

from __future__ import annotations

from demo.demo_config import DEMO_USER_ID
from demo.extraction_diagnostics import build_extraction_config
from experienceos import ExperienceOS
from experienceos.context import ContextBuilder, ExperienceCompressor
from experienceos.context.builder import MEMORY_HEADER
from experienceos.policy import LlamaCppLocalModelRunner, LocalModelMemoryPolicy
from experienceos.events.schema import EventType, ExperienceEvent
from experienceos.memory import InMemoryMemoryStore, SQLiteMemoryStore
from experienceos.providers import MockProvider, ModelProvider, QwenCloudProvider

PROVIDER_MOCK = "Mock (offline)"
PROVIDER_QWEN = "Qwen Cloud"
PROVIDER_CHOICES = [PROVIDER_MOCK, PROVIDER_QWEN]

STORAGE_IN_MEMORY = "In-memory"
STORAGE_SQLITE = "SQLite persistent"
STORAGE_CHOICES = [STORAGE_IN_MEMORY, STORAGE_SQLITE]
DEFAULT_SQLITE_PATH = ".experienceos/demo_memory.sqlite3"
# Slightly larger than the SDK default so the compression moment groups
# a meaningful number of travel memories while skipping stays visible.
DEMO_MEMORY_BUDGET = 6

QWEN_SETUP_HINT = (
    "Set QWEN_API_KEY (or DASHSCOPE_API_KEY), and QWEN_BASE_URL if your "
    "Model Studio workspace requires a regional endpoint."
)


def make_provider(choice: str = PROVIDER_MOCK) -> ModelProvider:
    """Build the selected provider. Mock is the default; never raises."""
    if choice == PROVIDER_QWEN:
        return QwenCloudProvider()
    return MockProvider()


def provider_status(provider: ModelProvider) -> str:
    if isinstance(provider, QwenCloudProvider):
        return "Configured" if provider.is_configured else "Missing credentials"
    return "Offline demo mode"


# -- canonical extraction controller selection -----------------------------

def qwen_extraction_configured(provider: ModelProvider) -> bool:
    """True when Qwen Cloud is present and holds credentials."""
    return isinstance(provider, QwenCloudProvider) and provider.is_configured


def build_canonical_extraction_config(mode: str, provider: ModelProvider):
    """Extraction config for a mode, using the canonical controller.

    Qwen extraction is canonical whenever Qwen Cloud is configured; the
    deterministic controller is the alternate implementation used
    offline, in tests, and for comparison benchmarks. Selection happens
    here, in composition, so the core package stays provider-neutral and
    the choice is made once against the same provider the agent uses.

    Qwen only proposes: the config flows through the existing
    integration seam, so the unchanged GroundedCandidateValidator and
    the engine's existing authority still decide everything downstream.
    There is no fallback and no retry — an unavailable or failing Qwen
    call is reported as an explicit non-candidate result, never silently
    swapped for a deterministic proposal.

    Extraction reuses the chat provider's credentials, endpoint, and
    model, but gets its own temperature-0, bounded-timeout provider: the
    validated extraction path must not inherit chat sampling settings.
    """
    # Reuse the mode guard so adopted mode stays unreachable from here.
    base = build_extraction_config(mode)
    if base is None or not qwen_extraction_configured(provider):
        return base
    from experienceos.memory.extraction_integration import (
        CONTROLLER_LEARNED,
        ExtractionIntegrationConfig,
    )
    from experiments.qwen_extraction import build_qwen_extraction_controller

    return ExtractionIntegrationConfig(
        effect_mode=base.effect_mode,
        controller_type=CONTROLLER_LEARNED,
        learned_controller=build_qwen_extraction_controller(
            api_key=provider.api_key,
            base_url=provider.base_url,
            model=provider.model,
        ),
    )


def make_memory_store(
    choice: str = STORAGE_IN_MEMORY, db_path: str = DEFAULT_SQLITE_PATH
):
    """Build the selected memory store. In-memory is the default."""
    if choice == STORAGE_SQLITE:
        return SQLiteMemoryStore(db_path)
    return InMemoryMemoryStore()


def storage_status(store) -> tuple[str, str]:
    """(storage label, database description) for the dashboard status panel."""
    if isinstance(store, SQLiteMemoryStore):
        return "SQLite", store.db_path
    return "In-memory", "none"


def build_canonical_transition_config():
    """The canonical adopted deterministic transition configuration.

    Fresh, immutable, provider-independent, and data-only: the two
    deterministic lifecycle controllers, the canonical verifier, and the
    bounded runtime authority — no store, no credentials, no user data, no
    precomputed proposal or replacement authorization, and no path to the
    experimental Qwen update controller. This is what makes the canonical
    chat path supersede and forget instead of only creating.
    """
    from experienceos.memory.forget_intelligence import (
        DeterministicForgetController,
    )
    from experienceos.memory.transition_authority import (
        BoundedRuntimeTransitionAuthority,
    )
    from experienceos.memory.transition_integration import (
        TransitionIntegrationConfig,
        TransitionIntegrationMode,
    )
    from experienceos.memory.transition_verification import TransitionVerifier
    from experienceos.memory.update_intelligence import (
        DeterministicUpdateController,
    )

    verifier = TransitionVerifier()
    return TransitionIntegrationConfig(
        mode=TransitionIntegrationMode.ADOPTED,
        update_controller=DeterministicUpdateController(verifier=verifier),
        forget_controller=DeterministicForgetController(verifier=verifier),
        verifier=verifier,
        runtime_authority=BoundedRuntimeTransitionAuthority(),
        planner_precedence=True,
    )


#: Sentinel: ``create_agent`` without an explicit ``transition`` argument
#: gets the canonical adopted config; an explicit ``transition=None`` keeps
#: transitions disabled (used by the dashboard's disabled selection).
_CANONICAL_TRANSITION = object()


def create_agent(
    provider: ModelProvider, memory_store=None, memory_policy=None,
    extraction=None, transition=_CANONICAL_TRANSITION,
) -> ExperienceOS:
    """Agent with fresh event history; memory store optional (in-memory default).

    The demo path enables experience compression so the dashboard can
    show related memories collapsing into compact context. SDK defaults
    remain uncompressed. ``memory_policy=None`` keeps the deterministic
    rule-based default; a local policy automatically gets the rule-based
    fallback from the SDK. ``extraction`` is an optional grounded-extraction
    config (None keeps grounded extraction disabled — the default); it can
    only ever be shadow or candidate here, which are non-mutating.
    ``transition`` defaults to the canonical adopted deterministic
    transition config so the canonical demo updates and forgets across
    sessions; an explicit config overrides it, and an explicit ``None``
    disables transitions (the dashboard's disabled/observational modes).
    """
    kwargs = {"memory_policy": memory_policy} if memory_policy is not None else {}
    if extraction is not None:
        kwargs["extraction"] = extraction
    if transition is _CANONICAL_TRANSITION:
        transition = build_canonical_transition_config()
    if transition is not None:
        kwargs["transition"] = transition
    return ExperienceOS(
        model=provider,
        memory_store=memory_store or InMemoryMemoryStore(),
        context_builder=ContextBuilder(
            memory_budget=DEMO_MEMORY_BUDGET,
            compressor=ExperienceCompressor(),
        ),
        **kwargs,
    )


def _truncate(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_event(event: ExperienceEvent) -> str:
    """One readable line per event for the dashboard event log."""
    p = event.payload
    if event.type == EventType.INTERACTION_STARTED:
        return _truncate(p.get("message", ""))
    if event.type == EventType.MEMORY_RETRIEVED:
        return f"{p.get('count', 0)} active memories retrieved."
    if event.type == EventType.CONTEXT_BUILT:
        selected = p.get("selected_memory_count", p.get("memory_count", 0))
        skipped = p.get("skipped_memory_count", 0)
        summary = f"Context built: {selected} selected, {skipped} skipped."
        summaries = p.get("compressed_summaries", [])
        if summaries:
            sources = sum(len(s.get("source_memory_ids", [])) for s in summaries)
            saved = sum(s.get("saved_chars", 0) for s in summaries)
            summary += (
                f" {sources} memories compressed into {len(summaries)} "
                f"summary (saved {saved} chars)."
            )
        return summary
    if event.type == EventType.MEMORY_ACTION_PLANNED:
        return f"{len(p.get('planned_actions', []))} create action(s) planned."
    if event.type == EventType.MEMORY_CREATED:
        return p.get("text", "")
    if event.type == EventType.MEMORY_SUPERSEDED:
        return f"Superseded: {p.get('text', '')}"
    if event.type == EventType.MEMORY_FORGOTTEN:
        return f"Forgotten: {p.get('text', '')}"
    if event.type == EventType.MODEL_CALLED:
        provider = p.get("provider", "provider")
        return f"{provider} called with {p.get('message_count', 0)} messages."
    if event.type == EventType.RESPONSE_RETURNED:
        return _truncate(p.get("response", ""))
    return ""


def safe_memory_metadata(memory) -> dict:
    """Memory metadata as a dict, tolerating None or wrong types."""
    metadata = getattr(memory, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def safe_memory_tags(memory) -> list[str]:
    """Memory tags, empty when metadata or tags are absent."""
    tags = safe_memory_metadata(memory).get("tags")
    return list(tags) if isinstance(tags, (list, tuple)) else []


def safe_memory_domain(memory) -> str | None:
    """Primary memory domain, or None when absent."""
    domain = safe_memory_metadata(memory).get("domain")
    return domain if isinstance(domain, str) and domain else None


def active_memory_rows(agent: ExperienceOS, user_id: str) -> list[dict]:
    """Display rows for active memories, tolerating missing metadata."""
    return [
        {
            "Memory": m.text,
            "Kind": m.kind,
            "Tags": ", ".join(safe_memory_tags(m)) or "—",
            "Status": m.status,
            "Source session": m.source_session_id or "—",
            "Created": m.created_at.strftime("%H:%M:%S"),
        }
        for m in agent.memories_for_user(user_id)
    ]


def selection_rows(records: list[dict] | None) -> list[dict]:
    """Display rows for selection records, tolerating missing fields."""
    rows = []
    for r in records or []:
        reason = r.get("reason") or ""
        rows.append(
            {
                "Decision": "Selected" if r.get("selected") else "Skipped",
                "Rank": r.get("rank", "—"),
                "Kind": r.get("kind", "—"),
                "Memory": r.get("text", ""),
                "Score": r.get("score", 0),
                "Matched keywords": ", ".join(r.get("matched_keywords") or []),
                "Domains": ", ".join(r.get("matched_domains") or []) or "—",
                "Reason": reason.split(": ", 1)[-1] if reason else "—",
            }
        )
    return rows


def summary_display(summary: dict | None) -> dict:
    """A compressed summary shaped safely for display."""
    summary = summary or {}
    return {
        "text": summary.get("text", ""),
        "source_texts": list(summary.get("source_texts") or []),
        "reason": summary.get("reason", ""),
        "original_chars": summary.get("original_chars", 0),
        "compressed_chars": summary.get("compressed_chars", 0),
        "saved_chars": summary.get("saved_chars", 0),
    }


def superseded_rows(agent: ExperienceOS, user_id: str) -> list[dict]:
    """Display rows for superseded memories, resolving replacement texts."""
    all_by_id = {m.id: m for m in agent.memories_for_user(user_id, status=None)}
    rows = []
    for m in agent.memories_for_user(user_id, status="superseded"):
        replacement = all_by_id.get(
            safe_memory_metadata(m).get("superseded_by", "")
        )
        rows.append(
            {
                "Memory": m.text,
                "Kind": m.kind,
                "Status": m.status,
                "Replaced by": replacement.text if replacement else "—",
                "Source session": m.source_session_id or "—",
                "Updated": m.updated_at.strftime("%H:%M:%S"),
            }
        )
    return rows


def forgotten_rows(agent: ExperienceOS, user_id: str) -> list[dict]:
    """Display rows for forgotten memories, kept visible as history."""
    rows = []
    for m in agent.memories_for_user(user_id, status="forgotten"):
        metadata = safe_memory_metadata(m)
        forgotten_at = metadata.get("forgotten_at", "")
        rows.append(
            {
                "Memory": m.text,
                "Kind": m.kind,
                "Status": m.status,
                "Reason": metadata.get("forget_reason", "—"),
                "Forgotten at": (
                    forgotten_at[:19].replace("T", " ") if forgotten_at else "—"
                ),
            }
        )
    return rows


def selection_summary(events: list[ExperienceEvent]) -> dict | None:
    """Budget and counts from the last turn's context selection."""
    for event in reversed(events):
        if event.type == EventType.CONTEXT_BUILT:
            p = event.payload
            return {
                "memory_budget": p.get("memory_budget"),
                "candidates": p.get("memory_count", 0),
                "selected": p.get("selected_memory_count", 0),
                "skipped": p.get("skipped_memory_count", 0),
            }
    return None


def selection_records(events: list[ExperienceEvent]) -> list[dict]:
    """Selection records from the last turn's context_built event."""
    for event in reversed(events):
        if event.type == EventType.CONTEXT_BUILT:
            return event.payload.get("selection_records", [])
    return []


def summarize_selection_record(record: dict) -> str:
    """One readable line per selection decision.

    e.g. "Selected: Home airport is SFO. — matched airport; fact
    priority; within budget"
    """
    prefix = "Selected" if record.get("selected") else "Skipped"
    reason = record.get("reason", "")
    detail = reason.split(": ", 1)[-1] if reason else ""
    return f"{prefix}: {record.get('text', '')} — {detail}"


def compressed_summaries(events: list[ExperienceEvent]) -> list[dict]:
    """Compressed summaries used in the last turn's context build."""
    for event in reversed(events):
        if event.type == EventType.CONTEXT_BUILT:
            return event.payload.get("compressed_summaries", [])
    return []


def compression_totals(summaries: list[dict]) -> dict:
    """Aggregate counts for the compressed-context display."""
    return {
        "count": len(summaries),
        "source_count": sum(len(s.get("source_memory_ids", [])) for s in summaries),
        "original_chars": sum(s.get("original_chars", 0) for s in summaries),
        "compressed_chars": sum(s.get("compressed_chars", 0) for s in summaries),
        "saved_chars": sum(s.get("saved_chars", 0) for s in summaries),
    }


POLICY_RULE_BASED = "Rule-based (deterministic)"
POLICY_LOCAL_MODEL = "Local model (optional)"
POLICY_CHOICES = [POLICY_RULE_BASED, POLICY_LOCAL_MODEL]


def make_memory_policy(choice: str = POLICY_RULE_BASED):
    """Build the selected memory policy; None means the SDK default.

    The local choice never loads a model — availability stays a shallow
    check, and an unavailable runtime simply means every decision falls
    back to the deterministic rules.
    """
    if choice == POLICY_LOCAL_MODEL:
        return LocalModelMemoryPolicy(LlamaCppLocalModelRunner())
    return None


def policy_provenance(events: list[ExperienceEvent]) -> dict | None:
    """Bounded provenance from the last planning event; None before any.

    Tolerates older or partial payloads: every field falls back to the
    rule-based defaults so pre-provenance events still render safely.
    """
    for event in reversed(events):
        if event.type != EventType.MEMORY_ACTION_PLANNED:
            continue
        payload = event.payload or {}
        policy = payload.get("policy") or {}
        mode = policy.get("mode", "rule_based")
        return {
            "mode": mode,
            "decision_source": policy.get("decision_source", mode),
            "fallback_used": bool(policy.get("fallback_used", False)),
            "fallback_reason": policy.get("fallback_reason"),
            "planned": list(payload.get("planned_actions") or []),
            "rejected": list(payload.get("rejected_actions") or []),
        }
    return None


def memory_intelligence_summary(provenance: dict | None) -> str:
    """One judge-readable line describing the last memory decision."""
    if provenance is None:
        return "No memory decisions yet."
    rejected = len(provenance["rejected"])
    reasons = ", ".join(
        sorted(
            {
                str(r.get("rejected_reason", "target_not_active")).replace(
                    "_", " "
                )
                for r in provenance["rejected"]
            }
        )
    )
    rejected_note = (
        f" {rejected} proposal(s) rejected by lifecycle validation "
        f"({reasons}) — no fallback."
        if rejected
        else ""
    )
    if provenance["fallback_used"]:
        return (
            f"Local decision rejected — rule-based fallback used "
            f"({provenance['fallback_reason']}).{rejected_note}"
        )
    if provenance["mode"] == "local_model":
        if provenance["planned"]:
            return f"Local model decisions accepted.{rejected_note}"
        if rejected:
            return rejected_note.strip()
        return "No memory action proposed (local model)."
    if provenance["planned"]:
        return f"Rule-based decision.{rejected_note}"
    return "No memory action proposed (rule-based)."


def decision_rows(provenance: dict | None) -> list[dict]:
    """Display rows for planned and rejected decisions, .get-safe."""
    if provenance is None:
        return []
    rows = []
    for action in provenance["planned"]:
        rows.append(
            {
                "Decision": "Accepted",
                "Action": action.get("action", "—"),
                "Memory": action.get("text", ""),
                "Source": action.get("decision_source", "rule_based"),
                "Confidence": action.get("confidence", "—"),
                "Explanation": action.get("explanation")
                or action.get("reason")
                or "—",
            }
        )
    for action in provenance["rejected"]:
        rows.append(
            {
                "Decision": "Rejected",
                "Action": action.get("action", "—"),
                "Memory": action.get("text", ""),
                "Source": action.get("decision_source", "—"),
                "Confidence": action.get("confidence", "—"),
                "Explanation": action.get("rejected_reason", "target_not_active"),
            }
        )
    return rows


def local_runtime_status(agent: ExperienceOS) -> dict:
    """Bounded projection of local runtime availability for display.

    Shallow only: rendering the dashboard never loads a model. The
    labels distinguish shallow readiness from an actual loaded model.
    """
    manager = agent.experience_manager
    policy = getattr(manager, "policy", None)
    runner = getattr(policy, "runner", None)
    if manager.policy_mode != "local_model" or runner is None:
        return {
            "configured": False,
            "label": "Not configured",
            "reason": None,
            "detail": "Default rule-based mode — no local runtime involved.",
        }
    availability = runner.availability()
    if availability.available:
        label = "Available (shallow check — model loads on first decision)"
    elif availability.reason == "model_load_failed":
        label = "Load failed"
    else:
        label = "Unavailable"
    return {
        "configured": True,
        "label": label,
        "reason": availability.reason,
        "detail": availability.detail,
    }


def reset_demo_state(agent: ExperienceOS, user_id: str = DEMO_USER_ID) -> None:
    """Return the demo to a known clean state for the given user.

    Removes the user's memories in every lifecycle status (works for
    both the in-memory and SQLite stores) and clears the in-process
    event history — which also empties every event-derived display:
    timeline, growth metrics, selection records, compressed summaries,
    and supplied context.
    """
    agent.memory_store.clear_user_memories(user_id)
    agent.event_bus.clear()


def growth_metrics(agent: ExperienceOS, user_id: str) -> dict:
    """Transparent counts showing accumulated experience over time."""
    events = agent.events

    def count(event_type: str) -> int:
        return sum(1 for e in events if e.type == event_type)

    compressed = [
        s
        for e in events
        if e.type == EventType.CONTEXT_BUILT
        for s in e.payload.get("compressed_summaries", [])
    ]
    return {
        "active_memories": len(agent.memories_for_user(user_id)),
        "created_memories": count(EventType.MEMORY_CREATED),
        "recalls": sum(
            1
            for e in events
            if e.type == EventType.MEMORY_RETRIEVED and e.payload.get("count", 0) > 0
        ),
        "updated_memories": count(EventType.MEMORY_SUPERSEDED),
        "forgotten_memories": count(EventType.MEMORY_FORGOTTEN),
        "compressed_summaries_used": len(compressed),
        "context_saved_chars": sum(s.get("saved_chars", 0) for s in compressed),
    }


def lifecycle_timeline(events: list[ExperienceEvent]) -> list[dict]:
    """Readable per-turn history of how experience changed."""
    created_texts = {
        e.payload.get("memory_id"): e.payload.get("text", "")
        for e in events
        if e.type == EventType.MEMORY_CREATED
    }
    replacement_ids = {
        e.payload.get("superseded_by")
        for e in events
        if e.type == EventType.MEMORY_SUPERSEDED
    } - {None}

    rows: list[dict] = []
    turn = 0
    for e in events:
        if e.type == EventType.INTERACTION_STARTED:
            turn += 1
        elif e.type == EventType.MEMORY_CREATED:
            # Replacements are covered by their "Updated" row.
            if e.payload.get("memory_id") not in replacement_ids:
                rows.append(
                    {"Turn": turn, "Event": "Remembered",
                     "Summary": e.payload.get("text", "")}
                )
        elif e.type == EventType.MEMORY_SUPERSEDED:
            new_text = created_texts.get(
                e.payload.get("superseded_by"), "a newer memory"
            )
            rows.append(
                {"Turn": turn, "Event": "Updated",
                 "Summary": f"{e.payload.get('text', '')} → {new_text}"}
            )
        elif e.type == EventType.MEMORY_FORGOTTEN:
            rows.append(
                {"Turn": turn, "Event": "Forgot",
                 "Summary": e.payload.get("text", "")}
            )
        elif e.type == EventType.CONTEXT_BUILT:
            selected = e.payload.get("selected_memory_count", 0)
            if selected:
                rows.append(
                    {"Turn": turn, "Event": "Recalled",
                     "Summary": f"{selected} selected, "
                                f"{e.payload.get('skipped_memory_count', 0)} skipped"}
                )
            summaries = e.payload.get("compressed_summaries", [])
            if summaries:
                sources = sum(
                    len(s.get("source_memory_ids", [])) for s in summaries
                )
                saved = sum(s.get("saved_chars", 0) for s in summaries)
                rows.append(
                    {"Turn": turn, "Event": "Compressed",
                     "Summary": f"{sources} memories → {len(summaries)} "
                                f"summary, saved {saved} chars"}
                )
    return rows


def supplied_context_lines(events: list[ExperienceEvent]) -> list[str]:
    """Experience lines ExperienceOS supplied to the provider on the last turn."""
    for event in reversed(events):
        if event.type != EventType.CONTEXT_BUILT:
            continue
        for message in event.payload.get("context_messages", []):
            content = message.get("content", "")
            if message.get("role") == "system" and MEMORY_HEADER in content:
                return [
                    line[2:].strip()
                    for line in content.splitlines()
                    if line.startswith("- ")
                ]
        return []
    return []


# ---------------------------------------------------------------------------
# Phase 11 retrieval diagnostics (Prompt 8). Pure, Streamlit-free,
# tolerant helpers: they read recorded event evidence and committed
# report data only — they never construct providers, load models,
# recompute retrieval, or mutate anything.
# ---------------------------------------------------------------------------

LIFECYCLE_AUTHORITY_NOTICE = (
    "Lifecycle rules are applied before semantic scoring. Embeddings "
    "and the shadow gate can rank or propose, but they cannot "
    "reactivate forgotten experience, override supersession, or "
    "bypass the context budget."
)

PHASE11_REPORT_DATA_PATH = (
    "benchmarks/results/committed/report-phase11/report_data_phase11.json"
)
PHASE11_ADOPTION_PATH = (
    "benchmarks/results/committed/report-phase11/"
    "adoption_gates_phase11.json"
)
PHASE11_REPORT_DOC = "docs/phase11_semantic_retrieval_report.md"

_HARD_LIFECYCLE_PREFIX = "inactive_"
_RELEVANCE_EXCLUSIONS = (
    "zero_relevance", "below_semantic_floor", "no_fused_evidence",
)
_LIMIT_EXCLUSIONS = ("below_candidate_limit",)
_BUDGET_EXCLUSIONS = ("token_budget",)


def format_score(value, precision: int = 3) -> str:
    """Safe display for possibly missing/malformed score values."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number or number in (float("inf"), float("-inf")):
        return "—"
    return f"{number:.{precision}f}"


def format_ms(value) -> str:
    """Safe milliseconds display; absent timing is never fabricated."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number or number < 0 or number == float("inf"):
        return "—"
    return f"{number:.1f} ms"


def format_flag(value) -> str:
    if value is None:
        return "—"
    return "Yes" if value else "No"


def format_rate(numerator, denominator) -> str:
    try:
        return f"{int(numerator)}/{int(denominator)}"
    except (TypeError, ValueError):
        return "—"


def exclusion_kind(reason) -> str:
    """Classify a canonical exclusion reason by its authority level.

    Hard lifecycle exclusions (forgotten/superseded records) are not
    the same kind of decision as relevance exclusions, ranking skips,
    or budget skips — the display keeps them distinct.
    """
    if not reason or not isinstance(reason, str):
        return "selected"
    if reason.startswith(_HARD_LIFECYCLE_PREFIX):
        return "lifecycle"
    if reason in _RELEVANCE_EXCLUSIONS:
        return "relevance"
    if reason in _BUDGET_EXCLUSIONS:
        return "budget"
    if reason in _LIMIT_EXCLUSIONS:
        return "candidate_limit"
    return "selection"


EXCLUSION_KIND_LABELS = {
    "selected": "Selected",
    "lifecycle": "Lifecycle exclusion (authoritative)",
    "relevance": "No query relevance",
    "candidate_limit": "Candidate-limit exclusion",
    "selection": "Ranking skip",
    "budget": "Token-budget skip",
}


def retrieval_diagnostics(events: list[ExperienceEvent]) -> dict | None:
    """Bounded Phase 11 retrieval summary from the last context event.

    Returns None before any retrieval; every field is guarded so old
    (Phase 8/9) events without diagnostics render safely.
    """
    for event in reversed(events):
        if event.type != EventType.CONTEXT_BUILT:
            continue
        payload = event.payload or {}
        diagnostics = payload.get("retrieval_diagnostics") or {}
        semantic = diagnostics.get("semantic") or {}
        gate = diagnostics.get("gate") or {}
        fusion = semantic.get("fusion") or {}
        profile = fusion.get("profile") or {}
        return {
            "retrieval_mode": diagnostics.get(
                "retrieval_mode", "disabled"
            ),
            "embedding_enabled": bool(semantic.get("enabled", False)),
            "provider_id": semantic.get("provider_id"),
            "model_id": semantic.get("model_id"),
            "dimensions": semantic.get("dimensions"),
            "provider_available": semantic.get("provider_available"),
            "semantic_floor": semantic.get("relevance_floor"),
            "fallback_used": semantic.get("fallback_used", False),
            "fallback_reason": semantic.get("fallback_reason"),
            "fallback_path": semantic.get("fallback_path"),
            "fusion_profile": profile.get("profile_id")
            or semantic.get("fusion_profile_id"),
            "fusion_profile_version": profile.get("version"),
            "eligible_count": diagnostics.get("eligible_count"),
            "lifecycle_excluded_count": diagnostics.get(
                "lifecycle_excluded_count"
            ),
            "semantic_candidate_count": semantic.get(
                "semantic_candidate_count"
            ),
            "union_count": fusion.get("union_count"),
            "post_limit_count": fusion.get("post_limit_count"),
            "cache": semantic.get("cache") or None,
            "context_token_estimate": diagnostics.get(
                "context_token_estimate"
            ),
            "k": diagnostics.get("k"),
            "budget_compliant": diagnostics.get("budget_compliant"),
            "gate_enabled": bool(gate.get("enabled", False)),
            "gate_controller_id": gate.get("controller_id"),
            "gate_status": gate.get("status"),
            "gate_shadow_mode": gate.get("shadow_mode"),
            "gate_affected_selection": gate.get("affected_selection", 0),
            "selected": payload.get("selected_memory_count", 0),
        }
    return None


def gate_shadow_summary(events: list[ExperienceEvent]) -> dict | None:
    """Shadow-gate tallies from the last context event; None when no
    gate is configured or the event predates Phase 11."""
    for event in reversed(events):
        if event.type != EventType.CONTEXT_BUILT:
            continue
        gate = (event.payload or {}).get(
            "retrieval_diagnostics", {}
        ).get("gate") or {}
        if not gate.get("enabled"):
            return None
        return {
            "controller_id": gate.get("controller_id", "—"),
            "evaluated": gate.get("evaluated", 0),
            "admit": gate.get("admit", 0),
            "reject": gate.get("reject", 0),
            "abstain": gate.get("abstain", 0),
            "agreement": gate.get("agreement", 0),
            "disagreement": gate.get("disagreement", 0),
            "failures": gate.get("failures", 0),
            "affected_selection": gate.get("affected_selection", 0),
            "status": gate.get("status", "—"),
        }
    return None


def _gate_cell(record_gate) -> str:
    if not isinstance(record_gate, dict) or not record_gate.get(
        "considered"
    ):
        return "—"
    if record_gate.get("status") == "failed":
        return "Shadow eval failed (contained)"
    proposal = str(record_gate.get("proposal", "—")).capitalize()
    return f"Shadow: {proposal}"


def phase11_candidate_rows(records: list[dict] | None) -> list[dict]:
    """Phase 11 columns for the selection table, preserving canonical
    audit order; safe on old records without Phase 11 fields."""
    rows = []
    for record in records or []:
        reason = record.get("exclusion_reason")
        kind = (
            "selected" if record.get("selected") else
            exclusion_kind(reason or "not_top_k")
        )
        semantic = record.get("semantic")
        fusion = record.get("fusion")
        semantic_score = (
            semantic.get("score")
            if isinstance(semantic, dict) and semantic.get("considered")
            else None
        )
        rows.append(
            {
                "Decision": EXCLUSION_KIND_LABELS.get(kind, "Skipped"),
                "Kind": record.get("kind", "—"),
                "Memory": str(record.get("text", ""))[:120],
                "Score": format_score(record.get("score")),
                "Semantic": format_score(semantic_score),
                "Fused": format_score(
                    fusion.get("fused_score")
                    if isinstance(fusion, dict) else None
                ),
                "Evidence": (
                    fusion.get("evidence_source", "—")
                    if isinstance(fusion, dict) else "—"
                ),
                "Cache": (
                    semantic.get("cache_status", "—")
                    if isinstance(semantic, dict)
                    and semantic.get("considered") else "—"
                ),
                "Shadow gate": _gate_cell(record.get("gate")),
            }
        )
    return rows


def candidate_detail(record: dict) -> dict:
    """Bounded per-candidate detail for an expander view. Never
    includes vectors, paths, or raw exceptions."""
    semantic = record.get("semantic")
    fusion = record.get("fusion")
    gate = record.get("gate")
    detail = {
        "canonical": {
            "lifecycle_status": record.get("status", "—"),
            "selected": format_flag(record.get("selected")),
            "reason": record.get("reason", "—"),
            "exclusion_kind": EXCLUSION_KIND_LABELS.get(
                "selected" if record.get("selected") else
                exclusion_kind(record.get("exclusion_reason")
                               or "not_top_k")
            ),
            "rank": record.get("rank", "—"),
        },
        "component_scores": {
            name: format_score(value)
            for name, value in (
                record.get("component_scores") or {}
            ).items()
        },
    }
    if isinstance(semantic, dict):
        if semantic.get("considered"):
            detail["semantic"] = {
                "provider": f"{semantic.get('provider_id', '—')} / "
                            f"{semantic.get('model_id', '—')}",
                "dimensions": semantic.get("dimensions", "—"),
                "raw_cosine": format_score(semantic.get("raw_cosine")),
                "score": format_score(semantic.get("score")),
                "floor": format_score(semantic.get("relevance_floor")),
                "above_floor": format_flag(semantic.get("above_floor")),
                "semantic_rank": semantic.get("rank", "—"),
                "cache": semantic.get("cache_status", "—"),
            }
        else:
            detail["semantic"] = {"considered": "No (never embedded)"}
    if isinstance(fusion, dict):
        detail["fusion"] = {
            "profile": f"{fusion.get('profile_id', '—')} v"
                       f"{fusion.get('profile_version', '—')}",
            "normalization": fusion.get("normalization_id", "—"),
            "raw": {k: format_score(v)
                    for k, v in (fusion.get("raw") or {}).items()},
            "normalized": {
                k: format_score(v)
                for k, v in (fusion.get("normalized") or {}).items()
            },
            "weights": fusion.get("weights") or {},
            "contributions": {
                k: format_score(v)
                for k, v in (fusion.get("contributions") or {}).items()
            },
            "fused_score": format_score(fusion.get("fused_score")),
            "evidence_source": fusion.get("evidence_source", "—"),
            "lexical_rank": fusion.get("lexical_rank", "—"),
            "fused_rank": fusion.get("fused_rank", "—"),
            "rank_delta": fusion.get("rank_delta", "—"),
        }
    if isinstance(gate, dict):
        if gate.get("considered"):
            if gate.get("status") == "failed":
                detail["shadow_gate"] = {
                    "status": "Evaluation failed (contained; canonical "
                              "selection preserved)",
                    "failure_type": gate.get("failure", "—"),
                }
            else:
                detail["shadow_gate"] = {
                    "controller": gate.get("controller_id", "—"),
                    "shadow_proposal": str(
                        gate.get("proposal", "—")
                    ).capitalize(),
                    "confidence": format_score(gate.get("confidence")),
                    "reason": str(gate.get("reason", "—"))[:160],
                    "canonical_result": (
                        "Selected" if gate.get("canonical_selected")
                        else "Skipped"
                    ),
                    "agreement": gate.get(
                        "agreement_with_selection", "—"
                    ),
                    "affected_selection": "No",
                }
        else:
            detail["shadow_gate"] = {"considered": "No"}
    return detail


def phase11_benchmark_summary(
    report_data_path: str = PHASE11_REPORT_DATA_PATH,
    adoption_path: str = PHASE11_ADOPTION_PATH,
) -> dict | None:
    """Compact Prompt 7 summary read from committed report data.

    Returns None when the committed artifacts are missing or
    malformed — the dashboard shows an unavailable state and never
    regenerates or recomputes benchmark evidence.
    """
    import json
    from pathlib import Path

    try:
        data = json.loads(Path(report_data_path).read_text())
        gates = json.loads(Path(adoption_path).read_text())
        external = data["external"]

        def row(system):
            cells = external[system]
            return {
                "selection": format_rate(
                    cells["answer_session_selection_rate"]["numerator"],
                    cells["answer_session_selection_rate"][
                        "denominator"
                    ],
                ),
                "mrr": format_score(
                    cells["answer_session_mrr"]["value"]
                ),
                "tokens": cells["context_tokens_total"],
            }

        return {
            "reference": row("experienceos_hybrid_full_v2_reference"),
            "embedding_only": row("experienceos_embedding_only_v1"),
            "fused": row("experienceos_fused_retrieval_v1"),
            "classifications": {
                "embedding_only": gates["experienceos_embedding_only_v1"][
                    "classification"
                ],
                "fused": gates["experienceos_fused_retrieval_v1"][
                    "classification"
                ],
                "gate_shadow": gates["experienceos_gate_shadow_v1"][
                    "classification"
                ],
            },
            "gate_affected_selection": data["gate_shadow"]["external"][
                "gate_affected_selection"
            ],
            "provider_note": (
                "Committed semantic results use the deterministic test "
                "embedding provider. They do not establish "
                "learned-embedding quality, and none of this is an "
                "official LongMemEval score."
            ),
            "report_doc": PHASE11_REPORT_DOC,
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None
