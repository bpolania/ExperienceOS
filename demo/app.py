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
from demo.extraction_diagnostics import (
    MODE_CHOICES,
    MODE_DISABLED,
    MODE_LABELS,
    build_extraction_config,
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
) -> None:
    """Recreate the agent and clear UI state.

    Persisted SQLite memories survive this — used at startup and when
    the provider, storage, policy, or extraction-mode selection changes,
    so switching never loses accumulated experience. ``extraction_mode``
    is only ever disabled, shadow, or candidate — all non-mutating; the
    dashboard never builds adopted mode.
    """
    st.session_state.agent = create_agent(
        make_provider(provider_choice),
        make_memory_store(storage_choice),
        make_memory_policy(policy_choice),
        extraction=build_extraction_config(extraction_mode),
    )
    st.session_state.agent_provider = provider_choice
    st.session_state.agent_storage = storage_choice
    st.session_state.agent_policy = policy_choice
    st.session_state.agent_extraction_mode = extraction_mode
    st.session_state.chat_history = []
    st.session_state.last_error = None


def full_demo_reset(
    provider_choice: str,
    storage_choice: str,
    demo_user_id: str,
    policy_choice: str = POLICY_RULE_BASED,
    extraction_mode: str = MODE_DISABLED,
) -> None:
    """Return the demo to a known clean state for the next run.

    Rebuilds the agent, then removes the demo user's memories in every
    lifecycle status (both storage modes) and clears event history —
    no stale state (including the live extraction trace) can leak into
    the next scripted run. Committed benchmark artifacts are untouched.
    """
    rebuild_agent(provider_choice, storage_choice, policy_choice,
                  extraction_mode)
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
    if (
        provider_choice != st.session_state.agent_provider
        or storage_choice != st.session_state.agent_storage
        or policy_choice != st.session_state.get("agent_policy", POLICY_RULE_BASED)
        or extraction_mode != st.session_state.get(
            "agent_extraction_mode", MODE_DISABLED)
    ):
        rebuild_agent(
            provider_choice, storage_choice, policy_choice, extraction_mode)

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
            extraction_mode)
        st.rerun()
    if storage_label == "SQLite":
        if st.button("Clear persistent memories", width="stretch"):
            st.session_state.agent.memory_store.clear()
            rebuild_agent(
                provider_choice, storage_choice, policy_choice,
                extraction_mode)
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
