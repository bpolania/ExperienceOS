"""External benchmark execution: three systems over the committed
LongMemEval 50-case stratified subset (or synthetic fixtures).

Fair-comparison configuration (identical across systems):

- identical underlying session content per case;
- retrieval/memory unit disclosure: full history uses every history
  turn (both roles); naive top-K indexes every history turn (both
  roles) as one unit each; ExperienceOS ingests each USER turn through
  the production ``chat`` path (assistant turns are not ingested —
  an architectural property recorded as a limitation, not hidden);
- K = memory budget = 6 for both structured systems;
- the same deterministic echo answer provider in offline modes
  (mock for ExperienceOS — both stateless and context-derived);
- offline runs enforce no provider context limit, so full history is
  labeled ``full_history_untruncated``;
- ceil(chars/4) token accounting everywhere;
- the expected answer and answer_session_ids never reach any system —
  they are used only by post-run evaluation.

State is fully isolated per case and per system; each case gets a
fresh system instance and a case-scoped user identity.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks.baselines.common import (
    DeterministicEchoProvider,
    approximate_tokens,
    content_words,
)
from benchmarks.contract import canonical_json, stable_dump
from benchmarks.external.longmemeval.evaluate import (
    EXTERNAL_METRICS,
    answer_contributions,
    aggregate_external,
    retrieval_contributions,
)
from benchmarks.external.longmemeval.loader import load_manifest
from benchmarks.external.longmemeval.schema import (
    REQUIRED_DISPLAY_LABEL,
    ExternalCase,
)

EXTERNAL_SYSTEMS = ("full_history", "naive_top_k", "experienceos_rules")

SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the provided conversation history "
    "or memory to answer the final question."
)

MEMORY_BUDGET = 6
SELECTION_K = 6

EXTERNAL_ARTIFACT_SCHEMA_VERSION = "1"

ARTIFACT_FILES = (
    "external_run_config.json",
    "external_provenance.json",
    "external_manifest.json",
    "selected_case_metadata.jsonl",
    "cases.jsonl",
    "retrieval_evidence.jsonl",
    "answer_evidence.jsonl",
    "metric_contributions.jsonl",
    "aggregate.json",
    "failures.json",
)


@dataclass
class ExternalCaseRun:
    question_id: str
    category: str
    system_id: str
    status: str = "completed"
    failure_reason: str | None = None
    sessions: int = 0
    history_turns: int = 0
    candidates: list = field(default_factory=list)
    selected_texts: list = field(default_factory=list)
    context_messages: list = field(default_factory=list)
    context_tokens: int = 0
    history_or_memory_tokens: int = 0
    truncation: str = "full_history_untruncated"
    response: str = ""
    contributions: list = field(default_factory=list)
    elapsed_ms: float = 0.0

    def record(self) -> dict:
        """Bounded case record: context evidence as per-message digests
        (chars + sha256 + short preview) so committed artifacts never
        embed full official histories (dataset_content_committed stays
        false); full candidate/selection detail lives once, in
        retrieval_evidence.jsonl."""
        return {
            "question_id": self.question_id,
            "category": self.category,
            "system_id": self.system_id,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "sessions": self.sessions,
            "history_turns": self.history_turns,
            "candidate_count": len(self.candidates),
            "selected_count": sum(
                1 for c in self.candidates if c["selected"]
            ),
            "context_message_digests": [
                {
                    "chars": len(m),
                    "sha256": hashlib.sha256(
                        m.encode("utf-8")
                    ).hexdigest(),
                    "preview": m[:120],
                }
                for m in self.context_messages
            ],
            "context_tokens": self.context_tokens,
            "history_or_memory_tokens": self.history_or_memory_tokens,
            "truncation": self.truncation,
            "response": self.response,
            "contributions": [c.to_payload() for c in self.contributions],
            "elapsed_ms": self.elapsed_ms,
        }

    def retrieval_record(self) -> dict:
        return {
            "question_id": self.question_id,
            "system_id": self.system_id,
            "candidates": self.candidates,
            "selected_texts": self.selected_texts,
        }


def _units(case: ExternalCase):
    """One unit per history turn (both roles), chronological order."""
    units = []
    for session in case.sessions:
        for turn in session.turns:
            units.append(
                (
                    session.session_id,
                    f"[{session.date}] {turn.role}: {turn.content}",
                )
            )
    return units


def _question_text(case: ExternalCase) -> str:
    return f"[{case.question_date}] {case.question}"


def _finish(run, case, context, candidates, structural=True):
    provider = DeterministicEchoProvider()
    run.context_messages = context
    run.response = provider.complete(context)
    total_chars = sum(len(m) for m in context)
    memory_chars = sum(len(m) for m in context[1:-1])
    run.context_tokens = approximate_tokens(total_chars)
    run.history_or_memory_tokens = approximate_tokens(memory_chars)
    run.candidates = [
        {"rank": rank, "session_id": session_id, "selected": selected}
        for rank, session_id, selected in candidates
    ]
    context_text = " ".join(context)
    run.contributions.extend(
        retrieval_contributions(
            case,
            [(r, s, sel) for r, s, sel in candidates],
            run.selected_texts,
            context_text,
        )
    )
    run.contributions.extend(
        answer_contributions(case, run.response, structural)
    )
    return run


def run_full_history(case: ExternalCase) -> ExternalCaseRun:
    run = ExternalCaseRun(case.question_id, case.category, "full_history")
    units = _units(case)
    run.sessions = len(case.sessions)
    run.history_turns = len(units)
    context = [SYSTEM_PROMPT, *(text for _, text in units), _question_text(case)]
    return _finish(run, case, context, candidates=[])


def run_naive_top_k(case: ExternalCase) -> ExternalCaseRun:
    run = ExternalCaseRun(case.question_id, case.category, "naive_top_k")
    units = _units(case)
    run.sessions = len(case.sessions)
    run.history_turns = len(units)
    query_words = content_words(_question_text(case))
    scored = []
    total = max(len(units) - 1, 1)
    for index, (session_id, text) in enumerate(units):
        overlap = float(len(query_words & content_words(text)))
        recency = 0.5 * (index / total)
        scored.append((overlap + recency, index, session_id, text))
    scored.sort(key=lambda item: (-item[0], item[1]))
    k = min(SELECTION_K, MEMORY_BUDGET)
    candidates = []
    selected_texts = []
    for rank, (score, index, session_id, text) in enumerate(scored, start=1):
        selected = rank <= k
        candidates.append((rank, session_id, selected))
        if selected:
            selected_texts.append(text)
    run.selected_texts = selected_texts
    run.truncation = "top_k_selection"
    context = [SYSTEM_PROMPT, *selected_texts, _question_text(case)]
    return _finish(run, case, context, candidates)


def run_experienceos_rules(case: ExternalCase) -> ExternalCaseRun:
    from experienceos import ExperienceOS
    from experienceos.context.builder import ContextBuilder
    from experienceos.context.compression import ExperienceCompressor
    from experienceos.events import EventType
    from experienceos.providers import MockProvider

    run = ExternalCaseRun(
        case.question_id, case.category, "experienceos_rules"
    )
    run.sessions = len(case.sessions)
    run.history_turns = sum(len(s.turns) for s in case.sessions)
    agent = ExperienceOS(
        model=MockProvider(),
        context_builder=ContextBuilder(
            memory_budget=MEMORY_BUDGET, compressor=ExperienceCompressor()
        ),
    )
    user_id = f"lme-{case.question_id}"
    memory_sessions: dict[str, str] = {}
    for session in case.sessions:
        for turn in session.turns:
            if turn.role != "user":
                continue  # production ingestion path: user turns only
            before = len(agent.events)
            agent.chat(
                user_id=user_id,
                session_id=session.session_id,
                message=turn.content,
            )
            for event in agent.events[before:]:
                if str(event.type) == "memory_created":
                    memory_sessions[event.payload["memory_id"]] = (
                        session.session_id
                    )

    before = len(agent.events)
    response = agent.chat(
        user_id=user_id,
        session_id="final-question",
        message=_question_text(case),
    )
    final_events = agent.events[before:]
    candidates = []
    context_contents: list[str] = []
    for event in final_events:
        if str(event.type) == "context_built":
            payload = event.payload
            context_contents = [
                m.get("content", "")
                for m in payload.get("context_messages", [])
            ]
            for record in payload.get("selection_records", []):
                session_id = memory_sessions.get(
                    record.get("memory_id"), "unknown"
                )
                candidates.append(
                    (
                        int(record.get("rank", 0)),
                        session_id,
                        bool(record.get("selected", False)),
                    )
                )
                if record.get("selected"):
                    run.selected_texts.append(record.get("text", ""))
    run.truncation = "memory_selection"
    context = [*context_contents, _question_text(case)]
    finished = _finish(run, case, context, candidates)
    finished.response = response  # actual production response path
    return finished


_RUNNERS = {
    "full_history": run_full_history,
    "naive_top_k": run_naive_top_k,
    "experienceos_rules": run_experienceos_rules,
}


def execute_external(cases, systems=EXTERNAL_SYSTEMS):
    runs = []
    failures = {"system_execution_failures": [], "deferred_evaluations": []}
    for system_id in systems:
        for case in cases:
            started = time.perf_counter()
            try:
                run = _RUNNERS[system_id](case)
            except Exception as exc:  # noqa: BLE001 — evidence over crash
                run = ExternalCaseRun(
                    case.question_id, case.category, system_id
                )
                run.status = "execution_failed"
                run.failure_reason = f"{type(exc).__name__}: {exc}"
                failures["system_execution_failures"].append(
                    {
                        "question_id": case.question_id,
                        "system_id": system_id,
                        "reason": run.failure_reason,
                    }
                )
            run.elapsed_ms = (time.perf_counter() - started) * 1000.0
            for contribution in run.contributions:
                if not contribution.applicable and (
                    contribution.metric == "abstention_match_proxy"
                ):
                    failures["deferred_evaluations"].append(
                        {
                            "question_id": case.question_id,
                            "system_id": system_id,
                            "reason": contribution.undefined_reason,
                        }
                    )
            runs.append(run)
    return runs, failures


def _normalized_digest(
    records: list, aggregate: dict, retrieval_records: list
) -> str:
    from benchmarks.artifacts.writer import normalize_for_digest

    normalized = normalize_for_digest(
        {
            "cases": records,
            "aggregate": aggregate,
            "retrieval": retrieval_records,
        }
    )
    return hashlib.sha256(
        canonical_json(normalized).encode("utf-8")
    ).hexdigest()


def write_external_artifacts(
    *,
    output_dir: str | Path,
    mode: str,
    data_file: str,
    cases,
    runs,
    failures,
    manifest: dict | None = None,
    overwrite: bool = False,
    timestamp: str | None = None,
) -> Path:
    manifest = manifest or load_manifest()
    final_dir = Path(output_dir)
    if final_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"output directory exists: {final_dir}"
            )
        shutil.rmtree(final_dir)
    staging = final_dir.parent / (final_dir.name + ".incomplete")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    synthetic = any(c.dataset_variant == "synthetic" for c in cases)
    records = [run.record() for run in runs]
    aggregate = {
        "artifact_schema_version": EXTERNAL_ARTIFACT_SCHEMA_VERSION,
        "display_label": REQUIRED_DISPLAY_LABEL,
        "mode": mode,
        "synthetic_data": synthetic,
        "official_evaluation": False,
        "metrics": aggregate_external(records),
        "composite_score": None,
    }
    config = {
        "display_label": REQUIRED_DISPLAY_LABEL,
        "mode": mode,
        "systems": list(EXTERNAL_SYSTEMS),
        "data_file": Path(data_file).name,
        "dataset_variant": cases[0].dataset_variant if cases else None,
        "memory_budget": MEMORY_BUDGET,
        "selection_k": SELECTION_K,
        "retrieval_weights": {"overlap": 1.0, "recency": 0.5},
        "retrieval_unit": "individual history turn (both roles); "
        "ExperienceOS ingests user turns via production chat",
        "answer_provider": "deterministic-echo/mock (offline)",
        "context_limit": "not enforced (offline deterministic provider); "
        "full history untruncated",
        "token_accounting_method": "approximation",
        "retry_policy": "none",
        "evaluator": "deterministic structural + labeled proxies; "
        "official GPT-4o judge NOT used",
    }
    provenance = _external_provenance(
        mode, manifest, cases, runs, synthetic, timestamp
    )

    _write(staging / "external_run_config.json", config)
    _write(staging / "external_provenance.json", provenance)
    _write(staging / "external_manifest.json", manifest)
    _write_jsonl(
        staging / "selected_case_metadata.jsonl",
        [
            {
                "question_id": c.question_id,
                "category": c.category,
                "official_type": c.official_type,
                "sessions": len(c.sessions),
                "history_turns": c.history_turn_count,
                "abstention": c.abstention,
                "answer_session_count": len(c.answer_session_ids),
            }
            for c in cases
        ],
    )
    _write_jsonl(staging / "cases.jsonl", records)
    retrieval_records = [run.retrieval_record() for run in runs]
    _write_jsonl(staging / "retrieval_evidence.jsonl", retrieval_records)
    _write_jsonl(
        staging / "answer_evidence.jsonl",
        [
            {
                "question_id": r["question_id"],
                "system_id": r["system_id"],
                "response": r["response"],
                "context_tokens": r["context_tokens"],
            }
            for r in records
        ],
    )
    _write_jsonl(
        staging / "metric_contributions.jsonl",
        [
            {
                "question_id": r["question_id"],
                "system_id": r["system_id"],
                **c,
            }
            for r in records
            for c in r["contributions"]
        ],
    )
    _write(staging / "aggregate.json", aggregate)
    _write(staging / "failures.json", failures)

    digest = _normalized_digest(records, aggregate, retrieval_records)
    artifact_manifest = {
        "artifact_schema_version": EXTERNAL_ARTIFACT_SCHEMA_VERSION,
        "display_label": REQUIRED_DISPLAY_LABEL,
        "synthetic_data": synthetic,
        "files": {
            name: {
                "sha256": hashlib.sha256(
                    (staging / name).read_bytes()
                ).hexdigest(),
                "records": (
                    sum(
                        1
                        for line in (staging / name)
                        .read_text()
                        .split("\n")
                        if line.strip()
                    )
                    if name.endswith(".jsonl")
                    else 1
                ),
            }
            for name in ARTIFACT_FILES
        },
        "case_run_count": len(runs),
        "normalized_result_digest": digest,
    }
    _write(staging / "artifact_manifest.json", artifact_manifest)
    (staging / "README.md").write_text(
        _readme(mode, manifest, synthetic, digest)
    )

    from benchmarks.external.longmemeval.validation import (
        validate_external_artifact,
    )

    validate_external_artifact(staging, allow_staging=True)
    staging.replace(final_dir)
    return final_dir


def _external_provenance(mode, manifest, cases, runs, synthetic, timestamp):
    import platform
    import subprocess
    import sys

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        clean = not subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        commit, clean = "unknown", False
    statuses = [r.status for r in runs]
    return {
        "display_label": REQUIRED_DISPLAY_LABEL,
        "mode": mode,
        "repository_commit": commit,
        "working_tree_clean": clean,
        "subset_version": manifest["subset_version"],
        "subset_manifest_hash": manifest["manifest_hash"],
        "official_dataset": manifest["official_dataset"],
        "source_revision": manifest["source_revision"],
        "source_fingerprint": manifest["source_fingerprint"],
        "dataset_variant": cases[0].dataset_variant if cases else None,
        "licenses": manifest["licenses"],
        "source_verification_date": manifest["source_verification_date"],
        "selection_algorithm_version": manifest[
            "selection_algorithm_version"
        ],
        "run_timestamp_utc": timestamp
        or time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "answer_provider": "deterministic-echo/mock",
        "answer_model": "deterministic-echo/mock",
        "evaluator": "deterministic structural + labeled proxies",
        "judge_model": None,
        "temperature": None,
        "max_output_tokens": None,
        "context_limit": "not enforced (offline)",
        "truncation_policy": "full_history_untruncated",
        "selection_k": SELECTION_K,
        "retrieval_weights": {"overlap": 1.0, "recency": 0.5},
        "token_accounting_method": "approximation",
        "retry_policy": "none",
        "platform": f"{platform.system().lower()}-{platform.machine()}",
        "python_version": (
            f"{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        "used_real_provider": False,
        "used_mock": True,
        "official_data": not synthetic,
        "synthetic_fixture_data": synthetic,
        "official_evaluation": False,
        "proxy_evaluation": True,
        "executed_cases": sum(1 for s in statuses if s == "completed"),
        "failed_cases": sum(1 for s in statuses if s == "execution_failed"),
        "skipped_cases": 0,
        "deferred_cases": sum(1 for c in cases if c.abstention)
        * len(EXTERNAL_SYSTEMS),
    }


def _write(path: Path, data) -> None:
    path.write_text(stable_dump(data), encoding="utf-8")


def _write_jsonl(path: Path, lines) -> None:
    path.write_text(
        "".join(canonical_json(line) + "\n" for line in lines),
        encoding="utf-8",
    )


def _readme(mode, manifest, synthetic, digest) -> str:
    data_kind = (
        "SYNTHETIC official-shape fixtures (NOT a benchmark result)"
        if synthetic
        else "official LongMemEval data"
    )
    return f"""# {REQUIRED_DISPLAY_LABEL} — {mode} run

- Data: {data_kind}; dataset variant per provenance; official source
  revision {manifest['source_revision']}.
- Systems: {', '.join(EXTERNAL_SYSTEMS)}, identical session content,
  identical answer-provider configuration, identical budgets.
- Evaluation: deterministic structural evidence (official
  answer_session_ids retrieval oracle) plus clearly-labeled proxy
  answer checks. The official GPT-4o judge was NOT used — nothing
  here is an official LongMemEval score, leaderboard result, or full
  500-question benchmark run.
- This artifact is a {mode} run: with the deterministic offline
  provider, answer-quality proxies reflect the echo provider equally
  across systems and are not live answer quality.
- Normalized result digest: `{digest}`
- Entirely separate from the custom lifecycle benchmark
  (benchmarks/results/committed/lifecycle-offline-v1); the two are
  never combined.
"""
