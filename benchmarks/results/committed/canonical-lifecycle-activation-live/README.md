# Canonical Lifecycle Activation — Live Competitive Evidence

The live counterpart to `../canonical-lifecycle-activation/` (the offline
lifecycle rerun). This family records a **single live sample** of the
complete frozen competitive-viability subset (40 cases) run through all
six required systems against live Qwen (`qwen-plus`, one shared response
model) and scored with the frozen deterministic + blinded-judge pipeline.

Additive and read-only with respect to frozen Phase 17/18 evidence
(referenced by hash in `integrity_manifest.json`).

## Headline result

| Metric (canonical ExperienceOS + Qwen) | Phase 17 | Phase 20 live | Δ |
|----------------------------------------|----------|---------------|---|
| Final-answer accuracy | 27/38 = 71.05% | 30/38 = 78.95% | +7.90 |
| Stale-answer use rate | 9/18 = 50.0% | 5/18 = 27.78% | −22.22 |
| Current-information accuracy | 13/17 = 76.47% | 15/17 = 88.24% | +11.77 |
| Preference adherence | 14/15 = 93.33% | 16/18 = 88.89% | −4.44 |
| Unsupported-claim rate | 7/38 = 18.42% | 5/38 = 13.16% | −5.26 |

- **Competitive decision: `COMPETITIVE_VIABILITY_COMPARABLE_WITH_NOTES`.**
  Canonical 78.95% vs strongest live baseline (stateless) 81.58% — a
  2.63-point gap, within the frozen ~5-point comparability heuristic
  (the prior gap was 7.90 points → `NOT_YET_DEMONSTRATED`).
- All four genuine Phase 18 stale failures are now scored correct with no
  stale-information use. The five evaluator false positives remain flagged
  under the unchanged frozen scoring contract — confirming they are
  scoring-criteria artifacts, not lifecycle failures (stale count 9 → 5
  is exactly the four genuine fixes).

## Reproducibility caveat

Live LLM outputs are stochastic; this is a single sample, like the frozen
Phase 17 run, and is **not** byte-reproducible. All six systems were run
in one campaign under one shared model, so the comparison is internally
aligned. The offline family (`../canonical-lifecycle-activation/`) remains
the deterministic, byte-reproducible lifecycle/retrieval/context proof.

## Files

| File | Contents |
|------|----------|
| `run_live_campaign.py` | The live campaign runner (execute + score) |
| `build_reports.py` | Deterministic builder for the derived reports |
| `raw_case_results.jsonl` | 240 execution records (6 systems × 40 cases) |
| `scoring_results.jsonl` | Per-(case,system) score records (deterministic + judge) |
| `aggregate_by_system.json` | Frozen-pipeline per-system aggregate |
| `aggregate_metrics.json` | Phase 17 vs Phase 20-live per-metric deltas |
| `competitive_decision.json` | Competitive comparison and decision |
| `phase18_followup_live.json` | Nine-case follow-up with live verdicts |
| `four_genuine_case_audit_live.json` | Four genuine cases: state + live answer + verdict |
| `integrity_manifest.json` | Frozen input hashes (unchanged) |
| `run_manifest.json` | Run id, model, judge, systems, git head, elapsed |
| `campaign_progress.log` | Per-case execution log (no secrets, no paths) |

## Reproduce (new live sample)

```bash
python benchmarks/results/committed/canonical-lifecycle-activation-live/run_live_campaign.py
python benchmarks/results/committed/canonical-lifecycle-activation-live/build_reports.py
```

Requires `QWEN_API_KEY` in `.env` (git-ignored). A fresh run produces a new
independent sample, not identical numbers.
