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

ExperienceOS remembers three kinds of experience — **preferences**
("I prefer aisle seats."), **facts** ("My home airport is SFO."), and
**instructions** ("Always include airport transfer time.") — and manages
their full lifecycle: created, retrieved, superseded when they change
(preferences, facts, and durable instructions alike), and forgotten on
request (kept as visible history, never used again). Every memory gets
deterministic domain **tags** (travel, airport, seat, timing, work,
style, …) so the system can explain why a piece of experience mattered.

Context is assembled deterministically: active memories are ranked by
keyword relevance, kind priority, and recency, and only the top few
(default budget: 4) are injected — with a per-memory explanation of why
each was selected or skipped, including matched domains. Related
selected memories can be **compressed** into one compact experience
summary, and a per-turn **timeline** shows experience growing across
the session.

Every `chat(...)` call publishes its internal steps as events:

```
interaction_started → context_requested → memory_retrieved → context_built
→ memory_action_planned → memory_superseded* → memory_forgotten*
→ memory_created* → model_called → response_returned → interaction_completed
```

Inspect them via `agent.events`; read accumulated experience via
`agent.memories_for_user(user_id)` (pass `status="superseded"` or
`"forgotten"` for history).

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

### Demo walkthrough (3–5 minutes)

See `docs/demo_script.md` for the full presenter script. In short:

1. Run the dashboard (provider stays on Mock).
2. Click **Run experience lifecycle demo** in the sidebar. Ten turns
   run: travel preferences, facts, and an instruction are remembered; a
   trip is planned; a fact and a preference change; a preference is
   forgotten; a final trip is planned.
3. **Experience growth** shows the accumulated counts and a per-turn
   timeline: Remembered → Recalled → Updated → Forgot → Compressed.
4. **Active memories** shows all three kinds, each with its domain tags.
5. **Context selection** shows the budget math — on the first planning
   turn, seven candidates compete for a budget of six and one memory is
   visibly *skipped*, with a domain-aware reason for every decision.
6. "Actually, my home airport is now SJC." supersedes the SFO **fact**;
   "Actually, I prefer evening flights." supersedes the morning-flight
   preference — both land in **Superseded experiences** with lineage.
7. "Forget my aisle seat preference." fires `memory_forgotten` — aisle
   seats moves to **Forgotten experiences**, kept as history.
8. On the final turn, **Compressed context** shows five related travel
   memories collapsed into one summary (with sources and saved
   characters), and **Context supplied** proves the model received only
   current experience — SJC, not SFO; evening, not morning; nothing
   forgotten.
9. Optionally set `QWEN_API_KEY` and switch the provider to Qwen Cloud
   to run the same flow against a live Qwen model.

The point to observe: ExperienceOS does not merely remember — it
retrieves selectively, adapts when reality changes, forgets on request,
compresses related experience, and explains every decision.

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
Persisted memories survive restarts and provider/storage switches.
**Reset demo** returns the demo to a known clean state — it removes the
demo user's memories in every lifecycle status (both storage modes) and
clears the event history, so a rerun starts fresh; **Clear persistent
memories** wipes the whole database.

### Persistence walkthrough

1. Run the dashboard in SQLite persistent mode.
2. Create travel preferences (send "I prefer aisle seats and morning flights.").
3. Restart the dashboard.
4. Ask for a trip recommendation — ExperienceOS retrieves the prior memories.
5. Change the seat preference ("Actually, I prefer window seats now.").
6. Restart again.
7. The updated active preference survived; the superseded one remains
   visible but is never injected into context.

## Experience compression

Related selected memories can be collapsed into one compact summary at
context-assembly time — for example, five travel memories become:

```
Travel experience summary:
The user's home airport is SJC. Include airport transfer time when
planning work trips, prefer evening flights, prefer quiet hotels near
the airport, and avoid red-eye flights.
```

Compression is deterministic and template-based (no model calls, no
embeddings), applies only when the summary genuinely shrinks the
rendered context, and is a context behavior — **not** storage mutation:
source memories stay intact and visible, the summary tracks their ids
and texts, and forgotten/superseded memories can never be compressed in.
The dashboard shows each summary with its sources and the saved
character count. Compression is enabled in the demo path and opt-in for
the SDK (`ContextBuilder(compressor=ExperienceCompressor())`).

## Memory lifecycle: update, supersede, forget

ExperienceOS keeps old experience visible instead of deleting it. When a
preference changes ("Actually, I prefer window seats now."), the
conflicting active memory is marked **superseded** — with lineage
metadata pointing to its replacement — and the new memory becomes
active. Conflict detection is deterministic and conservative: only known
preference domains (seats, flight times, hotels) with matching polarity
can conflict; unknown domains just create new memories.

Facts and durable instructions update the same way, via deterministic
update keys: "Actually, my home airport is now SJC." supersedes the SFO
fact; "From now on, keep travel plans even shorter." supersedes an older
detail-level planning instruction; "Going forward, keep answers concise."
supersedes an older response-style instruction. Content instructions
("Include airport transfer time…") intentionally accumulate rather than
replace each other.

Explicit requests ("Forget my morning flight preference.", "I no longer
prefer aisle seats.", "I don't care about hotel gyms anymore.") mark
matching memories **forgotten**, with the reason and timestamp recorded.
Superseded and forgotten memories are never injected into future
context, but remain visible in the dashboard so every state transition
is observable — and both states persist in SQLite across restarts.

## Context selection

Active memories are not dumped into the prompt. Each turn, candidates
are ranked deterministically — keyword overlap with the current message,
then kind priority (instructions > facts > preferences), then recency —
and only the top `memory_budget` (default 4; the demo uses 6) are
injected, still grouped by kind. The `context_built` event carries
`selection_records` explaining every decision with domain evidence
("selected: matched trip, work; domains travel + work + planning;
instruction priority; within budget" / "skipped: its meal experience was
less relevant to this request; budget reached after 4 selected
memories"), which the dashboard renders as a table with tags and
matched domains.

## Console examples

Offline (default, no credentials — all exit 0):

```bash
PYTHONPATH=. python examples/full_lifecycle_demo.py  # one-command full lifecycle proof with assertions
PYTHONPATH=. python examples/basic_qwen_demo.py      # one-turn lifecycle
PYTHONPATH=. python examples/memory_demo.py          # cross-session recall
PYTHONPATH=. python examples/update_demo.py          # superseding
PYTHONPATH=. python examples/persistence_demo.py     # SQLite restarts
```

Live Qwen smoke test (optional, credential-gated):

```bash
export QWEN_API_KEY="..."             # or DASHSCOPE_API_KEY
export QWEN_MODEL="qwen-plus"         # optional
# export QWEN_BASE_URL="..."          # if your workspace needs a regional endpoint

PYTHONPATH=. python examples/qwen_live_demo.py
```

Without credentials, `qwen_live_demo.py` exits cleanly with setup
instructions (intentional exit code 1 — not a crash). Live Qwen
credentials are never required for tests, the offline examples, or the
default dashboard; MockProvider is the credential-free path.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
python examples/basic_qwen_demo.py   # runs offline via MockProvider
```

Run the full offline demo validation path (compile check, test suite,
and every offline example — no network, no credentials):

```bash
./scripts/validate_demo.sh
```
