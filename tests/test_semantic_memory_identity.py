"""Semantic memory identity: projection, comparison, and safety.

All deterministic and offline: no provider, no model, no network, and
no lifecycle mutation anywhere in this module's subject under test.
"""

import json
import socket

import pytest

from benchmarks.annotations import transition_verification as tv
from benchmarks.semantic_identity.evaluation import (
    evaluate_corpus,
    is_applicable,
    relation_signature,
)
from experienceos.memory import ExperienceEntry, MemoryKind
from experienceos.memory.identity import (
    Durability,
    IdentityComparer,
    IdentityProjector,
    IdentityRelation,
    ScopeRelation,
    TemporalStatus,
    UNSCOPED,
    canonical_scope,
    canonical_value,
    compare_memory_identity,
    comparison_text,
    infer_kind,
    normalize_text,
    project_memory,
    project_statement,
    resolve_identity,
)
from experienceos.memory.store import InMemoryMemoryStore

PROJECTOR = IdentityProjector()
COMPARER = IdentityComparer()


def relate(existing_text, proposed_text, existing_kind=None, proposed_kind=None):
    """Relation between a stored memory text and a proposed statement."""
    existing = project_statement(existing_text, kind=existing_kind)
    proposed = project_statement(proposed_text, kind=proposed_kind)
    return compare_memory_identity(existing, proposed)


# --- 21.1 Normalization -------------------------------------------------------


def test_normalization_is_unicode_and_whitespace_deterministic():
    assert normalize_text("  I  PREFER\taisle\nseats ") == "i prefer aisle seats"
    # NFKC folds the compatibility ligature; curly quotes become plain.
    assert normalize_text("ﬁle") == "file"
    assert normalize_text("I don’t like it") == "I don't like it".lower()


def test_normalization_is_idempotent_and_stable():
    text = "Actually — I now prefer WINDOW seats."
    once = normalize_text(text)
    assert once == normalize_text(once)
    assert normalize_text(text) == normalize_text(text)


def test_comparison_text_drops_punctuation_case_and_articles():
    assert comparison_text("I prefer the aisle seat.") == comparison_text(
        "i prefer aisle seat"
    )
    assert comparison_text("I prefer aisle seats!") == comparison_text(
        "I prefer aisle seats."
    )


def test_synonyms_are_domain_scoped_and_deterministic():
    assert canonical_value("seat", "aisle seats")[0] == "aisle"
    assert canonical_value("ground_transport", "public transportation")[0] == (
        "public transit"
    )
    assert canonical_value("ground_transport", "rental cars")[0] == "rental car"
    assert canonical_value("cuisine", "vegetarian places")[0] == "vegetarian"


def test_synonyms_do_not_collide_across_domains():
    # "window" is a seat value; it must not canonicalize in a domain
    # that does not define it.
    assert canonical_value("theme", "window")[0] == "window"
    assert canonical_value("seat", "dark")[0] == "dark"


def test_canonical_scope_prefers_the_more_specific_alias():
    assert canonical_scope("short work trips")[0] == "short_work_trip"
    assert canonical_scope("short business trips")[0] == "short_work_trip"
    assert canonical_scope("work trips")[0] == "work_trip"
    assert canonical_scope("long international flights")[0] == "long_international"


# --- 21.2 Identity projection -------------------------------------------------


def test_projection_extracts_subject_attribute_value_and_scope():
    identity = project_statement("I prefer aisle seats for short work trips.")
    assert identity.subject.value == "travel"
    assert identity.attribute.value == "seat"
    assert identity.value.value == "aisle"
    assert identity.scope.value == "short_work_trip"
    assert identity.scope_specified is True
    assert identity.completeness == 1.0
    assert identity.unknown_fields == ()


def test_projection_prefers_structured_metadata_over_text_inference():
    entry = ExperienceEntry(
        user_id="u",
        text="Some unsupported phrasing entirely.",
        kind=MemoryKind.FACT,
        metadata={
            "semantic_identity": {
                "attribute": "employer",
                "value": "acme",
                "subject": "user",
            }
        },
    )
    identity = project_memory(entry)
    assert identity.attribute.value == "employer"
    assert identity.attribute.source == "structured_metadata"
    assert identity.value.value == "acme"


def test_unscoped_statement_is_marked_unspecified_not_unknown():
    identity = project_statement("I prefer aisle seats.")
    assert identity.scope.value == UNSCOPED
    assert identity.scope_specified is False
    assert identity.scope.known is True


def test_unsupported_text_falls_back_to_unknown_fields():
    identity = project_statement("The quarterly roadmap needs another look.")
    assert not identity.projected
    assert "attribute" in identity.unknown_fields
    assert identity.completeness < 1.0


def test_marker_detection_covers_each_non_durable_family():
    assert project_statement("This time only, use a window seat.").temporal_status == (
        TemporalStatus.TEMPORARY
    )
    assert project_statement("I used to prefer window seats.").temporal_status == (
        TemporalStatus.HISTORICAL
    )
    assert project_statement("If I moved, I might use JFK.").temporal_status == (
        TemporalStatus.HYPOTHETICAL
    )
    assert project_statement("Do you remember my seat preference?").temporal_status == (
        TemporalStatus.QUESTION
    )


def test_non_durable_markers_set_durability():
    assert project_statement("Temporarily, use a window seat.").durability == (
        Durability.NON_DURABLE
    )
    assert project_statement("I prefer aisle seats.").durability == Durability.DURABLE


def test_question_detection_does_not_fire_on_imperatives():
    # "Use SFO." is an imperative, not a question, despite the bounded
    # question lexicon containing "can you"/"could you".
    identity = project_statement("Use SFO for my work flights.")
    assert identity.temporal_status == TemporalStatus.CURRENT
    assert identity.durability == Durability.DURABLE


def test_compound_historical_and_current_statement_is_not_collapsed():
    identity = project_statement(
        "I used to prefer aisle seats, but now I prefer window seats."
    )
    assert identity.temporal_status == TemporalStatus.CURRENT
    assert identity.value.value == "window"
    assert identity.historical_value == "aisle"


def test_instead_of_clause_is_not_read_as_the_asserted_value():
    identity = project_statement(
        "Actually, I now prefer window seats for work trips instead of aisle seats."
    )
    assert identity.value.value == "window"
    assert identity.scope.value == "work_trip"


def test_kind_inference_is_bounded_and_ordered():
    assert infer_kind("I prefer aisle seats.") == MemoryKind.PREFERENCE
    assert infer_kind("My phone is a Pixel 9 now.") == MemoryKind.FACT
    assert infer_kind("I am allergic to shellfish.") == MemoryKind.FACT
    assert infer_kind("Use SFO for my work flights.") == MemoryKind.INSTRUCTION
    assert infer_kind("From now on, send my summary to #eng.") == (
        MemoryKind.INSTRUCTION
    )


def test_identity_keys_are_deterministic_and_stable():
    first = project_statement("I prefer aisle seats for short work trips.")
    second = project_statement("I prefer aisle seats for short work trips.")
    assert first.target_key() == second.target_key()
    assert first.semantic_key() == second.semantic_key()
    assert first.target_key() is not None


def test_target_key_excludes_value_so_replacement_lands_on_one_slot():
    old = project_statement("I prefer aisle seats for short work trips.")
    new = project_statement("I now prefer window seats for short work trips.")
    assert old.target_key() == new.target_key()
    assert old.semantic_key() != new.semantic_key()


def test_no_key_when_critical_identity_fields_are_unknown():
    identity = project_statement("Actually, make it window.")
    assert identity.target_key() is None
    assert identity.semantic_key() is None


# --- 21.3 Exact duplicate -----------------------------------------------------


def test_exact_duplicate_on_identical_text():
    result = relate("I don't like cilantro.", "I don't like cilantro.")
    assert result.relation == IdentityRelation.EXACT_DUPLICATE
    assert result.exact_text_match is True


def test_exact_duplicate_tolerates_punctuation_and_capitalization():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "i prefer aisle seats for short work trips!!",
    )
    assert result.relation == IdentityRelation.EXACT_DUPLICATE


def test_exact_duplicate_tolerates_harmless_article_variation():
    result = relate("I prefer the aisle seat.", "I prefer aisle seat.")
    assert result.relation == IdentityRelation.EXACT_DUPLICATE


def test_different_scope_is_not_an_exact_duplicate():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I prefer aisle seats for long international flights.",
    )
    assert result.relation != IdentityRelation.EXACT_DUPLICATE


# --- 21.4 Semantic duplicate --------------------------------------------------


def test_semantic_duplicate_across_wording_and_scope_synonym():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "For short business trips, aisle seats are my usual choice.",
    )
    assert result.relation == IdentityRelation.SEMANTIC_DUPLICATE
    assert result.value_relation == "equal"


def test_semantic_duplicate_on_transport_synonym():
    result = relate(
        "Include public transportation options for work trips.",
        "Include public transit options for work trips.",
    )
    assert result.relation in (
        IdentityRelation.SEMANTIC_DUPLICATE,
        IdentityRelation.EXACT_DUPLICATE,
    )


def test_different_value_is_not_a_duplicate():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I now prefer window seats for short work trips.",
    )
    assert result.relation == IdentityRelation.CURRENT_STATE_CONFLICT


def test_different_supported_scope_is_not_a_duplicate():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "For long international flights, I prefer aisle seats.",
    )
    assert result.relation == IdentityRelation.SCOPED_COEXISTENCE


def test_historical_restatement_is_not_a_duplicate():
    result = relate("I prefer aisle seats.", "I used to prefer aisle seats.")
    assert result.relation == IdentityRelation.HISTORICAL


# --- 21.5 Current-state conflict ----------------------------------------------


def test_now_prefer_replacement_conflicts():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I now prefer window seats for short work trips.",
    )
    assert result.relation == IdentityRelation.CURRENT_STATE_CONFLICT
    assert result.conflict_fields == ("value",)
    assert result.supersession_candidate is True


def test_instead_of_replacement_conflicts():
    result = relate(
        "Use SJC for my work flights.",
        "Use SFO instead of SJC for my work flights.",
    )
    assert result.relation == IdentityRelation.CURRENT_STATE_CONFLICT


def test_used_to_now_replacement_conflicts_on_the_current_value():
    result = relate(
        "I prefer aisle seats.",
        "I used to prefer aisle seats, but now I prefer window seats.",
    )
    assert result.relation == IdentityRelation.CURRENT_STATE_CONFLICT


def test_current_state_fact_replacement_conflicts():
    result = relate("My phone is a Pixel 6.", "My phone is a Pixel 9 now.")
    assert result.relation == IdentityRelation.CURRENT_STATE_CONFLICT


def test_no_conflict_when_attribute_differs():
    result = relate("My home airport is SJC.", "My phone is a Pixel 9 now.")
    assert result.relation == IdentityRelation.UNRELATED


def test_no_conflict_when_scope_differs():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "For long international flights, I prefer window seats.",
    )
    assert result.relation == IdentityRelation.SCOPED_COEXISTENCE


def test_repeated_correction_keeps_one_stable_target_identity():
    keys = {
        project_statement(text).target_key()
        for text in (
            "I prefer aisle seats for short work trips.",
            "I now prefer window seats for short work trips.",
            "I now prefer middle seats for short work trips.",
        )
    }
    assert len(keys) == 1


# --- 21.6 Scoped coexistence --------------------------------------------------


def test_work_and_personal_scopes_coexist():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "For weekend personal trips, I prefer window seats.",
    )
    assert result.relation == IdentityRelation.SCOPED_COEXISTENCE
    assert result.scope_relation == ScopeRelation.DISJOINT


def test_lexical_similarity_does_not_force_a_scope_collision():
    # Near-identical wording, different supported scope: not a
    # duplicate and not a supersession.
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I prefer window seats for long international flights.",
    )
    assert result.relation == IdentityRelation.SCOPED_COEXISTENCE
    assert result.supersession_candidate is False


def test_scope_containment_fails_closed_rather_than_coexisting():
    # "short work trips" is contained by "work trips": neither a clean
    # conflict nor clean coexistence.
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I prefer window seats for work trips.",
    )
    assert result.relation == IdentityRelation.AMBIGUOUS
    assert result.fail_closed is True


def test_unscoped_proposal_against_scoped_memory_does_not_assume_the_scope():
    existing = project_statement("I prefer aisle seats for short work trips.")
    proposed = project_statement("I prefer window seats.")
    result = COMPARER.compare(existing, proposed)
    assert result.scope_relation == ScopeRelation.UNKNOWN


def test_two_unscoped_statements_are_compatible_not_proven_equal():
    result = relate("I prefer aisle seats.", "I now prefer window seats.")
    assert result.scope_relation == ScopeRelation.COMPATIBLE
    assert result.relation == IdentityRelation.CURRENT_STATE_CONFLICT


def test_two_explicitly_scoped_statements_are_equal():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I now prefer window seats for short work trips.",
    )
    assert result.scope_relation == ScopeRelation.EQUAL


def test_synonym_match_reports_an_equivalent_value_not_an_equal_one():
    # Canonicalized from different surface wording: that difference is
    # exactly what separates a semantic duplicate from an exact one.
    result = relate(
        "Include public transportation options for work trips.",
        "Include public transit options for work trips.",
    )
    assert result.value_relation == "equivalent"
    assert result.relation == IdentityRelation.SEMANTIC_DUPLICATE


# --- 21.7 Temporary and historical --------------------------------------------


def test_temporary_exception_preserves_the_durable_preference():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "This time only, use a window seat.",
    )
    assert result.relation == IdentityRelation.TEMPORARY_EXCEPTION
    assert result.fail_closed is True
    assert result.supersession_candidate is False


def test_today_only_is_temporary():
    result = relate("I prefer aisle seats.", "Today only, give me a window seat.")
    assert result.relation == IdentityRelation.TEMPORARY_EXCEPTION


def test_historical_statement_never_replaces_a_current_memory():
    result = relate("I am based in the Austin office.", "I used to be based in the Denver office.")
    assert result.relation == IdentityRelation.HISTORICAL
    assert result.supersession_candidate is False


def test_historical_only_statement_preserves_current_identity():
    result = relate("I prefer aisle seats.", "Previously I preferred window seats.")
    assert result.relation == IdentityRelation.HISTORICAL


def test_hypothetical_statement_fails_closed():
    result = relate("My home airport is SJC.", "If I moved to New York, I might use JFK.")
    assert result.relation == IdentityRelation.HYPOTHETICAL
    assert result.fail_closed is True


def test_question_fails_closed():
    result = relate("I prefer aisle seats.", "Do you remember my seat preference?")
    assert result.relation == IdentityRelation.QUESTION
    assert result.fail_closed is True


# --- 21.8 Unrelated -----------------------------------------------------------


def test_seat_preference_and_airport_fact_are_unrelated():
    result = relate("My home airport is SJC.", "I now prefer window seats for work trips.")
    assert result.relation == IdentityRelation.UNRELATED


def test_device_and_travel_preference_are_unrelated():
    result = relate("I prefer dark mode in my code editor.", "My phone is a Pixel 9 now.")
    assert result.relation == IdentityRelation.UNRELATED


def test_shared_vocabulary_does_not_create_identity():
    # Both mention "work"; the attributes differ, so they are unrelated.
    result = relate(
        "Use SJC for my work flights.",
        "I prefer aisle seats for short work trips.",
    )
    assert result.relation == IdentityRelation.UNRELATED


def test_shared_value_token_but_different_subject_is_unrelated():
    # "morning" is both a drink-time and a study-time value.
    result = relate("I prefer studying in the morning.", "I prefer coffee in the morning.")
    assert result.relation == IdentityRelation.UNRELATED


# --- 21.9 Ambiguity -----------------------------------------------------------


def test_missing_value_is_ambiguous():
    result = relate("I prefer aisle seats for short work trips.", "Change my seat preference.")
    assert result.relation == IdentityRelation.AMBIGUOUS
    assert result.fail_closed is True


def test_unsupported_statement_against_known_memory_is_ambiguous():
    result = relate("I prefer aisle seats.", "Let's revisit the whole thing.")
    assert result.relation == IdentityRelation.AMBIGUOUS
    assert result.fail_closed is True


def test_multiple_plausible_targets_fail_closed():
    active = [
        project_statement("I prefer aisle seats for short work trips."),
        project_statement("I prefer window seats for long international flights."),
    ]
    resolution = resolve_identity(project_statement("Actually, make it middle."), active)
    assert resolution.relation == IdentityRelation.AMBIGUOUS
    assert resolution.fail_closed is True
    assert resolution.target_index is None


def test_single_plausible_target_resolves_an_elliptical_correction():
    active = [project_statement("I prefer aisle seats for short work trips.")]
    resolution = resolve_identity(project_statement("Actually, make it window."), active)
    assert resolution.relation == IdentityRelation.CURRENT_STATE_CONFLICT
    assert resolution.target_index == 0


def test_ambiguous_result_carries_diagnostics():
    result = relate("I prefer aisle seats.", "Change my seat preference.")
    assert result.rationale
    assert result.rationale[0].code


# --- 21.10 Non-mutation -------------------------------------------------------


def test_projection_does_not_alter_the_input_memory():
    entry = ExperienceEntry(user_id="u", text="I prefer aisle seats for short work trips.")
    before = json.dumps(entry.to_record(), sort_keys=True)
    project_memory(entry)
    assert json.dumps(entry.to_record(), sort_keys=True) == before


def test_comparison_does_not_alter_either_identity():
    existing = project_statement("I prefer aisle seats for short work trips.")
    proposed = project_statement("I now prefer window seats for short work trips.")
    snapshot = (json.dumps(existing.to_record(), sort_keys=True),
                json.dumps(proposed.to_record(), sort_keys=True))
    compare_memory_identity(existing, proposed)
    assert (json.dumps(existing.to_record(), sort_keys=True),
            json.dumps(proposed.to_record(), sort_keys=True)) == snapshot


def test_identity_never_writes_to_a_store():
    store = InMemoryMemoryStore()
    entry = store.add(
        ExperienceEntry(user_id="u", text="I prefer aisle seats for short work trips.")
    )
    before = [m.to_record() for m in store.list_memories(user_id="u")]
    project_memory(entry)
    resolve_identity(
        project_statement("I now prefer window seats for short work trips."),
        [project_memory(entry)],
    )
    assert [m.to_record() for m in store.list_memories(user_id="u")] == before


def test_identity_module_does_not_import_mutation_or_provider_code():
    import experienceos.memory.identity as module

    source = module.__file__
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for banned in (
        "experienceos.engine",
        "experienceos.policy",
        "experienceos.providers",
        "experienceos.embeddings",
        "MemoryAction",
        "_apply_memory_actions",
        "requests",
        "urllib",
        "httpx",
    ):
        assert banned not in text, f"identity module references {banned}"


def test_identity_performs_no_network_access(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("identity comparison attempted network access")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I now prefer window seats for short work trips.",
    )
    assert result.relation == IdentityRelation.CURRENT_STATE_CONFLICT


# --- 21.11 Serialization ------------------------------------------------------


def test_comparison_serializes_deterministically():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I now prefer window seats for short work trips.",
    )
    first = json.dumps(result.to_record(), sort_keys=True)
    second = json.dumps(result.to_record(), sort_keys=True)
    assert first == second
    assert json.loads(first)["relation"] == IdentityRelation.CURRENT_STATE_CONFLICT


def test_projection_record_marks_unknown_fields_explicitly():
    record = project_statement("Some entirely unsupported phrasing.").to_record()
    assert "attribute" in record["unknown_fields"]
    assert record["target_key"] is None
    assert record["attribute"]["known"] is False


def test_diagnostics_are_bounded_and_leak_no_paths_or_secrets():
    result = relate(
        "I prefer aisle seats for short work trips.",
        "I now prefer window seats for short work trips.",
    )
    blob = json.dumps(result.to_record())
    assert "/Users/" not in blob
    assert "/home/" not in blob
    for secret in ("api_key", "token", "password", "secret"):
        assert secret not in blob.lower()
    assert len(result.rationale) <= 4


def test_relation_values_are_stable_strings():
    assert IdentityRelation.CURRENT_STATE_CONFLICT == "current_state_conflict"
    assert IdentityRelation.SEMANTIC_DUPLICATE == "semantic_duplicate"
    assert IdentityRelation.SCOPED_COEXISTENCE == "scoped_coexistence"


# --- 21.12 Corpus evaluation --------------------------------------------------


def test_corpus_manifest_remains_unchanged_by_evaluation():
    before = tv.file_digest(tv.MANIFEST_PATH)
    evaluate_corpus()
    assert tv.file_digest(tv.MANIFEST_PATH) == before
    assert tv.verify_manifest() is True


def test_applicability_rule_is_deterministic_and_selective():
    corpus = tv.load_corpus()
    scored = [r for r in corpus["historical_scored"] if is_applicable(r)]
    fixtures = [r for r in corpus["development_fixtures"] if is_applicable(r)]
    assert len(scored) == 10
    assert len(fixtures) == 22
    # Forget/question/unsupported records are not forced into identity.
    assert all(
        r["expected_transition"]["primary_type"] != "forget_existing"
        for r in scored + fixtures
    )


def test_unresolved_and_excluded_records_are_never_scored():
    data = evaluate_corpus()
    assert data["excluded_records"] == 11
    scored_ids = set()
    for partition in ("historical_scored", "development_only"):
        scored_ids |= {r.case_id for r in data[partition]["results"]}
    for record in tv.load_corpus()["unresolved_candidates"]:
        assert record["case_id"] not in scored_ids


def test_historical_and_development_results_are_reported_separately():
    data = evaluate_corpus()
    assert data["historical_scored"]["applicable"] == 10
    assert data["development_only"]["applicable"] == 22
    assert all(
        r.partition == "historical_scored"
        for r in data["historical_scored"]["results"]
    )
    assert all(
        r.partition == "development_only"
        for r in data["development_only"]["results"]
    )


def test_evaluation_is_deterministically_repeatable():
    assert relation_signature() == relation_signature()


# --- Acceptance expectations (§20) --------------------------------------------


def test_zero_tolerance_safety_expectations_hold():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        safety = data[partition]["safety"]
        assert safety["false_duplicate"] == 0, partition
        assert safety["false_update_conflict"] == 0, partition
        assert safety["false_scoped_coexistence"] == 0, partition
        assert safety["unsafe_confident_classifications"] == 0, partition


def test_measured_relation_accuracy_matches_the_reported_result():
    data = evaluate_corpus()
    assert data["historical_scored"]["relation_accuracy"] == {
        "correct": 10,
        "total": 10,
    }
    assert data["development_only"]["relation_accuracy"] == {
        "correct": 22,
        "total": 22,
    }


@pytest.mark.parametrize(
    "partition,relation,expected",
    [
        ("historical_scored", IdentityRelation.EXACT_DUPLICATE, 1),
        ("historical_scored", IdentityRelation.SEMANTIC_DUPLICATE, 1),
        ("historical_scored", IdentityRelation.SCOPED_COEXISTENCE, 1),
        ("historical_scored", IdentityRelation.CURRENT_STATE_CONFLICT, 7),
        ("development_only", IdentityRelation.SCOPED_COEXISTENCE, 2),
        ("development_only", IdentityRelation.TEMPORARY_EXCEPTION, 1),
        ("development_only", IdentityRelation.HISTORICAL, 2),
        ("development_only", IdentityRelation.UNRELATED, 1),
        ("development_only", IdentityRelation.AMBIGUOUS, 2),
    ],
)
def test_each_required_relation_is_fully_classified(partition, relation, expected):
    data = evaluate_corpus()
    counts = data[partition]["by_relation"][relation]
    assert counts == {"correct": expected, "total": expected}


def test_latency_stays_within_the_contract_budget():
    data = evaluate_corpus()
    for partition in ("historical_scored", "development_only"):
        latency = data[partition]["latency"]
        # Contract gate 15: <= 5 ms mean added per interaction.
        assert latency["p95_ms"] < 5.0, partition
