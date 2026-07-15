# Transition ablations

Benchmark-only diagnostics. None of these is selectable from SDK configuration, none appears in demo or dashboard startup, and none can produce a canonical action: `runtime_eligible` and `action_applied` are false for every ablation.

Ablations are implemented in benchmark adapters. The identity, verifier, and controller code they measure is the committed code, unchanged.

Regenerate: `./scripts/run_benchmarks.sh transition-ablation`
Verify: `./scripts/run_benchmarks.sh transition-ablation-verify`
