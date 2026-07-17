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


def _rate(num, den):
    return round(num / den, 4) if den else None


def _confusion(rows, accept_key):
    """(TP, FP, FN, TN) of one controller against the oracle over rows."""
    tp = sum(1 for r in rows if r["candidate_expected"] and r[accept_key])
    fp = sum(1 for r in rows if not r["candidate_expected"] and r[accept_key])
    fn = sum(1 for r in rows if r["candidate_expected"] and not r[accept_key])
    tn = sum(1 for r in rows if not r["candidate_expected"] and not r[accept_key])
    return tp, fp, fn, tn


def _controller_metrics(rows, accept_key, prefix):
    tp, fp, fn, tn = _confusion(rows, accept_key)
    n = len(rows)
    return {
        f"{prefix}_true_positives": tp,
        f"{prefix}_false_positives": fp,
        f"{prefix}_false_negatives": fn,
        f"{prefix}_accepted": tp + fp,
        f"{prefix}_recall": _rate(tp, tp + fn),
        f"{prefix}_precision": _rate(tp, tp + fp),
        f"{prefix}_over_extraction": _rate(fp, fp + tn),
        f"{prefix}_correct": _rate(tp + tn, n),
    }


def aggregate(rows: list) -> dict:
    n = len(rows)
    # Both controllers are scored on the messages where Qwen actually
    # answered, so a provider failure is never counted as a comparison and
    # both share the same denominator.
    success = [r for r in rows if r["qwen_success"]]
    agreements = sum(1 for r in success if r["agreement"])
    latencies = sorted(r["qwen_latency_ms"] for r in success)

    def pct(vals, p):
        if not vals:
            return None
        return round(vals[min(len(vals) - 1, int(p * len(vals)))], 1)

    summary = {
        "messages_processed": n,
        "scorable_records": n,
        "qwen_success": len(success),
        "qwen_failed": n - len(success),
        "expected_candidates": sum(1 for r in success if r["candidate_expected"]),
        "not_expected_candidates": sum(
            1 for r in success if not r["candidate_expected"]
        ),
        "det_proposals": sum(r["det_accepted"] for r in success),
        "qwen_proposals": sum(r["qwen_accepted"] for r in success),
        "det_rejected": 0,  # deterministic returns grounded results only
        "qwen_rejected": sum(r["qwen_rejected"] for r in success),
        "agreement_pct": _rate(agreements, len(success)),
        "disagreement_pct": _rate(len(success) - agreements, len(success)),
        "avg_qwen_latency_ms": (
            round(sum(latencies) / len(latencies), 1) if latencies else None
        ),
        "median_qwen_latency_ms": pct(latencies, 0.5),
        "max_qwen_latency_ms": latencies[-1] if latencies else None,
    }
    summary.update(_controller_metrics(success, "det_accepted", "det"))
    summary.update(_controller_metrics(success, "qwen_accepted", "qwen"))
    return summary


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


def write_artifacts(data: dict, meta: dict, subset: str) -> Path:
    out = RESULT_DIR / subset
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(
        json.dumps({"meta": meta, **data}, indent=1, sort_keys=True) + "\n"
    )
    (out / "report.md").write_text(_report_md(data, meta))
    return out


def _combined_metrics(all_rows: list) -> dict:
    """Combined confusion + unique-win accounting across both corpora."""
    success = [r for r in all_rows if r["qwen_success"]]
    det = _controller_metrics(success, "det_accepted", "det")
    qwen = _controller_metrics(success, "qwen_accepted", "qwen")
    qwen_wins = [
        r for r in success
        if r["candidate_expected"] and r["qwen_accepted"] and not r["det_accepted"]
    ]
    det_wins = [
        r for r in success
        if r["candidate_expected"] and r["det_accepted"] and not r["qwen_accepted"]
    ]
    shared_fp = [
        r for r in success
        if not r["candidate_expected"] and r["qwen_accepted"] and r["det_accepted"]
    ]
    qwen_only_fp = [
        r for r in success
        if not r["candidate_expected"] and r["qwen_accepted"] and not r["det_accepted"]
    ]
    det_only_fp = [
        r for r in success
        if not r["candidate_expected"] and r["det_accepted"] and not r["qwen_accepted"]
    ]
    latencies = [r["qwen_latency_ms"] for r in success]
    combined = {
        "total_scorable": len(all_rows),
        "qwen_success": len(success),
        "qwen_failed": len(all_rows) - len(success),
        "expected_candidates": sum(1 for r in success if r["candidate_expected"]),
        "qwen_unique_wins": [r["case_id"] for r in qwen_wins],
        "deterministic_unique_wins": [r["case_id"] for r in det_wins],
        "shared_false_positives": [r["case_id"] for r in shared_fp],
        "qwen_only_false_positives": [r["case_id"] for r in qwen_only_fp],
        "deterministic_only_false_positives": [r["case_id"] for r in det_only_fp],
        "avg_qwen_latency_ms": (
            round(sum(latencies) / len(latencies), 1) if latencies else None
        ),
    }
    combined.update(det)
    combined.update(qwen)
    return combined


def combine() -> Path:
    """Merge per-corpus results into combined evidence + a final report."""
    subsets = {}
    all_rows = []
    for subset in ("lifecycle", "external"):
        path = RESULT_DIR / subset / "results.json"
        if not path.exists():
            raise SystemExit(f"missing {path}; run --subset {subset} first")
        data = json.loads(path.read_text())
        subsets[subset] = data
        all_rows.extend(data["cases"])
    combined = _combined_metrics(all_rows)
    payload = {
        "prompt_version": subsets["lifecycle"]["prompt_version"],
        "per_corpus": {k: v["summary"] for k, v in subsets.items()},
        "combined": combined,
    }
    (RESULT_DIR / "combined.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n"
    )
    (RESULT_DIR / "report.md").write_text(_final_report_md(subsets, combined))
    return RESULT_DIR / "combined.json"


def _final_report_md(subsets: dict, c: dict) -> str:
    def block(name, s):
        if s["scorable_records"] == 0:
            return [
                f"### {name} (0 scorable)",
                "- Unscorable for durable-memory extraction — see "
                f"`{name}/UNSCORABLE.md`. The corpus has no per-message "
                "source text or creation oracle; excluded from scoring.",
                "",
            ]
        return [
            f"### {name} ({s['scorable_records']} scorable, "
            f"{s['expected_candidates']} expected)",
            f"- Recall — deterministic **{s['det_recall']}**, "
            f"Qwen **{s['qwen_recall']}**",
            f"- Precision — deterministic {s['det_precision']}, "
            f"Qwen {s['qwen_precision']}",
            f"- Over-extraction — deterministic {s['det_over_extraction']}, "
            f"Qwen {s['qwen_over_extraction']}",
            f"- Overall correctness — deterministic **{s['det_correct']}**, "
            f"Qwen **{s['qwen_correct']}**",
            f"- False positives — deterministic {s['det_false_positives']}, "
            f"Qwen {s['qwen_false_positives']}",
            f"- Qwen: {s['qwen_success']} ok / {s['qwen_failed']} failed · "
            f"grounding-rejected {s['qwen_rejected']} · agreement "
            f"{s['agreement_pct']} · latency avg {s['avg_qwen_latency_ms']} ms "
            f"(median {s['median_qwen_latency_ms']}, max {s['max_qwen_latency_ms']})",
            "",
        ]
    lines = [
        "# Qwen vs Deterministic Grounded Extraction — Final Comparison",
        "",
        f"Prompt version {subsets['lifecycle']['prompt_version']} · model "
        f"`{subsets['lifecycle']['meta']['model']}` · temperature 0 · one "
        "inference, no retries · shadow only, no memory mutation.",
        "",
        "## Per corpus",
        "",
    ]
    lines += block("lifecycle", subsets["lifecycle"]["summary"])
    lines += block("external", subsets["external"]["summary"])
    lines += [
        "## Combined",
        f"- Scorable {c['total_scorable']} · expected candidates "
        f"{c['expected_candidates']} · Qwen ok {c['qwen_success']} / failed "
        f"{c['qwen_failed']}",
        f"- Recall — deterministic **{c['det_recall']}**, Qwen **{c['qwen_recall']}**",
        f"- Precision — deterministic {c['det_precision']}, Qwen {c['qwen_precision']}",
        f"- Overall correctness — deterministic **{c['det_correct']}**, "
        f"Qwen **{c['qwen_correct']}**",
        f"- Qwen unique wins: {len(c['qwen_unique_wins'])} · deterministic "
        f"unique wins: {len(c['deterministic_unique_wins'])}",
        f"- False positives — shared {len(c['shared_false_positives'])}, "
        f"Qwen-only {len(c['qwen_only_false_positives'])}, deterministic-only "
        f"{len(c['deterministic_only_false_positives'])}",
        f"- Average Qwen latency: {c['avg_qwen_latency_ms']} ms",
        "",
        "## Reading these numbers",
        "",
        "Three distinct things are reported and never conflated: a "
        "**proposal** is what a controller asserted; **accepted** is what "
        "the unchanged `GroundedCandidateValidator` allowed through "
        "(asserted-but-rejected shows as grounding-rejected); and "
        "**oracle-correct** is whether that accepted result matches the "
        "corpus `candidate_expected` label. An accepted candidate is not "
        "automatically correct.",
        "",
        "The quality result rests on **one** creation-scorable corpus "
        "(lifecycle, 39 messages / 15 expected). The external corpus is "
        "unscorable for extraction, so cross-corpus generalization is "
        "**unconfirmed**. Qwen adds ~2.8 s/message latency and a live "
        "provider dependency; a failed call is a visible failed record, "
        "never a deterministic substitution.",
        "",
        "## Reproduce",
        "",
        "```",
        "PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow "
        "run --subset lifecycle",
        "PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow "
        "run --subset external",
        "PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow "
        "combine",
        "```",
        "",
        "Requires `QWEN_API_KEY` in the environment or `.env`.",
        "",
    ]
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="qwen_extraction_shadow")
    parser.add_argument("command", choices=["run", "combine"])
    parser.add_argument("--subset", default="lifecycle", choices=list(CORPUS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args(argv)

    if args.command == "combine":
        path = combine()
        print(f"wrote {path}")
        print((RESULT_DIR / "report.md").read_text())
        return 0

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
    path = write_artifacts(data, meta, args.subset)
    s = data["summary"]
    print(f"wrote {path}")
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
