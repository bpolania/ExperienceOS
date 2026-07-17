"""End-to-end final-answer scoring for the competitive viability runs.

Scores the completed execution records from the frozen viability run into
structured per-(case, system) verdicts, using deterministic/rule-based
scoring where the frozen criteria permit and a blinded Qwen judge only
where they do not. Produces answer-quality evidence — never a competitive
profile or go/no-go decision.

Everything here reads the raw execution records read-only and writes new
score records; it never mutates the raw records or the frozen manifest.
"""

EVALUATOR_VERSION = "1"
JUDGE_PROMPT_VERSION = "1"

# Scoring methods.
METHOD_DETERMINISTIC = "deterministic"
METHOD_RULE_BASED = "rule_based"
METHOD_JUDGE = "blinded_judge"

# Verdict field names (the frozen answer-quality dimensions).
VERDICT_FIELDS = (
    "correct",
    "uses_current_information",
    "uses_stale_information",
    "follows_user_preferences",
    "unsupported_claim",
    "abstention_correct",
)

# Bounded reason-code vocabulary (versioned).
REASON_CODES = frozenset({
    "EXPECTED_VALUE_PRESENT",
    "EXPECTED_VALUE_MISSING",
    "CURRENT_VALUE_USED",
    "STALE_VALUE_USED",
    "FORGOTTEN_VALUE_USED",
    "PREFERENCE_FOLLOWED",
    "PREFERENCE_VIOLATED",
    "SUPPORTED_CLAIM",
    "UNSUPPORTED_CLAIM",
    "CORRECT_ABSTENTION",
    "INCORRECT_ABSTENTION",
    "ANSWER_NONRESPONSIVE",
    "INSUFFICIENT_EVIDENCE_TO_JUDGE",
})
