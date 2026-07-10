#!/usr/bin/env bash
# Offline benchmark entry point. Thin wrapper; the Python runner is
# the source of truth.
#
#   ./scripts/run_benchmarks.sh quick [output-dir]
#   ./scripts/run_benchmarks.sh full-offline [output-dir]
#   ./scripts/run_benchmarks.sh validate <result-dir>
#
# Optional modes (qwen, real-local) are configuration-only in this
# phase: they require explicit credentials/model setup and are never
# run by default validation.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
export PYTHONPATH=.

command="${1:?usage: run_benchmarks.sh quick|full-offline|validate [dir]}"
case "$command" in
    quick|full-offline)
        output="${2:-benchmarks/results/local/$command}"
        "$PYTHON" -m benchmarks.runner.cli run \
            --profile "$command" --output "$output" --overwrite
        "$PYTHON" -m benchmarks.runner.cli validate "$output"
        ;;
    validate)
        "$PYTHON" -m benchmarks.runner.cli validate "${2:?result dir required}"
        ;;
    *)
        echo "unknown command: $command (expected quick, full-offline, validate)"
        exit 2
        ;;
esac
