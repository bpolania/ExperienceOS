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
    report-v2)
        "$PYTHON" -m benchmarks.reporting.report_v2 generate
        ;;
    validate-report-v2)
        "$PYTHON" -m benchmarks.reporting.report_v2 validate
        ;;
    validate-v2-consistency)
        "$PYTHON" -m benchmarks.validation_v2 consistency \
            "${2:-benchmarks/results/committed/lifecycle-v2-ablation}" \
            "${3:-benchmarks/results/committed/longmemeval-50-subset-v2}"
        ;;
    run-phase11)
        "$PYTHON" -m benchmarks.phase11 lifecycle \
            --output "${2:-benchmarks/results/committed/phase11-retrieval-ablation}" \
            --overwrite
        ;;
    run-external-phase11)
        "$PYTHON" -m benchmarks.phase11 external \
            --output "${2:-benchmarks/results/committed/phase11-semantic-retrieval}" \
            --overwrite
        ;;
    validate-phase11)
        "$PYTHON" -m benchmarks.validation_phase11 lifecycle \
            "${2:-benchmarks/results/committed/phase11-retrieval-ablation}"
        ;;
    validate-external-phase11)
        "$PYTHON" -m benchmarks.validation_phase11 external \
            "${2:-benchmarks/results/committed/phase11-semantic-retrieval}"
        ;;
    validate-phase11-consistency)
        "$PYTHON" -m benchmarks.validation_phase11 consistency \
            "${2:-benchmarks/results/committed/phase11-retrieval-ablation}" \
            "${3:-benchmarks/results/committed/phase11-semantic-retrieval}"
        ;;
    report-phase11)
        "$PYTHON" -m benchmarks.reporting.report_phase11 generate
        ;;
    validate-report-phase11)
        "$PYTHON" -m benchmarks.reporting.report_phase11 validate
        ;;
    run-grounded-extraction)
        "$PYTHON" -m benchmarks.grounded_extraction.cli run "${@:2}"
        ;;
    validate-grounded-extraction)
        "$PYTHON" -m benchmarks.grounded_extraction.cli validate \
            "${2:-benchmarks/results/committed/grounded-extraction-ablation}"
        "$PYTHON" -m benchmarks.grounded_extraction.cli validate \
            "${3:-benchmarks/results/committed/grounded-extraction}"
        "$PYTHON" -m benchmarks.grounded_extraction.cli validate \
            "${4:-benchmarks/results/committed/report-grounded-extraction}"
        ;;
    smoke-grounded-extraction)
        "$PYTHON" -m benchmarks.grounded_extraction.cli smoke
        ;;
    report-grounded-extraction)
        "$PYTHON" -m benchmarks.grounded_extraction.cli report
        ;;
    evaluate-semantic-identity)
        "$PYTHON" -m benchmarks.semantic_identity.cli evaluate "${@:2}"
        ;;
    repeat-semantic-identity)
        "$PYTHON" -m benchmarks.semantic_identity.cli repeat
        ;;
    evaluate-transition-verification)
        "$PYTHON" -m benchmarks.transition_verification.cli evaluate "${@:2}"
        ;;
    repeat-transition-verification)
        "$PYTHON" -m benchmarks.transition_verification.cli repeat
        ;;
    evaluate-update-intelligence)
        "$PYTHON" -m benchmarks.update_intelligence.cli evaluate "${@:2}"
        ;;
    repeat-update-intelligence)
        "$PYTHON" -m benchmarks.update_intelligence.cli repeat
        ;;
    *)
        echo "unknown command: $command (expected quick, full-offline, validate, report, validate-report, longmemeval-fixture, longmemeval-prepare, longmemeval-structural, longmemeval-live, validate-external, validate-v2, validate-external-v2, validate-v2-consistency, report-v2, validate-report-v2, run-phase11, run-external-phase11, validate-phase11, validate-external-phase11, validate-phase11-consistency, report-phase11, validate-report-phase11, run-grounded-extraction, validate-grounded-extraction, smoke-grounded-extraction, report-grounded-extraction, evaluate-semantic-identity, repeat-semantic-identity, evaluate-transition-verification, repeat-transition-verification, evaluate-update-intelligence, repeat-update-intelligence)"
        exit 2
        ;;
esac
