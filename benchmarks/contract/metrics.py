"""Metric definition registry: every metric locks its denominator now.

Each metric is a named numerator/denominator pair. The registry is
committed before any benchmark result exists, so definitions cannot
drift after results are observed. Aggregates are always reported as
raw numerator and denominator counts alongside the ratio — no opaque
composite scores.

Zero-denominator convention (uniform across the suite): the metric is
``None`` ("undefined"), the case is excluded from that metric's
aggregate, and the exclusion count is reported. 0/0 is never 1.0 and
never 0.0.

Percentiles use the deterministic nearest-rank convention:
``sorted(samples)[ceil(q/100 * n) - 1]``. Percentiles computed from
fewer than MIN_PERCENTILE_SAMPLES samples must carry a small-sample
warning in the report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ZERO_DENOMINATOR_UNDEFINED = "undefined"

MIN_PERCENTILE_SAMPLES = 20


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    group: str
    numerator: str
    denominator: str
    description: str
    zero_denominator: str = ZERO_DENOMINATOR_UNDEFINED

    def to_payload(self) -> dict:
        return {
            "name": self.name,
            "group": self.group,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "description": self.description,
            "zero_denominator": self.zero_denominator,
        }


def _m(name, group, numerator, denominator, description) -> MetricDefinition:
    return MetricDefinition(
        name=name,
        group=group,
        numerator=numerator,
        denominator=denominator,
        description=description,
    )


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    # --- Memory-write quality ---------------------------------------
    _m(
        "memory_creation_precision", "memory_write",
        "applied creations matching an expected creation",
        "applied creations",
        "Of the memories the system actually created, how many were "
        "expected. Rejected duplicate proposals are not applied "
        "creations and do not lower precision; they are counted by "
        "duplicate_proposal_rate.",
    ),
    _m(
        "memory_creation_recall", "memory_write",
        "expected creations matched by an applied creation",
        "expected creations",
        "Of the creations the oracle expected, how many the system "
        "actually applied.",
    ),
    _m(
        "memory_creation_f1", "memory_write",
        "2 * precision * recall",
        "precision + recall",
        "Harmonic mean of creation precision and recall; undefined "
        "when both are undefined or sum to zero.",
    ),
    _m(
        "correct_memory_kind_rate", "memory_write",
        "applied creations with the expected kind",
        "applied creations matching an expected creation",
        "Kind correctness among matched creations only.",
    ),
    _m(
        "duplicate_proposal_rate", "memory_write",
        "proposals duplicating an active memory",
        "proposals",
        "Policy-level duplication pressure, counted per proposal.",
    ),
    _m(
        "duplicate_acceptance_rate", "memory_write",
        "applied creations duplicating a previously active memory",
        "proposals duplicating an active memory",
        "Containment failure: duplicates that reached the store.",
    ),
    _m(
        "non_durable_rejection_rate", "memory_write",
        "non-durable statements with no applied memory action",
        "non-durable statements",
        "Correct abstention from remembering chit-chat.",
    ),
    # --- Update and correction quality ------------------------------
    _m(
        "update_detection_accuracy", "update",
        "expected updates where any update action was proposed",
        "expected updates",
        "Did the system notice that a durable value changed.",
    ),
    _m(
        "correct_update_target_rate", "update",
        "update actions targeting the expected memory",
        "applied update actions",
        "Target correctness among applied updates.",
    ),
    _m(
        "supersession_accuracy", "update",
        "expected updates where the old memory left active status "
        "and a replacement became active",
        "expected updates",
        "Full supersession outcome, judged on final state.",
    ),
    _m(
        "new_value_accuracy", "update",
        "applied replacements satisfying the expected value constraints",
        "applied replacements",
        "Value correctness of the replacement memory.",
    ),
    _m(
        "old_value_deactivation_rate", "update",
        "expected-superseded memories not active in final state",
        "expected-superseded memories",
        "The old value must not remain active.",
    ),
    _m(
        "conflicting_active_memory_rate", "update",
        "cases with two active memories asserting conflicting values",
        "executed update cases",
        "Lower is better; measures contradictory final state.",
    ),
    # --- Lifecycle leakage (defined at four levels) -----------------
    _m(
        "stale_candidate_leakage_rate", "leakage",
        "inactive (superseded/forgotten) memories appearing as "
        "retrieval candidates",
        "retrieval candidate slots across executed cases",
        "Leakage level 1: candidates.",
    ),
    _m(
        "stale_selected_leakage_rate", "leakage",
        "inactive memories appearing in the selected set",
        "selected memory slots across executed cases",
        "Leakage level 2: selection.",
    ),
    _m(
        "stale_context_leakage_rate", "leakage",
        "cases where inactive memory content entered supplied context",
        "executed cases with at least one inactive memory",
        "Leakage level 3 — the primary lifecycle leakage metric: "
        "context actually supplied to the answer provider.",
    ),
    _m(
        "stale_response_contamination_rate", "leakage",
        "cases whose response asserts a superseded value",
        "executed cases with a superseded value and response "
        "constraints",
        "Leakage level 4: the answer itself.",
    ),
    # --- Forgetting quality ------------------------------------------
    _m(
        "forget_detection_accuracy", "forgetting",
        "expected forgets where a forget action was proposed",
        "expected forgets",
        "Did the system notice the forget request.",
    ),
    _m(
        "correct_forget_target_rate", "forgetting",
        "forget actions targeting the expected memory",
        "applied forget actions",
        "Target correctness among applied forgets.",
    ),
    _m(
        "forgotten_exclusion_rate", "forgetting",
        "post-forget answer turns whose supplied context contains no "
        "forgotten content",
        "post-forget answer turns",
        "Forgotten content stays out of context.",
    ),
    _m(
        "forgotten_response_contamination_rate", "forgetting",
        "cases whose response asserts a forgotten value",
        "executed cases with a forgotten value and response "
        "constraints",
        "Forgotten content contaminating the answer.",
    ),
    _m(
        "memory_resurrection_rate", "forgetting",
        "forgotten memory records returned to active status",
        "forgotten memory records",
        "A forgotten record silently reactivated. A genuinely new "
        "user statement creating a new auditable memory with the same "
        "value is NOT resurrection.",
    ),
    _m(
        "unrelated_preservation_rate", "forgetting",
        "unrelated active memories still active after a forget",
        "unrelated active memories present at forget time",
        "Forgetting must not splash onto unrelated memories.",
    ),
    # --- Retrieval and selection quality ------------------------------
    _m(
        "precision_at_k", "retrieval",
        "relevant memories in the selected set",
        "selected memories (at most K)",
        "Relevance of what was selected.",
    ),
    _m(
        "recall_at_k", "retrieval",
        "relevant memories in the selected set",
        "relevant memories",
        "Coverage of what should have been selected. Cases with zero "
        "relevant memories are undefined here and scored by "
        "correct_abstention_rate instead.",
    ),
    _m(
        "hit_at_k", "retrieval",
        "cases with at least one relevant memory selected",
        "cases with at least one relevant memory",
        "Any-hit rate.",
    ),
    _m(
        "mean_reciprocal_rank", "retrieval",
        "sum of 1/rank of the first relevant candidate per case",
        "cases with at least one relevant memory",
        "Ranking quality; rank ties are broken by the system's own "
        "deterministic order, which is part of the measured behavior.",
    ),
    _m(
        "relevant_selection_rate", "retrieval",
        "relevant candidates that were selected",
        "relevant candidates",
        "Selection captures what retrieval surfaced.",
    ),
    _m(
        "irrelevant_rejection_rate", "retrieval",
        "irrelevant candidates that were skipped",
        "irrelevant candidates",
        "Distractor resistance.",
    ),
    _m(
        "active_utilization_rate", "retrieval",
        "selected memories that are active",
        "selected memories",
        "Selected content should be active experience.",
    ),
    _m(
        "inactive_contamination_rate", "retrieval",
        "selected memories that are inactive",
        "selected memories",
        "Complement of active utilization, reported explicitly.",
    ),
    _m(
        "selection_budget_adherence", "retrieval",
        "cases whose selected count is within the configured budget",
        "executed cases",
        "The budget is a hard promise.",
    ),
    # --- Downstream response quality ----------------------------------
    _m(
        "preference_compliance_rate", "response",
        "cases whose response satisfies all preference constraints",
        "executed cases with preference constraints",
        "Deterministic concept checks on the answer.",
    ),
    _m(
        "instruction_compliance_rate", "response",
        "cases whose response satisfies all instruction constraints",
        "executed cases with instruction constraints",
        "Deterministic concept checks on the answer.",
    ),
    _m(
        "current_fact_accuracy", "response",
        "cases whose response asserts the current fact value",
        "executed cases with a current-fact constraint",
        "The answer reflects the newest value.",
    ),
    _m(
        "correct_abstention_rate", "response",
        "cases with expected abstention whose response abstains",
        "executed cases with expected abstention",
        "Not inventing experience that does not exist.",
    ),
    _m(
        "multi_session_accuracy", "response",
        "multi-session cases whose response satisfies all constraints",
        "executed multi-session cases",
        "Cross-session experience actually helped.",
    ),
    _m(
        "experience_use_rate", "response",
        "cases whose response uses at least one supplied memory concept",
        "executed cases with at least one selected memory",
        "Supplied experience visibly shaped the answer.",
    ),
    # --- Context efficiency -------------------------------------------
    _m(
        "context_budget_utilization", "context",
        "selected memory count",
        "configured selection budget",
        "How much of the budget was used.",
    ),
    _m(
        "memory_token_share", "context",
        "memory-context tokens",
        "total context tokens",
        "Share of context spent on experience.",
    ),
    _m(
        "relevant_token_share", "context",
        "tokens of relevant selected memories",
        "tokens of all selected memories",
        "Relevance density of supplied memory tokens.",
    ),
    _m(
        "compression_ratio", "context",
        "compressed memory-context characters",
        "uncompressed memory-context characters",
        "Only defined when compression ran.",
    ),
    _m(
        "answers_per_1k_memory_tokens", "context",
        "correct answers * 1000",
        "memory-context tokens supplied across executed cases",
        "Experience efficiency. Zero-memory systems (stateless) have "
        "a zero denominator: reported as undefined, never infinity.",
    ),
    _m(
        "token_reduction_vs_full_history", "context",
        "full-history context tokens minus system context tokens",
        "full-history context tokens",
        "Savings against the full-history baseline under the same "
        "accounting method.",
    ),
    # --- Operational ---------------------------------------------------
    _m(
        "fallback_rate", "operational",
        "turns where whole-batch fallback fired",
        "policy-planned turns",
        "Typed fallback frequency.",
    ),
    _m(
        "rejection_containment_rate", "operational",
        "invalid or duplicate proposals contained by validation",
        "invalid or duplicate proposals",
        "Engine containment success. 1.0 means nothing invalid "
        "reached the store.",
    ),
    # --- Local-model policy ---------------------------------------------
    _m(
        "local_valid_proposal_rate", "local_policy",
        "schema-valid local proposals",
        "local model invocations",
        "Structured-output reliability.",
    ),
    _m(
        "local_correct_action_type_rate", "local_policy",
        "local proposals with the expected action type",
        "expected-action turns run with the local policy",
        "Proposal correctness, before validation.",
    ),
    _m(
        "local_correct_target_rate", "local_policy",
        "local supersede/forget proposals targeting the expected memory",
        "local supersede/forget proposals",
        "ID-channel accuracy.",
    ),
    _m(
        "local_applied_action_accuracy", "local_policy",
        "turns whose applied actions match the oracle",
        "expected-action turns run with the local policy",
        "Post-containment correctness (fallback results included, "
        "labeled by decision source).",
    ),
    _m(
        "local_state_corruption_rate", "local_policy",
        "cases whose final state violates a lifecycle invariant",
        "executed local-policy cases",
        "Must be 0; a rejected proposal is NOT corruption.",
    ),
    _m(
        "local_explicit_wording_accuracy", "local_policy",
        "explicit-wording cases with oracle-matching applied actions",
        "explicit-wording local-policy cases",
        "Accuracy on explicit memory statements.",
    ),
    _m(
        "local_paraphrase_accuracy", "local_policy",
        "paraphrased-wording cases with oracle-matching applied actions",
        "paraphrased-wording local-policy cases",
        "Accuracy on paraphrased statements (known 0.5B weakness; "
        "measured honestly, not hidden).",
    ),
    # --- Phase 9 hybrid extraction (v2-only observational counters
    # --- from extraction diagnostics; Phase 8 metric formulas above
    # --- are unchanged) ----------------------------------------------
    _m(
        "durability_gate_pass_rate_v2", "extraction_v2",
        "gated unmatched sentences passing the durability gate",
        "gated unmatched sentences",
        "How often unmatched conversational content looked durable.",
    ),
    _m(
        "auxiliary_extractor_invocation_rate_v2", "extraction_v2",
        "auxiliary extractor invocations",
        "user turns processed",
        "Auxiliary extraction stays off turns deterministic rules "
        "already handle; low invocation on handled turns is the goal.",
    ),
    _m(
        "candidate_acceptance_rate_v2", "extraction_v2",
        "candidates accepted after validation and deduplication",
        "candidates proposed",
        "Share of proposed candidates that became create actions.",
    ),
    _m(
        "candidate_grounding_rejection_rate_v2", "extraction_v2",
        "candidates rejected by grounding validation",
        "candidates proposed",
        "Ungrounded proposals stopped before lifecycle planning.",
    ),
    _m(
        "candidate_schema_rejection_rate_v2", "extraction_v2",
        "candidates rejected by schema validation",
        "candidates proposed",
        "Structurally invalid proposals stopped before lifecycle "
        "planning.",
    ),
    _m(
        "duplicate_candidate_rate_v2", "extraction_v2",
        "candidates dropped as duplicates of active or batch memories",
        "candidates proposed",
        "Duplicate containment at the extraction layer.",
    ),
    _m(
        "extraction_failure_safe_rate_v2", "extraction_v2",
        "extractor invocations that failed safely with no candidates",
        "auxiliary extractor invocations",
        "Failures must produce no auxiliary memory, never fabricated "
        "fallback content.",
    ),
    _m(
        "accepted_candidates_per_invocation_v2", "extraction_v2",
        "candidates accepted after validation and deduplication",
        "auxiliary extractor invocations",
        "Yield of the auxiliary extraction stage.",
    ),
    # --- Phase 9 hybrid retrieval (v2-only observational counters
    # --- from retrieval diagnostics; Phase 8 metric formulas above
    # --- are unchanged) ----------------------------------------------
    _m(
        "retrieval_candidate_rate_v2", "retrieval_v2",
        "active memories with nonzero retrieval signal",
        "active memories considered",
        "Breadth of lexical+structured candidate generation.",
    ),
    _m(
        "zero_relevance_exclusion_v2", "retrieval_v2",
        "active memories excluded as zero relevance",
        "active memories considered",
        "Zero-signal memories are never selected to fill K.",
    ),
    _m(
        "inactive_candidate_filter_rate_v2", "retrieval_v2",
        "inactive records filtered before ranking",
        "records passed to retrieval",
        "Lifecycle filtering happens before final ranking.",
    ),
    _m(
        "retrieval_k_compliance_v2", "retrieval_v2",
        "retrievals whose selected count respects K",
        "retrievals",
        "No hidden K increase.",
    ),
    _m(
        "retrieval_budget_compliance_v2", "retrieval_v2",
        "retrievals within the configured token budget",
        "retrievals",
        "No token-budget overflow.",
    ),
    _m(
        "unresolved_conflict_selection_rate_v2", "retrieval_v2",
        "retrievals whose selection contains an unresolved active "
        "conflict",
        "retrievals",
        "Conflict pressure is reported, never silently resolved.",
    ),
    # --- Phase 9 coverage selection (v2-only observational counters
    # --- from selection diagnostics; Phase 8 metric formulas above
    # --- are unchanged) ----------------------------------------------
    _m(
        "query_facet_coverage_v2", "coverage_v2",
        "query facets covered by selected memories",
        "query facets extracted",
        "How much of what the query asked for reached the context.",
    ),
    _m(
        "redundant_selection_rate_v2", "coverage_v2",
        "selected memories carrying a redundancy penalty",
        "selected memories",
        "Redundant paraphrases admitted despite the penalty.",
    ),
    _m(
        "positive_utility_selection_rate_v2", "coverage_v2",
        "selected memories with positive coverage utility",
        "selected memories",
        "Selection stops instead of padding; must be complete.",
    ),
    _m(
        "coverage_stop_rate_v2", "coverage_v2",
        "selections stopped before K for lack of positive utility",
        "selections",
        "No zero-value padding: unused K is allowed and counted.",
    ),
    _m(
        "distinct_source_session_rate_v2", "coverage_v2",
        "distinct source sessions among selected memories",
        "selected memories",
        "Source diversity as measured outcome, never a quota.",
    ),
    _m(
        "conflict_warning_selection_rate_v2", "coverage_v2",
        "selections carrying an unresolved-conflict warning",
        "selections",
        "Conflicts stay visible through selection, never concealed.",
    ),
    # --- Phase 9 temporal/provenance (v2-only observational counters
    # --- from temporal diagnostics; Phase 8 metric formulas above are
    # --- unchanged) --------------------------------------------------
    _m(
        "temporal_metadata_coverage_v2", "temporal_v2",
        "user-asserted creates carrying temporal metadata",
        "user-asserted creates",
        "How much accepted experience carries explicit time.",
    ),
    _m(
        "temporal_expression_resolution_v2", "temporal_v2",
        "temporal expressions resolved against a reference date",
        "temporal expressions detected",
        "Unresolved expressions stay unresolved — never fabricated.",
    ),
    _m(
        "historical_query_mode_rate_v2", "temporal_v2",
        "retrievals interpreted as historical, as-of, or timeline",
        "retrievals",
        "Explicit temporal query modes; ambiguity defaults to current.",
    ),
    _m(
        "future_hold_rate_v2", "temporal_v2",
        "active future memories held as not yet valid",
        "retrievals",
        "A future fact is not current before its valid-from time.",
    ),
    _m(
        "assistant_candidate_rejection_v2", "temporal_v2",
        "assistant/tool candidates rejected by eligibility policy",
        "planning turns",
        "Unconfirmed assistant content never becomes user truth.",
    ),
    _m(
        "trusted_ingestion_acceptance_v2", "temporal_v2",
        "tool-verified, jointly-confirmed, or derived memories accepted",
        "planning turns",
        "Explicit-eligibility ingestion, separately labeled.",
    ),
    _m(
        "superseded_historical_admission_v2", "temporal_v2",
        "superseded records admitted under explicit historical modes",
        "retrievals",
        "Historical evidence preserved on request; never as current.",
    ),
    # --- Phase 9 forget/local-policy (v2-only observational counters
    # --- from Prompt 7 diagnostics; Phase 8 formulas unchanged) ------
    _m(
        "forget_intent_detection_v2", "forget_policy_v2",
        "durable forget intents detected",
        "policy decisions",
        "Generalized paraphrased forget-intent detection.",
    ),
    _m(
        "forget_target_resolution_v2", "forget_policy_v2",
        "forget targets resolved above thresholds",
        "durable forget intents detected",
        "Conservative resolution; ambiguity rejects instead of guessing.",
    ),
    _m(
        "forget_ambiguity_containment_v2", "forget_policy_v2",
        "forget intents rejected as unresolved or ambiguous",
        "durable forget intents detected",
        "Containment is correct behavior, not failure.",
    ),
    _m(
        "bulk_forget_containment_v2", "forget_policy_v2",
        "bulk forget requests rejected without mass action",
        "durable forget intents detected",
        "Bulk fuzzy deletion never happens.",
    ),
    _m(
        "local_structural_validity_v2", "forget_policy_v2",
        "local proposals structurally valid after parse/repair/retry",
        "policy decisions",
        "One-action schema validity through the strict parser.",
    ),
    _m(
        "local_fallback_rate_v2", "forget_policy_v2",
        "decisions resolved by per-action deterministic fallback",
        "policy decisions",
        "Lower is better only while containment stays complete.",
    ),
    _m(
        "local_applied_action_rate_v2", "forget_policy_v2",
        "decisions whose applied actions came from the local proposal",
        "policy decisions",
        "Direct local contribution after full validation.",
    ),
    _m(
        "local_retry_success_v2", "forget_policy_v2",
        "bounded retries producing a structurally valid proposal",
        "bounded retries attempted",
        "One retry maximum; success measured honestly.",
    ),
)


_BY_NAME = {m.name: m for m in METRIC_DEFINITIONS}


def metric(name: str) -> MetricDefinition:
    if name not in _BY_NAME:
        raise KeyError(f"unknown metric {name!r}")
    return _BY_NAME[name]


def ratio(numerator: float, denominator: float) -> float | None:
    """The suite-wide ratio convention: zero denominator is None."""
    if denominator == 0:
        return None
    return numerator / denominator


def percentile(samples: list[float], q: float) -> float:
    """Deterministic nearest-rank percentile (q in (0, 100])."""
    if not samples:
        raise ValueError("percentile requires at least one sample")
    if not 0 < q <= 100:
        raise ValueError(f"q must be in (0, 100], got {q!r}")
    ordered = sorted(samples)
    rank = math.ceil(q / 100 * len(ordered))
    return ordered[rank - 1]
