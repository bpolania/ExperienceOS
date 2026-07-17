"""Frozen scoring criteria: method assignment and deterministic scoring.

Criteria come only from the frozen scenario oracle — response
inclusion/exclusion constraints and the active/superseded/forgotten
memory refs — never from a system's output. Method assignment is fixed
before any answer is inspected:

- deterministic: the case defines response inclusion/exclusion criteria
  and is not an abstention case.
- blinded_judge: an abstention case, or a case whose final answer has no
  deterministic response criteria (statement/acknowledgment and
  lifecycle cases). The judge receives oracle-derived value criteria plus
  the conversation evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from experiments.competitive_viability.scoring import (
    METHOD_DETERMINISTIC,
    METHOD_JUDGE,
)

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Casefold and whitespace-collapse; substring matching basis."""
    return _WS.sub(" ", (text or "").casefold()).strip()


def present(token: str, normalized_answer: str) -> bool:
    return normalize(token) in normalized_answer


@dataclass(frozen=True)
class CaseCriteria:
    """Frozen answer criteria for one case, derived from the oracle."""

    case_id: str
    method: str
    must_include_all: tuple
    must_include_any: tuple
    must_exclude: tuple
    expect_abstention: bool
    current_values: tuple   # active memory match terms
    stale_values: tuple     # superseded memory match terms
    forgotten_values: tuple  # forgotten memory match terms
    is_preference: bool


def _terms(refs) -> tuple:
    out = []
    for ref in refs:
        out.extend(ref.match_terms)
    return tuple(dict.fromkeys(out))  # de-dup, order-preserving


def build_case_criteria(case) -> CaseCriteria:
    response = case.expected.response
    ia = tuple(response.must_include_all) if response else ()
    iany = tuple(response.must_include_any) if response else ()
    ex = tuple(response.must_exclude) if response else ()
    abstain = bool(response.expect_abstention) if response else False
    has_response_criteria = bool(ia or iany or ex)
    method = (
        METHOD_JUDGE
        if abstain or not has_response_criteria
        else METHOD_DETERMINISTIC
    )
    is_preference = case.category in ("update", "creation", "context") and any(
        t in case.tags for t in ("preference", "instruction", "scope")
    )
    return CaseCriteria(
        case_id=case.scenario_id,
        method=method,
        must_include_all=ia,
        must_include_any=iany,
        must_exclude=ex,
        expect_abstention=abstain,
        current_values=_terms(case.expected.active),
        stale_values=_terms(case.expected.superseded),
        forgotten_values=_terms(case.expected.forgotten),
        is_preference=is_preference,
    )


def deterministic_verdict(criteria: CaseCriteria, answer: str) -> tuple:
    """Score one answer deterministically from response constraints.

    Returns (verdict_dict, applicability_mask, reason_codes). Fields that
    do not apply to this case are ``None`` (and masked out of denominators
    later). A forbidden (must_exclude) value present counts as both stale
    use and an unsupported claim.
    """
    body = normalize(answer)
    include_all_ok = all(present(t, body) for t in criteria.must_include_all)
    include_any_ok = (
        True if not criteria.must_include_any
        else any(present(t, body) for t in criteria.must_include_any)
    )
    forbidden_present = [t for t in criteria.must_exclude if present(t, body)]

    correct = include_all_ok and include_any_ok and not forbidden_present

    reasons = []
    verdict = {}
    mask = {}

    # correct always applies.
    verdict["correct"] = correct
    mask["correct"] = True
    reasons.append("EXPECTED_VALUE_PRESENT" if (include_all_ok and include_any_ok)
                   else "EXPECTED_VALUE_MISSING")

    # current information: applies when the case expects a current value.
    if criteria.must_include_all or criteria.must_include_any:
        uses_current = include_all_ok and include_any_ok
        verdict["uses_current_information"] = uses_current
        mask["uses_current_information"] = True
        reasons.append("CURRENT_VALUE_USED" if uses_current
                       else "EXPECTED_VALUE_MISSING")
    else:
        verdict["uses_current_information"] = None
        mask["uses_current_information"] = False

    # stale information: applies when the case forbids a stale value.
    if criteria.must_exclude:
        uses_stale = bool(forbidden_present)
        verdict["uses_stale_information"] = uses_stale
        mask["uses_stale_information"] = True
        reasons.append("STALE_VALUE_USED" if uses_stale else "SUPPORTED_CLAIM")
    else:
        verdict["uses_stale_information"] = None
        mask["uses_stale_information"] = False

    # preference adherence: applies for preference/instruction cases with a
    # positive expected value.
    if criteria.is_preference and (
        criteria.must_include_all or criteria.must_include_any
    ):
        follows = include_all_ok and include_any_ok
        verdict["follows_user_preferences"] = follows
        mask["follows_user_preferences"] = True
        reasons.append("PREFERENCE_FOLLOWED" if follows
                       else "PREFERENCE_VIOLATED")
    else:
        verdict["follows_user_preferences"] = None
        mask["follows_user_preferences"] = False

    # unsupported claim: a forbidden value surfaced is an unsupported claim;
    # otherwise none is deterministically detectable from these criteria.
    verdict["unsupported_claim"] = bool(forbidden_present)
    mask["unsupported_claim"] = True
    reasons.append("UNSUPPORTED_CLAIM" if forbidden_present else "SUPPORTED_CLAIM")

    # abstention never applies to a deterministic (non-abstention) case.
    verdict["abstention_correct"] = None
    mask["abstention_correct"] = False

    return verdict, mask, reasons
