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

For a persistent local setup, copy `.env.example` to `.env` and add your
key — the dashboard and Qwen examples load it automatically when
python-dotenv is installed (part of the `demo` extra). `.env` is
gitignored; already-set environment variables always take precedence,
and the SDK itself never reads files — only entry points load `.env`.

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

## Local model runner (optional)

ExperienceOS includes an optional CPU-only local inference seam
(`LocalModelRunner`), with llama.cpp as the first concrete runtime. It
is absent from the default install, loads lazily, never downloads
model weights, and requires no GPU. The intended candidate model class
is a small Qwen2.5 Instruct GGUF (0.5B or 1.5B); point it at any local
GGUF file explicitly:

```bash
pip install -e ".[local]"
export EXPERIENCEOS_LOCAL_MODEL_PATH=/path/to/model.gguf

PYTHONPATH=. python examples/local_runner_smoke.py
```

Without the dependency or model path, the smoke check skips cleanly
(exit 0).

A configured local GGUF model was successfully verified through the
local runner and one ExperienceOS memory-policy interaction
(Qwen2.5-0.5B-Instruct Q4_K_M, CPU-only, structured JSON in under a
second; the local model proposed a memory decision that the engine
validated and applied). This verifies the integration path for that
model, not broad model compatibility — and proposal confidence is
model metadata, not proof a decision is semantically correct.

`LocalModelMemoryPolicy` connects the runner to memory decisions:

```python
from experienceos import (
    ExperienceOS,
    LlamaCppLocalModelRunner,
    LocalModelMemoryPolicy,
    QwenCloud,
)

runner = LlamaCppLocalModelRunner(model_path="/path/to/qwen-small.gguf")

agent = ExperienceOS(
    model=QwenCloud(),  # Qwen Cloud remains the reasoning/response provider
    memory_policy=LocalModelMemoryPolicy(runner),
)
```

The local model manages memory proposals only — it can never mutate
storage, and the engine validates every proposed target against the
active-memory snapshot before applying anything. The SDK automatically
supplies the deterministic rule-based policy as fallback, which runs
whenever the local path is unavailable, fails, returns invalid output,
or any proposal falls below the confidence threshold (default 0.60;
batches are accepted or rejected atomically). Fallback decisions carry
a typed reason (`dependency_missing`, `model_unavailable`,
`model_load_failed`, `generation_failed`, `invalid_output`,
`validation_failed`, `low_confidence`). A valid empty decision list
means "nothing worth remembering" and does not fall back. Without the
optional dependency, the agent simply behaves rule-based.

**Decision provenance in the dashboard:** pick **Memory policy: Local
model (optional)** in the sidebar. The **Memory intelligence** panel
shows the configured policy and fallback, the local runtime status
(shallow availability only — rendering never loads a model), and for
each turn whether decisions were accepted from the local model, made
by rules, produced by an attributed fallback, or rejected by lifecycle
validation — with per-decision source, confidence, and explanation.

**Memory value comparison** — one offline command proves what
accumulated experience changes by running the same six-turn travel
scenario three ways (no memory, rule-based, local policy with a fake
runner exercising accepted local decisions and one typed fallback):

```bash
PYTHONPATH=. python examples/memory_value_comparison.py
```

The no-memory agent ends with zero injected experience; both
experienced agents recall the home airport, use the *updated* flight
preference, and exclude the forgotten one — verified by deterministic
assertions, not prose. The local mode uses a fake runner by design
(deterministic and offline); real local-model execution is verified
separately through `local_runner_smoke.py` and a real memory-policy
interaction (see the local model runner section above).

## Benchmarking (Phase 8, in progress)

A lifecycle benchmark comparing ExperienceOS against stateless,
full-history, append-only, and naive-retrieval baselines is being
built. The measurement rules — schemas, metric denominators, leakage
definitions, context accounting, and fair-comparison constraints —
are committed **before** any results in
[docs/benchmark_contract.md](docs/benchmark_contract.md), with
machine-readable contracts under `benchmarks/contract/`. The
40-scenario lifecycle dataset and its fixed oracle are documented in
[docs/lifecycle_benchmark_dataset.md](docs/lifecycle_benchmark_dataset.md),
the four comparison baselines (stateless, full-history,
append-only, naive top-K) in
[docs/benchmark_baselines.md](docs/benchmark_baselines.md), and the
two ExperienceOS adapters (rule-based and local-model policies) in
[docs/benchmark_experienceos_adapters.md](docs/benchmark_experienceos_adapters.md).
The deterministic runner, metric evaluators, and raw artifacts are
documented in [docs/benchmark_runner.md](docs/benchmark_runner.md)
and [docs/benchmark_metrics.md](docs/benchmark_metrics.md).
The default benchmark path is fully offline (no credentials, no
network, no model downloads). Raw comparative artifacts exist under
`benchmarks/results/committed/`; the final comparative report has
not been written yet, and no result numbers are quoted here.

Run and validate the offline benchmark:

```bash
./scripts/run_benchmarks.sh quick
./scripts/run_benchmarks.sh full-offline
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
```

Validate the contract, dataset, baselines, and adapters:

```bash
PYTHONPATH=. python -m pytest tests/test_benchmark_contract.py tests/test_benchmark_dataset.py tests/test_benchmark_baselines.py tests/test_benchmark_adapters.py
PYTHONPATH=. python -m benchmarks.scenarios.validate
PYTHONPATH=. python -m benchmarks.baselines.smoke
PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_rules
PYTHONPATH=. python -m benchmarks.adapters.smoke --system experienceos_local --scripted
```

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
