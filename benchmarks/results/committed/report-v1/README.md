# Benchmark report artifact (report-v1)

Generated from the two committed raw artifacts (paths and digests in
`artifact_manifest.json`) by `./scripts/run_benchmarks.sh report` at
commit `12b86992e9a6032b52002bd84d68a52e30510e08`. No benchmark systems were rerun. Generated files
must not be edited manually — `validate-report` detects edits. The
Markdown report lives at `docs/benchmark_report.md`. Custom lifecycle
and LongMemEval evidence stay separate; the external artifact is the
LongMemEval 50-case stratified subset, not an official score; the
local policy mode is scripted-plus-fallback, not a real GGUF run.
