# Phase 9 Experiment Contract

Contract version **phase9-v2.1** (machine-readable companion:
`benchmarks/contract/phase9_v2.json`, enforced by
`tests/test_phase9_contract.py`). This contract was committed
**before any Phase 9 architecture work** and governs how every v2
improvement is measured against the frozen Phase 8 evidence.

ExperienceOS remains the experience layer for LLM-powered agents —
remember, update, forget, retrieve, rank, compress, and place
experience into bounded context. Phase 9 improves and measures that
layer; it does not redesign the product around the benchmark.

## 1. Verified starting baseline

Verified in-repository before this contract was written:

- Commit `13ca2e8e610a87c5aaf737d00831f82c13c08012` = origin/main,
  clean tree; Python 3.14.3 (`.venv/bin/python`).
- Full `pytest`: **647 passed** (clean checkouts without the optional
  official LongMemEval data: 645 passed + 2 designed skips).
- `PYTHON=.venv/bin/python ./scripts/validate_demo.sh`: passing
  (includes the quick benchmark smoke + artifact validation).
- All three Phase 8 canonical artifacts re-validated with exact
  digests (below). No baseline discrepancies.

## 2. Frozen Phase 8 evidence (immutable)

The following may never be edited, regenerated-with-drift, replaced,
or reinterpreted. Regeneration is permitted only when it reproduces
the recorded normalized digest through the existing validators.

| Evidence | Path | Integrity anchor |
|---|---|---|
| Lifecycle dataset (40 scenarios) | `benchmarks/scenarios/lifecycle/` | per-file hashes in manifest |
| Lifecycle manifest | `benchmarks/scenarios/lifecycle_manifest.json` | hash `0481f41e03795ce66133e01929dea563f326d7ce790adc4ee0ab4d37f1cfd6eb` |
| LongMemEval subset manifest (IDs only) | `benchmarks/external/longmemeval/manifest.json` | hash `a077cca377469ac3450ef5446e7d289bcbd42eb2c95beed677220f69fca73030`; official revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`; label **LongMemEval 50-case stratified subset** |
| v1 lifecycle artifact (240 case-runs, 2,782 contributions) | `benchmarks/results/committed/lifecycle-offline-v1/` | digest `8b0e245d914a43bc578923111e8ff40e70d9c8aa487664c00125fc52fa319b33`, generated at `d96c76c` |
| v1 external artifact (150 case-runs) | `benchmarks/results/committed/longmemeval-50-subset-v1/` | digest `2b3e2000647b8d3ca85e0539ce3ac518afb32e4eb343c96a20538607d428ea03`, generated at `7a79729` |
| v1 comparative report | `benchmarks/results/committed/report-v1/` + `docs/benchmark_report.md` | report-data digest `999a38c98075919965b728c0d9f595e38a818d8fa6475ad974b8f529bc7935f6`, generated at `12b8699`; spec `benchmarks/reporting/report_spec.json` |
| v1 system IDs | `benchmarks/contract/system.py` | `stateless`, `full_history`, `append_only`, `naive_top_k`, `experienceos_rules`, `experienceos_local` |
| v1 metric registries | `benchmarks/contract/metrics.py` (50 defs), `benchmarks/external/longmemeval/evaluate.py` (8 defs) | Phase 8 numerators/denominators/semantics frozen |
| Schema versions | case `1`, result `1`, provenance `1`, artifact schemas `1`, selection algorithm `1`, suite `experienceos-lifecycle-v1`, report `report-v1` | version bumps required for any change |

### The five-layer distinction

1. **Immutable historical evidence** — the table above.
2. **Executable v1 benchmark code** (`benchmarks/{contract,scenarios,
   baselines,adapters,evaluators,runner,artifacts,external,
   reporting}`) — must continue reproducing the historical digests;
   verified during Phase 8 closure by fresh runs reproducing both
   canonical digests exactly. Behavioral changes to this code that
   alter v1 outputs are forbidden.
3. **Shared benchmark infrastructure** — may be *extended*
   backward-compatibly (new system IDs, new v2 metric identifiers,
   new artifact roots) provided v1 reproduction still passes.
4. **New v2 system implementations** — new adapters/policies behind
   new `*_v2` system IDs; production ExperienceOS changes are
   permitted (that is the point of Phase 9) but their v1-visible
   effects must be understood: `experienceos_rules` names the Phase 8
   *behavior*; if production changes alter that behavior, the v1
   artifact stays frozen as historical evidence and the report must
   say the live `experienceos_rules` reproduction diverges — never
   silently reuse a v1 ID for changed behavior. Prefer gating v2
   behavior behind the v2 systems/flags so `experienceos_rules`
   reproduction remains exact.
5. **Development fixtures and final v2 evidence** — §6 and §7.

### Forbidden without exception

Editing v1 scenarios or expected answers after seeing v2 results;
changing denominators or metric semantics under an existing metric
name; replacing v1 artifacts; reusing a v1 system ID for changed
behavior; presenting development-fixture results as final evidence;
combining lifecycle and LongMemEval results into one score;
presenting the fixed subset as an official LongMemEval score;
benchmark-only logic keyed to scenario IDs, expected answers, or
`answer_session_ids`.

## 3. V2 systems and ablation matrix

All eight v2 IDs are new (collision-checked by contract tests). Each
ablation isolates one change against the unchanged historical
reference (`experienceos_rules`, and `experienceos_local` for G).

| ID | Isolates | Primary metrics | Non-regression |
|---|---|---|---|
| `experienceos_slots_v2` (A) | normalized semantic identity, generalized conflict candidates, conservative supersession | supersession accuracy, old-value deactivation, conflicting-active rate, stale context leakage | scoped coexistence, unrelated preservation, inactive-memory exclusion |
| `experienceos_hybrid_extract_v2` (B) | deterministic-first extraction + durability gate + structured proposal for unmatched durable content (engine-validated) | creation precision/recall/F1, non-durable rejection, external answer-session candidate rate | duplicate containment, precision reported with denominator |
| `experienceos_hybrid_retrieval_v2` (C) | broader candidate generation + lifecycle filtering + scoring (stored memories unchanged) | Recall@K, MRR, answer-session candidate/selection rates | forgotten/superseded contamination, budget adherence, comparable context tokens |
| `experienceos_extract_retrieval_v2` (D) | B+C interaction: do extra memories become evidence or contamination? | union of B and C | union of B and C |
| `experienceos_coverage_v2` (E) | deterministic diversity/facet reranking + redundancy penalty; **no hidden K increase** | multi-session coverage (v2 metric), answer-context presence, redundant selection (v2 metric), answers/1k memory tokens | budget adherence, K unchanged |
| `experienceos_temporal_v2` (F) | temporal/provenance fields, validity transitions, historical queries, flagged assistant-derived ingestion | temporal evidence presence (v2), current-fact accuracy, current-vs-historical disambiguation (v2) | no stale-current confusion, auditability |
| `experienceos_local_v2` (G) | smaller schema, one action/generation, constrained generation, syntax repair, one bounded retry, per-action fallback; engine authoritative | valid proposal rate, action-type/target accuracy, rejection/fallback rates, applied accuracy, state corruption, latency/tokens per decision | containment completeness |
| `experienceos_hybrid_full_v2` | **only** ablation-proven components | full metric suite vs v1 | every blocker in §5 |

A component stays out of full v2 when it improves one metric but
regresses lifecycle safety, increases state corruption, materially
worsens context efficiency without evidence gains, lacks reproducible
benchmark evidence, or needs hidden benchmark-specific behavior.

## 4. Metrics, denominators, eligibility

v1 metrics keep their exact Phase 8 names, numerators, denominators,
and eligibility rules (documented in `docs/benchmark_contract.md` and
`docs/benchmark_metrics.md`; sources: lifecycle aggregate for
lifecycle metrics, external aggregate for external metrics — never
mixed). Every reported rate preserves its raw numerator and
denominator; undefined stays undefined.

New Phase 9 measurements (multi-session coverage, redundant-selection
rate, temporal evidence presence, current-vs-historical
disambiguation, assistant-derived acceptance/rejection counts,
per-decision latency/token stats for local v2) must be defined as
**new v2 metrics with new identifiers** (suffix `_v2` or a distinct
registry), with numerator/denominator/eligibility declared before v2
results are interpreted. No v1 metric is silently changed.

## 5. Targets, non-regression, and hard blockers

Targets are evaluation goals against recorded Phase 8 values (raw
values in `phase9_v2.json`):

- **Updates**: supersession accuracy materially above 2/7; stale
  rendered-context leakage materially below 10/11; scoped-preference
  coexistence unchanged.
- **Forgetting**: detection above 2/4; no increase in incorrect-target
  forgetting; unrelated preservation intact (2/2 pattern).
- **Extraction**: creation recall above 10/13 with defensible,
  denominator-reported precision (v1: 10/11); external answer-session
  candidate rate materially above 28/50.
- **Retrieval**: external selection materially above 14/50; external
  MRR materially above 0.186; lifecycle Recall@K not below 15/17;
  context remains substantially below full history (v1: 33.7%
  lifecycle reduction, ~207 vs ~126k external tokens).
- **Coverage**: improved multi-session coverage; fewer redundant
  selections; K unchanged.
- **Temporal**: improved temporal evidence presence; session dates
  auditable; current vs historical distinguishable.
- **Local policy**: fallback materially below 97/104; containment
  remains complete; state corruption not above the v1 measurement
  under the identical definition; real-model results reported
  separately from scripted/mock/fallback.

**Hard adoption blockers** (any one excludes a component from full
v2, regardless of other gains): forgotten memory rendered as active
current context; superseded memory rendered for a current-state query
without an explicit historical request; increased incorrect-target
forgetting; increased state corruption; benchmark oracle
modification; v1 artifact overwrite; unreported denominator change;
context-budget violation; benchmark-only logic keyed to scenario IDs,
expected answers, or answer-session oracle data.

## 6. Development fixture boundary

Development fixtures live under **`benchmarks/fixtures/phase9_dev/`**
(new root; contract tests keep it disjoint from frozen evaluation
paths). They may include adversarial and edge cases — semantic scope,
lexical mismatch, temporal wording, assistant provenance, paraphrased
forgetting — for unit/integration development, must be labeled
development-only, and may never alter final-evaluation denominators
or be cited as final evidence.

Final evidence must use the unchanged Phase 8 lifecycle set
(manifest-hash-verified), the unchanged 50-case subset when official
data is available (fingerprint-verified), new v2 system IDs, new raw
and aggregate artifacts, and must preserve all failed cases and
fallbacks.

## 7. V2 artifact layout

v2 evidence never overwrites v1. Output roots (contract-tested to be
disjoint from v1 roots):

- `benchmarks/results/committed/lifecycle-v2-ablation/` — lifecycle
  runs of v2 systems (per-ablation subdirectories or run IDs)
- `benchmarks/results/committed/longmemeval-50-subset-v2/` — external
  runs of v2 systems
- `benchmarks/results/committed/report-v2/` — the v2 comparative
  report, which **references** v1 evidence by path + digest, never
  copies or rewrites it
- `benchmarks/results/local/` — gitignored scratch (unchanged)

Every v2 artifact carries the existing metadata conventions:
repository commit + clean-tree flag, system ID, dataset ID + manifest
hash, metric/schema versions, runner suite version, Python version,
provider mode, model identity where applicable, local-policy mode,
context budget/K, seeds, raw per-case evidence, aggregate raw
numerators/denominators, latency, fallback and rejection counts,
per-file hashes, and a normalized digest (timestamps excluded from
digests, per the existing normalization design).

## 8. Reproduction commands

Existing commands (work today):

```bash
# Baseline
PYTHONPATH=. python -m pytest
PYTHON=.venv/bin/python ./scripts/validate_demo.sh
./scripts/run_benchmarks.sh quick

# Historical v1 reproduction and verification
./scripts/run_benchmarks.sh full-offline            # temp dir; digest must equal 8b0e245d...
./scripts/run_benchmarks.sh validate benchmarks/results/committed/lifecycle-offline-v1
./scripts/run_benchmarks.sh longmemeval-structural benchmarks/data/external/longmemeval/longmemeval_s_cleaned.json  # digest must equal 2b3e2000...
./scripts/run_benchmarks.sh validate-external benchmarks/results/committed/longmemeval-50-subset-v1
./scripts/run_benchmarks.sh report && ./scripts/run_benchmarks.sh validate-report benchmarks/results/committed/report-v1
PYTHONPATH=. python -m benchmarks.scenarios.validate
```

Phase 9 implementation requirements (interfaces to build; **do not
pretend they exist yet**):

```bash
# V2 development (to be implemented in Prompts 2+)
PYTHONPATH=. python -m pytest tests/test_phase9_*.py
./scripts/run_benchmarks.sh v2-smoke --system <v2-id>            # ablation smoke, local output
# V2 final evidence (to be implemented before closure)
./scripts/run_benchmarks.sh lifecycle-v2 --systems <ids> --output benchmarks/results/committed/lifecycle-v2-ablation
./scripts/run_benchmarks.sh longmemeval-v2 <data-path> --systems <ids>
./scripts/run_benchmarks.sh report-v2 && ./scripts/run_benchmarks.sh validate-report-v2
```

Closure sweep: compileall + full tests + `validate_demo.sh` + quick
smoke + **v1 preservation verification** (fresh v1 runs reproduce
both canonical digests; all three v1 validators pass) + v2
reproduction (repeated-run digest stability) + hygiene checks +
clean-checkout validation where practical.

## 9. Evidence gate for entering full v2

A change enters `experienceos_hybrid_full_v2` only with, in order:

1. Development-fixture tests passing (labeled dev-only).
2. A committed ablation run on the frozen lifecycle set (and the
   external subset where relevant) under its own v2 system ID.
3. Primary-metric improvement shown with raw numerators/denominators.
4. All §5 non-regression metrics intact and all blockers absent.
5. v1 preservation verification still passing.

## 10. Phase 9 closure conditions

Closure requires: all adopted components ablation-evidenced; full v2
lifecycle + external artifacts committed and validated; report-v2
generated from committed artifacts (referencing v1 by digest);
v1 digests reproduced fresh at the closure commit; full test suite
and `validate_demo.sh` green; hygiene clean (no secrets, models,
official datasets, runtime DBs, personal paths); documentation
consistent; the same claims boundaries as Phase 8 (no official
LongMemEval score, no real-GGUF claims unless a real run is
separately artifacted and labeled, no composite score, denominators
everywhere); publication (push) owned by closure.
