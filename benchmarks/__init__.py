"""ExperienceOS benchmark suite (Phase 8).

Measures whether accumulated experience remains current, relevant,
safe, and context-efficient compared with stateless, full-history,
append-only, and naive-retrieval baselines.

Prompt 1 establishes the measurement contract only:

- ``benchmarks.contract`` — case, result, system, provenance, and
  metric contracts that later prompts implement against.
- ``benchmarks/fixtures`` — tiny declarative fixtures that validate
  the contract. Fixtures are never benchmark results.

The default benchmark path is fully offline: no credentials, no
network, no model downloads, no local GGUF. Qwen Cloud, local-model,
and external-dataset modes are optional and explicitly labeled.

The measurement rules live in docs/benchmark_contract.md and are
committed before any results are produced, so denominators cannot
move after results are observed.
"""
