# ExperienceOS

**The Experience Operating System for AI Agents.**

AI today has intelligence but no life experience. ExperienceOS gives any
LLM-powered agent the ability to accumulate experience over time — an
experience layer that attaches to any model provider.

```python
from experienceos import ExperienceOS
from experienceos.providers import QwenCloud

agent = ExperienceOS(model=QwenCloud(model="qwen-plus", api_key="..."))
# or attach to an existing provider:
agent = ExperienceOS.wrap(QwenCloud(...))

response = agent.chat(
    user_id="demo-user",
    session_id="session-1",
    message="I prefer aisle seats and morning flights.",
)
```

Built on Qwen Cloud. The platform is the product; the demo makes the
platform visible.

## How it works

- **Session 1:** the user states preferences ("I prefer aisle seats and
  morning flights.") — ExperienceOS detects them, stores them as active
  experience entries, and emits `memory_created` events.
- **Session 2:** the user asks for help ("Help me book a work trip to
  NYC.") — ExperienceOS retrieves the active memories and injects them
  into the context sent to the model provider.

Every `chat(...)` call publishes its internal steps as events:

```
interaction_started → context_requested → memory_retrieved → context_built
→ memory_action_planned → memory_superseded* → memory_created* → model_called
→ response_returned → interaction_completed
```

Inspect them via `agent.events`; read accumulated experience via
`agent.memories_for_user(user_id)`.

## Layout

```
experienceos/   # the SDK: sdk.py, providers/, engine/, memory/, context/, events/
demo/           # Streamlit dashboard
examples/       # runnable SDK usage
tests/          # test suite
docs/           # architecture notes
```

## Providers

- **MockProvider** is the default local path: deterministic, offline, no
  credentials — used by tests and the demo.
- **Qwen Cloud** is the primary cloud provider. `QwenCloudProvider`
  is an OpenAI-compatible adapter (DashScope chat completions) isolated
  behind the `ModelProvider` interface — the core SDK never sees Qwen
  details.

### Qwen environment variables

| Variable | Purpose |
|---|---|
| `QWEN_API_KEY` (or `DASHSCOPE_API_KEY`) | required for live calls |
| `QWEN_BASE_URL` (or `DASHSCOPE_BASE_URL`) | optional; defaults to the international DashScope compatible-mode endpoint — set this if your Model Studio workspace uses a different regional endpoint (e.g. `https://dashscope.aliyuncs.com/compatible-mode/v1` for China) |
| `QWEN_MODEL` | optional; defaults to `qwen-plus` |

Explicit constructor arguments always win over environment variables.
Live Qwen credentials are **never** required for tests — the suite makes
no network calls.

## Dashboard

Install the demo extra and launch:

```bash
pip install -e ".[demo]"
PYTHONPATH=. streamlit run demo/app.py
```

The dashboard defaults to the offline **Mock** provider — no credentials
needed. It shows the chat on the left and the experience layer on the
right: active memories, the context ExperienceOS supplied to the model
on the last turn, and the live event log.

**Qwen Cloud** can be selected from the sidebar; if credentials are
missing it shows a warning with setup instructions instead of crashing,
and you can switch back to Mock.

### Demo walkthrough (2 minutes)

1. Run the dashboard (provider stays on Mock).
2. Click **Run preference update demo** in the sidebar.
3. Watch the event log: `memory_created` for aisle seats and morning
   flights in the first session.
4. On the second turn ("Actually, I prefer window seats now."), watch
   the `memory_superseded` event fire and "Prefers aisle seats." move to
   the **Superseded experiences** panel, replaced by "Prefers window
   seats." in **Active memories**.
5. On the final turn, the **Context supplied** panel proves the model
   received the new preference and morning flights — not the old aisle
   seat preference.
6. Optionally set `QWEN_API_KEY` and switch the provider to Qwen Cloud
   to run the same flow against a live Qwen model.

The point to observe: ExperienceOS does not merely remember — it adapts
its accumulated experience when the user changes.

## Persistence: experience survives restarts

In-memory storage remains the default lightweight mode, but SQLite
persistence makes the cross-session claim real — accumulated experience
survives process restarts:

```python
from experienceos import ExperienceOS
from experienceos.memory import SQLiteMemoryStore
from experienceos.providers import MockProvider

agent = ExperienceOS(
    model=MockProvider(),
    memory_store=SQLiteMemoryStore("experienceos_demo.sqlite3"),
)
# or the shorthand:
agent = ExperienceOS.with_sqlite_memory(model=MockProvider(), db_path="...")
```

Active/superseded statuses and lineage metadata all persist. Run the
offline persistence demo (three agents sharing one database, simulating
restarts):

```bash
PYTHONPATH=. python examples/persistence_demo.py
```

In the dashboard, pick **Memory storage: SQLite persistent** in the
sidebar (database at `.experienceos/demo_memory.sqlite3`, gitignored).
**Reset demo** clears only UI state — persisted memories survive; use
**Clear persistent memories** to wipe the database.

### Persistence walkthrough

1. Run the dashboard in SQLite persistent mode.
2. Create travel preferences (send "I prefer aisle seats and morning flights.").
3. Restart the dashboard.
4. Ask for a trip recommendation — ExperienceOS retrieves the prior memories.
5. Change the seat preference ("Actually, I prefer window seats now.").
6. Restart again.
7. The updated active preference survived; the superseded one remains
   visible but is never injected into context.

## Memory update and superseding

ExperienceOS keeps old experience visible instead of deleting it. When a
preference changes ("Actually, I prefer window seats now."), the
conflicting active memory is marked **superseded** — with lineage
metadata pointing to its replacement — and the new memory becomes
active. Superseded memories are never injected into future context, but
remain visible in the dashboard so the state transition is observable.
Conflict detection is deterministic and conservative: only known
preference domains (seats, flight times, hotels) with matching polarity
can conflict; unknown domains just create new memories.

## Console examples

Offline (default, no credentials):

```bash
PYTHONPATH=. python examples/memory_demo.py
```

Live Qwen smoke test (optional):

```bash
export QWEN_API_KEY="..."
export QWEN_MODEL="qwen-plus"         # optional
# export QWEN_BASE_URL="..."          # if your workspace needs a regional endpoint

PYTHONPATH=. python examples/qwen_live_demo.py
```

If credentials are missing, it prints setup instructions instead of
crashing. Live Qwen credentials are never required for tests or the
default dashboard.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
python examples/basic_qwen_demo.py   # runs offline via MockProvider
```
