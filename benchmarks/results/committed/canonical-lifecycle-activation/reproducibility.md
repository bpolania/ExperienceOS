# Reproducibility — Canonical Lifecycle Activation Evidence

## Environment

- Python: 3.14.3
- pytest: 9.1.1, numpy: 2.5.1, streamlit: 1.59.0
- Git HEAD at generation: `e4d931f` (Phase 20 fail-closed hardening)
- Response provider: `MockProvider` (recorded); Qwen Cloud **not configured**
  (credential presence recorded as boolean `false`)
- Random seeds: none required — the lifecycle/retrieval/context path is
  deterministic; per-run UUID memory ids are normalized to stable
  positional labels (`mem-N`) in committed records
- Timeout / retry: not applicable offline (no network calls)
- No timestamps or latency values are committed as semantic evidence

## Deterministic reproducible steps

Regenerate the entire family (idempotent; byte-identical output):

```bash
python benchmarks/results/committed/canonical-lifecycle-activation/generate_evidence.py
```

Integrity verification of frozen inputs (must be unchanged):

```bash
for f in benchmarks/results/committed/competitive-viability/*; do
  shasum -a 256 "$f"
done
```

Determinism check (two runs are byte-identical):

```bash
python .../generate_evidence.py && cp .../complete_case_results.jsonl /tmp/a
python .../generate_evidence.py && diff /tmp/a .../complete_case_results.jsonl
```

## Live provider-dependent steps (NOT executed here)

The competitive final-answer campaign (all six systems through the frozen
scoring pipeline and blinded Qwen judge) requires Qwen Cloud credentials.
It was not executed; its outputs are recorded as `UNAVAILABLE_LIVE_JUDGE`
and `LIVE_COMPETITIVE_RESULT_UNAVAILABLE`.

## Reused historical evidence

Frozen Phase 17 per-system final-answer metrics and the Phase 18
nine-case classification are cited by path and hash from
`benchmarks/results/committed/competitive-viability/` and are not
recomputed.

## Validation performed

- `compileall` over `benchmarks experiments tests`
- Full test suite (`pytest -q`)
- JSON / JSONL validity of every generated artifact
- Frozen input hashes unchanged before and after generation
