# ExperienceOS Demo Script (3–5 minutes)

## Setup (before presenting)

```bash
pip install -e ".[demo]"
PYTHONPATH=. streamlit run demo/app.py
```

Leave the provider on **Mock (offline)** — the demo is fully
deterministic and needs no credentials or network. Keep the sidebar and
the right-hand "Experience layer" column visible.

## Opening line (15 seconds)

> "AI today has intelligence but no life experience. Every session
> starts from zero. ExperienceOS is the experience layer for AI agents —
> it lets any LLM-powered agent accumulate experience across sessions:
> remember, retrieve, update, forget, compress, and explain."

Point at the empty dashboard: **the agent currently knows nothing** —
Active memories is empty, Experience growth shows zeros.

## Run the demo (one click)

Click **▶ Run experience lifecycle demo**. Ten turns execute. Then walk
the panels top to bottom:

### 1. Experience growth (the headline)

Read the counts line aloud: memories created, recalls, updates,
forgotten, summaries used, context saved. Then scroll the timeline:

- Turns 1–5: **Remembered** rows — preferences, facts, an instruction —
  with small **Recalled** rows as each turn already reuses what came
  before.
- Turn 6: **Recalled** — "6 selected, 1 skipped" for the first trip.
- Turn 7: **Updated** — "Home airport is SFO. → Home airport is SJC."
  A *fact* changed, and the agent adapted.
- Turn 8: **Updated** — morning flights → evening flights.
- Turn 9: **Forgot** — "Prefers aisle seats."
- Turn 10: **Recalled** + **Compressed** for the final trip. (Compressed
  rows also appear on earlier turns — compression runs whenever it
  saves space.)

> "This is the story: the agent became more experienced over the
> session, and every step is visible."

### 2. Active memories

All three kinds — preference, fact, instruction — each with domain tags
(travel, airport, seat, timing, work, …). Note SJC is here; SFO is not.

### 3. Superseded and Forgotten experiences

Nothing was deleted. SFO and the morning-flight preference sit in
**Superseded** with lineage to their replacements; the aisle-seat
preference sits in **Forgotten** with the reason. History is preserved;
it just stops being used.

### 4. Context selection

The budget math: on the first trip, seven candidates competed for a
budget of six — one memory was skipped, and every row has a reason with
domain evidence ("matched trip, work; domains travel + work + planning").

> "It doesn't dump everything it knows into the prompt. It selects, and
> it can tell you why."

### 5. Compressed context (the Phase-defining moment)

Five related travel memories were collapsed into one summary:

> Travel experience summary: The user's home airport is SJC. Include
> airport transfer time when planning work trips, prefer evening
> flights, prefer quiet hotels near the airport, and avoid red-eye
> flights.

Open the sources expander: the five source memories are listed with the
character savings. Emphasize: **SJC, not SFO — the summary is built from
current experience only**, and the originals still exist unchanged in
Active memories.

### 6. Context supplied

This is literally what the model received: the summary plus the one
uncompressed fact. No superseded, no forgotten memories. The mock
response even confirms how many experience entries were injected.

### 7. Grounded extraction: ExperienceOS evaluates its own components

Scroll to **Extraction decision trace** and **Grounded extraction
evaluation (committed evidence)**. This shows ExperienceOS judging one of
its own experience-management components and refusing to adopt it.

1. Leave **Grounded extraction** on *Disabled* — that is the default.
2. Switch it to *Shadow (observe, non-mutating)* and send a durable
   statement (e.g. "I prefer aisle seats for short work trips.").
3. The trace shows the controller **proposed a candidate**.
4. The committed case examples show the **exact evidence span** it cited.
5. Grounding validation shows **valid**.
6. Canonical effect shows **no** — shadow proposes but never changes
   memory; the memory you see was created by the canonical planner.
7. Open the committed evaluation: one case
   (`creation_002_durable_user_fact`) is a **durable fact the controller
   missed**.
8. Another (`forgetting_003_forget_one_of_several`) is a **forget
   directive it wrongly extracted from** — a false positive.
9. The adoption-gate table shows **12/15 passed** but the **decisive
   gates fail**: no creation-recall improvement and duplicate active
   memories.
10. So ExperienceOS keeps the controller **Shadow only** — it evaluates
    the evidence and refuses adoption when the evidence is insufficient.

Nothing in this view changes runtime behavior: shadow and candidate are
non-mutating, adopted mode is not selectable, and no controller is
adopted.

## Optional live Qwen close (30 seconds)

If credentials are set (`QWEN_API_KEY`), switch the sidebar provider to
**Qwen Cloud** and send one message — the identical experience layer
now drives a live Qwen model, because ExperienceOS is
provider-independent and Qwen specifics live in one isolated adapter.

## Closing line

> "The platform is the product. The dashboard just makes it visible:
> ExperienceOS turned a session of scattered statements into managed,
> compact, explainable experience — and it will still know all of this
> tomorrow." (If time allows: flip Memory storage to SQLite, rerun, and
> restart the app to show memories surviving.)
