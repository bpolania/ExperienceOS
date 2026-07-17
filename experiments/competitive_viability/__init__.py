"""Lean comparison harness for the competitive viability evaluation.

A thin, removable layer over the existing benchmark infrastructure
(`benchmarks/contract`, `benchmarks/baselines`, `benchmarks/adapters`,
`benchmarks/scenarios`). It does not reimplement the benchmark: it
registers the evaluation's logical systems, normalizes existing cases,
drives every system through the existing execution drivers, and records
one comparable per-(case, system) record plus a run manifest.

It lives outside ``benchmarks/`` because the canonical system adapter
imports the provider-coupled demo composition (`demo.support`,
`experiments.qwen_extraction`), which the provider-neutral benchmark
adapters deliberately avoid. Nothing here mutates memory beyond the
systems' own governed behavior, and the whole package is removable.

This module produces execution evidence only. It computes no competitive
metrics, rankings, or conclusions; scoring and analysis are later work.
"""

HARNESS_SCHEMA_VERSION = "1"

DEVELOPMENT_ONLY_MARKER = "DEVELOPMENT_ONLY_NOT_COMPETITIVE_EVIDENCE"
