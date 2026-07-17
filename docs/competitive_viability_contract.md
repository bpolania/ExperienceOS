# Competitive viability contract

Governing contract for every remaining prompt of the competitive
viability evaluation. It is frozen and reproducible: it fixes the
systems, datasets, evaluation questions, metrics, fairness rules,
evaluator, decision profiles, claims policy, artifact locations, and stop
conditions **before** any comparative result is produced. Later prompts
must conform to this document or stop and surface the conflict.

> **Filename note.** The originating prompt suggested a phase-numbered
> filename. The repository policy in `CLAUDE.md` forbids phase terms in
> new committed filenames and content, so this contract is feature-named,
> consistent with every artifact named in the preceding work. It is the
> single governing contract regardless of filename.

## 1. Objective

Determine whether the current ExperienceOS architecture has a credible,
defensible path to competing with established memory approaches
(full-history prompting, naive top-K retrieval, append-only memory,
lightweight Mem0-style memory, stateless interaction), using assets the
repository already holds.

**This phase evaluates competitive viability. It does not attempt to
prove state-of-the-art performance.** The goal is not to win every
metric; it is to establish whether at least one defensible competitive
profile exists (§9). No frozen architectural decision is revisited here.

## 2. Systems

Seven logical systems. Six are baselines/references already driven
through the shared adapter contract (`benchmarks/contract/system.py`,
`benchmarks/baselines/`); the canonical Qwen system is the demo
composition and needs a small benchmark-side adapter. Readiness is
classified READY (runs today), SMALL_ADAPTER (small reuse layer needed),
or OUT_OF_SCOPE.

- **canonical_experienceos_qwen** — the actual hackathon demo
  architecture: `demo.support.create_agent` with
  `build_canonical_extraction_config` selecting `QwenExtractionController`
  when Qwen Cloud is configured, then grounded validation, deterministic
  governance, memory lifecycle, lifecycle-aware retrieval, the canonical
  context builder, and a Qwen final response via `agent.chat(...)`. It is
  the system under test. *Readiness: SMALL_ADAPTER* — the demo produces a
  full answering agent, but no benchmark adapter wires it into a graded
  conversation→answer run yet; the evaluation must exercise this
  canonical path, never the `experiments/qwen_extraction_shadow.py`
  proposal-only harness.
- **deterministic_experienceos** — the historical deterministic
  extraction and governance path (`experienceos_rules` adapter). Used as
  an internal reference, not as proof of general superiority. *Readiness:
  READY.*
- **stateless** — no persistent memory; each turn answers from the
  current message only. *Readiness: READY.*
- **full_history** — the complete available conversation history is given
  to the same response model. *Readiness: READY.*
- **naive_top_k** — raw conversation turns/records retrieved by the
  existing top-K baseline, no lifecycle. *Readiness: READY.*
- **append_only** — memories stored without update, forgetting, or
  lifecycle management. *Readiness: READY.*
- **mem0_style_lightweight** *(conditional)* — a minimal add/update/
  delete/no-op memory over the same Qwen provider: extract candidate
  facts → retrieve related facts → choose an operation → store. Labelled
  exactly `mem0_style_lightweight`; the official Mem0 product is not run
  and it is never called "Mem0". *Readiness: SMALL_ADAPTER* — it can
  reuse the existing baseline execution pipeline
  (`benchmarks/baselines/common.py`, factory) as one new baseline class.
  It is built only if that stays small; otherwise it is **deferred**, and
  the other comparisons complete without it.

## 3. Frozen architecture

The canonical architecture, exactly as adopted and verified present in
the demo agent:

```
Conversation
    ↓
Qwen Extraction
    ↓
Grounded Validation
    ↓
Deterministic Governance
    ↓
Memory Lifecycle
    ↓
Retrieval
    ↓
Context Builder
    ↓
Qwen Response
```

**Deterministic governance remains authoritative** over validation,
authorization, lifecycle, updates, forgetting, lineage, persistence,
mutation, and context construction. Qwen only proposes extraction
candidates; every candidate passes the unchanged `GroundedCandidateValidator`
and the engine's existing authority. **Qwen update intelligence remains
experimental and non-canonical** (`experiments/qwen_update.py`, not wired
into any runtime path). The core `experienceos/` package is unchanged
from the published baseline `6f893f9` and is not modified by this phase.

## 4. Datasets

Only existing materials are reused; no large new corpus is authored.
Presence is classified VERIFIED / PARTIAL / MISSING.

| Dataset | Source | Frozen/dev | Purpose | Expected use | Status |
|---|---|---|---|---|---|
| Lifecycle benchmark (40 scenarios: creation 6, updates 8, forgetting 6, retrieval 8, containment 6, context 6) | `benchmarks/scenarios/lifecycle/` + `lifecycle_manifest.json` | frozen historical | creation, preferences, instructions, updates, corrections, scoped coexistence, forgetting, retrieval, current-state | primary lifecycle + retrieval cases in the viability subset | VERIFIED |
| LongMemEval 50-case stratified subset (abstention / information-extraction / knowledge-updates / multi-session-reasoning / temporal-reasoning, 10 each) | `benchmarks/external/longmemeval/manifest.json`; committed evidence `benchmarks/results/committed/longmemeval-50-subset-v2` | frozen (IDs/manifest) | multi-session retrieval, temporal/current-state, abstention, personalized answering | multi-session and abstention cases | PARTIAL — manifest, IDs, and committed evidence present; raw dataset **content is gitignored/not committed** and loads from a local path |
| Retrieval benchmark evidence | `benchmarks/results/committed/phase11-semantic-retrieval`, `benchmarks/evaluators/retrieval*.py` | frozen historical | answer-bearing recall, Recall@K, MRR | retrieval metric definitions and reference numbers | VERIFIED |
| Grounded-extraction annotations (lifecycle 40, external 50) | `benchmarks/annotations/grounded-extraction/` | frozen historical | creation precision/recall, answer-bearing candidate presence | memory-acquisition scoring | VERIFIED |
| Transition corpus (28 historical-scored + 27 development + 13 unresolved; 48 classification-applicable) | `benchmarks/annotations/transition-verification/` | frozen historical + development marked separately | update / forget / coexistence lifecycle correctness | memory-evolution scoring | VERIFIED |
| Applied-state evidence | `benchmarks/results/committed/action-replacement`, `...-adoption` | frozen historical | deduplicated applied-state, wrong-target safety | safety reference | VERIFIED |
| Qwen extraction evidence | `experiments/results/qwen_extraction_shadow/` | frozen historical | extraction quality vs deterministic | acquisition reference | VERIFIED |
| Canonical evaluation path | `docs/qwen_adoption_closure.md`, `demo/support.py` | current | the system under test | drives `canonical_experienceos_qwen` | VERIFIED |

Historical-scored cases stay separate from development-only fixtures.
Unscorable cases (e.g. external records without committed source text)
are marked unscorable and excluded from scored numerators and
denominators — never silently substituted.

## 5. Evaluation questions

The phase must answer, without altering their meaning:

1. Does Qwen extraction improve memory creation quality over
   deterministic extraction?
2. Does Qwen extraction reduce answer-bearing candidate absence?
3. Does ExperienceOS retrieve answer-bearing memories as reliably as
   naive top-K?
4. Does ExperienceOS produce better final answers than stateless
   interaction?
5. Does ExperienceOS approach full-history answer quality with less
   context?
6. Does ExperienceOS outperform append-only memory on updates and
   forgetting?
7. Does ExperienceOS maintain better current-state correctness than raw
   RAG?
8. Does lifecycle governance produce measurable user-facing benefits?
9. Is there at least one credible competitive profile?
10. Is further full-scale benchmarking justified?

## 6. Metrics

Only these families; no additional benchmark families are introduced.
Several are already computed by the existing harness aggregate
(`answers_per_1k_memory_tokens`, `correct_update_target_rate`,
`correct_forget_target_rate`, `conflicting_active_memory_rate`,
`duplicate_acceptance_rate`, `context_budget_utilization`).

- **Memory acquisition:** creation precision, creation recall, creation
  F1, unsupported-memory rate, candidate-absence rate.
- **Memory evolution:** update accuracy, stale-memory rate, duplicate
  active-memory rate, scoped-coexistence preservation, forget accuracy,
  forgotten-memory exclusion.
- **Retrieval:** answer-bearing candidate recall, Recall@K, MRR,
  answer-bearing selection rate.
- **Final answer:** final-answer accuracy, preference-adherence accuracy,
  current-vs-stale answer accuracy, abstention accuracy where evidence is
  missing.
- **Efficiency:** context tokens, answer accuracy per 1,000 context
  tokens, average latency (secondary).
- **Safety:** wrong-target mutations, unrelated-memory loss,
  scoped-memory loss, state corruption, forgotten-memory resurrection.

Every class-level rate states whether it is accuracy, recall, precision,
or correct/total. No ambiguous numbers are published.

## 7. Fairness rules

Inherited from `docs/benchmark_contract.md` and made concrete for the
live answer run. All are required:

- **identical response model** — one Qwen model (`qwen-plus`, fixed
  temperature and max-output in `SystemConfig`) answers for every system;
  only the memory system differs.
- **identical prompts** — the same final-answer prompt and the same fixed,
  versioned Qwen extraction prompt for every applicable system.
- **identical conversations** — the same histories and question order.
- **identical scoring** — the same evaluator and judge prompt for all.
- **identical token accounting** — the harness `ContextAccounting` method.
- **no benchmark-oracle leakage** — adapters are observers of public
  interfaces; no oracle field reaches any system; no benchmark branch
  enters the production engine.
- **no per-system tuning** — no per-case tuning, no prompt search.
- **no hidden manual intervention** — no case is edited, retried
  selectively, or hand-corrected to change a score.

ExperienceOS receives no information unavailable to the baselines;
baselines receive no oracles.

## 8. Evaluator

Final-answer quality is the important new layer. Scoring order, most
deterministic first:

1. **Deterministic scoring** — the existing
   `benchmarks/evaluators/response.py` constraint matching
   (`must_include_all` / `must_include_any` / `must_exclude`), which
   already yields current-fact, multi-session, instruction, and
   preference compliance.
2. **Rule-based scoring** — explicit expected-answer criteria and
   abstention flags.
3. **Blinded LLM judge** — only where deterministic scoring is not
   practical (free-form answers, `model_scored` cases the offline
   evaluator defers). This judge is a new, minimal addition; no LLM judge
   exists in the repository today.

Structured verdict schema (the judge returns exactly this; never a lone
1–10 score):

```json
{
  "correct": true,
  "uses_current_information": true,
  "uses_stale_information": false,
  "follows_user_preferences": true,
  "unsupported_claim": false
}
```

Judge rules when used: the same judge prompt for every system; system
identity hidden; answer ordering randomized where practical; judge model
and prompt recorded; the judge never sees system labels or oracle
rationale beyond the expected-answer criteria required to grade.

## 9. Competitive profiles

ExperienceOS need not win every metric. The five-percentage-point bands
are practical hackathon heuristics, not statistical confidence claims.

- **Profile A — Better overall quality:** `canonical_experienceos_qwen`
  is best or effectively tied on final-answer quality.
- **Profile B — Comparable quality with better lifecycle:** within ~5
  points of the best answer-quality system **and** materially better on
  updating, forgetting, stale-state control, memory consistency, or state
  safety.
- **Profile C — Comparable quality with better context efficiency:**
  similar answer quality with substantially less context — **provided**
  the savings do not come from dropping relevant evidence.
- **Not yet competitive:** materially behind on answer quality with no
  compensating lifecycle or efficiency advantage.

Phase decision vocabulary (exactly one at closure):
`COMPETITIVE_VIABILITY_DEMONSTRATED`,
`DIFFERENTIATED_VIABILITY_DEMONSTRATED`,
`COMPETITIVE_VIABILITY_NOT_YET_DEMONSTRATED`, or
`COMPETITIVE_VIABILITY_INCONCLUSIVE`.

## 10. Claims policy

**This evaluation is a hackathon viability assessment. Results must not
be generalized beyond the evaluated datasets. No unsupported superiority
claims may be made.** State the subset size and composition prominently.
Distinguish classification/extraction quality from validator acceptance
and from final-answer correctness — never conflate them. Separate frozen
historical, reused external, development-only, and unscorable evidence.
Latency and provider dependency are reported as real costs. A failed
system run is a recorded result, never replaced by another system's
output.

## 11. Artifact locations

Feature-named, following existing conventions
(`docs/benchmark_runner.md`). Listed here without being created; live
runs are non-deterministic and land in the non-committed local tree,
while only a curated summary and the report are committed.

- Comparison harness code: `experiments/` and/or a small
  `benchmarks/` adapter (smallest reuse layer; no framework rewrite).
- Live comparison runs: `benchmarks/results/local/competitive-viability/`
  (`aggregate.json`, `cases.jsonl`, `metric_contributions.jsonl`,
  provenance / run-config, `artifact_manifest.json`, `README.md`).
- Committed evidence summary:
  `benchmarks/results/committed/competitive-viability/` (curated
  `results.json` + manifest; ids and metrics only, no raw provider
  payloads, no source text beyond what annotations already commit).
- End-to-end answer evidence and judge verdicts: alongside the run under
  the local tree, curated summary committed.
- Closure report: `docs/competitive_viability_report.md`.
- This contract: `docs/competitive_viability_contract.md`.

## 12. Stop conditions

Later steps of this evaluation must stop and surface the problem — not
expand scope or repair silently — if any hold:

- **missing canonical architecture** — the canonical demo path or any of
  its six stages cannot be exercised.
- **missing benchmark assets** — a required dataset, runner, evaluator, or
  baseline is absent or altered.
- **unavailable Qwen execution** — credentials are missing or the provider
  is unreachable mid-run (report cases attempted/completed and which
  metrics are incomplete; never fabricate results).
- **inability to execute a fair comparison** — achieving fairness would
  require a non-goal (retrieval redesign, update-controller adoption,
  compression/consolidation, a large new corpus, model fine-tuning, or
  statistical-research infrastructure).

Only bounded corrections strictly required to run a fair comparison are
permitted, and each must be reported explicitly. `mem0_style_lightweight`
is deferred rather than pursued if it would materially expand scope.

## Decision

`PHASE_17_VIABILITY_CONTRACT_COMPLETE`
