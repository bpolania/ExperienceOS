"""Phase 11 Prompt 8: dashboard diagnostic helper tests.

Pure helper-level coverage over synthetic payload fixtures for every
retrieval mode and degradation state, plus one end-to-end fixture
through the real engine/event path.
"""

import copy
import json

from demo.support import (
    EXCLUSION_KIND_LABELS,
    LIFECYCLE_AUTHORITY_NOTICE,
    candidate_detail,
    exclusion_kind,
    format_flag,
    format_ms,
    format_rate,
    format_score,
    gate_shadow_summary,
    phase11_benchmark_summary,
    phase11_candidate_rows,
    retrieval_diagnostics,
)
from experienceos.events.schema import EventType, ExperienceEvent


def _event(payload, event_type=EventType.CONTEXT_BUILT):
    return ExperienceEvent(
        type=event_type, user_id="u1", session_id="s1", payload=payload
    )


OLD_PHASE9_PAYLOAD = {
    "selected_memory_count": 2,
    "memory_budget": 4,
    "selection_records": [
        {"memory_id": "m1", "text": "old record", "kind": "fact",
         "status": "active", "selected": True, "rank": 1, "score": 3,
         "matched_keywords": ["tea"], "kind_priority": 1,
         "reason": "selected: matched tea"},
    ],
}

FUSED_PAYLOAD = {
    "selected_memory_count": 1,
    "retrieval_diagnostics": {
        "strategy": "hybrid_retrieval",
        "retrieval_mode": "fused",
        "semantic": {
            "mode": "fused",
            "enabled": True,
            "provider_available": True,
            "provider_id": "deterministic",
            "model_id": "stable-feature-hash-v1",
            "dimensions": 512,
            "relevance_floor": 0.30,
            "fallback_used": False,
            "fallback_reason": None,
            "fusion_profile_id": "full_fusion",
            "semantic_candidate_count": 1,
            "cache": {"lookups": 4, "hits": 2, "misses": 2,
                      "evictions": 0},
            "fusion": {
                "profile": {"profile_id": "full_fusion", "version": "1"},
                "union_count": 2,
                "post_limit_count": 2,
            },
        },
        "gate": {
            "enabled": True,
            "shadow_mode": True,
            "controller_id": "gate_shadow_heuristic-1",
            "status": "evaluated",
            "evaluated": 2,
            "admit": 1,
            "reject": 1,
            "abstain": 0,
            "agreement": 1,
            "disagreement": 1,
            "failures": 0,
            "affected_selection": 0,
        },
        "eligible_count": 2,
        "lifecycle_excluded_count": 1,
        "context_token_estimate": 9,
        "k": 2,
        "k_compliant": True,
        "budget_compliant": True,
    },
    "selection_records": [
        {
            "memory_id": "m-selected", "text": "prefers green tea",
            "kind": "preference", "status": "active", "selected": True,
            "rank": 1, "score": 0.31, "matched_keywords": ["tea"],
            "kind_priority": 0, "reason": "selected: matched tea",
            "component_scores": {"lexical_score": 2.1},
            "exclusion_reason": None,
            "semantic": {"considered": True, "score": 0.42,
                         "raw_cosine": 0.42, "rank": 1,
                         "above_floor": True, "cache_status": "hit",
                         "relevance_floor": 0.3,
                         "provider_id": "deterministic",
                         "model_id": "stable-feature-hash-v1",
                         "dimensions": 512},
            "fusion": {"profile_id": "full_fusion",
                       "profile_version": "1",
                       "normalization_id": "bounded_ratio-1",
                       "raw": {"lexical": 2.1, "semantic": 0.42},
                       "normalized": {"lexical": 0.41,
                                      "semantic": 0.42},
                       "weights": {"lexical": 0.35, "semantic": 0.30},
                       "contributions": {"lexical": 0.144,
                                         "semantic": 0.126},
                       "fused_score": 0.31,
                       "evidence_source": "lexical_and_semantic",
                       "lexical_rank": 1, "semantic_rank": 1,
                       "fused_rank": 1, "rank_delta": 0},
            "gate": {"considered": True, "status": "evaluated",
                     "controller_id": "gate_shadow_heuristic-1",
                     "proposal": "reject", "score": 0.1,
                     "confidence": 0.6, "reason": "near-floor",
                     "shadow_mode": True, "affected_selection": False,
                     "canonical_selected": True,
                     "agreement_with_selection": "disagreement"},
        },
        {
            "memory_id": "m-forgotten", "text": "forgotten memory",
            "kind": "fact", "status": "forgotten", "selected": False,
            "rank": 2, "score": 0, "matched_keywords": [],
            "kind_priority": 1,
            "reason": "skipped: inactive_forgotten",
            "exclusion_reason": "inactive_forgotten",
            "semantic": {"considered": False},
            "fusion": None,
            "gate": {"considered": False},
        },
        {
            "memory_id": "m-budget", "text": "over budget memory",
            "kind": "fact", "status": "active", "selected": False,
            "rank": 3, "score": 0.2, "matched_keywords": ["tea"],
            "kind_priority": 1, "reason": "skipped: token_budget",
            "exclusion_reason": "token_budget",
            "gate": {"considered": True, "status": "failed",
                     "failure": "RuntimeError",
                     "shadow_mode": True, "affected_selection": False,
                     "canonical_selected": False},
        },
    ],
}

FALLBACK_PAYLOAD = {
    "selected_memory_count": 1,
    "retrieval_diagnostics": {
        "retrieval_mode": "fused",
        "semantic": {
            "mode": "fused", "enabled": True,
            "provider_available": False,
            "provider_id": "sentence-transformers-local",
            "model_id": "local:unconfigured",
            "fallback_used": True,
            "fallback_reason": "dependency_missing",
            "fallback_path": "lexical_reference",
            "fusion_profile_id": "full_fusion",
        },
        "gate": {},
        "eligible_count": 2,
        "lifecycle_excluded_count": 0,
    },
    "selection_records": [],
}


# -- retrieval summary -----------------------------------------------------------


def test_no_events_returns_none():
    assert retrieval_diagnostics([]) is None
    assert gate_shadow_summary([]) is None


def test_old_phase9_event_renders_as_disabled():
    summary = retrieval_diagnostics([_event(OLD_PHASE9_PAYLOAD)])
    assert summary is not None
    assert summary["retrieval_mode"] == "disabled"
    assert summary["embedding_enabled"] is False
    assert summary["gate_enabled"] is False
    assert summary["cache"] is None


def test_fused_event_summary_fields():
    summary = retrieval_diagnostics([_event(FUSED_PAYLOAD)])
    assert summary["retrieval_mode"] == "fused"
    assert summary["embedding_enabled"] is True
    assert summary["provider_id"] == "deterministic"
    assert summary["model_id"] == "stable-feature-hash-v1"
    assert summary["dimensions"] == 512
    assert summary["semantic_floor"] == 0.30
    assert summary["fusion_profile"] == "full_fusion"
    assert summary["union_count"] == 2
    assert summary["cache"]["hits"] == 2
    assert summary["eligible_count"] == 2
    assert summary["lifecycle_excluded_count"] == 1
    assert summary["gate_enabled"] is True
    assert summary["gate_affected_selection"] == 0
    assert summary["budget_compliant"] is True


def test_fallback_event_summary():
    summary = retrieval_diagnostics([_event(FALLBACK_PAYLOAD)])
    assert summary["fallback_used"] is True
    assert summary["fallback_reason"] == "dependency_missing"
    assert summary["fallback_path"] == "lexical_reference"
    assert summary["provider_available"] is False
    assert summary["gate_enabled"] is False


def test_latest_event_wins():
    events = [_event(OLD_PHASE9_PAYLOAD), _event(FUSED_PAYLOAD)]
    assert retrieval_diagnostics(events)["retrieval_mode"] == "fused"


# -- exclusion classification ---------------------------------------------------


def test_exclusion_kind_classification():
    assert exclusion_kind("inactive_forgotten") == "lifecycle"
    assert exclusion_kind("inactive_superseded") == "lifecycle"
    assert exclusion_kind("zero_relevance") == "relevance"
    assert exclusion_kind("below_semantic_floor") == "relevance"
    assert exclusion_kind("no_fused_evidence") == "relevance"
    assert exclusion_kind("token_budget") == "budget"
    assert exclusion_kind("below_candidate_limit") == "candidate_limit"
    assert exclusion_kind("not_top_k") == "selection"
    assert exclusion_kind(None) == "selected"
    assert exclusion_kind(123) == "selected"
    # Every kind has a display label; lifecycle is marked authoritative.
    assert "authoritative" in EXCLUSION_KIND_LABELS["lifecycle"].lower()


# -- candidate rows and detail ---------------------------------------------------


def test_candidate_rows_extract_phase11_columns():
    rows = phase11_candidate_rows(FUSED_PAYLOAD["selection_records"])
    selected, forgotten, budget = rows
    assert selected["Decision"] == "Selected"
    assert selected["Semantic"] == "0.420"
    assert selected["Fused"] == "0.310"
    assert selected["Evidence"] == "lexical_and_semantic"
    assert selected["Cache"] == "hit"
    assert selected["Shadow gate"] == "Shadow: Reject"
    assert forgotten["Decision"] == (
        "Lifecycle exclusion (authoritative)"
    )
    assert forgotten["Semantic"] == "—"  # never scored
    assert forgotten["Shadow gate"] == "—"  # never gated
    assert budget["Decision"] == "Token-budget skip"
    assert budget["Shadow gate"] == "Shadow eval failed (contained)"


def test_candidate_rows_tolerate_old_records():
    rows = phase11_candidate_rows(
        OLD_PHASE9_PAYLOAD["selection_records"]
    )
    assert rows[0]["Semantic"] == "—"
    assert rows[0]["Fused"] == "—"
    assert rows[0]["Shadow gate"] == "—"


def test_candidate_rows_do_not_mutate_input():
    records = copy.deepcopy(FUSED_PAYLOAD["selection_records"])
    snapshot = copy.deepcopy(records)
    phase11_candidate_rows(records)
    for record in records:
        candidate_detail(record)
    assert records == snapshot


def test_candidate_detail_selected_with_gate_disagreement():
    detail = candidate_detail(FUSED_PAYLOAD["selection_records"][0])
    assert detail["canonical"]["selected"] == "Yes"
    gate = detail["shadow_gate"]
    assert gate["shadow_proposal"] == "Reject"
    assert gate["canonical_result"] == "Selected"
    assert gate["agreement"] == "disagreement"
    assert gate["affected_selection"] == "No"
    fusion = detail["fusion"]
    assert fusion["profile"] == "full_fusion v1"
    assert fusion["fused_score"] == "0.310"
    assert fusion["evidence_source"] == "lexical_and_semantic"


def test_candidate_detail_forgotten_shows_no_scores():
    detail = candidate_detail(FUSED_PAYLOAD["selection_records"][1])
    assert detail["canonical"]["exclusion_kind"] == (
        "Lifecycle exclusion (authoritative)"
    )
    assert detail["semantic"] == {"considered": "No (never embedded)"}
    assert detail["shadow_gate"] == {"considered": "No"}
    assert "fusion" not in detail


def test_candidate_detail_failed_gate_is_bounded():
    detail = candidate_detail(FUSED_PAYLOAD["selection_records"][2])
    gate = detail["shadow_gate"]
    assert "failed" in gate["status"]
    assert gate["failure_type"] == "RuntimeError"
    assert "Traceback" not in json.dumps(detail)


# -- gate shadow summary ---------------------------------------------------------


def test_gate_shadow_summary_extracts_counts():
    summary = gate_shadow_summary([_event(FUSED_PAYLOAD)])
    assert summary["controller_id"] == "gate_shadow_heuristic-1"
    assert summary["evaluated"] == 2
    assert summary["disagreement"] == 1
    assert summary["affected_selection"] == 0


def test_gate_shadow_summary_none_when_disabled():
    assert gate_shadow_summary([_event(OLD_PHASE9_PAYLOAD)]) is None
    assert gate_shadow_summary([_event(FALLBACK_PAYLOAD)]) is None


# -- formatting ------------------------------------------------------------------


def test_format_score_safety():
    assert format_score(0.42196) == "0.422"
    assert format_score(0) == "0.000"  # zero distinct from absent
    assert format_score(None) == "—"
    assert format_score("junk") == "—"
    assert format_score(float("nan")) == "—"
    assert format_score(float("inf")) == "—"


def test_format_ms_safety():
    assert format_ms(1.234) == "1.2 ms"
    assert format_ms(None) == "—"
    assert format_ms(-5) == "—"
    assert format_ms("junk") == "—"


def test_format_flag_and_rate():
    assert format_flag(True) == "Yes"
    assert format_flag(False) == "No"
    assert format_flag(None) == "—"
    assert format_rate(12, 50) == "12/50"
    assert format_rate(None, 50) == "—"


def test_authority_notice_wording():
    lowered = LIFECYCLE_AUTHORITY_NOTICE.lower()
    assert "before semantic scoring" in lowered
    assert "cannot" in lowered
    assert "forgotten" in lowered
    assert "shadow gate" in lowered


# -- benchmark summary -----------------------------------------------------------


def test_benchmark_summary_from_committed_data():
    summary = phase11_benchmark_summary()
    assert summary is not None
    assert summary["reference"]["selection"] == "12/50"
    assert summary["fused"]["selection"] == "13/50"
    assert summary["reference"]["mrr"] == "0.305"
    assert summary["fused"]["mrr"] == "0.293"
    assert summary["reference"]["tokens"] == 5527
    assert summary["fused"]["tokens"] == 5448
    assert summary["classifications"] == {
        "embedding_only": "not_adopted",
        "fused": "experimental",
        "gate_shadow": "experimental",
    }
    assert summary["gate_affected_selection"] == 0
    note = summary["provider_note"].lower()
    assert "deterministic test" in note
    assert "official longmemeval" in note


def test_benchmark_summary_missing_artifact_contained(tmp_path):
    assert phase11_benchmark_summary(
        report_data_path=str(tmp_path / "missing.json")
    ) is None


def test_benchmark_summary_malformed_artifact_contained(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert phase11_benchmark_summary(
        report_data_path=str(bad)
    ) is None
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text("{}")
    assert phase11_benchmark_summary(
        report_data_path=str(incomplete)
    ) is None


def test_benchmark_summary_does_not_modify_artifacts():
    from pathlib import Path

    from demo.support import PHASE11_REPORT_DATA_PATH

    before = Path(PHASE11_REPORT_DATA_PATH).read_bytes()
    phase11_benchmark_summary()
    assert Path(PHASE11_REPORT_DATA_PATH).read_bytes() == before


# -- end-to-end through the real engine/event path -------------------------------


def test_real_fused_gate_event_flows_to_helpers():
    from experienceos import ExperienceOS
    from experienceos.context.builder import ContextBuilder
    from experienceos.context.retrieval import HybridRetrievalStrategy
    from experienceos.context.semantic import SemanticCandidateGenerator
    from experienceos.controllers import HeuristicShadowMemoryGate
    from experienceos.embeddings import DeterministicEmbeddingProvider
    from experienceos.providers import MockProvider

    strategy = HybridRetrievalStrategy(
        semantic_generator=SemanticCandidateGenerator(
            DeterministicEmbeddingProvider()
        ),
        semantic_mode="fused",
        memory_gate=HeuristicShadowMemoryGate(),
    )
    agent = ExperienceOS(
        model=MockProvider(),
        context_builder=ContextBuilder(
            memory_budget=2, retrieval_strategy=strategy
        ),
    )
    agent.chat(user_id="u1", session_id="s1",
               message="I always drink green tea in the morning")
    snapshot = [
        (m.id, m.status) for m in agent.memories_for_user("u1")
    ]
    agent.chat(user_id="u1", session_id="s1",
               message="what do I drink in the morning?")
    summary = retrieval_diagnostics(agent.events)
    assert summary is not None
    assert summary["retrieval_mode"] == "fused"
    assert summary["provider_id"] == "deterministic"
    assert summary["gate_enabled"] is True
    assert summary["gate_affected_selection"] == 0
    from demo.support import selection_records

    rows = phase11_candidate_rows(selection_records(agent.events))
    assert rows  # candidates rendered with Phase 11 columns
    # Reading diagnostics mutated nothing.
    assert [
        (m.id, m.status) for m in agent.memories_for_user("u1")
    ] == snapshot
