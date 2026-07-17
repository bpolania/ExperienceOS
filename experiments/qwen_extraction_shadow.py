"""Shadow comparison: deterministic vs live-Qwen grounded extraction.

For each corpus message this runs BOTH the canonical deterministic
extractor and the experimental ``QwenExtractionController`` over the
exact same message, through the same grounded validation, and records a
per-message comparison. Neither controller can mutate memory — both are
proposal-only and hold no store — so this harness performs no persistence
and no lifecycle change. The deterministic path is the comparison
baseline; the Qwen path speaks for itself with no fallback.

The corpus is the committed grounded-extraction annotation set, which
carries a per-record oracle (``candidate_expected``) for durable-memory
recall and over-extraction. This harness never edits that corpus.

Run (live Qwen; requires QWEN_API_KEY in the environment or .env):

    PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.memory.grounded_extraction import (
    DeterministicGroundedExtractionController,
)
from experienceos.memory.learned_extraction import RUNNER_OK
from experiments.qwen_extraction import (
    QWEN_EXTRACTION_VERSION,
    QwenExtractionController,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = {
    "lifecycle": REPO_ROOT
    / "benchmarks/annotations/grounded-extraction/lifecycle.jsonl",
    "external": REPO_ROOT
    / "benchmarks/annotations/grounded-extraction/external.jsonl",
}
RESULT_DIR = REPO_ROOT / "experiments/results/qwen_extraction_shadow"

# The extraction prompt version, incremented on a bounded correction.
PROMPT_VERSION = QWEN_EXTRACTION_VERSION

# Qwen runner-status value that means the model actually answered.
_SUCCESS_STATUS = RUNNER_OK
# Outcomes where the model asserted a candidate (accepted or grounding-rejected).
_PROPOSED_OUTCOMES = {"candidate", "validation_rejected"}


def load_corpus(subset: str = "lifecycle", *, scorable_only: bool = True) -> list:
    """Read a grounded-extraction annotation subset (read-only)."""
    records = []
    for line in CORPUS[subset].read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if scorable_only and not rec.get("scorable", True):
            continue
        records.append(rec)
    return records


def _accepted(proposal) -> bool:
    return proposal.recommendation == "candidate"


def agree(det_proposal, qwen_proposal) -> bool:
    """One stable agreement definition: both controllers reach the same
    accepted recommendation (both a grounded candidate, or both none)."""
    return _accepted(det_proposal) == _accepted(qwen_proposal)


def evaluate_message(record, deterministic, qwen) -> dict:
    source_text = record.get("source_text") or ""
    case_id = record.get("case_id")
    expected = bool(record.get("candidate_expected"))
    evidence = ExtractionEvidence(
        user_text=source_text, metadata={"source_id": case_id}
    )

    det = deterministic.extract(evidence)

    started = time.perf_counter()
    qw = qwen.extract(evidence)
    qwen_latency_ms = (time.perf_counter() - started) * 1000.0

    qwen_status = qw.diagnostics.get("runner_status")
    qwen_outcome = qw.diagnostics.get("outcome")
    qwen_success = qwen_status == _SUCCESS_STATUS
    qwen_proposed = qwen_outcome in _PROPOSED_OUTCOMES

    return {
        "case_id": case_id,
        "candidate_expected": expected,
        "det_recommendation": det.recommendation,
        "det_accepted": int(_accepted(det)),
        "det_kind": det.candidate.kind if det.candidate else None,
        "qwen_recommendation": qw.recommendation,
        "qwen_accepted": int(_accepted(qw)),
        "qwen_proposed": int(qwen_proposed),
        "qwen_rejected": int(qwen_proposed and not _accepted(qw)),
        "qwen_kind": qw.candidate.kind if qw.candidate else None,
        "qwen_status": qwen_status,
        "qwen_outcome": qwen_outcome,
        "qwen_success": qwen_success,
        "qwen_latency_ms": round(qwen_latency_ms, 1),
        "agreement": agree(det, qw),
        "prompt_version": PROMPT_VERSION,
    }


def run_comparison(qwen_provider, records) -> dict:
    deterministic = DeterministicGroundedExtractionController()
    qwen = QwenExtractionController(qwen_provider)
    rows = [evaluate_message(r, deterministic, qwen) for r in records]
    return {"prompt_version": PROMPT_VERSION, "cases": rows,
            "summary": aggregate(rows)}


def aggregate(rows: list) -> dict:
    n = len(rows)
    success = [r for r in rows if r["qwen_success"]]
    # Correctness is scored only where Qwen actually answered, so a
    # provider failure is never counted as a valid Qwen comparison.
    expected = [r for r in success if r["candidate_expected"]]
    not_expected = [r for r in success if not r["candidate_expected"]]

    def rate(num, den):
        return round(num / den, 4) if den else None

    det_accepted = sum(r["det_accepted"] for r in rows)
    qwen_accepted = sum(r["qwen_accepted"] for r in success)
    agreements = sum(1 for r in success if r["agreement"])
    latencies = [r["qwen_latency_ms"] for r in success]

    return {
        "messages_processed": n,
        "qwen_success": len(success),
        "qwen_failed": n - len(success),
        "det_proposals": det_accepted,
        "qwen_proposals": qwen_accepted,
        "det_accepted": det_accepted,
        "det_rejected": 0,  # deterministic controller returns grounded results only
        "qwen_accepted": qwen_accepted,
        "qwen_rejected": sum(r["qwen_rejected"] for r in success),
        "agreement_pct": rate(agreements, len(success)),
        "disagreement_pct": rate(len(success) - agreements, len(success)),
        "avg_qwen_latency_ms": (
            round(sum(latencies) / len(latencies), 1) if latencies else None
        ),
        # Oracle quality (scored on successful Qwen messages only).
        "expected_candidates": len(expected),
        "not_expected_candidates": len(not_expected),
        "det_recall": rate(
            sum(r["det_accepted"] for r in expected), len(expected)
        ),
        "qwen_recall": rate(
            sum(r["qwen_accepted"] for r in expected), len(expected)
        ),
        "det_over_extraction": rate(
            sum(r["det_accepted"] for r in not_expected), len(not_expected)
        ),
        "qwen_over_extraction": rate(
            sum(r["qwen_accepted"] for r in not_expected), len(not_expected)
        ),
        "det_correct": rate(
            sum(1 for r in success
                if r["det_accepted"] == int(r["candidate_expected"])),
            len(success),
        ),
        "qwen_correct": rate(
            sum(1 for r in success
                if r["qwen_accepted"] == int(r["candidate_expected"])),
            len(success),
        ),
    }


# --- artifacts ---------------------------------------------------------------


def _report_md(data: dict, meta: dict) -> str:
    s = data["summary"]
    lines = [
        "# Qwen vs Deterministic Grounded Extraction — Shadow Comparison",
        "",
        f"- Model: `{meta['model']}` · temperature {meta['temperature']} · "
        f"timeout {meta['timeout_ms']} ms · one inference, no retries · "
        f"prompt version {data['prompt_version']}",
        f"- Corpus: `{meta['corpus']}` ({s['messages_processed']} scorable "
        "messages) · shadow only, no memory mutation",
        "",
        "## Aggregate",
        f"- Qwen inference: {s['qwen_success']} succeeded, {s['qwen_failed']} failed",
        f"- Deterministic accepted candidates: {s['det_accepted']}",
        f"- Qwen accepted candidates: {s['qwen_accepted']} "
        f"(rejected by grounding: {s['qwen_rejected']})",
        f"- Agreement: {s['agreement_pct']} · disagreement: {s['disagreement_pct']}",
        f"- Average Qwen latency: {s['avg_qwen_latency_ms']} ms",
        "",
        "## Oracle quality (scored on successful Qwen messages)",
        f"- Durable-memory recall — deterministic **{s['det_recall']}**, "
        f"Qwen **{s['qwen_recall']}** "
        f"(of {s['expected_candidates']} expected candidates)",
        f"- Over-extraction — deterministic **{s['det_over_extraction']}**, "
        f"Qwen **{s['qwen_over_extraction']}** "
        f"(of {s['not_expected_candidates']} not-expected messages)",
        f"- Overall correctness vs oracle — deterministic "
        f"**{s['det_correct']}**, Qwen **{s['qwen_correct']}**",
        "",
        f"Reproduce: `{meta['reproduce']}`",
        "",
    ]
    return "\n".join(lines)


def write_artifacts(data: dict, meta: dict) -> Path:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    (RESULT_DIR / "results.json").write_text(
        json.dumps({"meta": meta, **data}, indent=1, sort_keys=True) + "\n"
    )
    (RESULT_DIR / "report.md").write_text(_report_md(data, meta))
    return RESULT_DIR


# --- CLI ---------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="qwen_extraction_shadow")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--subset", default="lifecycle", choices=list(CORPUS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args(argv)

    from demo.env import load_local_env
    from experienceos.providers.qwen_cloud import QwenCloudProvider

    load_local_env()
    provider = QwenCloudProvider(temperature=0.0, timeout=args.timeout_ms / 1000.0)
    if not provider.is_configured:
        print(
            "EXPERIMENT_BLOCKED: no Qwen credential in the environment or .env "
            "(QWEN_API_KEY / DASHSCOPE_API_KEY). Live evidence requires it.",
            file=sys.stderr,
        )
        return 2

    records = load_corpus(args.subset)
    if args.limit:
        records = records[: args.limit]

    data = run_comparison(provider, records)
    meta = {
        "model": provider.model,
        "temperature": provider.temperature,
        "timeout_ms": args.timeout_ms,
        "corpus": f"grounded-extraction/{args.subset}.jsonl",
        "reproduce": (
            "PYTHONPATH=. .venv/bin/python -m experiments."
            f"qwen_extraction_shadow run --subset {args.subset}"
        ),
    }
    path = write_artifacts(data, meta)
    s = data["summary"]
    print(f"wrote {path}")
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
