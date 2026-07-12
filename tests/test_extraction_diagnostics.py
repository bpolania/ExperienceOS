"""Focused tests for the grounded-extraction dashboard view models.

Non-UI: the event view model, committed artifact loader, evidence helper,
classification display, and privacy bounds. No Streamlit, no providers,
no models.
"""

import json

import pytest

from demo import extraction_diagnostics as ed

# ---- configured mode -----------------------------------------------------


class _FakeCoordinator:
    def __init__(self, mode):
        self.config = type("C", (), {"effect_mode": mode})()


class _FakeAgent:
    def __init__(self, coordinator):
        self.extraction_coordinator = coordinator


def test_configured_mode_disabled_when_no_coordinator():
    assert ed.configured_extraction_mode(_FakeAgent(None)) == "disabled"


def test_configured_mode_reads_effect_mode():
    agent = _FakeAgent(_FakeCoordinator("shadow"))
    assert ed.configured_extraction_mode(agent) == "shadow"


def test_build_extraction_config_never_builds_adopted():
    assert ed.build_extraction_config("disabled") is None
    assert ed.build_extraction_config("adopted") is None  # never
    shadow = ed.build_extraction_config("shadow")
    assert shadow.effect_mode == "shadow"
    candidate = ed.build_extraction_config("candidate")
    assert candidate.effect_mode == "candidate"


# ---- event view model ----------------------------------------------------


def _event(payload):
    return type("E", (), {"type": ed.EXTRACTION_EVENT, "payload": payload})()


CANDIDATE_PAYLOAD = {
    "effect_mode": "shadow", "controller_type": "deterministic",
    "controller_id": "grounded_rules-1", "proposal_present": True,
    "proposed_kind": "preference", "normalized_text": "Prefers aisle seats.",
    "evidence_start": 0, "evidence_end": 20, "grounding_status": True,
    "grounding_code": "valid", "integration_status": "proposed",
    "canonical_effect": False, "action_applied": False,
    "final_proposal_source": "controller",
}


def test_candidate_event_normalizes():
    view = ed.normalize_extraction_event(CANDIDATE_PAYLOAD)
    assert view["proposal_present"] is True
    assert view["proposed_kind"] == "preference"
    assert ed.outcome_label(view) == "Candidate proposed"
    assert ed.canonical_effect_label(view) == "No — durable state unchanged"


def test_abstention_event():
    view = ed.normalize_extraction_event(
        {"proposal_present": False, "integration_status": "no_candidate",
         "canonical_effect": False})
    assert ed.outcome_label(view) == "Controller abstained — no candidate"


def test_grounding_rejected_event():
    view = ed.normalize_extraction_event(
        {"proposal_present": False,
         "integration_status": "grounding_rejected"})
    assert ed.outcome_label(view) == "Grounding rejected the candidate"


def test_learned_unavailable_event():
    view = ed.normalize_extraction_event(
        {"proposal_present": False, "controller_type": "learned",
         "runner_status": "unavailable", "integration_status": "no_candidate"})
    assert ed.outcome_label(view) == "Learned runner unavailable"


def test_fallback_event_final_source_preserved():
    view = ed.normalize_extraction_event(
        {"proposal_present": True, "fallback_used": True,
         "fallback_mode": "on_error",
         "final_proposal_source": "deterministic_fallback",
         "canonical_effect": False})
    assert view["fallback_used"] is True
    assert view["final_proposal_source"] == "deterministic_fallback"


def test_adopted_applied_event():
    view = ed.normalize_extraction_event(
        {"proposal_present": True, "effect_mode": "adopted",
         "adoption_authorized": True, "action_applied": True,
         "canonical_effect": True, "lifecycle_evaluation": "eligible"})
    assert ed.canonical_effect_label(view) == "Yes — durable memory changed"


def test_adopted_rejected_event():
    view = ed.normalize_extraction_event(
        {"proposal_present": True, "effect_mode": "adopted",
         "adoption_authorized": True, "action_applied": False,
         "canonical_effect": False, "lifecycle_evaluation": "rejected",
         "duplicate_or_conflict": "duplicate_of_planned"})
    assert ed.canonical_effect_label(view) == "No — durable state unchanged"
    assert view["duplicate_or_conflict"] == "duplicate_of_planned"


def test_controller_error_event():
    view = ed.normalize_extraction_event(
        {"integration_status": "controller_error",
         "error_class": "ControllerInputError", "canonical_effect": False})
    assert ed.outcome_label(view) == "Controller error (contained)"


def test_old_event_without_extraction_fields():
    view = ed.normalize_extraction_event({})
    assert view["proposal_present"] is None
    assert ed.canonical_effect_label(view) == "Unavailable"
    assert ed.outcome_label(view) == "No candidate proposed"


def test_partial_event_uses_none_not_false():
    view = ed.normalize_extraction_event({"effect_mode": "shadow"})
    assert view["grounding_status"] is None
    assert view["canonical_effect"] is None


def test_unknown_fields_ignored():
    view = ed.normalize_extraction_event(
        {"proposal_present": True, "some_new_field": "x", "canonical_effect": False})
    assert view["proposal_present"] is True
    assert "some_new_field" not in view


def test_trace_most_recent_first_and_bounded():
    events = [_event({"effect_mode": "shadow", "proposal_present": i % 2 == 0})
              for i in range(12)]
    trace = ed.extraction_trace(events, limit=5)
    assert len(trace) == 5
    # most recent first: last event (i=11) first
    assert trace[0]["proposal_present"] is False


def test_trace_ignores_non_extraction_events():
    other = type("E", (), {"type": "context_built", "payload": {}})()
    assert ed.extraction_trace([other]) == []


# ---- evidence rendering --------------------------------------------------


def test_evidence_exact_text_and_offsets():
    block = ed.evidence_block("I prefer aisle seats.", 2, 21)
    assert block["available"] is True
    assert "aisle seats" in block["excerpt_text"]
    assert "zero-based, end-exclusive" in block["offsets_label"]
    assert "<mark>" in block["excerpt_html"]


def test_evidence_escapes_html():
    block = ed.evidence_block("go <script>alert(1)</script> now", 3, 28)
    assert "<script>" not in block["excerpt_html"]
    assert "&lt;script&gt;" in block["excerpt_html"]
    # only the mark tag we add is a real tag
    assert block["excerpt_html"].count("<mark>") == 1


def test_evidence_escapes_markdown_like_input():
    block = ed.evidence_block("**bold** _under_ [x](y)", 0, 8)
    assert "&#x27;" in block["excerpt_html"] or "**bold**" in (
        block["excerpt_text"])
    # asterisks are preserved as literal text, not markdown, in the span
    assert "<mark>**bold**</mark>" in block["excerpt_html"]


def test_evidence_unicode():
    block = ed.evidence_block("I prefer café ☕ seats", 9, 15)
    assert block["available"] is True
    assert "café" in block["excerpt_text"]


def test_evidence_invalid_offsets():
    assert ed.evidence_block("short", 3, 1)["available"] is False
    assert ed.evidence_block("short", 0, 99)["available"] is False


def test_evidence_missing_source():
    block = ed.evidence_block(None, 0, 5)
    assert block["available"] is False
    assert block["excerpt_html"] is None


def test_evidence_never_synthesizes_from_candidate():
    # No candidate text is passed to the evidence helper at all; it only
    # ever slices the provided source. Missing source -> unavailable.
    assert ed.evidence_block(None, 0, 10)["excerpt_text"] is None


# ---- committed loader ----------------------------------------------------

SUMMARY = ed.grounded_extraction_summary()


def test_summary_loads_from_committed_artifacts():
    assert SUMMARY is not None
    assert SUMMARY["classification"] == "shadow_only"


def test_summary_metrics_have_numerators_and_denominators():
    m = SUMMARY["metrics"]
    assert m["precision"] == "5/6 (83.3%)"
    assert m["recall"] == "5/13 (38.5%)"
    assert m["grounded_span_validity"] == "6/6 (100.0%)"
    assert m["no_candidate_recall"] == "23/24 (95.8%)"


def test_summary_durable_creation_no_improvement():
    m = SUMMARY["metrics"]
    assert m["durable_creation_reference"] == m["durable_creation_grounded"]


def test_summary_failed_gates_visible_and_decisive():
    gates = SUMMARY["gates"]
    assert gates["passed"] == 12
    assert gates["total"] == 15
    assert gates["all_pass"] is False
    assert "creation_recall_or_absence_improvement" in gates["failed_gates"]
    assert "duplicate_active_memories" in gates["failed_gates"]


def test_summary_learned_systems_unavailable():
    for learned in SUMMARY["learned"]:
        assert learned["executed"] is False
        assert learned["skip_reason"]


def test_summary_unavailable_when_missing(tmp_path):
    assert ed.grounded_extraction_summary(
        report_data_path=tmp_path / "nope.json",
        adoption_path=tmp_path / "nope2.json") is None


def test_summary_unavailable_on_malformed(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    assert ed.grounded_extraction_summary(
        report_data_path=bad, adoption_path=bad) is None


def test_loader_ratio_distinguishes_unavailable_from_zero():
    assert ed._ratio({"numerator": None, "denominator": None,
                      "rate": None}) == "Unavailable"
    assert ed._ratio({"numerator": 0, "denominator": 5,
                      "rate": 0.0}) == "0/5 (0.0%)"


# ---- classification ------------------------------------------------------


def test_classification_shadow_only_label():
    assert ed.classification_label("shadow_only") == "Shadow only"


def test_classification_unavailable_and_insufficient_distinct():
    assert ed.classification_label("unavailable") == "Unavailable"
    assert ed.classification_label("insufficient_evidence") == (
        "Insufficient evidence")


# ---- case examples -------------------------------------------------------

CARDS = ed.extraction_case_examples()


def test_case_examples_resolve_from_committed_ids():
    ids = {c["case_id"] for c in CARDS}
    assert "creation_002_durable_user_fact" in ids
    assert "forgetting_003_forget_one_of_several" in ids


def test_missed_fact_case_has_no_proposal():
    card = next(c for c in CARDS
               if c["case_id"] == "creation_002_durable_user_fact")
    assert card["proposal_present"] is False
    assert card["proposal_score"] == "false_negative"


def test_forget_directive_case_is_false_positive_with_evidence():
    card = next(c for c in CARDS
               if c["case_id"] == "forgetting_003_forget_one_of_several")
    assert card["proposal_score"] == "false_positive"
    assert card["evidence"]["available"] is True
    assert "<mark>" in card["evidence"]["excerpt_html"]


def test_duplicate_case_shows_leak():
    card = next(c for c in CARDS
               if c["case_id"] == "updates_003_instruction_replacement")
    assert card["duplicate_active_leak"] >= 1


def test_case_examples_missing_files_do_not_crash(tmp_path):
    assert ed.extraction_case_examples(
        cases_path=tmp_path / "nope.jsonl",
        annotations_path=tmp_path / "nope.jsonl") == []


# ---- privacy -------------------------------------------------------------


def test_no_personal_paths_or_secrets_in_summary():
    blob = json.dumps(SUMMARY) + json.dumps(CARDS)
    for token in ("/Users/", "/home/", "api_key", "sk-", "password"):
        assert token not in blob


def test_normalized_text_is_bounded():
    long_text = "x" * 5000
    view = ed.normalize_extraction_event({"normalized_text": long_text})
    assert len(view["normalized_text"]) <= 240


def test_evidence_excerpt_is_bounded():
    long_source = "y" * 5000
    block = ed.evidence_block(long_source, 0, 4000)
    if block["excerpt_text"] is not None:
        assert len(block["excerpt_text"]) <= 200
