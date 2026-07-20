"""ExperienceOS dashboard (Streamlit).

Makes the experience layer visible: chat on the left, and the platform's
internals — active memories, supplied context, and the live event
lifecycle — on the right.

Run:

    pip install -e ".[demo]"
    PYTHONPATH=. streamlit run demo/app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import streamlit as st
except ImportError:
    sys.exit(
        "Streamlit is not installed. Install the demo extra first:\n"
        '    pip install -e ".[demo]"\n'
        "then run:\n"
        "    PYTHONPATH=. streamlit run demo/app.py"
    )

if not st.runtime.exists():
    sys.exit("Run this dashboard with: PYTHONPATH=. streamlit run demo/app.py")

from demo.demo_config import (
    DEMO_NOTE,
    DEMO_TITLE,
    DEMO_USER_ID,
    SCRIPTED_DEMO,
    TAGLINE,
)
from demo.env import load_local_env

load_local_env()  # optional .env with Qwen credentials; env vars win
from demo.support import (
    PROVIDER_CHOICES,
    PROVIDER_MOCK,
    QWEN_SETUP_HINT,
    POLICY_CHOICES,
    POLICY_LOCAL_MODEL,
    POLICY_RULE_BASED,
    STORAGE_CHOICES,
    STORAGE_IN_MEMORY,
    active_memory_rows,
    build_canonical_extraction_config,
    compressed_summaries,
    compression_totals,
    create_agent,
    decision_rows,
    forgotten_rows,
    growth_metrics,
    lifecycle_timeline,
    local_runtime_status,
    make_memory_policy,
    make_memory_store,
    make_provider,
    memory_intelligence_summary,
    policy_provenance,
    provider_status,
    reset_demo_state,
    selection_records,
    selection_rows,
    selection_summary,
    storage_status,
    summarize_event,
    summary_display,
    superseded_rows,
    supplied_context_lines,
)
from demo.support import (
    LIFECYCLE_AUTHORITY_NOTICE,
    candidate_detail,
    format_flag,
    format_score,
    gate_shadow_summary,
    phase11_benchmark_summary,
    phase11_candidate_rows,
    retrieval_diagnostics,
)
from demo.transition_diagnostics import (
    REPORT_DOC as REPORT_DOC_PATH,
    MODE_CHOICES as TRANSITION_MODE_CHOICES,
    MODE_ADOPTED as TRANSITION_ADOPTED,
    MODE_DISABLED as TRANSITION_DISABLED,
    MODE_LABELS as TRANSITION_MODE_LABELS,
    TRANSITION_LABELS,
    ablation_rows,
    benchmark_available,
    build_transition_config,
    case_ids,
    case_rows,
    case_systems,
    claim_rows,
    configured_transition_mode,
    downstream_summary,
    duplicate_finding,
    duplicate_stale_rows,
    gate_rows,
    highlighted_gates,
    lifecycle_cards,
    lifecycle_chain,
    lifecycle_groups,
    limitation_rows,
    lineage_rows,
    partition_counts,
    pipeline_stages,
    safety_rows,
    STATUS_BADGES,
    status_summary,
    system_rows,
    transition_trace,
    replacement_available,
    replacement_summary,
    replacement_gate_rows,
    replacement_gate_detail,
    replacement_conditions,
    pure_create_residual_rows,
    replacement_systems,
    historical_replacement_example,
)
from demo.extraction_diagnostics import (
    MODE_CHOICES,
    MODE_DISABLED,
    MODE_LABELS,
    canonical_effect_label,
    classification_label,
    configured_extraction_mode,
    extraction_case_examples,
    extraction_trace,
    grounded_extraction_summary,
    outcome_label,
)

st.set_page_config(page_title="ExperienceOS", page_icon="🧠", layout="wide")


def rebuild_agent(
    provider_choice: str,
    storage_choice: str = STORAGE_IN_MEMORY,
    policy_choice: str = POLICY_RULE_BASED,
    extraction_mode: str = MODE_DISABLED,
    transition_mode: str = TRANSITION_ADOPTED,
) -> None:
    """Recreate the agent and clear UI state.

    Persisted SQLite memories survive this — used at startup and when
    the provider, storage, policy, or extraction-mode selection changes,
    so switching never loses accumulated experience. ``transition_mode``
    defaults to adopted: the canonical deterministic lifecycle path, whose
    per-request authorization comes from the bounded runtime authority.
    """
    provider = make_provider(provider_choice)
    st.session_state.agent = create_agent(
        provider,
        make_memory_store(storage_choice),
        make_memory_policy(policy_choice),
        extraction=build_canonical_extraction_config(extraction_mode, provider),
        transition=build_transition_config(transition_mode),
    )
    st.session_state.agent_provider = provider_choice
    st.session_state.agent_storage = storage_choice
    st.session_state.agent_policy = policy_choice
    st.session_state.agent_extraction_mode = extraction_mode
    st.session_state.agent_transition_mode = transition_mode
    st.session_state.chat_history = []
    st.session_state.last_error = None


def full_demo_reset(
    provider_choice: str,
    storage_choice: str,
    demo_user_id: str,
    policy_choice: str = POLICY_RULE_BASED,
    extraction_mode: str = MODE_DISABLED,
    transition_mode: str = TRANSITION_ADOPTED,
) -> None:
    """Return the demo to a known clean state for the next run.

    Rebuilds the agent, then removes the demo user's memories in every
    lifecycle status (both storage modes) and clears event history —
    no stale state (including the live extraction trace) can leak into
    the next scripted run. Committed benchmark artifacts are untouched.
    """
    rebuild_agent(provider_choice, storage_choice, policy_choice,
                  extraction_mode, transition_mode)
    reset_demo_state(st.session_state.agent, demo_user_id)


def send_message(user_id: str, session_id: str, message: str) -> None:
    agent = st.session_state.agent
    try:
        response = agent.chat(
            user_id=user_id, session_id=session_id, message=message
        )
    except Exception as exc:
        st.session_state.last_error = str(exc)
        return
    st.session_state.last_error = None
    st.session_state.chat_history.append(
        {"session_id": session_id, "user": message, "assistant": response}
    )


# --- Session state -----------------------------------------------------------

if "agent" not in st.session_state:
    rebuild_agent(PROVIDER_MOCK)

# --- Sidebar: provider, identity, demo controls ------------------------------

with st.sidebar:
    st.header("Setup")
    provider_choice = st.selectbox("Provider", PROVIDER_CHOICES, index=0)
    storage_choice = st.selectbox("Memory storage", STORAGE_CHOICES, index=0)
    policy_choice = st.selectbox("Memory policy", POLICY_CHOICES, index=0)
    extraction_label = st.selectbox(
        "Grounded extraction", MODE_CHOICES, index=0,
        help=(
            "Disabled is the default. Shadow and candidate are "
            "non-mutating: the controller proposes and is evaluated, but "
            "durable memory never changes. Adopted mode is not selectable "
            "here — it requires an explicit authorization object."
        ),
    )
    extraction_mode = MODE_LABELS[extraction_label]
    transition_label = st.selectbox(
        "Transition intelligence", TRANSITION_MODE_CHOICES, index=0,
        help=(
            "Adopted is the canonical default: the deterministic update and "
            "forget controllers supersede or forget obsolete memory, with "
            "each per-request authorization issued by the bounded runtime "
            "authority. Shadow, candidate, and verify-only are non-mutating "
            "diagnostics; disabled observes nothing."
        ),
    )
    transition_mode = TRANSITION_MODE_LABELS[transition_label]
    if (
        provider_choice != st.session_state.agent_provider
        or storage_choice != st.session_state.agent_storage
        or policy_choice != st.session_state.get("agent_policy", POLICY_RULE_BASED)
        or extraction_mode != st.session_state.get(
            "agent_extraction_mode", MODE_DISABLED)
        or transition_mode != st.session_state.get(
            "agent_transition_mode", TRANSITION_ADOPTED)
    ):
        rebuild_agent(
            provider_choice, storage_choice, policy_choice, extraction_mode,
            transition_mode)

    agent = st.session_state.agent
    if policy_choice == POLICY_LOCAL_MODEL:
        runtime = local_runtime_status(agent)
        if runtime["reason"]:
            st.warning(
                f"Local runtime: {runtime['label']} ({runtime['reason']}).\n\n"
                f"{runtime['detail']}\n\nMemory decisions will fall back "
                "to the deterministic rules."
            )
        else:
            st.markdown(f"**Local runtime:** {runtime['label']}")
    status = provider_status(agent.model)
    st.markdown(f"**Provider:** `{agent.model.name}`")
    if status == "Missing credentials":
        st.warning(
            f"Status: {status}\n\n{QWEN_SETUP_HINT}\n\n"
            "Chat will fail until credentials are set — or switch back to "
            "the Mock provider."
        )
    else:
        st.markdown(f"**Status:** {status}")

    storage_label, db_description = storage_status(agent.memory_store)
    st.markdown(f"**Memory storage:** {storage_label}")
    st.markdown(f"**Database:** `{db_description}`")
    if storage_label == "SQLite":
        st.caption(
            "Memories survive restarts and storage switches. Reset demo "
            "clears this demo user's memories."
        )

    user_id = st.text_input("User ID", DEMO_USER_ID)
    session_id = st.text_input("Session ID", "session-1")

    st.divider()
    if st.button("▶ Run experience lifecycle demo", width="stretch"):
        for demo_session_id, demo_message in SCRIPTED_DEMO:
            send_message(user_id, demo_session_id, demo_message)
    st.caption(
        "One run shows the full lifecycle: preferences, facts, and "
        "instructions remembered; context retrieved within a budget; a "
        "preference superseded; a memory forgotten; and a final request "
        "using only current experience."
    )
    if st.button("Reset demo", width="stretch"):
        full_demo_reset(
            provider_choice, storage_choice, user_id, policy_choice,
            extraction_mode, transition_mode)
        st.rerun()
    if storage_label == "SQLite":
        if st.button("Clear persistent memories", width="stretch"):
            st.session_state.agent.memory_store.clear()
            rebuild_agent(
                provider_choice, storage_choice, policy_choice,
                extraction_mode, transition_mode)
            st.rerun()

# --- Header -------------------------------------------------------------------

st.title(f"🧠 {DEMO_TITLE}")
st.markdown(f"**{TAGLINE}**")
st.caption(DEMO_NOTE)

agent = st.session_state.agent

# --- Chat input (processed before rendering panels) ---------------------------

chat_message = st.chat_input("Send a message through ExperienceOS")
if chat_message:
    send_message(user_id, session_id, chat_message)

if st.session_state.last_error:
    st.error(st.session_state.last_error)

# --- Persistent transition status ----------------------------------------------
# Loaded from the committed benchmark evidence, never recomputed here. The
# honest headline is fixed: candidate only, gate 1 failed, default disabled.

_status = status_summary()
_effective_mode = configured_transition_mode(st.session_state.agent)
_latest_trace = transition_trace(st.session_state.agent.events, limit=1)
_latest_applied = bool(_latest_trace and _latest_trace[-1].get("action_applied"))

st.markdown("#### Transition intelligence status")
_s1, _s2, _s3, _s4 = st.columns(4)
_s1.metric("Runtime default", _status["runtime_default"])
_s1.caption(f"Configured now: {TRANSITION_DISABLED if _effective_mode is None else _effective_mode}")
_s2.metric("Transition path", _status["classification_label"])
_s2.caption("From committed benchmark evidence")
_s3.metric("Canonical controller", _status["canonical_controller"])
_s3.caption("No controller is canonical")
_s4.metric(
    "Latest applied controller action", "Yes" if _latest_applied else "No"
)
_s4.caption(f"Effective mode: {_effective_mode}")

# --- Main layout ---------------------------------------------------------------

col_chat, col_platform = st.columns([3, 2], gap="large")

with col_chat:
    st.subheader("Chat")
    if not st.session_state.chat_history:
        st.info(
            "Send a message, or click **Run travel preference demo** in the "
            "sidebar to see ExperienceOS accumulate and retrieve experience."
        )
    for turn in st.session_state.chat_history:
        with st.chat_message("user"):
            st.caption(f"session: {turn['session_id']}")
            st.write(turn["user"])
        with st.chat_message("assistant"):
            st.write(turn["assistant"])

with col_platform:
    st.subheader("Experience layer")

    st.markdown("**Memory intelligence (last turn)**")
    manager = agent.experience_manager
    fallback_name = (
        "rule_based" if manager.fallback_policy is not None else "none"
    )
    st.caption(
        f"Policy: {manager.policy_mode} · Fallback policy: {fallback_name}"
    )
    provenance = policy_provenance(agent.events)
    st.caption(memory_intelligence_summary(provenance))
    intelligence_rows = decision_rows(provenance)
    if intelligence_rows:
        st.dataframe(intelligence_rows, width="stretch", hide_index=True)

    st.markdown("**Experience growth**")
    metrics = growth_metrics(agent, user_id)
    st.caption(
        f"Active {metrics['active_memories']} · "
        f"Created {metrics['created_memories']} · "
        f"Recalls {metrics['recalls']} · "
        f"Updated {metrics['updated_memories']} · "
        f"Forgotten {metrics['forgotten_memories']} · "
        f"Summaries used {metrics['compressed_summaries_used']} · "
        f"Context saved {metrics['context_saved_chars']} chars"
    )
    timeline = lifecycle_timeline(agent.events)
    if timeline:
        st.dataframe(timeline, width="stretch", hide_index=True)
    else:
        st.caption("No experience accumulated yet.")

    st.markdown("**Active memories**")
    memory_rows = active_memory_rows(agent, user_id)
    if memory_rows:
        st.dataframe(memory_rows, width="stretch", hide_index=True)
    else:
        st.caption(
            "No active memories yet. Run the scripted demo to generate "
            "lifecycle activity."
        )

    superseded = superseded_rows(agent, user_id)
    if superseded:
        st.markdown("**Superseded experiences**")
        st.dataframe(superseded, width="stretch", hide_index=True)
        st.caption(
            "Kept for lineage — never injected into model context again."
        )

    forgotten = forgotten_rows(agent, user_id)
    if forgotten:
        st.markdown("**Forgotten experiences**")
        st.dataframe(forgotten, width="stretch", hide_index=True)
        st.caption(
            "Kept as inactive history — excluded from retrieval and context."
        )

    st.markdown("**Context selection (last turn)**")
    raw_records = selection_records(agent.events)
    records = selection_rows(raw_records)
    if records:
        summary = selection_summary(agent.events) or {}
        st.caption(
            f"Budget {summary.get('memory_budget', '—')} — considered "
            f"{summary.get('candidates', 0)}, selected "
            f"{summary.get('selected', 0)}, skipped {summary.get('skipped', 0)}."
        )
        st.dataframe(records, width="stretch", hide_index=True)
    else:
        st.caption("No context selection has been built yet.")

    st.markdown("**Retrieval diagnostics (Phase 11)**")
    st.caption(LIFECYCLE_AUTHORITY_NOTICE)
    diagnostics = retrieval_diagnostics(agent.events)
    if diagnostics is None:
        st.caption("No retrieval event yet.")
    elif diagnostics["retrieval_mode"] == "disabled":
        st.caption(
            "Retrieval mode: lexical (Phase 9 path). Semantic retrieval "
            "disabled — no embedding provider configured, no cache, no "
            "shadow gate."
        )
    else:
        provider = (
            f"{diagnostics.get('provider_id') or 'Not available'} / "
            f"{diagnostics.get('model_id') or 'Not available'}"
        )
        st.caption(
            f"Retrieval mode: {diagnostics['retrieval_mode']} — "
            f"embedding provider {provider} "
            f"(deterministic test provider: plumbing evidence, not "
            f"learned semantic quality). "
            f"Fusion profile: "
            f"{diagnostics.get('fusion_profile') or 'None'}. "
            f"Fallback: "
            f"{diagnostics.get('fallback_reason') or 'No fallback'}. "
            f"Eligible {diagnostics.get('eligible_count', '—')}, "
            f"lifecycle-excluded "
            f"{diagnostics.get('lifecycle_excluded_count', '—')}, "
            f"budget compliant "
            f"{format_flag(diagnostics.get('budget_compliant'))}."
        )
        cache = diagnostics.get("cache")
        if cache:
            st.caption(
                f"Embedding cache: {cache.get('hits', 0)} hits / "
                f"{cache.get('lookups', 0)} lookups "
                f"({cache.get('misses', 0)} misses, "
                f"{cache.get('evictions', 0)} evictions)."
            )
        gate = gate_shadow_summary(agent.events)
        if gate is not None:
            st.caption(
                f"Shadow gate {gate['controller_id']}: "
                f"{gate['evaluated']} evaluated — {gate['admit']} admit, "
                f"{gate['reject']} reject, {gate['abstain']} abstain; "
                f"{gate['disagreement']} disagreements. Proposals did "
                f"not change context (affected selection: "
                f"{gate['affected_selection']})."
            )
        else:
            st.caption("Shadow gate: Disabled.")
        phase11_rows = phase11_candidate_rows(raw_records)
        if phase11_rows:
            st.dataframe(phase11_rows, width="stretch", hide_index=True)
        with st.expander("Per-candidate score breakdowns"):
            for record in raw_records:
                st.markdown(
                    f"`{str(record.get('memory_id', ''))[:8]}` "
                    f"{str(record.get('text', ''))[:80]}"
                )
                st.json(candidate_detail(record))

    with st.expander("Phase 11 benchmark summary (committed evidence)"):
        benchmark = phase11_benchmark_summary()
        if benchmark is None:
            st.caption("Benchmark summary unavailable.")
        else:
            st.dataframe(
                [
                    {"System": "Phase 9 reference",
                     **benchmark["reference"]},
                    {"System": "Embedding-only",
                     **benchmark["embedding_only"]},
                    {"System": "Fused (experimental)",
                     **benchmark["fused"]},
                ],
                width="stretch",
                hide_index=True,
            )
            classifications = benchmark["classifications"]
            st.caption(
                f"Adoption: embedding-only "
                f"{classifications['embedding_only']}; fused "
                f"{classifications['fused']}; fused+gate "
                f"{classifications['gate_shadow']}. Lifecycle leakage "
                f"zero; gate affected selection "
                f"{benchmark['gate_affected_selection']}."
            )
            st.caption(benchmark["provider_note"])
            st.caption(
                f"Full benchmark evidence: `{benchmark['report_doc']}`"
            )

    # --- Extraction decision trace (live) ---
    st.markdown("**Extraction decision trace**")
    st.caption(
        "Grounded extraction is a bounded seam. Shadow and candidate "
        "modes propose and evaluate but never change durable memory; "
        "only an explicitly authorized adopted action can. This "
        "dashboard never enables adopted mode."
    )
    configured_mode = configured_extraction_mode(agent)
    trace = extraction_trace(agent.events)
    if configured_mode == MODE_DISABLED and not trace:
        st.caption("Grounded extraction integration is disabled.")
    elif not trace:
        st.caption("No extraction decisions have been recorded.")
    else:
        latest = trace[0]
        st.caption(
            f"Mode: {latest.get('effect_mode') or configured_mode} · "
            f"Controller: {latest.get('controller_id') or '—'} "
            f"({latest.get('controller_type') or '—'}) · "
            f"Outcome: {outcome_label(latest)}"
        )
        st.dataframe(
            [
                {"Signal": "Proposal present",
                 "Value": format_flag(latest.get("proposal_present"))},
                {"Signal": "Proposed kind",
                 "Value": latest.get("proposed_kind") or "None"},
                {"Signal": "Normalized text",
                 "Value": latest.get("normalized_text") or "None"},
                {"Signal": "Evidence offsets",
                 "Value": (
                     f"[{latest.get('evidence_start')}, "
                     f"{latest.get('evidence_end')})"
                     if latest.get("evidence_start") is not None
                     else "Not applicable")},
                {"Signal": "Grounding",
                 "Value": (
                     f"{latest.get('grounding_code')}"
                     if latest.get("grounding_status") is not None
                     else "Not evaluated")},
                {"Signal": "Lifecycle evaluation",
                 "Value": latest.get("lifecycle_evaluation") or (
                     "Not evaluated")},
                {"Signal": "Duplicate / conflict",
                 "Value": latest.get("duplicate_or_conflict") or "None"},
                {"Signal": "Adoption authorized",
                 "Value": format_flag(latest.get("adoption_authorized"))},
                {"Signal": "Action generated",
                 "Value": format_flag(latest.get("action_generated"))},
                {"Signal": "Action applied",
                 "Value": format_flag(latest.get("action_applied"))},
                {"Signal": "Canonical effect",
                 "Value": canonical_effect_label(latest)},
                {"Signal": "Final proposal source",
                 "Value": latest.get("final_proposal_source") or "None"},
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Grounding validity is proposal quality, not lifecycle "
            "acceptance — a valid, non-mutating proposal still shows "
            "canonical effect: no."
        )
        runner_status = latest.get("runner_status")
        st.caption(
            "Learned runner: "
            + (str(runner_status) if runner_status is not None
               else "Not applicable (deterministic controller)")
            + f" · Parser: {latest.get('parser_status') or 'Not applicable'}"
            + f" · Fallback used: "
            + format_flag(latest.get("fallback_used"))
        )
        if len(trace) > 1:
            with st.expander(f"Recent extraction decisions ({len(trace)})"):
                st.dataframe(
                    [
                        {
                            "Mode": v.get("effect_mode") or "—",
                            "Outcome": outcome_label(v),
                            "Kind": v.get("proposed_kind") or "None",
                            "Grounding": v.get("grounding_code") or "—",
                            "Lifecycle": v.get("lifecycle_evaluation") or "—",
                            "Canonical effect": format_flag(
                                v.get("canonical_effect")),
                        }
                        for v in trace
                    ],
                    width="stretch",
                    hide_index=True,
                )

    # --- Grounded extraction evaluation (committed evidence) ---
    with st.expander("Grounded extraction evaluation (committed evidence)"):
        summary = grounded_extraction_summary()
        if summary is None:
            st.caption(
                "Committed grounded-extraction evaluation is unavailable."
            )
        else:
            st.caption(
                f"Deterministic controller classification: "
                f"**{classification_label(summary['classification'])}**"
            )
            st.caption(summary["classification_reason"])
            m = summary["metrics"]
            st.dataframe(
                [
                    {"Metric": "Proposal precision", "Value": m["precision"]},
                    {"Metric": "Proposal recall", "Value": m["recall"]},
                    {"Metric": "Proposal F1", "Value": m["f1"]},
                    {"Metric": "Grounded-span validity",
                     "Value": m["grounded_span_validity"]},
                    {"Metric": "No-candidate recall",
                     "Value": m["no_candidate_recall"]},
                    {"Metric": "Durable creation — canonical reference",
                     "Value": m["durable_creation_reference"]},
                    {"Metric": "Durable creation — grounded (benchmark "
                               "adopted)",
                     "Value": m["durable_creation_grounded"]},
                    {"Metric": "Duplicate active memories",
                     "Value": str(m["duplicate_active_memories"])},
                    {"Metric": "State corruption",
                     "Value": str(m["state_corruption"])},
                ],
                width="stretch",
                hide_index=True,
            )
            gates = summary["gates"]
            st.caption(
                f"Adoption gates: {gates['passed']}/{gates['total']} passed "
                f"— passing most gates is not adoption approval; the failed "
                f"gates are decisive. Failed: "
                f"{', '.join(gates['failed_gates']) or 'none'}."
            )
            st.dataframe(
                [
                    {"Gate": g["gate"], "Status": g["status"],
                     "Threshold": g["threshold"]}
                    for g in gates["rows"]
                ],
                width="stretch",
                hide_index=True,
            )
            for learned in summary["learned"]:
                st.caption(
                    f"`{learned['system_id']}`: "
                    + ("executed" if learned["executed"]
                       else f"not executed — {learned['skip_reason']}")
                )
            cards = extraction_case_examples()
            if cards:
                st.caption("Illustrative committed cases:")
                for card in cards:
                    st.markdown(
                        f"`{card['case_id']}` — {card['why']}"
                    )
                    st.caption(
                        f"Expected candidate: "
                        f"{format_flag(card['expected_candidate'])} · "
                        f"Proposed: {format_flag(card['proposal_present'])} "
                        f"({card['proposed_kind'] or 'none'}) · "
                        f"Score: {card['proposal_score']} · "
                        f"Grounding: {card['grounding_code'] or '—'} · "
                        f"Duplicate-active leak: "
                        f"{card['duplicate_active_leak']} · "
                        f"Canonical effect: "
                        f"{format_flag(card['canonical_effect'])}"
                    )
                    evidence = card["evidence"]
                    if evidence["available"]:
                        st.markdown(
                            evidence["excerpt_html"],
                            unsafe_allow_html=True,
                        )
                        st.caption(f"Evidence span {evidence['offsets_label']}")
                    elif card["source_excerpt"]:
                        st.caption(
                            f"Source: {card['source_excerpt']} "
                            "(controller proposed no candidate)"
                        )
            st.caption(summary["provider_note"])
            st.caption(f"Full benchmark evidence: `{summary['report_doc']}`")

    st.markdown("**Compressed context (last turn)**")
    summaries = [summary_display(s) for s in compressed_summaries(agent.events)]
    if summaries:
        totals = compression_totals(summaries)
        st.caption(
            f"{totals['source_count']} related memories compressed into "
            f"{totals['count']} summary — {totals['original_chars']} chars "
            f"→ {totals['compressed_chars']} chars "
            f"(saved {totals['saved_chars']})."
        )
        for s in summaries:
            st.success(s["text"])
            with st.expander(
                f"Sources and savings ({len(s['source_texts'])} memories)"
            ):
                st.markdown(
                    "\n".join(f"- {t}" for t in s["source_texts"]) or "—"
                )
                st.caption(
                    f"{s['reason']} Original {s['original_chars']} chars → "
                    f"compressed {s['compressed_chars']} chars "
                    f"(saved {s['saved_chars']})."
                )
    else:
        st.caption("No compressed summaries yet.")

    st.markdown("**Context supplied on the last turn**")
    context_lines = supplied_context_lines(agent.events)
    summary_texts = [s["text"] for s in summaries if s["text"]]
    if context_lines or summary_texts:
        body = "ExperienceOS supplied this context:"
        if summary_texts:
            body += "\n\n" + "\n\n".join(summary_texts)
        if context_lines:
            body += "\n\n" + "\n".join(f"- {line}" for line in context_lines)
        st.success(body)
    else:
        st.caption("No prior experience was added to this turn.")

    st.markdown("**Event log**")
    if agent.events:
        st.dataframe(
            [
                {
                    "Time": e.timestamp.strftime("%H:%M:%S"),
                    "Event": e.type,
                    "Session": e.session_id,
                    "Summary": summarize_event(e),
                }
                for e in agent.events
            ],
            width="stretch",
            hide_index=True,
        )
        with st.expander("Raw event payloads"):
            for e in agent.events:
                st.json(
                    {
                        "id": e.id,
                        "type": e.type,
                        "timestamp": e.timestamp.isoformat(),
                        "user_id": e.user_id,
                        "session_id": e.session_id,
                        "payload": e.payload,
                    }
                )
    else:
        st.caption("No events yet.")

# --- Transition intelligence ---------------------------------------------------
# Live runtime diagnostics and committed benchmark evidence. Everything
# below reads; nothing recomputes a metric or re-derives a decision.

st.divider()
st.subheader("Transition intelligence")
st.caption(
    "How ExperienceOS decides whether a new statement is the same "
    "experience, a replacement, a scoped addition, a forget directive, or "
    "something it must refuse. Proposal, verification, authorization, "
    "translation, and application are separate stages — none implies the "
    "next."
)

_trace = transition_trace(st.session_state.agent.events)

with st.expander("Transition trace (live)", expanded=False):
    if _effective_mode == TRANSITION_DISABLED:
        st.info(
            "No transition analysis ran because integration is disabled "
            "(the default). Select shadow, candidate, or verify-only in the "
            "sidebar to observe the pipeline without mutating memory."
        )
    elif not _trace:
        st.caption("No transition decisions have been recorded yet.")
    else:
        _latest = _trace[-1]
        if _latest.get("malformed"):
            st.warning(
                "The latest transition annotation could not be read "
                f"({_latest.get('reason', 'unknown')}); no values are shown "
                "for it."
            )
        else:
            st.caption(
                f"Configured: {_latest['configured_mode']} · Effective: "
                f"{_latest['effective_mode']} · System: "
                f"{_latest['system_id'] or '—'} · Annotation v"
                f"{_latest['annotation_version']}"
            )
            st.dataframe(
                [
                    {
                        "Stage": stage["stage"],
                        "Status": STATUS_BADGES.get(
                            stage["status"], stage["status"]
                        ),
                        "Detail": stage["detail"],
                    }
                    for stage in pipeline_stages(_latest)
                ],
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "NOT RUN means the stage did not execute — it does not mean "
                "the stage passed."
            )
            if _latest["diagnostics"]:
                with st.expander(
                    f"Diagnostics ({len(_latest['diagnostics'])})"
                ):
                    st.dataframe(
                        _latest["diagnostics"], width="stretch",
                        hide_index=True,
                    )
        if len(_trace) > 1:
            with st.expander(f"Recent transition decisions ({len(_trace)})"):
                st.dataframe(
                    [
                        {
                            "Mode": r.get("effective_mode", "—"),
                            "Route": r.get("route", "—"),
                            "Transition": TRANSITION_LABELS.get(
                                r.get("transition_type"), r.get("transition_type")
                                or "—"
                            ),
                            "Verifier": r.get("verifier_status") or "—",
                            "Applied": "Yes" if r.get("action_applied") else "No",
                        }
                        for r in _trace
                        if not r.get("malformed")
                    ],
                    width="stretch", hide_index=True,
                )

with st.expander("Memory lifecycle (live)", expanded=False):
    _cards = lifecycle_cards(st.session_state.agent, user_id)
    if not _cards:
        st.caption("No memories yet for this user.")
    else:
        _groups = lifecycle_groups(_cards)
        _g1, _g2, _g3, _g4 = st.columns(4)
        _g1.metric("Active", _groups["active"])
        _g2.metric("Superseded", _groups["superseded"])
        _g3.metric("Forgotten", _groups["forgotten"])
        _g4.metric("Duplicate pairs", len(_groups["duplicate_pairs"]))
        st.caption(
            f"Stale active pairs: {len(_groups['stale_pairs'])} · Scoped "
            f"siblings: {len(_groups['scoped_pairs'])}. Superseded and "
            "forgotten records are kept and shown: accumulated experience "
            "includes its history."
        )
        st.dataframe(
            [
                {
                    "Memory": c["memory_id"][:12],
                    "Status": c["status"],
                    "Kind": c["kind"],
                    "Subject": c["subject"],
                    "Attribute": c["attribute"],
                    "Value": c["value"],
                    "Scope": c["scope"],
                    "Text": c["text"],
                }
                for c in _cards
            ],
            width="stretch", hide_index=True,
        )
        _lineage = lineage_rows(_cards)
        if _lineage:
            with st.expander(f"Lineage and audit records ({len(_lineage)})"):
                st.dataframe(_lineage, width="stretch", hide_index=True)
                st.caption(
                    "Replaced and forgotten experience is retained for audit "
                    "and excluded from current context."
                )

# --- Committed benchmark evidence ---------------------------------------------

if not benchmark_available():
    st.info(
        "Committed transition benchmark artifacts are unavailable. No "
        "metrics are shown and none are inferred."
    )
else:
    _finding = duplicate_finding()
    _partitions = partition_counts()

    with st.expander(
        "Benchmark: the central finding (committed evidence)", expanded=False
    ):
        st.markdown(
            f"**Transition path: {_status['classification_label']}**"
        )
        st.caption(_status["rationale"])
        st.markdown(
            "The proposal intelligence is correct and the projected state is "
            "cleaner — but applying it duplicates the replacement create, so "
            "the applied lifecycle fails the duplicate-reduction gate."
        )
        st.dataframe(
            [
                {
                    "Metric": r["metric"],
                    "Reference (applied)": str(r["reference"]),
                    "Candidate projection": str(r["candidate_projection"]),
                    "Isolated applied": str(r["isolated_applied"]),
                }
                for r in duplicate_stale_rows()
            ],
            width="stretch", hide_index=True,
        )
        st.warning(
            f"Stale active pairs improve {_finding['reference_stale']} → "
            f"{_finding['applied_stale']}, but duplicate pairs regress "
            f"{_finding['reference_duplicates']} → "
            f"{_finding['applied_duplicates']}. Cause: {_finding['cause']}. "
            f"Consequence: {_finding['consequence']}. Required future work: "
            f"{_finding['future_work']} — not done here."
        )
        st.caption(
            "Candidate projection is what a verified proposal *would* do. "
            "Isolated applied is what an authorized benchmark action really "
            "did through the existing manager and engine. Neither is normal "
            "runtime state, which remains disabled."
        )

    with st.expander("Benchmark: adoption gates (all 20)", expanded=False):
        st.caption(
            f"{_status['gate_summary']} · Historical evidence: "
            f"{_partitions.get('historical_scored', '—')} cases · "
            f"Development fixtures: "
            f"{_partitions.get('development_fixtures', '—')} cases "
            "(reported separately, never merged)."
        )
        for _g in highlighted_gates():
            st.warning(
                f"**Gate {_g['gate']} — {_g['decision_label']}: {_g['name']}**"
                f"\n\nReference: {_g['reference']} · Candidate: "
                f"{_g['candidate']}\n\n{_g['justification']}"
            )
        st.dataframe(
            [
                {
                    "#": g["gate"],
                    "Gate": g["name"],
                    "Decision": g["decision_label"],
                    "Blocking": "Yes" if g["blocking"] else "No",
                    "Reference": str(g["reference"]),
                    "Candidate": str(g["candidate"]),
                }
                for g in gate_rows()
            ],
            width="stretch", hide_index=True,
        )
        with st.expander("Gate detail"):
            _gate_choice = st.selectbox(
                "Gate", [f"{g['gate']}. {g['name']}" for g in gate_rows()],
                key="transition_gate_detail",
            )
            _gate = gate_rows()[int(_gate_choice.split(".")[0]) - 1]
            st.json(
                {
                    "gate": _gate["gate"],
                    "role": _gate["role"],
                    "threshold_or_procedure": _gate["threshold"],
                    "reference": _gate["reference"],
                    "candidate": _gate["candidate"],
                    "absolute_delta": _gate["absolute_delta"],
                    "relative_delta": _gate["relative_delta"],
                    "decision": _gate["decision"],
                    "blocking": _gate["blocking"],
                    "justification": _gate["justification"],
                    "evidence": _gate["evidence"],
                }
            )

    with st.expander("Benchmark: system comparison", expanded=False):
        st.caption(
            "Historical-scored evidence only. Unavailable systems receive no "
            "score."
        )
        st.dataframe(
            [
                {
                    "System": r["system_id"],
                    "Reference level": r["reference_level"],
                    "Mode": r["mode"],
                    "Available": "Yes" if r["available"] else "No",
                    "Classification": r["classification"],
                    "Targets": r["targets"],
                    "Stale pairs": str(r["stale_pairs"]),
                    "Duplicate pairs": str(r["duplicate_pairs"]),
                    "Preservation": str(r["preservation"]),
                    "Applied": str(r["actions_applied"]),
                }
                for r in system_rows()
            ],
            width="stretch", hide_index=True,
        )
        for _r in system_rows():
            if not _r["available"]:
                st.caption(f"{_r['system_id']}: Unavailable — {_r['unavailable_reason']}")

    with st.expander("Benchmark: lifecycle chain and context budget"):
        _chain = lifecycle_chain()
        _turn_rows = []
        for _sid, _c in (_chain.get("systems") or {}).items():
            for _turn in _c["turns"]:
                _turn_rows.append(
                    {
                        "System": _sid.replace("experienceos_", ""),
                        "Turn": _turn["turn"],
                        "Active": _turn["active"],
                        "Superseded": _turn["superseded"],
                        "Forgotten": _turn["forgotten"],
                        "Duplicates": _turn["duplicate_pairs"],
                        "Stale": _turn["stale_pairs"],
                    }
                )
        if _turn_rows:
            st.caption(
                f"{_chain.get('turns', 0)}-turn chain. {_chain.get('note', '')}"
            )
            st.dataframe(_turn_rows, width="stretch", hide_index=True)
        _down = downstream_summary()
        if _down:
            st.markdown("**Context budget and retrieval**")
            st.dataframe(
                [
                    {
                        "Metric": "Selection rate",
                        "Reference": str(_down["reference"]["selection_rate"]),
                        "Transition": str(_down["adopted"]["selection_rate"]),
                    },
                    {
                        "Metric": "Context tokens",
                        "Reference": str(_down["reference"]["context_tokens"]),
                        "Transition": str(_down["adopted"]["context_tokens"]),
                    },
                    {
                        "Metric": "Inactive memories retrieved",
                        "Reference": str(_down["reference"]["inactive_retrieved"]),
                        "Transition": str(_down["adopted"]["inactive_retrieved"]),
                    },
                ],
                width="stretch", hide_index=True,
            )
            st.caption(
                "Unchanged selection rate and token count are reported as "
                "non-regression, not improvement. Recall@K and MRR are "
                "unavailable: the transition corpus carries no relevance "
                "judgements and none were synthesized."
            )

    with st.expander("Benchmark: ablations (read-only evidence)"):
        st.caption(
            "Which architectural pieces earn their place. Every ablation is "
            "benchmark-only and non-adoptable; none is a runtime control."
        )
        st.dataframe(
            [
                {
                    "Ablation": r["ablation_id"],
                    "Component removed": r["disabled_component"],
                    "Cases": str(r["applicable_cases"]),
                    "Score": str(r["score"]),
                    "Safety failures": str(r["safety_failures"]),
                    "Runtime eligible": "No" if not r["runtime_eligible"] else "Yes",
                }
                for r in ablation_rows()
            ],
            width="stretch", hide_index=True,
        )
        st.caption(
            "The verifier-with-oracle-proposals row is an upper bound on "
            "verifier correctness — not controller quality."
        )

    with st.expander("Benchmark: safety (every zero-tolerance metric)"):
        st.dataframe(safety_rows(), width="stretch", hide_index=True)
        _blocking = [g for g in gate_rows() if g["blocking"]]
        _blocking_passed = sum(1 for g in _blocking if g["decision"] == "pass")
        st.caption(
            "Reported whether or not they passed. Blocking safety gates: "
            f"{_blocking_passed}/{len(_blocking)} pass."
        )

    _claims = claim_rows()
    with st.expander("Claims and limitations", expanded=False):
        st.markdown("**Supported by measurement**")
        st.dataframe(
            [
                {"Claim": c["claim"], "Evidence": c.get("detail", ""),
                 "Backing": c.get("backing", "")}
                for c in _claims["supported"]
            ],
            width="stretch", hide_index=True,
        )
        st.markdown("**Not supported**")
        st.dataframe(
            [
                {"Claim": c["claim"], "Reason": c.get("reason", "")}
                for c in _claims["unsupported"]
            ],
            width="stretch", hide_index=True,
        )
        st.markdown("**Limitations**")
        for _limit in limitation_rows():
            st.markdown(f"- {_limit}")
        st.caption(
            "Fixture-only categories (negative forget, forget and inspection "
            "questions, hypothetical forget, broad forget, ambiguous forget "
            "targets, switched-from-to, no-longer-now, overlapping scope) are "
            "engineering evidence, not historical evidence."
        )

    with st.expander("Diagnostics explorer (committed per-case evidence)"):
        _f1, _f2, _f3 = st.columns(3)
        _sys_filter = _f1.selectbox(
            "System", ["(all)"] + case_systems(), key="transition_case_system"
        )
        _part_filter = _f2.selectbox(
            "Partition", ["(all)", "historical_scored", "development_only"],
            key="transition_case_partition",
        )
        _case_filter = _f3.selectbox(
            "Case", ["(all)"] + case_ids(), key="transition_case_id"
        )
        _rows = case_rows(
            system_id=None if _sys_filter == "(all)" else _sys_filter,
            partition=None if _part_filter == "(all)" else _part_filter,
            source_case_id=None if _case_filter == "(all)" else _case_filter,
        )
        st.caption(f"{len(_rows)} case records")
        st.dataframe(
            [
                {
                    "Case": r["source_case_id"],
                    "Partition": r["partition"],
                    "System": r["system_id"].replace("experienceos_", ""),
                    "Observed": TRANSITION_LABELS.get(
                        r["observed_type"], r["observed_type"] or "—"
                    ),
                    "Correct": "Yes" if r["classification_correct"] else "No",
                    "Target correct": "Yes" if r["target_correct"] else "No",
                    "Verifier": r["verifier_status"] or "—",
                    "Applied": "Yes" if r["action_applied"] else "No",
                }
                for r in _rows[:200]
            ],
            width="stretch", hide_index=True,
        )
        if _rows:
            with st.expander("Case detail"):
                st.caption(
                    "Expected-transition fields are scoring evidence and are "
                    "not part of any system's input."
                )
                st.json(_rows[0])

    st.caption(
        f"Committed evidence: `{REPORT_DOC_PATH}` · artifacts under "
        "`benchmarks/results/committed/transition-verification`, "
        "`transition-ablation`, and `report-transition-verification`. The "
        "dashboard reads these; it does not recompute them."
    )


# --- Action replacement (read-only evidence) ----------------------------------

st.subheader("Action replacement")
st.caption(
    "Governed replacement suppresses the uniquely matched conflicting planner "
    "create and inserts the verified transition sequence in its place — under "
    "exact authorization, through the same manager admission and the single "
    "engine mutation boundary. Everything below is read from committed "
    "evidence; the dashboard applies no replacement."
)

if not replacement_available():
    st.info(
        "Committed action-replacement evidence is unavailable. No metrics are "
        "shown and none are inferred."
    )
else:
    _repl = replacement_summary()

    # Classification, prominent and unflattering.
    st.markdown(f"**Classification: `{_repl['classification']}`**")
    st.caption(
        f"Runtime default: **{_repl['runtime_default']}** · canonical "
        f"controller: **{_repl['canonical_controller']}** · adopted "
        "infrastructure is benchmark/test-only, never canonical runtime."
    )
    st.markdown(
        "The implementation succeeded for the supersede-bearing class, but the "
        "frozen overall duplicate gate (Gate 1) still failed because "
        f"**{_repl['pure_create_residual']} pure-create duplicates remain**. "
        "ExperienceOS therefore refused canonical adoption."
    )

    # Benchmark comparison: 0 -> 10 -> 4, supersede-bearing 6 -> 0.
    with st.expander("Benchmark evidence: append vs governed replacement", expanded=True):
        st.dataframe(
            [
                {"Metric": "Semantic duplicate pairs (overall)",
                 "Reference": _repl["reference_duplicates"],
                 "Append (defect)": _repl["append_duplicates"],
                 "Governed replacement": _repl["replacement_duplicates"]},
                {"Metric": "Supersede-bearing duplicate pairs",
                 "Reference": 0,
                 "Append (defect)": _repl["supersede_bearing_append"],
                 "Governed replacement": _repl["supersede_bearing_replacement"]},
                {"Metric": "Pure-create residual (out of scope)",
                 "Reference": 0,
                 "Append (defect)": _repl["pure_create_residual"],
                 "Governed replacement": _repl["pure_create_residual"]},
                {"Metric": "Stale active pairs",
                 "Reference": _repl["stale_reference"],
                 "Append (defect)": _repl["stale_replacement"],
                 "Governed replacement": _repl["stale_replacement"]},
            ],
            width="stretch", hide_index=True,
        )
        st.caption(
            f"Replacements applied: {_repl['replacements_applied']} · lineage "
            f"correct {_repl['lineage_correct']}/"
            f"{_repl['lineage_correct'] + _repl['lineage_broken']} · scoped and "
            f"unrelated memories lost: {_repl['seeded_memories_lost']} · every "
            "applied replacement reported ACTION_REPLACED, suppressed exactly "
            "the conflicting planner create, and inserted the transition create "
            "exactly once."
        )

    # A genuine historical before/after.
    _ex = historical_replacement_example()
    if _ex.get("available"):
        with st.expander("Historical case: append failure vs governed replacement"):
            st.markdown(
                "**Old append path (historical benchmark behavior):** planner "
                "creates the new value, the transition supersedes the old and "
                "creates the new value, both persist — duplicate pairs "
                f"**{_ex['append_duplicate_pairs']}**."
            )
            st.markdown(
                "**Governed replacement path:** the planner create is matched "
                "and suppressed, the transition supersede + create are inserted "
                "once, the old value is superseded, lineage is "
                f"{'intact' if _ex['lineage_ok'] else 'broken'} — duplicate "
                f"pairs **{_ex['replacement_duplicate_pairs']}** "
                f"(effect: {_ex['canonical_effect']})."
            )
            st.caption(
                "The old path is historical benchmark behavior, shown from "
                "committed evidence; it is not executed to render this example."
            )

    # The frozen twenty-gate table, replacement-enabled.
    with st.expander("Adoption gates (all twenty, replacement-enabled)"):
        st.dataframe(
            [
                {"Gate": g["gate"], "Name": g["name"],
                 "Blocking": "yes" if g["blocking"] else "no",
                 "Committed": g["committed_decision"],
                 "Replacement": g["replacement_decision"]}
                for g in replacement_gate_rows()
            ],
            width="stretch", hide_index=True,
        )
        _tally = _repl["tally"]
        st.caption(
            f"Tally: {_tally['passed']} pass / {_tally['failed']} fail / "
            f"{_tally['inconclusive']} inconclusive. Blocking gates "
            f"{_repl['blocking_gate_numbers']}: all pass = "
            f"{_repl['blocking_all_pass']}."
        )
        _detail = replacement_gate_detail()
        if _detail.get("available"):
            _g1 = _detail["gate1"]
            st.warning(
                f"Gate 1 — **{_g1.get('replacement_decision', '').upper()}**: "
                f"replacement leaves {_g1.get('replacement')} duplicate pair(s) "
                f"vs reference {_g1.get('reference')} (threshold: "
                f"{_g1.get('threshold')}). The supersede-bearing class is "
                "eliminated (6 → 0) and shown as supplementary evidence, but "
                "the overall gate remains failed."
            )
            st.info(
                "Gate 6 — **INCONCLUSIVE** (non-blocking): both reference and "
                "adopted create 0 forget-directive memories, so no reduction "
                "can be demonstrated; not rounded up to pass."
            )

    # Supplementary acceptance conditions, kept separate from the gates.
    _conditions = replacement_conditions()
    if _conditions:
        _passed = sum(1 for v in _conditions.values() if v == "pass")
        with st.expander(
            f"Additional replacement conditions ({_passed}/{len(_conditions)} PASS)"
        ):
            st.caption(
                "Supplementary action-replacement acceptance conditions; not "
                "part of the frozen twenty-gate framework."
            )
            st.dataframe(
                [
                    {"Condition": k.replace("_", " "), "Result": v.upper()}
                    for k, v in _conditions.items()
                ],
                width="stretch", hide_index=True,
            )

    # The pure-create residual, shown honestly.
    _residuals = pure_create_residual_rows()
    if _residuals:
        with st.expander(f"Pure-create residual duplicates ({len(_residuals)})"):
            st.caption(
                "Pure-create redundant duplicates: no supersede-bearing "
                "transition exists, so replacement does not apply. Canonical "
                "action replacement is not generic create deduplication, and "
                "this phase intentionally did not solve them."
            )
            st.dataframe(
                [
                    {"Case": r["case_id"].split(":")[-2],
                     "Append duplicates": r["append_duplicate_pairs"],
                     "Replacement duplicates": r["replacement_duplicate_pairs"],
                     "Why unresolved": r["reason"]}
                    for r in _residuals
                ],
                width="stretch", hide_index=True,
            )

    # The authority chain and the live replacement record.
    with st.expander("Governance: authority chain and live replacement record"):
        st.markdown(
            "controller proposes → verifier verifies → matcher matches → plan "
            "builder projects → authorization permits → manager admits → "
            "**engine applies (sole durable mutation boundary)**. The matcher, "
            "plan builder, and authorization mutate nothing; a failed "
            "replacement falls back to the canonical planner list — never "
            "append-both, never a partial replacement."
        )
        _live = transition_trace(st.session_state.agent.events, limit=1)
        _record = _live[-1].get("replacement") if _live else None
        if not _record or not _record.get("available"):
            st.caption(
                "No live replacement record yet (older events and disabled "
                "mode carry none). This renders as unavailable, never a crash."
            )
        else:
            st.json({
                "attempted": _record["attempted"],
                "applied": _record["applied"],
                "matcher_decision": _record["matcher_decision"],
                "plan_status": _record["plan_status"],
                "canonical_effect": _record["canonical_effect"],
                "authorization_status": _record["authorization_status"],
                "authorization_mismatched_fields": _record[
                    "authorization_mismatched_fields"
                ],
                "fallback_used": _record["fallback_used"],
                "fallback_reason": _record["fallback_reason"],
                "suppressed_occurrence_index": _record["suppressed_occurrence_index"],
                "plan_digest": _record["plan_digest"],
            })

    st.caption(
        "Committed evidence: `docs/action_replacement_adoption_report.md` · "
        "artifacts under `benchmarks/results/committed/action-replacement`, "
        "`action-replacement-adoption`, and their reports. The dashboard reads "
        "these; it does not recompute or apply them."
    )
