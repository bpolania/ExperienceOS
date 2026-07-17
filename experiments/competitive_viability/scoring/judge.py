"""Blinded Qwen judge for cases without deterministic answer criteria.

The judge sees only an opaque candidate id, the case question, the
conversation evidence, oracle-derived value criteria, and the candidate
answer — never a system id, family, or memory architecture. It returns a
strict structured verdict; malformed output triggers one bounded retry
and then an explicit judge-failure status. The judge never rewrites the
answer and never ranks answers against each other.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from experiments.competitive_viability.scoring import (
    JUDGE_PROMPT_VERSION,
    REASON_CODES,
    VERDICT_FIELDS,
)

MAX_JUDGE_RETRIES = 1

JUDGE_STATUS_OK = "ok"
JUDGE_STATUS_MALFORMED = "malformed"
JUDGE_STATUS_ERROR = "provider_error"

_ALLOWED_KEYS = frozenset(set(VERDICT_FIELDS) | {"reason_codes"})

_SYSTEM_PROMPT = (
    "You evaluate a single assistant answer for correctness and "
    "grounding. Judge only the answer against the supplied conversation "
    "evidence and criteria. Ignore writing style unless it makes the "
    "answer wrong. Do not rewrite the answer. Never mention or guess "
    "which system produced it.\n"
    "\n"
    "Reply with ONE JSON object and nothing else — no prose, no markdown.\n"
    "Keys (exact): correct, uses_current_information, "
    "uses_stale_information, follows_user_preferences, unsupported_claim, "
    "abstention_correct, reason_codes.\n"
    "Each verdict field is true, false, or null. Use null only when the "
    "field genuinely does not apply to this case (e.g. no preference is "
    "involved, or abstention is not required). Do not use null to avoid a "
    "judgment.\n"
    "\n"
    "Definitions:\n"
    "- correct: the answer is responsive and consistent with the "
    "conversation evidence and criteria.\n"
    "- uses_current_information: the answer reflects the current value(s) "
    "when the case has one; null if none applies.\n"
    "- uses_stale_information: the answer surfaces a superseded value; "
    "null if none could apply.\n"
    "- follows_user_preferences: the answer respects an applicable stated "
    "preference/instruction; null if none applies.\n"
    "- unsupported_claim: the answer asserts a specific fact not supported "
    "by the evidence.\n"
    "- abstention_correct: for insufficient-evidence cases, true if the "
    "answer appropriately declines/says it lacks the information; null if "
    "abstention is not required.\n"
    "- reason_codes: a short list from the allowed set only.\n"
    f"Allowed reason_codes: {sorted(REASON_CODES)}.\n"
)


@dataclass(frozen=True)
class JudgeCriteria:
    current_values: tuple
    stale_values: tuple
    forgotten_values: tuple
    expect_abstention: bool


def build_judge_request(
    candidate_id: str,
    question: str,
    evidence_messages,
    criteria: JudgeCriteria,
    answer: str,
) -> list:
    """The judge-visible message list. Carries no system identity."""
    evidence = "\n".join(f"- {m}" for m in evidence_messages) or "- (none)"
    user = (
        f"candidate_id: {candidate_id}\n"
        f"Conversation evidence (user turns, in order):\n{evidence}\n\n"
        f"Current request/question: {question}\n\n"
        "Criteria derived from the case oracle:\n"
        f"- current values (should be reflected if a value is expected): "
        f"{list(criteria.current_values)}\n"
        f"- stale/superseded values (must not be surfaced as current): "
        f"{list(criteria.stale_values)}\n"
        f"- forgotten values (must not be surfaced): "
        f"{list(criteria.forgotten_values)}\n"
        f"- abstention required: {criteria.expect_abstention}\n\n"
        f"Candidate answer to evaluate:\n{answer}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def judge_input_hash(messages) -> str:
    return hashlib.sha256(
        json.dumps(messages, sort_keys=True).encode("utf-8")
    ).hexdigest()


def request_mentions_system(messages, system_labels) -> bool:
    """True if any known system label leaks into the judge request."""
    blob = json.dumps(messages).lower()
    return any(label.lower() in blob for label in system_labels)


def parse_judge_output(raw) -> tuple:
    """Strictly parse a judge verdict. Returns (verdict, reason_codes,
    error). error is None on success."""
    if not isinstance(raw, str):
        return None, None, "non_string"
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None, None, "malformed_json"
    if not isinstance(data, dict):
        return None, None, "not_object"
    if set(data.keys()) - _ALLOWED_KEYS:
        return None, None, "unexpected_keys"
    verdict = {}
    for field in VERDICT_FIELDS:
        value = data.get(field, None)
        if value not in (True, False, None):
            return None, None, f"bad_field:{field}"
        verdict[field] = value
    codes = data.get("reason_codes", [])
    if not isinstance(codes, list) or any(c not in REASON_CODES for c in codes):
        return None, None, "bad_reason_codes"
    return verdict, list(codes), None


class BlindedJudge:
    """One judge configuration over the injected provider."""

    prompt_version = JUDGE_PROMPT_VERSION

    def __init__(self, provider, *, max_retries: int = MAX_JUDGE_RETRIES):
        self._provider = provider
        self._max_retries = max_retries

    def judge(self, messages) -> dict:
        """Return {status, verdict, reason_codes, retries, error}."""
        attempts = 0
        last_error = None
        while attempts <= self._max_retries:
            try:
                raw = self._provider.complete(messages)
            except Exception as exc:  # noqa: BLE001 — contained
                return {
                    "status": JUDGE_STATUS_ERROR, "verdict": None,
                    "reason_codes": None, "retries": attempts,
                    "error": type(exc).__name__,
                }
            verdict, codes, error = parse_judge_output(raw)
            if error is None:
                return {
                    "status": JUDGE_STATUS_OK, "verdict": verdict,
                    "reason_codes": codes, "retries": attempts, "error": None,
                }
            last_error = error
            attempts += 1
        return {
            "status": JUDGE_STATUS_MALFORMED, "verdict": None,
            "reason_codes": None, "retries": attempts - 1, "error": last_error,
        }


def assign_candidate_ids(record_keys, seed: int) -> list:
    """Map each (system, case) key to an opaque candidate id and a
    reproducible shuffled order. Returns a list of dicts with
    candidate_id, and the ordered sequence; the mapping is kept by the
    caller, never in the judge payload."""
    rng = random.Random(seed)
    order = list(record_keys)
    rng.shuffle(order)
    assignments = []
    for index, key in enumerate(order):
        opaque = hashlib.sha256(
            f"{seed}:{index}:{key}".encode("utf-8")
        ).hexdigest()[:16]
        assignments.append({"candidate_id": f"cand-{opaque}", "key": key})
    return assignments
