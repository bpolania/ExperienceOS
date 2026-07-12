"""Unit tests for the deterministic grounded extraction controller."""

import json

import pytest

from experienceos.controllers.extraction import (
    ExtractionController,
    ExtractionEvidence,
    ExtractionProposal,
)
from experienceos.memory.grounded_extraction import (
    ABSTENTION_REASONS,
    DeterministicGroundedExtractionController,
    GROUNDED_EXTRACTION_CONTROLLER_ID,
)

CONTROLLER = DeterministicGroundedExtractionController()


def extract(message, assistant="", provenance="", source_id="t-1"):
    return CONTROLLER.extract(
        ExtractionEvidence(
            user_text=message,
            assistant_text=assistant,
            provenance_label=provenance,
            metadata={"source_id": source_id},
        )
    )


# -- protocol and construction -----------------------------------------------------


def test_conforms_to_extraction_controller_protocol():
    # ExtractionController is a plain (non-runtime-checkable) Protocol;
    # verify structural conformance directly.
    assert hasattr(CONTROLLER, "controller_id")
    assert callable(getattr(CONTROLLER, "extract"))
    for name in ExtractionController.__protocol_attrs__:
        assert hasattr(CONTROLLER, name), name
    assert CONTROLLER.controller_id == GROUNDED_EXTRACTION_CONTROLLER_ID
    assert CONTROLLER.version == "1"


def test_construction_accepts_no_authority_handles():
    import inspect

    parameters = inspect.signature(
        DeterministicGroundedExtractionController
    ).parameters
    assert not any(
        token in name
        for name in parameters
        for token in ("store", "engine", "manager", "bus", "provider",
                      "callback")
    )


def test_construction_loads_no_models_or_env():
    import sys

    DeterministicGroundedExtractionController()
    heavy = {"sentence_transformers", "torch", "onnxruntime",
             "llama_cpp"}
    assert not heavy & set(sys.modules)


# -- positive extraction -----------------------------------------------------------


@pytest.mark.parametrize("message,expected_kind,expected_text", [
    ("I prefer aisle seats for short work trips.", "preference",
     "Prefers aisle seats for short work trips."),
    ("I usually prefer aisle seats.", "preference",
     "Usually prefers aisle seats."),
    ("My home airport is SJC.", "fact", "Home airport is SJC."),
    ("I work at Initech as a data engineer.", "fact",
     "Works at Initech as a data engineer."),
    ("When planning work trips, always include airport transfer time.",
     "instruction",
     "When planning work trips, always include airport transfer time."),
    ("I do not prefer red-eye flights.", "preference",
     "Does not prefer red-eye flights."),
    ("From now on, use SJC as my default airport.", "instruction",
     "Use SJC as the default airport from now on."),
    ("I do all my note taking in Obsidian, so keep exports in "
     "Markdown.", "preference", "Does all note taking in Obsidian."),
    ("I usually plan sprints on Monday mornings.", "preference",
     "Usually plans sprints on Monday mornings."),
])
def test_positive_rule_families(message, expected_kind, expected_text):
    proposal = extract(message)
    assert proposal.recommendation == "candidate", proposal.diagnostics
    assert proposal.candidate.kind == expected_kind
    assert proposal.candidate.text == expected_text


def test_scoped_preference_preserves_scope():
    proposal = extract(
        "Window is fine for long flights, but for short work trips I "
        "usually want aisle."
    )
    assert proposal.recommendation == "candidate"
    assert proposal.candidate.text == (
        "Usually wants aisle for short work trips."
    )
    span = proposal.candidate.evidence_spans[0]
    assert span.excerpt == "for short work trips I usually want aisle"


def test_preference_change_extracts_new_state_only():
    proposal = extract(
        "I used to prefer window seats, but now I choose aisle."
    )
    assert proposal.recommendation == "candidate"
    assert proposal.candidate.text == "Now chooses aisle."
    assert "window" not in proposal.candidate.text.lower()
    # No lifecycle instruction anywhere in the output.
    payload = json.dumps(proposal.diagnostics)
    assert "supersede" not in payload and "forget" not in payload


def test_durable_clause_beside_temporary_request():
    proposal = extract(
        "Book me an aisle seat for tomorrow - I always prefer aisle "
        "anyway."
    )
    assert proposal.recommendation == "candidate"
    span = proposal.candidate.evidence_spans[0]
    assert span.excerpt == "I always prefer aisle"
    assert "tomorrow" not in span.excerpt
    assert proposal.candidate.text == "Always prefers aisle."


def test_durable_assertion_beside_question():
    proposal = extract(
        "I usually fly from SJC. Should I use SFO this time?"
    )
    assert proposal.recommendation == "candidate"
    span = proposal.candidate.evidence_spans[0]
    assert "?" not in span.excerpt
    assert "SFO" not in span.excerpt
    assert proposal.candidate.text == "Usually flies from SJC."


# -- abstention ---------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "I am flying out of SFO this month.",
    "I'm working from the Austin office this week.",
    "For this trip only, put me in a window seat.",
    "Until Friday I'm reachable only on my personal phone.",
    "Book me an aisle seat for tomorrow.",
    "Should I use SFO or SJC?",
    "Do you think I prefer aisle or window, based on my trips?",
    "If I ever move to Seattle, I might use SEA.",
    "If I traveled more, I would prefer morning flights.",
    "Lately I guess I lean toward quieter hotels, sort of.",
    "My manager always prefers early flights.",
    "My partner keeps saying 'always pick the exit row'.",
])
def test_abstention_scenarios(message):
    proposal = extract(message)
    assert proposal.recommendation == "none", (message,
                                               proposal.candidate)
    assert proposal.candidate is None
    reason = proposal.diagnostics.get("abstention_reason")
    assert reason in ABSTENTION_REASONS


def test_empty_and_whitespace_messages_abstain():
    for message in ("", "   ", "\n\t"):
        proposal = extract(message)
        assert proposal.recommendation == "none"
        assert proposal.diagnostics["abstention_reason"] == (
            "empty_source"
        )


def test_assistant_only_claim_abstains():
    proposal = extract(
        "Thanks, that itinerary works.",
        assistant="Noted - since you prefer window seats, I chose 12A.",
    )
    assert proposal.recommendation == "none"
    # Assistant text is never scanned as an evidence source.
    assert proposal.diagnostics["raw_candidate_count"] == 0


def test_invalid_provenance_yields_no_candidate():
    proposal = extract("I prefer aisle seats.",
                       provenance="assistant_derived")
    assert proposal.recommendation == "none"
    assert proposal.diagnostics["abstention_reason"] == (
        "invalid_grounding"
    )
    rejected = proposal.diagnostics["rejected_candidates"]
    assert rejected[0]["code"] == "assistant_only_source"


# -- exact evidence -----------------------------------------------------------------


def test_evidence_is_exact_slice_of_original():
    message = "I prefer aisle seats for short work trips."
    proposal = extract(message)
    span = proposal.candidate.evidence_spans[0]
    assert message[span.start:span.end] == span.excerpt
    assert span.excerpt == message  # full-sentence span incl. period


def test_narrower_clause_preferred_over_whole_message():
    message = (
        "Book me an aisle seat for tomorrow - I always prefer aisle "
        "anyway."
    )
    proposal = extract(message)
    span = proposal.candidate.evidence_spans[0]
    assert span.end - span.start < len(message)


def test_punctuation_casing_unicode_preserved():
    message = "My préférence café is Blue Bottle."
    proposal = extract(message)
    if proposal.recommendation == "candidate":
        span = proposal.candidate.evidence_spans[0]
        assert message[span.start:span.end] == span.excerpt


# -- normalization safety ------------------------------------------------------------


def test_usually_never_becomes_always():
    proposal = extract("I usually prefer aisle seats.")
    assert "always" not in proposal.candidate.text.lower()


def test_negation_preserved():
    proposal = extract("I do not prefer red-eye flights.")
    assert "not" in proposal.candidate.text.lower()
    proposal = extract(
        "Do not include rental cars in my work-trip plans."
    )
    assert proposal.candidate.text == (
        "Do not include rental cars in work-trip plans."
    )
    assert proposal.candidate.kind == "instruction"


def test_no_universalizers_added():
    for message in (
        "I usually prefer aisle seats.",
        "I fly out of Lisbon most weeks.",
        "My home airport is SJC.",
    ):
        proposal = extract(message)
        text = proposal.candidate.text.lower()
        for word in ("all ", "every ", " any "):
            assert word not in text, (message, text)


# -- one-candidate limit and arbitration ----------------------------------------------


def test_never_more_than_one_candidate():
    proposal = extract(
        "I prefer aisle seats. My home airport is SJC. I usually "
        "drink green tea."
    )
    assert proposal.recommendation == "candidate"
    # ExtractionProposal structurally holds at most one candidate;
    # arbitration is recorded in diagnostics.
    assert proposal.diagnostics["raw_candidate_count"] >= 2
    assert proposal.diagnostics["valid_candidate_count"] >= 2
    assert proposal.diagnostics["skipped_candidates"]


def test_arbitration_prefers_higher_tier():
    proposal = extract(
        "I usually drink green tea. From now on, use SJC as my "
        "default airport."
    )
    assert proposal.candidate.kind == "instruction"
    assert proposal.diagnostics["rule_family"] == "current_replacement"


def test_unrelated_claims_never_combined():
    proposal = extract(
        "I prefer aisle seats. My home airport is SJC."
    )
    text = proposal.candidate.text
    assert not ("aisle" in text and "SJC" in text)


# -- validator integration -----------------------------------------------------------


def test_every_returned_candidate_passed_validation():
    proposal = extract("I prefer aisle seats.")
    validation = proposal.diagnostics["validation"]
    assert validation["valid"] is True
    assert validation["validator_id"] == "grounded_candidate_validator"
    assert validation["canonical_effect"] is False


def test_invalid_raw_candidate_becomes_none():
    # Temporary marker inside the only matching span: the rule may
    # fire, but the validator rejects and the public result is none.
    proposal = extract("I usually work from the cafe this month.")
    assert proposal.recommendation == "none"
    if proposal.diagnostics["raw_candidate_count"]:
        assert proposal.diagnostics["abstention_reason"] == (
            "invalid_grounding"
        )
        codes = {r["code"] for r in
                 proposal.diagnostics["rejected_candidates"]}
        assert "temporary_state" in codes


# -- determinism and serialization ----------------------------------------------------


def test_repeated_runs_identical():
    message = "I prefer aisle seats for short work trips."
    first = extract(message)
    second = extract(message)
    assert first.candidate == second.candidate
    d1 = {k: v for k, v in first.diagnostics.items()
          if k not in ("evaluation", "validation")}
    d2 = {k: v for k, v in second.diagnostics.items()
          if k not in ("evaluation", "validation")}
    assert d1 == d2


def test_results_serialize_safely():
    for message in ("I prefer aisle seats.",
                    "Should I use SFO or SJC?"):
        proposal = extract(message)
        payload = json.dumps(proposal.diagnostics)
        assert "/Users/" not in payload and "/home/" not in payload
        assert proposal.diagnostics["canonical_effect"] is False
        assert "elapsed_ms" in proposal.diagnostics["evaluation"]
        assert isinstance(proposal, ExtractionProposal)


# -- side effects and canonical compatibility ------------------------------------------


def test_extraction_has_no_side_effects(tmp_path):
    from experienceos.events.bus import EventBus
    from experienceos.memory.store import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    bus = EventBus()
    extract("I prefer aisle seats.")
    assert store.list_memories("u1") == []
    assert bus.history() == []
    assert not list(tmp_path.iterdir())


def test_controller_not_constructed_by_canonical_code():
    import pathlib

    for path in pathlib.Path("experienceos").rglob("*.py"):
        if path.name == "grounded_extraction.py":
            continue
        assert "DeterministicGroundedExtractionController" not in (
            path.read_text()
        ), path


def test_experienceos_construction_does_not_use_controller():
    import subprocess
    import sys
    import os

    probe = (
        "import sys\n"
        "from experienceos import ExperienceOS\n"
        "from experienceos.providers.mock import MockProvider\n"
        "ExperienceOS(model=MockProvider())\n"
        "print('grounded_extraction' in str(sys.modules.keys()))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        check=True, env=dict(os.environ, PYTHONPATH="."),
    )
    assert completed.stdout.strip() == "False"
