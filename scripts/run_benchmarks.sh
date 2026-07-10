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
    longmemeval-fixture)
        out="${2:-benchmarks/results/local/longmemeval-fixture}"
        "$PYTHON" -m benchmarks.external.longmemeval.cli fixture \
            --output "$out" --overwrite
        "$PYTHON" -m benchmarks.external.longmemeval.cli validate "$out"
        ;;
    longmemeval-prepare)
        "$PYTHON" -m benchmarks.external.longmemeval.cli prepare \
            --data-path "${2:?official data path required}"
        ;;
    longmemeval-structural)
        data="${2:?official data path required}"
        out="${3:-benchmarks/results/local/longmemeval-structural}"
        "$PYTHON" -m benchmarks.external.longmemeval.cli structural \
            --data-path "$data" --output "$out" --overwrite
        "$PYTHON" -m benchmarks.external.longmemeval.cli validate "$out"
        ;;
    longmemeval-live)
        "$PYTHON" -m benchmarks.external.longmemeval.cli live \
            --data-path "${2:-unset}" --output "${3:-unset}"
        ;;
    report)
        "$PYTHON" -m benchmarks.reporting.cli generate --overwrite
        ;;
    validate-report)
        "$PYTHON" -m benchmarks.reporting.cli validate \
            "${2:-benchmarks/results/committed/report-v1}"
        ;;
    validate-external)
        "$PYTHON" -m benchmarks.external.longmemeval.cli validate \
            "${2:?result dir required}"
        ;;
    validate-v2)
        "$PYTHON" -m benchmarks.validation_v2 lifecycle \
            "${2:-benchmarks/results/committed/lifecycle-v2-ablation}"
        ;;
    validate-external-v2)
        "$PYTHON" -m benchmarks.validation_v2 external \
            "${2:-benchmarks/results/committed/longmemeval-50-subset-v2}"
        ;;
    validate-v2-consistency)
        "$PYTHON" -m benchmarks.validation_v2 consistency \
            "${2:-benchmarks/results/committed/lifecycle-v2-ablation}" \
            "${3:-benchmarks/results/committed/longmemeval-50-subset-v2}"
        ;;
    *)
        echo "unknown command: $command (expected quick, full-offline, validate, report, validate-report, longmemeval-fixture, longmemeval-prepare, longmemeval-structural, longmemeval-live, validate-external, validate-v2, validate-external-v2, validate-v2-consistency)"
        exit 2
        ;;
esac
