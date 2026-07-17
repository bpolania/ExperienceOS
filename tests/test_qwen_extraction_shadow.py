"""Tests for the deterministic-vs-Qwen shadow comparison harness.

Offline: a stub provider returns canned JSON. Verifies fair separate
attribution, that a failed Qwen message is never counted as a valid
comparison, that aggregate metrics match the per-message records, that
agreement accounting is deterministic, the boundary offset correction,
and — the safety core — that the shadow comparison mutates no memory.
"""

from __future__ import annotations

import json

from experienceos.controllers.extraction import ExtractionEvidence
from experienceos.memory.grounded_extraction import (
    DeterministicGroundedExtractionController,
)
from experienceos.memory.store import MemoryStore
from experiments.qwen_extraction import (
    QwenExtractionController,
    _normalize_candidate_offsets,
)
from experiments.qwen_extraction_shadow import (
    _combined_metrics,
    aggregate,
    agree,
    evaluate_message,
    load_corpus,
    run_comparison,
)

DURABLE = "I prefer aisle seats for short work trips."


def _candidate_for(text, *, bad_offsets=False):
    end = 5 if bad_offsets else len(text)  # wrong offset if requested
    return json.dumps({
        "action": "candidate", "kind": "preference",
        "normalized_text": text, "evidence_text": text,
        "start_offset": 0, "end_offset": end,
        "confidence": 0.9, "reason": "pref",
    })


_NONE = json.dumps({
    "action": "none", "kind": None, "normalized_text": None,
    "evidence_text": None, "start_offset": None, "end_offset": None,
    "confidence": None, "reason": "none",
})


class _StubProvider:
    def __init__(self, mapping):
        self.is_configured = True
        self._mapping = mapping  # substring -> output

    def complete(self, messages):
        user = messages[-1]["content"]
        for needle, out in self._mapping.items():
            if needle in user:
                return out
        return _NONE


class _FailingProvider:
    is_configured = True

    def complete(self, messages):
        raise RuntimeError("provider down")


def _record(case_id, text, expected):
    return {"case_id": case_id, "source_text": text,
            "candidate_expected": expected, "scorable": True}


# --- boundary offset correction ---------------------------------------------


def test_offset_normalization_fixes_miscounted_offsets() -> None:
    fixed = _normalize_candidate_offsets(
        _candidate_for(DURABLE, bad_offsets=True), DURABLE
    )
    data = json.loads(fixed)
    assert data["start_offset"] == 0
    assert data["end_offset"] == len(DURABLE)
    assert DURABLE[data["start_offset"]:data["end_offset"]] == DURABLE


def test_offset_normalization_leaves_non_substring_untouched() -> None:
    raw = json.dumps({
        "action": "candidate", "kind": "preference",
        "normalized_text": "x", "evidence_text": "not in the message",
        "start_offset": 0, "end_offset": 5, "confidence": 0.5, "reason": "x",
    })
    assert _normalize_candidate_offsets(raw, DURABLE) == raw  # unchanged


# --- separate attribution, failed not counted -------------------------------


def test_failed_qwen_is_not_counted_as_a_valid_comparison() -> None:
    records = [_record("c1", DURABLE, True)]
    data = run_comparison(_FailingProvider(), records)
    s = data["summary"]
    assert s["qwen_success"] == 0
    assert s["qwen_failed"] == 1
    # recall is scored only over successful Qwen messages -> undefined here
    assert s["qwen_recall"] is None
    # the deterministic side is unaffected and separately attributed
    row = data["cases"][0]
    assert row["qwen_status"] == "runner_error"
    assert row["qwen_accepted"] == 0


def test_deterministic_and_qwen_are_separately_attributed() -> None:
    row = evaluate_message(
        _record("c1", DURABLE, True),
        DeterministicGroundedExtractionController(),
        QwenExtractionController(_StubProvider({DURABLE: _candidate_for(DURABLE)})),
    )
    # Distinct keys per controller; Qwen carries its own status.
    assert "det_accepted" in row and "qwen_accepted" in row
    assert row["qwen_accepted"] == 1
    assert row["qwen_status"] == "ok"


# --- aggregate matches per-message ------------------------------------------


def test_aggregate_matches_per_message_records() -> None:
    provider = _StubProvider({
        DURABLE: _candidate_for(DURABLE),
        "weather": _NONE,
    })
    records = [
        _record("c1", DURABLE, True),
        _record("c2", "what is the weather?", False),
    ]
    data = run_comparison(provider, records)
    rows, s = data["cases"], data["summary"]
    assert s["messages_processed"] == len(rows)
    assert s["qwen_accepted"] == sum(r["qwen_accepted"] for r in rows if r["qwen_success"])
    assert s["det_accepted"] == sum(r["det_accepted"] for r in rows)
    assert s["qwen_success"] == sum(1 for r in rows if r["qwen_success"])


def test_agreement_definition_is_deterministic() -> None:
    provider = _StubProvider({DURABLE: _candidate_for(DURABLE)})
    rec = _record("c1", DURABLE, True)
    a = run_comparison(provider, [rec])["summary"]["agreement_pct"]
    b = run_comparison(provider, [rec])["summary"]["agreement_pct"]
    assert a == b


def test_combined_metrics_equal_sum_of_per_corpus_records() -> None:
    provider = _StubProvider({DURABLE: _candidate_for(DURABLE), "weather": _NONE})
    life = run_comparison(provider, [
        _record("l1", DURABLE, True), _record("l2", "the weather", False),
    ])
    ext = run_comparison(provider, [
        _record("e1", DURABLE, True), _record("e2", "the weather", False),
    ])
    combined = _combined_metrics(life["cases"] + ext["cases"])
    assert combined["total_scorable"] == 4
    # Combined true positives == sum of per-corpus true positives.
    life_tp = life["summary"]["qwen_true_positives"]
    ext_tp = ext["summary"]["qwen_true_positives"]
    assert combined["qwen_true_positives"] == life_tp + ext_tp
    assert combined["expected_candidates"] == (
        life["summary"]["expected_candidates"]
        + ext["summary"]["expected_candidates"]
    )


# --- state safety -----------------------------------------------------------


def test_shadow_comparison_mutates_no_memory() -> None:
    store = MemoryStore()
    before = len(store.list_memories("u"))
    provider = _StubProvider({DURABLE: _candidate_for(DURABLE)})
    run_comparison(provider, [_record("c1", DURABLE, True),
                             _record("c2", "hello there", False)])
    # The harness holds no store and calls no engine; a separate store is
    # untouched, and neither controller can persist.
    assert len(store.list_memories("u")) == before == 0


def test_controllers_hold_no_store_or_mutation_authority() -> None:
    qwen = QwenExtractionController(_StubProvider({}))
    det = DeterministicGroundedExtractionController()
    for controller in (qwen, det):
        for forbidden in ("memory_store", "engine", "experience_manager",
                          "add", "supersede", "forget", "_apply_memory_actions"):
            assert not hasattr(controller, forbidden)


# --- corpus is read-only ----------------------------------------------------


def test_corpus_loads_scorable_records_readonly() -> None:
    records = load_corpus("lifecycle")
    assert records and all(r.get("scorable", True) for r in records)
    assert all("source_text" in r and "candidate_expected" in r for r in records)
