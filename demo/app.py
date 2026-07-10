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

st.set_page_config(page_title="ExperienceOS", page_icon="🧠", layout="wide")


def rebuild_agent(
    provider_choice: str,
    storage_choice: str = STORAGE_IN_MEMORY,
    policy_choice: str = POLICY_RULE_BASED,
) -> None:
    """Recreate the agent and clear UI state.

    Persisted SQLite memories survive this — used at startup and when
    the provider, storage, or policy selection changes, so switching
    never loses accumulated experience.
    """
    st.session_state.agent = create_agent(
        make_provider(provider_choice),
        make_memory_store(storage_choice),
        make_memory_policy(policy_choice),
    )
    st.session_state.agent_provider = provider_choice
    st.session_state.agent_storage = storage_choice
    st.session_state.agent_policy = policy_choice
    st.session_state.chat_history = []
    st.session_state.last_error = None


def full_demo_reset(
    provider_choice: str,
    storage_choice: str,
    demo_user_id: str,
    policy_choice: str = POLICY_RULE_BASED,
) -> None:
    """Return the demo to a known clean state for the next run.

    Rebuilds the agent, then removes the demo user's memories in every
    lifecycle status (both storage modes) and clears event history —
    no stale state can leak into the next scripted run.
    """
    rebuild_agent(provider_choice, storage_choice, policy_choice)
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
    if (
        provider_choice != st.session_state.agent_provider
        or storage_choice != st.session_state.agent_storage
        or policy_choice != st.session_state.get("agent_policy", POLICY_RULE_BASED)
    ):
        rebuild_agent(provider_choice, storage_choice, policy_choice)

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
        full_demo_reset(provider_choice, storage_choice, user_id, policy_choice)
        st.rerun()
    if storage_label == "SQLite":
        if st.button("Clear persistent memories", width="stretch"):
            st.session_state.agent.memory_store.clear()
            rebuild_agent(provider_choice, storage_choice, policy_choice)
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
    records = selection_rows(selection_records(agent.events))
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
