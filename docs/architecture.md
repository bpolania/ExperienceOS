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
context_built          (bounded selection made and context assembled;
                        payload carries candidate/selected/skipped ids
                        and per-memory selection_records with reasons)
memory_action_planned  (deterministic planner scans the user message)
memory_superseded      (one per replaced memory; only on preference changes)
memory_forgotten       (one per memory removed by an explicit forget request)
memory_created         (one per new memory; preferences, facts, instructions)
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
  (`active`/`superseded`/`forgotten`), source_session_id, timestamps,
  metadata.
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
- **`MemoryPlanner`** (`memory/planner.py`) — rule-based detection of
  preferences ("I prefer / like / don't like ...", conjunction splitting,
  trailing modifiers stripped), facts ("My home airport is SFO.",
  "I work out of / live near / am based in ..."), and instructions
  ("Remember to ...", "From now on ...", "When <clause>, ...",
  "Always ..."). Produces human-readable texts; duplicates of the same
  kind are skipped via normalized-text comparison. The planner is a
  seam: an alternative planner with smarter extraction can replace it
  without touching the engine.
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
  all future context.
- **Forgetting** — explicit requests ("Forget my ...", "I no longer
  prefer ...", "I don't care about ... anymore") are matched against
  active memories by conservative content-word containment. Matches are
  marked `forgotten` with `forgotten_at`/`forget_reason` metadata and a
  `memory_forgotten` event; no hard deletes. Forget-request phrases are
  scrubbed before creation detection so "Forget that I prefer X" never
  creates X.
- **Update keys for facts and instructions** — deterministic keys
  (`fact:home_airport`, `fact:work_location`, `fact:company_location`,
  `instruction:planning`, `instruction:travel`,
  `instruction:response_style`) let changed facts and detail-level
  instructions supersede their predecessors through the same lifecycle
  mechanics as preferences. Content instructions carry no key and
  accumulate instead of replacing each other.
- **Tags/domains** (`memory/tags.py`) — deterministic keyword rules
  assign tags (travel, flight, seat, airport, hotel, timing, transfer,
  meal, budget, work, company, location, style, response_style,
  planning) to every created memory, stored in metadata and persisted.
  Tags are explanation evidence, not a second ranking system.
- **Context selection** (`context/builder.py`) — retrieval happens
  *before* new memories are planned, so a memory created now influences
  later interactions. Active candidates are ranked deterministically
  (keyword overlap with the message, kind priority
  instruction > fact > preference, recency, stable id tie-break) and
  only the top `memory_budget` (default 4) render into the context
  system message, grouped by kind under "ExperienceOS retrieved these
  active user experiences:". Every candidate gets a
  `ContextSelectionRecord` (rank, score, matched keywords, tags,
  matched domains, reason) exposed via the `context_built` payload —
  the dashboard's selection table reads these records directly.
- **Experience compression** (`context/compression.py`) — a
  context-assembly behavior, not storage mutation. Among the memories
  already selected for context, related groups (travel keyword group of
  two or more; per-kind fallback of three or more) are collapsed into
  one `ExperienceSummary` via deterministic templates — no model calls,
  no embeddings, and deliberately not semantic summarization. A summary
  is used only when it genuinely shrinks the rendered context. Source
  memories remain stored and unchanged; each summary carries source
  ids/texts, a reason, and original/compressed/saved character counts
  in the `context_built` payload's `compressed_summaries`. Forgotten
  and superseded memories can never be compressed in, because only
  active selected memories reach the compressor. Compression is opt-in
  (`ContextBuilder(compressor=ExperienceCompressor())`); the demo path
  enables it.

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
- **Memory policy layer** (`experienceos/policy/`) — the optional Local
  Experience Manager. A `MemoryPolicy` proposes lifecycle changes from
  bounded context only; `RuleBasedMemoryPolicy` wraps the deterministic
  planner (the default and the fallback), and `LocalModelMemoryPolicy`
  drives an optional CPU `LocalModelRunner` (llama.cpp, lazy, no
  downloads) through a strict JSON schema. `ExperienceManager` validates
  every proposal, resolves contradictions, enforces the confidence
  threshold, and performs whole-batch typed fallback to the rules;
  the engine still validates targets against the active snapshot and
  remains the only mutation authority. Policies never touch storage.
- **Dashboard** (`demo/`) — a Streamlit visibility layer over the SDK's
  event history and memory store. The dashboard is not the product: it
  exists to make the ExperienceOS platform observable — memories
  accumulating, context being injected, the event lifecycle firing.
  Panels: Experience growth (transparent counts plus a per-turn
  lifecycle timeline of Remembered/Recalled/Updated/Forgot/Compressed
  rows, all derived from the event stream), Active/Superseded/Forgotten
  experiences (with tags and lineage), Context selection (with domains
  and reasons), Compressed context (summaries, sources, savings), the
  context actually supplied, and the raw event log. Provider selection
  lives here, not in the SDK. Display logic that doesn't need Streamlit
  sits in `demo/support.py` so it stays testable without the demo
  extra.

## Flow

```
user message → context builder (injects experience) → provider (Qwen Cloud)
      ↘ events published on the bus → experience engine → memory store
```

Deliberately out of scope: vector databases, embeddings, auth,
background workers, and production infrastructure.
