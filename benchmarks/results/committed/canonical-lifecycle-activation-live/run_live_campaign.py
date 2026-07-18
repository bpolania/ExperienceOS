"""Live competitive campaign under the frozen Prompt 6 controls.

Runs the complete frozen viability subset (40 cases) through all six
required systems against the live Qwen provider (one shared response
model), scores with the frozen deterministic + blinded-judge pipeline, and
writes an additive live-results evidence family. Credentials are loaded
from .env into the process only; no secret is printed or written.

Reads the frozen Phase 17/18 evidence read-only and modifies none of it.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

for _line in (REPO / ".env").read_text().splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from experiments.competitive_viability.cases import (  # noqa: E402
    load_cases, EVIDENCE_FROZEN_HISTORICAL,
)
from experiments.competitive_viability.systems import run_system_case  # noqa: E402
from experiments.competitive_viability.viability_subset import viability_case_ids  # noqa: E402
from experiments.competitive_viability import harness  # noqa: E402
from experiments.competitive_viability.scoring.criteria import build_case_criteria  # noqa: E402
from experiments.competitive_viability.scoring.campaign import (  # noqa: E402
    score_records, aggregate_by_system,
)
from experiments.competitive_viability.scoring.judge import BlindedJudge  # noqa: E402
from benchmarks.scenarios.loader import load_dataset, load_manifest  # noqa: E402
from experienceos.providers.qwen_cloud import QwenCloudProvider  # noqa: E402

OUT = REPO / "benchmarks/results/committed/canonical-lifecycle-activation-live"
RUN_ID = "cv-live-canonical-lifecycle-activation"
JUDGE_MODEL = "qwen-plus"
SYSTEMS = [
    "canonical_experienceos_qwen", "deterministic_experienceos",
    "stateless", "full_history", "naive_top_k", "append_only",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    provider = QwenCloudProvider(timeout=90)
    assert provider.is_configured
    response_model = provider.model
    case_ids = viability_case_ids()
    vcases = load_cases(case_ids, EVIDENCE_FROZEN_HISTORICAL)
    scenario_cases = {s.case.scenario_id: s.case for s in load_dataset(load_manifest())}

    log = (OUT / "campaign_progress.log").open("w")

    def note(m):
        log.write(m + "\n"); log.flush()

    records = []
    t0 = time.time()
    total = len(SYSTEMS) * len(vcases)
    for sysid in SYSTEMS:
        for vc in vcases:
            try:
                res = run_system_case(sysid, vc.scenario, provider, RUN_ID)
                rec = harness._build_record(
                    vc, res, run_id=RUN_ID, execution_mode="live",
                    response_model=response_model, system_id=sysid,
                )
                payload = rec.to_payload()
            except Exception as exc:  # preserve; never crash the campaign
                payload = harness._build_record(
                    vc, None, run_id=RUN_ID, execution_mode="live",
                    response_model=response_model, system_id=sysid,
                ).to_payload()
                payload["execution_error"] = type(exc).__name__
                note(f"ERROR {sysid}/{vc.case_id}: {type(exc).__name__}")
            records.append(payload)
            note(f"[{len(records)}/{total}] {sysid}/{vc.case_id} "
                 f"status={payload['status']} {time.time()-t0:.0f}s")
        with (OUT / "raw_case_results.jsonl").open("w") as f:
            for r in records:
                f.write(json.dumps(r, sort_keys=True, default=str) + "\n")
        note(f"-- checkpoint after {sysid} --")

    # scoring
    criteria_by_case = {cid: build_case_criteria(scenario_cases[cid]) for cid in case_ids}
    note("scoring with live blinded judge...")
    scored, judge_tasks = score_records(
        records, criteria_by_case, run_id=RUN_ID,
        judge=BlindedJudge(provider), judge_model=JUDGE_MODEL,
    )
    note(f"scoring done: {len(scored)} records {time.time()-t0:.0f}s")

    agg = aggregate_by_system(scored)
    with (OUT / "scoring_results.jsonl").open("w") as f:
        for s in scored:
            f.write(json.dumps(s.to_payload(), sort_keys=True, default=str) + "\n")
    (OUT / "aggregate_by_system.json").write_text(
        json.dumps(agg, indent=1, sort_keys=True) + "\n")
    (OUT / "run_manifest.json").write_text(json.dumps({
        "run_id": RUN_ID, "execution_mode": "live",
        "provider_name": provider.name, "model": response_model,
        "judge_model": JUDGE_MODEL, "systems": SYSTEMS,
        "total_cases": len(vcases), "single_response_model": True,
        "credential_present": True,
        "git_head": os.popen("git rev-parse HEAD").read().strip(),
        "elapsed_seconds": round(time.time() - t0, 1),
    }, indent=1, sort_keys=True) + "\n")
    note("DONE")
    print("DONE; wrote to", OUT)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
