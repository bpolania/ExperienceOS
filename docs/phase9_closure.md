# Phase 9 Closure — Experience Quality Improvements

**Decision: PHASE_9_COMPLETE_WITH_NOTES_AND_PUBLISHED** (notes: the
real 0.5B local model remains a contained development path, and the
external evaluation is a fixed subset with an offline provider).

## Executive summary

Phase 9 rebuilt experience quality end to end and proved it against
frozen Phase 8 evidence. The final system,
`experienceos_hybrid_full_v2`, passes 21/40 frozen lifecycle scenarios
(rules baseline: 17/40) with creation 12/13 precision and recall,
supersession 6/7, forget detection 4/4, forgotten exclusion 2/2,
Recall@K 17/17, inactive contamination 0/18, and zero state
corruption. On the frozen LongMemEval 50-case subset it reaches MRR
0.305 (rules: 0.186) at 5,527 context tokens (rules: 10,328, −46.5%),
with the disclosed selection-rate trade-off (14/50 → 12/50 after
zero-relevance padding removal) and naive top-K retaining superior
raw-turn recall (42/50, 0.658). Every result is committed,
digest-locked, deterministic, and reproducible offline.

## Phase objective

Close the quality gaps Phase 8 measured honestly: conversational
memory creation (10/13 recall), generalized updating (2/7
supersession), paraphrased forgetting (2/4 detection, 0/2 exclusion),
lexical-mismatch retrieval (15/17 Recall@K), bounded-context quality
(zero-value padding, 10/11 stale leakage), temporal/provenance
blindness, and local-policy reliability (97/104 fallback) — all under
a frozen-evidence contract that forbade touching Phase 8 datasets,
metrics, denominators, or artifacts.

## Prompt-by-prompt outcomes

| Prompt | Objective | Decision | Commit |
|---|---|---|---|
| 1 | Experiment contract; frozen evaluation design; v2 system matrix | CONTRACT_COMPLETE | `abf4edd` |
| 2 | Semantic identity + conservative generalized supersession | SEMANTIC_IDENTITY_COMPLETE_WITH_NOTES | `a73cea4` |
| 3 | Hybrid conversational extraction (gate, grounding, validation) | HYBRID_EXTRACTION_COMPLETE_WITH_NOTES | `1e166d7` |
| 4 | Lifecycle-aware hybrid retrieval (BM25-style + structured) | HYBRID_RETRIEVAL_COMPLETE_WITH_NOTES | `25fa1d2` |
| 5 | Coverage-aware context selection (MMR-style, conflict-visible) | COVERAGE_SELECTION_COMPLETE_WITH_NOTES | `05dd00d` |
| 6 | Temporal + provenance metadata, query modes, eligibility rules | TEMPORAL_PROVENANCE_COMPLETE_WITH_NOTES | `0a2a3a6` |
| 7 | Forget resolution + local-policy v2 containment | POLICY_RELIABILITY_COMPLETE_WITH_NOTES | `6997e91` |
| 8 | Final composition + committed v2 benchmark artifacts | PHASE_9_V2_ARTIFACTS_COMPLETE_WITH_NOTES | `f8c2815` |
| 9 | Comparative v1-to-v2 report, artifact-derived and validated | PHASE_9_COMPARATIVE_REPORT_COMPLETE | `315c017` |
| 10 | Stabilization, documentation, closure, publication | this document | final commit |

## Final architecture

```
Agent API (ExperienceOS / .wrap)
  ↓
ExperienceEngine (lifecycle authority; events)
  ↓
Policy / Planner
  ├─ semantic identity + generalized supersession   (Prompt 2)
  ├─ hybrid conversational extraction               (Prompt 3)
  ├─ temporal + provenance metadata                 (Prompt 6)
  ├─ forget-intent detection + target resolution    (Prompt 7)
  └─ local-policy v2 parse/validate/fallback/audit  (Prompt 7)
  ↓
ExperienceManager (proposal validation)
  ↓
Memory Store (in-memory / SQLite; metadata channel)
  ↓
Lifecycle-aware Hybrid Retrieval                    (Prompt 4)
  ↓
Coverage-aware Context Selection                    (Prompt 5)
  ↓
Bounded, labeled Context
  ↓
Model Provider (Qwen Cloud | Mock | optional local llama.cpp)
```

Models propose; ExperienceOS validates and decides. The local model
never sits inside or controls the lifecycle engine.

## Final system

`experienceos_hybrid_full_v2` — canonical policy mode
scripted-simulated (`local_model_mode: scripted_simulated`,
`proposal_source:
deterministic_plan_serialized_through_local_v2_pipeline`,
`simulated_proposal: true`, `direct_model_inference: false`);
provider-independent; K, context budgets, answer provider, and both
frozen datasets unchanged from v1; no embeddings; no canonical 0.5B
dependency. It is architecturally identical to `experienceos_local_v2`
under the canonical mode — the separate final ID records the
contract-selected complete configuration and its provenance, so
identical benchmark rows are expected, not duplicated fabrication.

## Lifecycle results (rules → full v2)

Passed cases 17/40 → **21/40**; creation precision 10/11 → 12/13;
creation recall 10/13 → 12/13; supersession 2/7 → 6/7; old-value
deactivation 3/8 → 7/8; conflicting-active 3/7 → 0/7; stale leakage
10/11 → 7/11; forget detection 2/4 → 4/4; correct forget target 2/2 →
4/4; forgotten exclusion 0/2 → 2/2; unrelated preservation 3/3 → 3/3;
resurrection/incorrect target 0/6 → 0/6; Recall@K 15/17 → 17/17;
inactive contamination 2/20 → 0/18; policy structural validity
104/104; scripted-simulated fallback 0/104; state corruption 0.

## LongMemEval fixed-subset results

Rules: candidate 28/50, selection 14/50, MRR 0.186, 10,328 tokens.
Full v2: candidate 31/50, selection 12/50, MRR 0.305, 5,527 tokens,
2/12,245 policy fallbacks, zero corruption. Naive top-K reference:
50/50, 42/50, 0.658. Fixed 50-case stratified subset (official
revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`), deterministic
offline answer provider — **not an official LongMemEval score**;
naive top-K retrieves raw turns while ExperienceOS retrieves distilled
durable memories with lifecycle guarantees.

## Component contributions (ablation-supported only)

Semantic identity → update correctness (supersession 5/7, conflicts
0/7, leakage 6/11). Extraction → creation coverage (11/13 recall
alone; 12/13 composed) at a leakage cost when uncomposed (11/11).
Retrieval → Recall@K 17/17, MRR 0.246, tokens halved, padding removed.
Coverage → leakage 8/11, contamination 0/18, fewer tokens; no external
change (pools rarely exceed K). Temporal/provenance → best
no-extraction row (30/50, 0.266) plus query modes and labels (~7%
overhead). Forget resolver + policy → forget ceiling (4/4, 4/4, 2/2),
final two passes, complete containment.

## Real local-model evidence

Qwen2.5-0.5B-Instruct Q4_K_M through the identical pipeline: **0/15
(Prompt 7) and 0/8 (Prompt 8) directly valid proposals**
(percentage-scale confidences, action confusion, prompt-echo
evidence); retries never recovered; per-action deterministic fallback
produced fully correct final lifecycle state with zero corruption in
every run. This demonstrates model-failure containment, not reliable
autonomous memory management. Development summary:
`benchmarks/results/local/full-v2-real-local-dev/summary.json`
(gitignored, non-canonical).

## Benchmark limitations

Fixed subset; offline deterministic provider (availability/selection/
rank, not answer quality); no production-scale, security, or
multi-tenant evaluation; no human evaluation; no embeddings; assistant/
tool ingestion feature-flagged and lightly exercised by frozen data;
conservative temporal parsing; ambiguous forgets reject rather than
ask clarification; no universal-superiority claim over raw-turn
retrieval.

## Validation evidence

Full pytest **1036 passed**; targeted Phase 9 suites 389; compileall
clean; demo validation passing; all seven validators passing (v1
lifecycle/external/report, v2 lifecycle/external/consistency,
report-v2); v1 digest reproduced exactly during Prompt 8; v2 artifacts
double-run digest-matched before commit; report regeneration
deterministic.

## Artifacts and digests

| Artifact | Path | Normalized digest |
|---|---|---|
| v1 lifecycle | `benchmarks/results/committed/lifecycle-offline-v1/` | `8b0e245d914a43bc578923111e8ff40e70d9c8aa487664c00125fc52fa319b33` |
| lifecycle v2 | `benchmarks/results/committed/lifecycle-v2-ablation/` | `ee437bb3e9fde909f343112e40aaa6ecf63155a07a81ad67e017e310fbefb547` |
| LongMemEval v2 | `benchmarks/results/committed/longmemeval-50-subset-v2/` | `19b66cacb330e943b0460ccdb33e8cc6577fccb17621cb7a129f7420f5c7868f` |
| report-v2 data | `benchmarks/results/committed/report-v2/` | `3bc955b0c4940ef73a01c4066bff695596fc45cc144f8c850441ed30f5ab76fd` |

Human-readable report: `docs/benchmark_report_v2.md`. Historical v1
report (immutable): `docs/benchmark_report.md`.

## Commit chain

1. `abf4edd` Define Phase 9 experiment contract
2. `a73cea4` Add semantic identity and generalized supersession
3. `1e166d7` Add hybrid conversational memory extraction
4. `25fa1d2` Add lifecycle-aware hybrid retrieval
5. `05dd00d` Add coverage-aware context selection
6. `0a2a3a6` Add temporal and provenance-aware experience
7. `6997e91` Improve forget resolution and local policy reliability
8. `f8c2815` Add Phase 9 v2 benchmark artifacts
9. `315c017` Add Phase 9 comparative benchmark report
10. Close and document Phase 9 (this commit)

## Future recommendations (not started)

1. Optional embeddings / richer semantic retrieval (19 external
   candidate-but-unselected cases). 2. Broader conversational
   extraction (19 candidate-absence cases; 1/13 lifecycle miss).
3. Supersession for the remaining stale-leakage classes (7/11).
4. Stronger small local model or grammar-constrained decoding (0/15,
   0/8 direct-valid). 5. Interactive clarification for ambiguous
   forgets. 6. Broader temporal language. 7. Live Qwen answer-quality
   evaluation. 8. Human evaluation. 9. Dashboard presentation polish.
10. Submission video and judge script.

## Reproduction

```bash
# full gates
PYTHONPATH=. .venv/bin/python -m pytest
PYTHON=.venv/bin/python ./scripts/validate_demo.sh

# v1 evidence (frozen)
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1
./scripts/run_benchmarks.sh validate-report

# Phase 9 v2 evidence
./scripts/run_benchmarks.sh validate-v2
./scripts/run_benchmarks.sh validate-external-v2
./scripts/run_benchmarks.sh validate-v2-consistency
./scripts/run_benchmarks.sh validate-report-v2
./scripts/run_benchmarks.sh report-v2
```

All commands run offline: no network, no model files, no secrets, no
official source data required.

**Phase 9 is closed.**
