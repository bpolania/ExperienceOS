# ExperienceOS Benchmark Report v2 — Phase 9 Comparative Evidence

ExperienceOS is the experience layer for AI agents: it decides what an
agent should remember, update, forget, retrieve, and place into
bounded context, with temporal state, source provenance, and
containment of unreliable model proposals. This report compares the
Phase 8 rules baseline (v1) with the Phase 9 final system,
`experienceos_hybrid_full_v2`, using only the committed, digest-locked benchmark
artifacts. Every rate keeps its raw numerator and denominator; no
blended score exists.

**Sources** (validate before trusting any number here):

- Lifecycle v2: `benchmarks/results/committed/lifecycle-v2-ablation` — digest
  `ee437bb3e9fde909f343112e40aaa6ecf63155a07a81ad67e017e310fbefb547`
- LongMemEval v2: `benchmarks/results/committed/longmemeval-50-subset-v2` — digest
  `19b66cacb330e943b0460ccdb33e8cc6577fccb17621cb7a129f7420f5c7868f`
- v1 anchor: `benchmarks/results/committed/lifecycle-offline-v1` —
  digest `8b0e245d914a43bc578923111e8ff40e70d9c8aa487664c00125fc52fa319b33`

## 1. Executive summary

On the frozen 40-scenario lifecycle benchmark, full v2 passes
**21 cases vs the rules baseline's 17**,
improving every lifecycle dimension it targeted: creation
(10/13 →
12/13 recall), updates
(supersession 2/7 →
6/7), forgetting (detection
2/4 →
4/4, forgotten exclusion
0/2 →
2/2), retrieval (Recall@K
15/17 →
17/17), and safety (inactive contamination
2/20 →
0/18, zero state
corruption, K and budget unchanged, no zero-value padding). On the
frozen LongMemEval subset, MRR rose from 0.186 to
0.305 while context tokens fell
4,801 (46.5%),
from 10,328 to 5,527.
The selection **rate fell** from 14/50 to 12/50 — a disclosed trade-off
analyzed in §7 — and raw-turn naive top-K retains superior raw recall
(§6). The LongMemEval evaluation uses a frozen 50-case stratified subset with a deterministic offline answer provider; it is not an official LongMemEval score.

## 2. What was measured and how

Two frozen evaluations, unchanged from Phase 8: the 40-scenario
lifecycle benchmark (creation, updates, forgetting, retrieval,
context, containment; manifest hash locked) and the LongMemEval
50-case stratified subset (official revision
`98d7416c24c778c2fee6e6f3006e7a073259d48f`, manifest hash locked,
fingerprint-verified official source, deterministic offline answer
provider — results measure memory availability, selection, and rank,
not live answer quality). Nine systems ran on the lifecycle benchmark
and ten on the subset; `experienceos_slots_v2` has no distinct
external runner (no distinct external runner: slot supersession is not exercised by the subset's retrieval-only evaluation).

## 3. The final system

`experienceos_hybrid_full_v2` composes the measured Phase 9 components: semantic identity
with conservative generalized supersession, hybrid deterministic
conversational extraction, lifecycle-aware hybrid retrieval,
coverage-aware selection, temporal/provenance metadata with
current/historical/as-of/timeline query modes, a deterministic forget
resolver, and the local-policy v2 parsing/validation/audit/containment
pipeline. experienceos_local_v2 and experienceos_hybrid_full_v2 use scripted-simulated local proposals (direct model inference: false); results are never real-model accuracy. K, context
budgets, the answer provider, and both datasets are unchanged from v1.

## 4. Lifecycle headline results

| Metric | Rules (v1) | Full v2 | Change |
|---|---|---|---|
| Creation precision | 10/11 | 12/13 | (+2.0, better) |
| Creation recall | 10/13 | 12/13 | (+2.0, better) |
| Supersession accuracy | 2/7 | 6/7 | (+4.0, better) |
| Old-value deactivation | 3/8 | 7/8 | (+4.0, better) |
| Conflicting-active rate ↓ | 3/7 | 0/7 | (-3.0, better) |
| Stale context leakage ↓ | 10/11 | 7/11 | (-3.0, better) |
| Forget detection | 2/4 | 4/4 | (+2.0, better) |
| Correct forget target | 2/2 | 4/4 | (+2.0, better) |
| Forgotten exclusion | 0/2 | 2/2 | (+2.0, better) |
| Unrelated preservation | 3/3 | 3/3 | unchanged |
| Resurrection/incorrect target ↓ | 0/6 | 0/6 | unchanged |
| Recall@K | 15/17 | 17/17 | (+2.0, better) |
| Inactive contamination ↓ | 2/20 | 0/18 | (-2.0, better) |
| Passed cases (of 40 scenarios) | 17 | 21 | (+4, better) |

Direction notes: metrics marked ↓ are better when lower. The 0/18 vs
2/20 contamination rows keep their own denominators (eligible
inactive-memory slots differ when supersession changes final states).

## 5. What each component contributed (ablation evidence)

- **Semantic identity (slots_v2)**: supersession 2/7 → 5/7, conflicting
  actives 3/7 → 0/7, stale leakage 10/11 → 6/11. No creation or
  retrieval gains by itself.
- **Hybrid extraction (hybrid_extract_v2)**: creation recall 10/13 →
  11/13 and precision numerator up (11/12); external candidates 28/50 →
  29/50. Without supersession it worsens leakage (11/11) — the
  composition resolves this.
- **Hybrid retrieval (hybrid_retrieval_v2)**: lifecycle Recall@K 15/17 →
  17/17; external MRR 0.186 → 0.246; context tokens roughly halved;
  zero-relevance padding removed (which lowers raw selection counts —
  §7).
- **Coverage selection (coverage_v2)**: stale leakage 10/11 → 8/11 and
  contamination 2/20 → 0/18 at equal Recall@K, with fewer tokens; no
  external MRR/selection change on this subset because candidate pools
  rarely exceed K after zero-relevance exclusion.
- **Temporal/provenance (temporal_v2)**: the best no-extraction
  composition (supersession 5/7, leakage 6/11, Recall@K 17/17);
  external candidates 30/50, MRR 0.266; adds current/historical/as-of/
  timeline behavior and provenance at ~7% context-label overhead.
- **Forget resolver + policy pipeline (local_v2)**: forget detection
  2/4 → 4/4, forgotten exclusion 0/2 → 2/2, correct targets 4/4,
  supersession 6/7, and the final two passed cases; policy containment
  complete (structural validity 104/104, fallback 0/104
  scripted-simulated, zero corruption).
- **Full v2**: identical rows to local_v2 by design — the final
  contract ID records the selected complete configuration and its
  provenance; it is not an independent extra measurement.

## 6. LongMemEval fixed-subset results

| System | Candidate | Selection | MRR | Context tokens |
|---|---|---|---|---|
| full_history | n/a | n/a | n/a | 6,308,650 |
| naive_top_k | 50/50 | 42/50 | 0.658 | 130,210 |
| experienceos_rules | 28/50 | 14/50 | 0.186 | 10,328 |
| experienceos_hybrid_extract_v2 | 29/50 | 16/50 | 0.225 | 10,321 |
| experienceos_hybrid_retrieval_v2 | 28/50 | 9/50 | 0.246 | 5,142 |
| experienceos_extract_retrieval_v2 | 29/50 | 11/50 | 0.285 | 5,218 |
| experienceos_coverage_v2 | 28/50 | 9/50 | 0.246 | 5,073 |
| experienceos_temporal_v2 | 30/50 | 10/50 | 0.266 | 5,445 |
| experienceos_local_v2 | 31/50 | 12/50 | 0.305 | 5,527 |
| experienceos_hybrid_full_v2 | 31/50 | 12/50 | 0.305 | 5,527 |

The LongMemEval evaluation uses a frozen 50-case stratified subset with a deterministic offline answer provider; it is not an official LongMemEval score.
naive_top_k retrieves raw conversation turns and retains superior raw recall on this subset; ExperienceOS retrieves distilled durable memories with lifecycle guarantees the baseline lacks. full_history is the untruncated
raw-history reference (no candidate/selection denominators).

## 7. The selection-rate trade-off, stated plainly

External answer-session selection rate fell (14/50 to 12/50) because Prompt 4 removed zero-value padding; MRR and context efficiency improved, and part of the v1 selection credit was accidental padding. Concretely: v1 filled all
K=6 slots regardless of relevance, and on 2 of its 14 credited cases
the "selected" answer-session memory had no retrieval signal at all.
Full v2 selects ~2–3 relevant memories per case instead of 6, ranks
the genuinely relevant ones higher (MRR 0.186 → 0.305), and halves
context cost — but 19 cases still lack
any answer-session memory (extraction gaps) and
19 more have candidates that lexical
retrieval does not select (semantic-gap misses). Embeddings and richer
extraction remain future work.

## 8. Context efficiency

External context: 10,328 → 5,527
tokens (−4,801,
−46.5%), with K unchanged and no
padding. Lifecycle memory-token share:
1036/2295 (rules) →
1027/2289 (full v2) — flat despite the
added temporal/provenance labels. Efficiency claims hold only because
quality rose simultaneously (MRR, Recall@K, passed cases).

## 9. Temporal, provenance, forgetting, and policy evidence

Temporal metadata attaches to every eligible create (expression
resolution 15/19 on the frozen data; 4 expressions honestly kept
unresolved); superseded records are reachable only under explicit
historical/as-of/timeline intent and always labeled; forgotten
memories are excluded from every user-facing mode. Forgetting reaches
the frozen-denominator ceiling (4/4, 4/4, 2/2) with ambiguity and bulk
requests contained rather than guessed, and zero incorrect-target
forgetting (0/6). The local-policy pipeline validated 104/104
proposals with zero fallbacks in canonical scripted-simulated mode and
zero state corruption everywhere, including at external scale
(2 safe fallbacks across 12,245 decisions).

## 10. Real local-model evidence (supplemental, non-canonical)

Bounded development runs of Qwen2.5-0.5B-Instruct (Q4_K_M) through the
identical pipeline produced **0/15 (Prompt 7) and 0/8 (Prompt 8)
directly valid proposals** (percentage-scale confidences, action
confusion); retries did not recover; per-action deterministic fallback
produced fully correct final lifecycle state with zero corruption in
every run. This evidence proves containment — invalid model output
cannot corrupt accumulated experience, and local proposals can improve
later without redesigning the lifecycle engine. It does not prove
direct model competence, and canonical results never include it.

## 11. Failure analysis (nothing aggregated away)

Lifecycle (full v2): 15 failed + 2 partial + 2 skipped cases retained
with per-case evidence — remaining classes include one unextracted
creation form (recall 12/13), one unresolved supersession (6/7), stale
leakage on 7/11 eligible cases (the extraction-vs-supersession
boundary), and `requires_local_model` skips. External (full v2):
19 candidate-absent cases,
19 candidate-but-unselected cases,
10 abstention deferrals. Full per-case
records live in the committed artifacts.

## 12. Trade-offs

| Component | Benefit | Cost |
|---|---|---|
| Hybrid extraction | +creation recall/precision | +leakage without supersession |
| Semantic supersession | update correctness | conservative ambiguity stays unresolved |
| Hybrid retrieval | +MRR, +Recall@K, −tokens | −selection count (padding removed), +runtime |
| Coverage selection | −leakage, −contamination, −tokens | no external gain when pools < K |
| Temporal labels | current/historical correctness, audit | ~7% context-label overhead |
| Local-policy v2 | validation + containment | real 0.5B not directly useful; retry latency |
| Durable-memory abstraction | lifecycle-aware experience | lower raw-turn recall than naive top-K |

## 13. What this evidence proves

Semantic identity improves generalized updates; hybrid extraction
increases creation coverage; lifecycle-aware retrieval improves rank
and reduces context; coverage selection improves containment and
efficiency; temporal metadata enables current/historical behavior;
generalized forget resolution improves forgetting to the frozen
ceiling; the full composition improves lifecycle outcomes over rules
(21 vs 17 passed) while preserving safety; local-policy validation
prevents bad model output from corrupting state; and all of it is
deterministic and reproducible from committed artifacts.

## 14. What this evidence does not prove

It does not prove official LongMemEval performance, end-answer quality
under a real production model, generalization to every memory domain,
reliable autonomous lifecycle decisions from a 0.5B model,
production-scale performance, security, or multi-tenant correctness,
universal superiority over raw-turn retrieval (naive top-K keeps
higher raw recall here), human-level temporal reasoning, or
embedding-based semantic recall (not implemented).

## 15. Reproduction

```
# validate historical v1 evidence
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1
./scripts/run_benchmarks.sh validate-report

# validate Phase 9 v2 evidence
./scripts/run_benchmarks.sh validate-v2
./scripts/run_benchmarks.sh validate-external-v2
./scripts/run_benchmarks.sh validate-v2-consistency

# regenerate and validate this report from committed artifacts
./scripts/run_benchmarks.sh report-v2
./scripts/run_benchmarks.sh validate-report-v2

# full gates
PYTHONPATH=. .venv/bin/python -m pytest
PYTHON=.venv/bin/python ./scripts/validate_demo.sh
```

Report generation reads committed artifacts only: no network, no
model, no official source data, no secrets.
