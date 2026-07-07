# ExperienceOS — Judging Pitch (speaking notes)

## Problem

AI today has intelligence but no life experience. Agents forget
everything between sessions, and the naive fix — stuffing every stored
note into the prompt — pollutes limited context with stale, conflicting,
irrelevant text.

## Product

**ExperienceOS is the Experience Operating System for AI Agents** — an
experience layer that attaches to any LLM-powered agent. It gives the
agent accumulated experience across sessions: it **remembers** (typed
preferences, facts, and standing instructions), **updates** (changed
facts and preferences supersede their predecessors, with lineage),
**forgets** on request (kept as history, never reused), **retrieves and
ranks** what matters for the current request, **compresses** related
experience into compact summaries, and **explains** every decision with
domain evidence.

It is not a chatbot, not a vector database, not an embedding framework,
and not a generic memory SDK. It is the operating layer that manages
experience between the user and any model.

## Demo proof (all offline, deterministic, one click)

- Agent starts with zero experience; ten turns later the growth timeline
  shows Remembered → Recalled → Updated → Forgot → Compressed.
- "My home airport is now SJC" supersedes the SFO fact; the final trip's
  context contains SJC only — the old fact is visible history, not
  active context.
- Seven candidate memories compete for a budget of six; the skipped one
  has a readable, domain-aware reason.
- Five related travel memories collapse into one summary with source
  tracking and honest character savings.
- Flip storage to SQLite and restart: the experience survives.

## Why Qwen Cloud

Qwen Cloud is the primary inference provider: the adapter speaks the
DashScope OpenAI-compatible API with zero extra dependencies, and one
sidebar switch runs the identical experience layer against a live Qwen
model (`QWEN_API_KEY`; regional endpoints via `QWEN_BASE_URL`).

## Why provider independence

The experience layer is the durable asset — models change, experience
persists. The core never imports provider specifics (enforced by test);
MockProvider gives a deterministic offline demo, and any provider that
implements one `complete(messages)` method gets accumulated experience
for free.

## Intentionally hackathon-simple

Deterministic rule-based extraction, tagging, conflict keys, and
template compression — no embeddings, no vector store, no background
jobs, no migrations. Transparent and auditable by design; each of those
seams (planner, selector, compressor) can be upgraded independently
later.

## What this build proves

Experience management is a layer, not a feature: lifecycle
(active → superseded/forgotten), bounded selection with explanations,
compression that respects lifecycle state, growth you can watch, and
persistence across restarts — 166 automated tests, fully offline.

## One-liner

> ExperienceOS gives any AI agent the ability to accumulate experience
> over time — and to use it the way experience should be used:
> selectively, currently, and explainably.
