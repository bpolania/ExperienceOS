"""End-to-end canonical lifecycle transitions through the real composition.

These drive the actual demo agent (``demo.support.create_agent``, adopted
by default) with the MockProvider, so they exercise the whole canonical
chat path: extraction, grounded validation, deterministic governance, the
adopted transition coordinator with the bounded runtime authority, memory
lifecycle, retrieval, and context. They assert on durable lifecycle state
and on what retrieval surfaces — never on internal digests.

Note on text fidelity: for a create-only conflict the canonical planner
does not itself supersede, so the transition supersedes the obsolete
memory and inserts a create carrying the raw source statement (e.g.
"Actually, I prefer coffee in the morning."). That text is semantically
correct, retrieval selects it over the superseded memory, and identity
stays single — so it is accepted as-is rather than normalized. When the
planner already performs the same transition (a keyed domain), the
planner-precedence guard keeps its normalized text instead.
"""

from __future__ import annotations

import pytest

from demo.support import (
    create_agent,
    forgotten_rows,
    superseded_rows,
)
from experienceos.memory import SQLiteMemoryStore
from experienceos.providers import MockProvider


def _texts(agent, uid, status):
    return [m.text for m in agent.memories_for_user(uid, status=status)]


def _context_texts(agent, since):
    for e in agent.events[since:]:
        if e.type == "context_built":
            return [
                (m.get("content") or "")
                for m in e.payload.get("context_messages", [])
            ]
    return []


# -- create ------------------------------------------------------------------


def test_create_adds_active_memory():
    agent = create_agent(MockProvider())
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="I prefer aisle seats.")
    active = _texts(agent, uid, "active")
    assert any("aisle" in t.lower() for t in active)
    assert _texts(agent, uid, "superseded") == []
    assert _texts(agent, uid, "forgotten") == []


# -- update: the three genuine create-only conflict cases --------------------


GENUINE_UPDATES = [
    ("I prefer tea in the morning.",
     "Actually, I prefer coffee in the morning.",
     "tea", "coffee"),
    ("I prefer dark mode in my code editor.",
     "Switch that — I prefer light mode in my editor now.",
     "dark", "light"),
    ("My phone is a Pixel 6.",
     "I upgraded — my phone is a Pixel 9 now.",
     "pixel 6", "pixel 9"),
]


@pytest.mark.parametrize("setup,update,old_token,new_token", GENUINE_UPDATES)
def test_genuine_update_supersedes_and_surfaces_new_value(
    setup, update, old_token, new_token
):
    agent = create_agent(MockProvider())
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message=setup)
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s2", message=update)

    active = _texts(agent, uid, "active")
    superseded = _texts(agent, uid, "superseded")
    # Exactly one active memory carrying the new value; the old is superseded.
    assert len(active) == 1
    assert new_token in active[0].lower()
    assert any(old_token in t.lower() for t in superseded)
    # No duplicate identity: the obsolete value is not still active.
    assert not any(old_token in t.lower() for t in active)

    # Retrieval/context surface the new value and not the obsolete one.
    ask = len(agent.events)
    agent.chat(user_id=uid, session_id="s3", message="Remind me of my preference.")
    ctx = " ".join(_context_texts(agent, ask)).lower()
    assert new_token in ctx
    assert old_token not in ctx

    # Lineage: the superseded row resolves to the replacement.
    rows = superseded_rows(agent, uid)
    assert len(rows) == 1
    assert old_token in rows[0]["Memory"].lower()
    assert new_token in rows[0]["Replaced by"].lower()
    del n


# -- forget ------------------------------------------------------------------


def test_forget_removes_from_active_exactly_once():
    agent = create_agent(MockProvider())
    uid = "u"
    agent.chat(user_id=uid, session_id="s1", message="My favorite color is blue.")
    assert any("blue" in t.lower() for t in _texts(agent, uid, "active"))
    n = len(agent.events)
    agent.chat(user_id=uid, session_id="s2", message="Forget my favorite color.")

    assert not any("blue" in t.lower() for t in _texts(agent, uid, "active"))
    assert any("blue" in t.lower() for t in _texts(agent, uid, "forgotten"))
    # The planner-precedence guard prevents a double forget.
    forgets = [e for e in agent.events[n:] if e.type == "memory_forgotten"]
    assert len(forgets) == 1
    rows = forgotten_rows(agent, uid)
    assert len(rows) == 1
    assert "blue" in rows[0]["Memory"].lower()


# -- cross-session persistence -----------------------------------------------


def test_lifecycle_survives_agent_reconstruction(tmp_path):
    db = str(tmp_path / "memory.sqlite3")
    uid = "u"

    agent = create_agent(MockProvider(), SQLiteMemoryStore(db))
    agent.chat(user_id=uid, session_id="s1", message="I prefer tea in the morning.")
    agent.chat(user_id=uid, session_id="s2",
               message="Actually, I prefer coffee in the morning.")
    before_active = sorted(_texts(agent, uid, "active"))
    before_superseded = sorted(_texts(agent, uid, "superseded"))
    assert any("coffee" in t.lower() for t in before_active)
    assert any("tea" in t.lower() for t in before_superseded)

    # Discard the agent; reconstruct against the same store.
    del agent
    reborn = create_agent(MockProvider(), SQLiteMemoryStore(db))
    assert sorted(_texts(reborn, uid, "active")) == before_active
    assert sorted(_texts(reborn, uid, "superseded")) == before_superseded

    # The superseded memory stays superseded — a further mention of the
    # active value does not resurrect it.
    ask = len(reborn.events)
    reborn.chat(user_id=uid, session_id="s3", message="What do I drink?")
    ctx = " ".join(_context_texts(reborn, ask)).lower()
    assert "coffee" in ctx
    assert "tea" not in ctx
