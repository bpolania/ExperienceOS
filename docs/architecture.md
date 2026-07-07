# ExperienceOS Architecture

ExperienceOS is an experience layer that attaches to any LLM-powered agent
so the agent can accumulate experience across sessions.

## Interaction lifecycle

Every `ExperienceOS.chat(user_id, session_id, message)` call routes through
the experience engine, which publishes each step to the event bus:

```
SDK → ExperienceEngine → MemoryStore + ContextBuilder → ModelProvider → EventBus

interaction_started
context_requested
memory_retrieved       (prior active memories loaded for the user)
context_built          (context assembled, including retrieved experience)
memory_action_planned  (deterministic planner scans the user message)
memory_superseded      (one per replaced memory; only on preference changes)
memory_created         (one per new memory; only when preferences detected)
model_called           (provider invoked with context + user message)
response_returned
interaction_completed
```

Events are `ExperienceEvent` dataclasses (UUID id, UTC timestamp, user_id,
session_id, payload) kept in the bus's in-memory history — this is what the
demo surfaces to make the platform visible.

## Memory

- **`ExperienceEntry`** (`memory/schema.py`) — one unit of experience:
  id, user_id, kind (`preference`/`fact`/`instruction`), text, status
  (`active`/`superseded`/`forgotten` — `forgotten` is reserved),
  source_session_id, timestamps, metadata.
- **Memory stores** — one small interface (`add`, `get`,
  `list_memories(user_id, status=...)`, `active_for_user`, `supersede`,
  `clear`), two implementations:
  - **`InMemoryMemoryStore`** (`memory/store.py`, aliased `MemoryStore`) —
    the deterministic default for tests and quick local flows.
  - **`SQLiteMemoryStore`** (`memory/sqlite_store.py`) — stdlib `sqlite3`,
    one self-bootstrapping table (`experience_entries`) with user/status
    indexes. `ExperienceEntry.to_record()/from_record()` round-trip all
    fields: timestamps as ISO-8601 strings, metadata as JSON text — so
    active/superseded states and lineage (`superseded_by`, `replaces`)
    survive restarts. SQLite keeps persistence lightweight: zero
    services, zero migrations, one gitignorable file — and it makes
    "experience accumulates across sessions" literally true across
    process restarts.
- **`MemoryPlanner`** (`memory/planner.py`) — rule-based preference
  detection ("I prefer / like / don't like ...", optional "Remember that"
  prefix, conjunction splitting, trailing modifiers like "now"/"instead"
  stripped). Produces human-readable texts like "Prefers aisle seats."
  Texts already active for the user are skipped. The planner is a seam:
  an alternative planner with smarter extraction can replace it without
  touching the engine.
- **Superseding** — when a new preference conflicts with an active one,
  the planner emits a `supersede` action alongside the `create`. Conflict
  detection is deterministic: both texts must map to the same known
  preference domain (`seat`, `flight_time`, `hotel`) with the same
  polarity; unknown domains never supersede (false negatives beat false
  positives in a demo). The old memory keeps lineage metadata
  (`superseded_by`, `superseded_at`, `superseded_reason`), the new one
  records `replaces`, and a `memory_superseded` event makes the
  transition visible. Superseded memories stay in the store for the
  dashboard but are excluded from `active_for_user` — and therefore from
  all future context. Forgetting is not implemented.
- **Context assembly** — retrieval happens *before* new memories are
  planned, so a memory created now influences later interactions (the
  cross-session experience story). Retrieved memories are injected as a
  system message: "ExperienceOS retrieved these active user experiences: ..."

## Seams

- **SDK entrypoint** (`experienceos/sdk.py`) — the public `ExperienceOS`
  class. Two construction shapes: `ExperienceOS(model=...)` and
  `ExperienceOS.wrap(provider)`.
- **Provider abstraction** (`experienceos/providers/base.py`) — the
  `ModelProvider` interface. The SDK, engine, context, memory, and event
  layers never depend on a concrete provider; the same experience
  lifecycle runs unchanged behind either adapter.
  - `qwen_cloud.py` — Qwen Cloud adapter using the DashScope
    OpenAI-compatible chat completions API (stdlib urllib, no extra
    dependencies). All Qwen config (env vars, base URL, model), request
    shaping, and response parsing stay inside this module. Construction
    never touches the network; `complete()` raises a clear configuration
    error when credentials are absent.
  - `mock.py` — deterministic offline provider for tests and development
    (the default demo path).
- **Experience engine** (`experienceos/engine/`) — turns interaction events
  into accumulated experience.
- **Event system** (`experienceos/events/`) — in-process bus that makes the
  experience layer's activity observable (feeds the demo UI).
- **Memory** (`experienceos/memory/`) — `ExperienceEntry` schema, the
  rule-based planner, and the in-memory and SQLite stores.
- **Context builder** (`experienceos/context/`) — selects accumulated
  experience and assembles it into the prompt sent to the provider.
- **Dashboard** (`demo/`) — a Streamlit visibility layer over the SDK's
  event history and memory store. The dashboard is not the product: it
  exists to make the ExperienceOS platform observable — memories
  accumulating, context being injected, the event lifecycle firing.
  Provider selection lives here, not in the SDK. Display logic
  that doesn't need Streamlit sits in `demo/support.py` so it stays
  testable without the demo extra.

## Flow

```
user message → context builder (injects experience) → provider (Qwen Cloud)
      ↘ events published on the bus → experience engine → memory store
```

Deliberately out of scope: vector databases, embeddings, auth,
background workers, and production infrastructure.
