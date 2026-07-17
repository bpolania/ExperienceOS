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


## Phase 9: the full v2 experience layer

Phase 9 rebuilt experience quality end to end. The final system,
**`experienceos_hybrid_full_v2`**, composes every measured component:

- **semantic identity + generalized supersession** — "my phone is a
  Pixel 9 now" supersedes the Pixel 6 fact without per-domain rules;
  scoped preferences (aisle for short work trips, window for long
  international trips) coexist
- **hybrid conversational extraction** — durable facts stated
  naturally ("I work for Globex now", "my daughter's soccer practice
  moved to Thursday") become gated, grounded, validated memories
- **lifecycle-aware hybrid retrieval** — BM25-style lexical +
  structured-identity recall over ACTIVE memories only; forgotten and
  superseded records can never enter current context
- **coverage-aware context selection** — complementary, non-redundant
  evidence within the unchanged K and budget; zero-value padding is
  gone
- **temporal + provenance metadata** — observed vs event time,
  validity derived from supersession links,
  current/historical/as-of/timeline query modes, source types with a
  documented trust ordering; exact dates are never fabricated
- **generalized forget resolution** — paraphrased forget requests
  ("forget my morning drink preference") resolve conservatively;
  ambiguity and "forget everything" are rejected, never guessed
- **local-policy v2 containment** — one-action structured proposals,
  strict parsing, syntax-only repair, one bounded retry, per-action
  deterministic fallback; malformed model output cannot corrupt state

The canonical policy mode is **scripted-simulated**
(`simulated_proposal: true`, `direct_model_inference: false`): the
deterministic plan is serialized through the real local-policy-v2
parse/validation/audit pipeline. The development real-local mode
(Qwen2.5-0.5B-Instruct Q4_K_M) produced **0/15 and 0/8 directly valid
proposals** in bounded runs — every failure was contained by
deterministic fallback with zero state corruption. The local model
path currently demonstrates model-failure containment, not reliable
autonomous memory management.

### Phase 9 benchmark evidence (v2)

Lifecycle benchmark (frozen 40 scenarios; raw numerators/denominators;
full ablation across nine systems in
[docs/benchmark_report_v2.md](docs/benchmark_report_v2.md)):

| Metric | Rules (v1) | Full v2 |
|---|---:|---:|
| Lifecycle cases passed | 17/40 | **21/40** |
| Creation recall | 10/13 | **12/13** |
| Supersession | 2/7 | **6/7** |
| Forget detection | 2/4 | **4/4** |
| Forgotten exclusion | 0/2 | **2/2** |
| Recall@K | 15/17 | **17/17** |
| Inactive contamination ↓ | 2/20 | **0/18** |
| State corruption | 0 | 0 |

LongMemEval fixed subset (frozen 50-case stratified subset,
deterministic offline provider — **not an official LongMemEval
score**):

| Metric | Rules (v1) | Full v2 |
|---|---:|---:|
| Candidate rate | 28/50 | **31/50** |
| Selection rate | 14/50 | 12/50 |
| MRR | 0.186 | **0.305** |
| Context tokens | 10,328 | **5,527** |

Read the selection row carefully: the selection rate **fell** because
Phase 9 removed zero-relevance K-padding (part of v1's credit was
accidental), while MRR rose and context tokens dropped 46.5%. The
naive top-K baseline retains higher raw-turn retrieval recall (42/50
selection, 0.658 MRR) — it retrieves raw conversation turns, while
ExperienceOS retrieves distilled durable memories with lifecycle
guarantees. Remaining gaps (stale leakage 7/11, 19 external
candidate-absence cases, no embeddings) are itemized in the report.

Validate and reproduce the v2 evidence (offline, no model, no
network):

```bash
./scripts/run_benchmarks.sh validate-v2
./scripts/run_benchmarks.sh validate-external-v2
./scripts/run_benchmarks.sh validate-v2-consistency
./scripts/run_benchmarks.sh validate-report-v2
./scripts/run_benchmarks.sh report-v2   # regenerate the comparative report
```

Full comparative report: [docs/benchmark_report_v2.md](docs/benchmark_report_v2.md)
· Phase 9 closure: [docs/phase9_closure.md](docs/phase9_closure.md)
· Component docs: [semantic identity](docs/phase9_semantic_identity.md),
[extraction](docs/phase9_hybrid_extraction.md),
[retrieval](docs/phase9_hybrid_retrieval.md),
[coverage](docs/phase9_coverage_selection.md),
[temporal/provenance](docs/phase9_temporal_provenance.md),
[forgetting & local policy](docs/phase9_forget_policy.md).

## Phase 11: semantic retrieval and controller foundation

Phase 11 added an optional, measured semantic-retrieval capability
and the first specialized-controller seams on top of the deterministic
kernel — **without changing the canonical default**: Phase 9
lexical/hybrid retrieval remains the recommended path.

What exists now:

- **provider-independent embedding abstraction**
  (`experienceos/embeddings/`): a deterministic test provider
  (`stable-feature-hash-v1`, 512 dims) for CI/reproducibility, plus an
  optional local sentence-transformers provider (`pip install -e
  ".[embeddings-local]"`, lazy import, local-files-only, never
  downloads) — implemented but **unmeasured** (dependency not
  installed)
- **lifecycle-safe semantic scoring** with a bounded process-local
  cache: eligibility is decided before any similarity, so forgotten
  and superseded memories are never embedded and can never be
  resurrected
- **deterministic fixed-weight score fusion** with frozen versioned
  profiles and a reference bypass proven byte-identical to Phase 9
- **shadow-only MemoryGate**: proposes admit/reject/abstain on the
  finished selection; `affected_selection` is invariantly zero
- **proposal-only contracts** for six specialized controller roles
  (admission, extraction, update, forget-intent, gate, transition
  verification) — interface-only except the shadow gate
- **dashboard diagnostics**: retrieval mode, provider status, score
  breakdowns, lifecycle-exclusion labels, cache counters, and
  shadow-gate proposals (see
  [docs/dashboard_phase11_diagnostics.md](docs/dashboard_phase11_diagnostics.md))

**Measured result** (fixed 50-case subset, deterministic test
embedding provider — plumbing evidence, not learned semantic quality,
and not an official LongMemEval score): the Phase 9 reference
reproduced exactly (selection 12/50, MRR 0.305, 5,527 context
tokens); embedding-only retrieval regressed materially (2/50, MRR
0.168) and is **not adopted**; fused retrieval selected one more case
(13/50) with fewer tokens (5,448) but materially regressed MRR
(0.293) and remains **experimental**; the gate shadow produced 34,148
proposals with zero selection effect and zero failures. Lifecycle
leakage stayed zero for every system. Full evidence:
[docs/phase11_semantic_retrieval_report.md](docs/phase11_semantic_retrieval_report.md);
architecture:
[docs/controller_architecture.md](docs/controller_architecture.md).

## Grounded experience extraction

ExperienceOS can accept memory proposals from deterministic or learned
components, but a component earns durable-write access only by citing
exact user evidence, clearing the same lifecycle authority, and passing
predeclared adoption gates. Grounded extraction is the machinery for
**evaluating** such components — it changes no default (extraction
integration is `disabled`).

What exists now:

- **grounded candidate validation** (`experienceos/memory/grounding.py`):
  exact evidence-span matching, approved source and provenance, canonical
  kinds, and rejection of questions, hypotheticals, temporary states,
  one-off requests, unsupported third-party ownership, and unsupported
  normalization — proposal-only, non-mutating
- **a deterministic controller** (`grounded_rules-1`) that proposes
  exactly one grounded candidate or abstains — the explicit alternate
  implementation used offline, in tests, and for comparison benchmarks
- **a Qwen extraction controller** that is **canonical for the hackathon
  demo whenever Qwen Cloud is configured** (selected in composition by
  `demo.support.build_canonical_extraction_config`, so the core stays
  provider-neutral; the SDK default outside the demo is unchanged). It
  only proposes: every candidate still passes the unchanged grounded
  validator and the same lifecycle authority, and it holds no mutation
  authority. One temperature-0 call per message, with no fallback and no
  retries — a failed call is an explicit non-candidate result, never a
  deterministic proposal in disguise. A Qwen update-intelligence
  controller was also implemented and evaluated but remains experimental
  and not canonical. Decisions and limitations:
  [docs/qwen_adoption_closure.md](docs/qwen_adoption_closure.md)
- **an optional learned-controller foundation** — narrow runner protocol,
  strict structured output, untrusted-output handling, exact-span
  verification, explicit deterministic fallback, and optional lazy local
  and Qwen runners — proposal-only and, in the committed benchmark,
  **unavailable** (no runtime configured; never downloads a model)
- **an integration seam** with four effect modes — `disabled` (default),
  `shadow`, `candidate`, `adopted` — where shadow and candidate never
  mutate and adopted requires explicit authorization and still routes
  through the single engine mutation boundary (no second write path)
- **dashboard diagnostics** exposing the live decision trace, evidence
  spans, grounding/lifecycle separation, canonical effect, and the
  committed benchmark evidence (see
  [docs/extraction_diagnostics_dashboard.md](docs/extraction_diagnostics_dashboard.md))

**Measured result** (frozen lifecycle annotations; committed evidence,
not an official benchmark): the deterministic controller was well
grounded — grounded-span validity 6/6 (100%), unsupported-claim rate
0/6, proposal precision 5/6 (83.3%), recall 5/13 (38.5%) — but it did
**not** improve durable creation over the canonical planner (11/13
both), missed durable facts, and under benchmark-only adoption produced
one forget-directive false positive and two semantic-duplicate active
memories. State corruption, inactive contamination, and forgotten and
superseded leakage all stayed zero. **12 of 15 adoption gates passed**,
but passing most gates is not adoption: the three failed gates — no
creation-recall/candidate-absence improvement, semantic duplicate active
memories, and no measured downstream benefit — are decisive (the formal
`precision_defensible` gate passed, yet durable false positives still
increased, a real trade-off). The controller is therefore classified
**shadow-only** and **no controller is adopted**. This is the product
working as intended: ExperienceOS evaluates an experience component and
refuses to let it affect durable memory until the evidence justifies it.
Full evidence:
[docs/grounded_extraction_report.md](docs/grounded_extraction_report.md).

## Experience transition verification (evaluated, candidate-only)

Accumulating experience is not just adding memories — it is knowing when
a new statement *replaces* an old one, when it merely coexists with it,
and when it asks to remove one. ExperienceOS treats that judgement as a
**transition**: a proposal about how durable state should change, which
must be verified against evidence and authorized before it can touch
anything. Transition integration is `disabled` by default and **no
transition controller is canonical**.

What exists now:

- **semantic memory identity** (`experienceos/memory/identity.py`):
  projects a statement into subject, attribute, value, and scope, then
  compares it against existing memories — so "my phone is a Pixel" can
  supersede "my phone is an iPhone" while "aisle seats **for work
  trips**" coexists with an unscoped seat preference. Identity is
  structural, not a similarity score; a float never decides safety
- **a proposal and verification model**
  (`experienceos/memory/transition_verification.py`): a controller
  proposes a transition, and a separate verifier checks it against the
  before-state and the cited evidence. **The verifier never applies
  anything** — `action_applied` is invariantly false
- **deterministic update and forget controllers**
  (`update_intelligence.py`, `forget_intelligence.py`): propose
  supersession or forget-target resolution, or abstain. Forget
  directives are routed to the forget path rather than answered with a
  new memory, questions about removal ("could you remove my airport
  preference?") are never treated as directives, and ambiguous targets
  fail closed instead of guessing
- **governed integration** (`transition_integration.py`) with five
  modes — `disabled` (default), `shadow`, `candidate`, `verify_only`,
  `adopted`. Only `adopted` can reach durable state, and only with an
  authorization bound to **20 exact fields** of one specific verified
  proposal. Any mismatch fails closed and names the field; there is no
  wildcard and no environment-variable path. Everything still routes
  through the single engine mutation boundary — no second write path
- **dashboard diagnostics** exposing the live 13-stage transition trace,
  identity and target resolution, projected-versus-applied state, and
  the committed benchmark evidence (see
  [docs/transition_dashboard.md](docs/transition_dashboard.md))

**Measured result** (28 historical scored cases from frozen lifecycle
annotations, plus 27 development fixtures kept separate; committed
evidence, not an official benchmark): the transition intelligence
**proposes correctly** — 28/28 transition classifications correct, 11/11
update targets resolved with **0 wrong**, 0 scoped and 0 unrelated
memories lost, 0 ambiguous targets guessed into a mutation, and 20/20
authorization mismatches rejected. Stale active-memory leakage drops
materially: **6 → 1** stale pairs. But under isolated benchmark-only
adoption the integration **adds** its replacement create alongside the
canonical planner's create, so both persist: semantic-duplicate active
pairs go **0 → 10**. **18 of 20 adoption gates passed, 1 failed, 1 is
inconclusive** — and all **9 blocking safety gates passed**. Passing
every safety gate is still not adoption: the failed Gate 1 (duplicate
active memories) is decisive, so the path is classified
**`TRANSITION_PATH_CANDIDATE_ONLY`** and no controller is adopted. Gate
6 is reported **inconclusive**, not passed — both systems already create
zero memories from forget directives, so no reduction can be
demonstrated, and absence of regression is not measured improvement.

The known cause is integration semantics — the transition's create is
*added* rather than *replacing* the planner's — and it is documented
rather than papered over. This is the product working as designed:
ExperienceOS evaluated its own transition intelligence, found the
proposals sound and the applied outcome wanting, and refused adoption.
Full evidence:
[docs/transition_verification_report.md](docs/transition_verification_report.md)
· closure: [docs/transition_verification_closure.md](docs/transition_verification_closure.md)
· judge runbook: [docs/transition_demo_runbook.md](docs/transition_demo_runbook.md)
· contract (frozen before results):
[docs/transition_verification_contract.md](docs/transition_verification_contract.md)
· components: [semantic identity](docs/semantic_memory_identity.md),
[verification model](docs/transition_verification.md),
[update](docs/update_intelligence.md),
[forget](docs/forget_directive_intelligence.md),
[integration](docs/transition_integration.md).

Validate the committed transition evidence (offline; no credentials, no
network, no model):

```bash
./scripts/run_benchmarks.sh validate-transition-verification
```

The section below is the frozen **Phase 8 (v1)** evidence, preserved
unchanged as the historical baseline the v2 numbers are measured
against.

<!-- benchmark-evidence:begin (generated; do not edit) -->
## Benchmark Evidence

Two separate evidence tracks, both fully offline and generated from committed raw artifacts (deterministic provider, approximated `ceil(chars/4)` token accounting): the **custom lifecycle benchmark** (40 scenarios × 6 systems) measures whether accumulated experience stays current, relevant, and bounded; the **LongMemEval 50-case stratified subset** (official data, structural run, proxy answer metrics, no official judge — not an official LongMemEval score) probes long-history retrieval. ExperienceOS local is the scripted-plus-fallback offline mode, not a real-GGUF result. Full detail, denominators, failures, and limitations: [docs/benchmark_report.md](docs/benchmark_report.md).

**Custom lifecycle (ExperienceOS rules vs strongest contrasts; raw n/d shown):**

| Metric | ExperienceOS rules | Append-only | Full history |
|---|---|---|---|
| Old-value deactivation | 3/8 (37.5%) | 0/8 (0.0%) | 8/8 (100.0%) |
| Expected-memory Recall@K | 15/17 (88.2%) | 10/17 (58.8%) | 0/17 (0.0%) |
| Duplicate acceptance | N/A (3 undefined, 0 eligible) | 2/2 (100.0%) | N/A (3 undefined, 0 eligible) |
| Avg context tokens (38 cases) | 60.4 | 32.2 | 91.1 |

Honest hard-case results stay visible: stale rendered-context leakage for ExperienceOS rules is 10/11 (90.9%) (the dataset's aspirational unkeyed-domain update oracles), and forgotten-content exclusion is 0/2 (0.0%) on its two eligible probes.

**LongMemEval 50-case stratified subset (structural offline run):**

| Metric | ExperienceOS rules | Naive top-K | Full history |
|---|---|---|---|
| Answer-session selection | 14/50 (28.0%) | 42/50 (84.0%) | N/A (50 undefined, 0 eligible) |
| Answer-session MRR | 9.28315/50 (18.6%) | 32.8795/50 (65.8%) | N/A (50 undefined, 0 eligible) |
| Avg supplied context tokens (50 cases) | 206.6 | 2604.2 | 126173.0 |

Naive lexical retrieval outperforms ExperienceOS's sparse rule-based extraction on this conversational subset — a measured limitation, reported as such. Reproduce/verify: `./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1`, `./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1`, `./scripts/run_benchmarks.sh report`.
<!-- benchmark-evidence:end -->

## Benchmarking

A lifecycle benchmark compares ExperienceOS against stateless,
full-history, append-only, and naive-retrieval baselines, and the
Phase 9 ablation extends it across nine system configurations (see
the Phase 9 section above). The measurement rules — schemas, metric denominators, leakage
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
An external
track — the **LongMemEval 50-case stratified subset** (not an
official full-benchmark score) — is documented in
[docs/longmemeval_subset.md](docs/longmemeval_subset.md) and kept
fully separate from the custom lifecycle results.
The default benchmark path is fully offline (no credentials, no
network, no model downloads). Raw comparative artifacts live under
`benchmarks/results/committed/`, and the generated comparative report
is [docs/benchmark_report.md](docs/benchmark_report.md) — headline
values (with raw denominators) appear in the Benchmark Evidence
section above.

Run and validate the offline benchmark:

```bash
./scripts/run_benchmarks.sh quick
./scripts/run_benchmarks.sh full-offline
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1
./scripts/run_benchmarks.sh validate-report
```

Validate the Phase 9 v2 evidence and report:

```bash
./scripts/run_benchmarks.sh validate-v2
./scripts/run_benchmarks.sh validate-external-v2
./scripts/run_benchmarks.sh validate-v2-consistency
./scripts/run_benchmarks.sh validate-report-v2
```

Validate the committed Phase 11 retrieval evidence (four systems,
double-run digest-locked, deterministic test embedding provider):

```bash
./scripts/run_benchmarks.sh validate-phase11
./scripts/run_benchmarks.sh validate-external-phase11
./scripts/run_benchmarks.sh validate-phase11-consistency
./scripts/run_benchmarks.sh validate-report-phase11
```

Validate the committed transition evidence (three artifact families:
per-case verification, ablations, and the report):

```bash
./scripts/run_benchmarks.sh validate-transition-verification
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
