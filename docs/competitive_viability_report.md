# ExperienceOS Competitive Viability Report

A feasibility-and-positioning assessment of whether the current
ExperienceOS architecture has a defensible path to competing with
established memory approaches, using assets already in the repository. It
is not a claim of state-of-the-art performance. Governed by
`docs/competitive_viability_contract.md`; all metrics trace to the
committed evidence under
`benchmarks/results/committed/competitive-viability/`.

## 1. Executive summary

Six systems answered the same 38 scorable frozen lifecycle cases through
one shared `qwen-plus` response model. On final-answer accuracy the
canonical ExperienceOS + Qwen extraction path scored **27/38 (71.05%)**,
**7.90 points behind the strongest baselines** (stateless and
full-history, both 78.95%) — outside the contract's ~5-point
comparable-quality heuristic. Qwen extraction did **not** improve
final answers over deterministic extraction (both 71.05%). ExperienceOS
uses **~87% less context than full-history** (60.4 vs 455.9 mean tokens)
and shows **strong preference adherence (93.33%)**, but it also
**surfaces stale information in 50% of applicable answers — the highest
of any system** — which is the clearest fixable bottleneck. No
contract-defined competitive profile (A, B, or C) is supported on this
subset.

## 2. Final decision

**`COMPETITIVE_VIABILITY_NOT_YET_DEMONSTRATED`**

The final-answer evidence is valid and unfavorable: ExperienceOS is
materially behind the strongest baselines on aggregate answer quality,
and its real strengths (governed lifecycle, preference adherence, context
economy vs full-history) do not close the answer-quality gate that
Profiles A/B/C require. This is not `INCONCLUSIVE` — the evidence is
clear, just not favorable.

## 3. Systems evaluated

| System | Role |
|---|---|
| `canonical_experienceos_qwen` | system under test (demo composition, live Qwen extraction) |
| `deterministic_experienceos` | internal reference (deterministic extraction) |
| `stateless` / `full_history` / `naive_top_k` / `append_only` | baselines |
| `mem0_style_lightweight` | registered, unavailable, not executed |

## 4. Evaluation dataset

40 frozen lifecycle scenarios (all `frozen_historical`), 38 scorable, 2
uniformly `not_applicable` (local-model). Selection: all lifecycle
scenarios in manifest order — deterministic, complete, no cherry-pick
(`viability_manifest.json`, hash `9c7f3009…`). The LongMemEval 50-case
subset was **not run** (419–608 turns/case make a live all-system run
infeasible); its existing offline-structural evidence stands separately.
No broad generalization is claimed from 38 cases.

## 5. Fairness controls

One `qwen-plus` model answered every system (verified: single response
model across 240 records); identical case set and order per system;
oracle never reached execution adapters (manifest carries references
only); blinded judge with opaque candidate ids (0 system-label leaks
across 144 requests); no per-system tuning; core `experienceos/`
byte-identical to the published baseline `6f893f9` (0-line diff).

## 6. Memory acquisition results

Internal acquisition evidence (not final-answer), from the frozen Qwen
extraction comparison (`experiments/results/qwen_extraction_shadow/`,
Phase 15): Qwen extraction recall **0.867 vs deterministic 0.333**,
precision **0.929 vs 0.833**, overall correctness **0.923 vs 0.718**, 0
Qwen-only false positives. Creation precision/recall/F1 as separate
`frozen_historical` figures — source-referenced, **internal**, single
corpus. Candidate-absence: Qwen materially reduced missed durable
candidates in that corpus. **Whether this improved user-facing answers:
it did not** (see §9). Applies to the canonical path's extraction stage
only.

## 7. Memory evolution results

Lifecycle correctness is governed by the **deterministic** engine, shared
by canonical and deterministic ExperienceOS (Qwen only proposes
extraction). Internal, offline evidence: the deterministic update
benchmark scores **update/transition accuracy at ceiling (24/24 per
partition), correct supersession targets, 0 wrong-target mutations**
(`benchmarks/results/committed/lifecycle-offline-v1`,
`.../action-replacement`, `benchmarks/update_intelligence`). Experimental
Qwen update intelligence (`experiments/results/qwen_update/`) scored
**32/48 vs deterministic 48/48** and **remains non-canonical**. These are
**internal state** metrics; they did not translate into a user-facing
answer advantage on this run.

| Metric (internal, deterministic governance) | Value | Source |
|---|---|---|
| update / supersession target correctness | at ceiling on frozen corpus | lifecycle / transition committed evidence |
| wrong-target mutations | 0 | action-replacement committed evidence |
| duplicate active-memory rate | governed to 0 by dedup | action-replacement committed evidence |
| baselines' update/forget/supersede | not implemented | — |

## 8. Retrieval results

Live per-run Recall@K / MRR / answer-bearing recall were **`NOT_MEASURED`**
in this campaign (the run measured final answers, not retrieval against a
retrieval oracle). Historical retrieval evidence exists
(`benchmarks/results/committed/phase11-semantic-retrieval`) for the
deterministic architecture, offline — referenced but **not combined** with
this live run. On the user-facing proxy, canonical current-information
accuracy (76.47%) is **below** naive top-K (80.0%) and full-history
(87.5%), so lifecycle-aware selection did not retrieve current
answer-bearing content more reliably than naive retrieval here.

## 9. Final-answer results

Frozen final-answer results (`scoring_evidence.json`), reproduced exactly.
Stale-info use and unsupported-claim: lower is better. Every rate carries
counts; null fields excluded from denominators.

| System | Final acc | Current-info | Stale-info use | Pref adh | Unsupported | Abstention | scored/excl |
|---|---|---|---|---|---|---|---|
| canonical_experienceos_qwen | 27/38 **71.05%** | 13/17 76.47% | 9/18 **50.00%** | 14/15 93.33% | 7/38 18.42% | 1/1 100% | 38/0 |
| deterministic_experienceos | 27/38 71.05% | 14/17 82.35% | 9/18 50.00% | 15/18 83.33% | 6/38 15.79% | 1/2 50.00% | 38/0 |
| stateless | 30/38 **78.95%** | 11/16 68.75% | 1/16 6.25% | 10/15 66.67% | 1/38 2.63% | 2/2 100% | 38/0 |
| full_history | 30/38 **78.95%** | 14/16 87.50% | 5/17 29.41% | 16/17 94.12% | 5/38 13.16% | 2/2 100% | 38/0 |
| naive_top_k | 29/38 76.32% | 12/15 80.00% | 6/16 37.50% | 14/15 93.33% | 4/38 10.53% | 1/2 50.00% | 38/0 |
| append_only | 27/37 72.97% | 11/15 73.33% | 6/15 40.00% | 13/15 86.67% | 5/37 13.51% | 1/1 100% | 37/1 |

Category answer accuracy: abstention 8/12 (66.67%), current_vs_stale
45/66 (68.18%), personalized_response 84/113 (74.34%),
personalized_retrieval 33/36 (91.67%). One append-only answer is excluded
by the single preserved judge failure (37 vs 38).

**Key reads:** canonical == deterministic on final accuracy (Qwen
extraction gave no answer-quality lift); canonical is behind every
baseline except its own deterministic twin; canonical's stale-info use
(50%) is the worst of all systems; stateless "wins" partly because 22/38
cases are statement/acknowledgment lifecycle cases that need no memory,
so having no memory avoids stale-memory errors (stateless stale-use
6.25%).

## 10. Context efficiency

Live token evidence (mean context tokens per completed run). Efficiency =
final-answer accuracy fraction ÷ (mean context tokens / 1000).

| System | mean toks | median | max | final acc | acc per 1k toks |
|---|---|---|---|---|---|
| canonical_experienceos_qwen | 60.4 | 62 | 85 | 71.05% | 11.76 |
| deterministic_experienceos | 60.4 | 62 | 85 | 71.05% | 11.76 |
| stateless | 19.7 | 19.5 | 32 | 78.95% | 40.06 |
| full_history | 455.9 | 294 | 1627 | 78.95% | 1.73 |
| naive_top_k | 32.5 | 33 | 59 | 76.32% | 23.48 |
| append_only | 32.2 | 32.5 | 59 | 72.97% | 22.67 |

ExperienceOS uses **~87% less context than full-history** at similar-ish
accuracy vs full-history's much larger context — a real economy. But the
7.90-point answer gap is **not** "comparable" under the contract, so
**Profile C is not supportable**: large context savings **and** an
out-of-threshold answer gap are both true. The stateless acc-per-1k ratio
(40.06) is unstable — its ~20-token context makes the ratio semantically
misleading; it is not evidence of a better memory system.

## 11. Safety and governance

| Property | Evidence |
|---|---|
| wrong-target mutations (canonical governance) | 0 — internal, `action-replacement` committed evidence |
| forgotten-memory resurrection / scoped loss / state corruption | none observed; governed by deterministic engine (internal tests + committed evidence) |
| lineage preservation | preserved by governance (internal) |
| baselines' mutation safety | `NOT_APPLICABLE` — they implement no update/forget/supersede, so "no unsafe mutation" is absence of the feature, not a safety win |
| user-facing stale-answer behavior | **worst for canonical (50%)** — a governed store still surfaced stale context to the answer |

No safety incident occurred in the campaign (0 execution failures). The
governance safety guarantees are **internal**; they did not prevent the
user-facing stale-answer problem, which lives in retrieval/context
assembly, not mutation.

## 12. Competitive profile

- **Profile A (better overall):** NO — 7.90 pts behind the strongest
  baseline.
- **Profile B (comparable + better lifecycle):** NO — the comparable gate
  (~5 pts) is not met; ExperienceOS's governed lifecycle and preference
  adherence are real but cannot be claimed as a differentiated profile
  without redefining the threshold, which the contract forbids.
- **Profile C (comparable + less context):** NO — context savings are
  large, but the answer gap is outside "close."
- **Result: Not Yet Competitive.**

## 13. Ten required questions

1. Qwen extraction improves memory *creation* quality over deterministic?
   **YES** (internal acquisition: recall 0.867 vs 0.333; Phase 15
   evidence) — but this is acquisition, not answers.
2. Qwen extraction reduces answer-bearing candidate absence? **YES** on
   the frozen acquisition corpus (higher recall) — **PARTIALLY** at the
   answer level (no measured downstream lift).
3. Retrieves answer-bearing memories as reliably as naive top-K?
   **INCONCLUSIVE** — live Recall@K `NOT_MEASURED`; the user-facing proxy
   (current-info 76.47% vs 80.0%) suggests not better.
4. Better final answers than stateless? **NO** — 71.05% vs 78.95%.
5. Approaches full-history quality with less context? **PARTIALLY** — much
   less context (~87%), but answer quality is 7.90 pts lower (outside
   comparable).
6. Outperforms append-only on updates and forgetting? **PARTIALLY** —
   YES internally (append-only has no update/forget), **NO** on
   user-facing answers (71.05% vs 72.97%).
7. Better current-state correctness than raw RAG (naive top-K)? **NO** —
   current-info 76.47% < 80.0% and stale-use 50% > 37.5%.
8. Lifecycle governance produces measurable user-facing benefit? **NO**
   on this run — governance correctness is internal; canonical == its
   deterministic twin on answers and worst on stale-use.
9. At least one credible competitive profile? **NO**.
10. Further full-scale benchmarking justified? **PARTIALLY** — full
    benchmark not justified; a targeted validation is (§17).

## 14. Limitations

Small subset (38 scored cases; several metric denominators 15–18); the
benchmark is composed largely of statement/acknowledgment lifecycle cases
that under-measure multi-session personalization and favor
memory-free responses; LongMemEval not run live; 22/38 cases lacked
explicit response criteria and were judged against conversation evidence
(a weaker oracle); single Qwen judge at temperature 0 with no
repeatability audit; one preserved judge failure; historical acquisition/
lifecycle/retrieval evidence is internal and offline and is referenced,
never merged into the live denominators. No statistical significance is
claimed.

## 15. Supported claims

- Qwen extraction improves candidate **acquisition** over deterministic
  extraction on the frozen corpus (recall 0.867 vs 0.333). *(internal)*
- ExperienceOS provides governed update/forgetting/supersession semantics
  and lineage that the simpler baselines do not implement. *(internal)*
- Deterministic governance shows 0 wrong-target mutations and governed
  deduplication on the frozen corpus. *(internal)*
- ExperienceOS achieves high preference adherence (93.33%) on this subset.
  *(user-facing)*
- ExperienceOS uses substantially less context than full-history
  prompting (~87% fewer mean tokens). *(user-facing)*

## 16. Unsupported claims

- Better overall final-answer quality than the baselines — **not
  supported** (behind by 7.90 pts).
- Qwen extraction improving **final-answer** accuracy — **not supported**
  (71.05% == deterministic).
- A lifecycle-governance advantage translating into better **answers** —
  **not supported** on this run.
- Reliable stale-answer suppression — **contradicted** (worst, 50%).
- Better current-state correctness than raw RAG — **not supported**.
- Comparison with official Mem0; LongMemEval live/broad validation;
  state-of-the-art or universal RAG superiority; generalization beyond 38
  cases; statistical significance; production scalability — **none
  claimed or supported**.

## 17. Go / No-Go recommendation

**`TARGETED_VALIDATION_JUSTIFIED`.** None of Go Conditions A/B/C is met, so
a full benchmark program is not justified. But the evidence points to one
specific, fixable bottleneck — user-facing stale-state suppression (50%
stale-info use, worst of all systems, despite correct internal
governance) — and a benchmark composition that under-measures
ExperienceOS's multi-session strengths. A bounded, targeted validation is
warranted; a broad benchmark is not (and is not justified merely because
the harness now exists).

## 18. Recommended next action

**Improve final-answer stale-state suppression in retrieval/context
assembly, then re-validate on the current-vs-stale / multi-session
subset.** This is the smallest bounded action most likely to strengthen
or falsify the competitive claim: the canonical path already governs
memory correctly internally (0 wrong-target mutations) yet surfaced stale
values to the answer in 50% of applicable cases — the gap is in what
reaches the context, not in mutation. *Objective:* cut canonical
stale-info use toward the full-history/naive levels without lowering
current-info accuracy. *Stop condition:* re-scored stale-info use on the
current-vs-stale subset is materially reduced (or the change is shown not
to move it). No implementation anchor is drafted here.

## 19. Conclusion

ExperienceOS is **not yet competitive** on aggregate final-answer quality
on this bounded subset, and Qwen extraction did not improve answers over
deterministic extraction. Its genuine strengths — governed lifecycle,
lineage, preference adherence, and large context savings vs full-history
— are real but do not, on this evidence, establish a contract-defined
competitive profile. The most actionable finding is that correct internal
governance is not reaching the answer: stale context suppression is the
one bounded fix most likely to change the verdict.

Decisions: `PHASE_17_COMPETITIVE_REPORT_COMPLETE`, `PHASE_17_COMPLETE`,
`COMPETITIVE_VIABILITY_NOT_YET_DEMONSTRATED`.
