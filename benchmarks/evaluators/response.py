"""Deterministic response-constraint evaluation.

Normalization (documented, no hidden thresholds): both response and
constraint phrases are casefolded and whitespace-collapsed; a phrase
matches when it appears as a substring of the normalized response.
``must_include_any`` needs one alternative; ``must_include_all``
needs every phrase; ``must_exclude`` forbids every phrase.

Deferral rules: model-scored cases and abstention expectations are
never scored deterministically offline — they are recorded as
deferred with a reason, excluded from numerators AND denominators,
and counted in the deferred lists.

Metric mapping (benchmark-side, documented): must-include constraints
contribute to current_fact_accuracy on update-category cases,
instruction_compliance_rate on instruction-tagged cases,
multi_session_accuracy on multi_session cases, and
preference_compliance_rate otherwise. Contamination via must_exclude
is scored by the leakage evaluators. experience_use_rate checks
whether any selected memory's distinctive terms surface in the
response.
"""

from __future__ import annotations

import re

from benchmarks.evaluators.records import contribution

_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS.sub(" ", text.casefold()).strip()


def _present(phrase: str, response: str) -> bool:
    return _normalize(phrase) in response


def evaluate_constraints(constraints, response: str) -> list[dict]:
    body = _normalize(response)
    results = []
    for phrase in constraints.must_include_all:
        results.append(
            {
                "constraint": f"must_include_all:{phrase}",
                "passed": _present(phrase, body),
            }
        )
    if constraints.must_include_any:
        results.append(
            {
                "constraint": "must_include_any:"
                + "|".join(constraints.must_include_any),
                "passed": any(
                    _present(p, body) for p in constraints.must_include_any
                ),
            }
        )
    for phrase in constraints.must_exclude:
        results.append(
            {
                "constraint": f"must_exclude:{phrase}",
                "passed": not _present(phrase, body),
            }
        )
    return results


def _inclusion_metric(case) -> str:
    if case.category == "update":
        return "current_fact_accuracy"
    if case.category == "multi_session":
        return "multi_session_accuracy"
    if "instruction" in case.tags or "instruction-priority" in case.tags:
        return "instruction_compliance_rate"
    return "preference_compliance_rate"


def response_contributions(case, result):
    out = []
    constraint_results: list[dict] = []
    deferred: list[str] = []
    if not result.turns:
        return out, constraint_results, deferred
    constraints = case.expected.response
    if constraints is None:
        # Experience-use still applies when memories were selected.
        out.extend(_experience_use(case, result))
        return out, constraint_results, deferred
    if case.evaluation_mode == "model_scored":
        deferred.append(
            "model_scored response evaluation requires a judge; deferred "
            "in deterministic offline mode"
        )
        return out, constraint_results, deferred
    if constraints.expect_abstention:
        deferred.append(
            "abstention verification requires provider-backed evaluation; "
            "deferred in deterministic offline mode"
        )
        # Exclusion constraints remain checkable and are scored by the
        # leakage evaluators; inclusion metrics are not scored here.
        constraint_results = evaluate_constraints(
            constraints, result.turns[-1].response or ""
        )
        return out, constraint_results, deferred

    response = result.turns[-1].response or ""
    constraint_results = evaluate_constraints(constraints, response)
    has_inclusion = bool(
        constraints.must_include_all or constraints.must_include_any
    )
    if has_inclusion:
        inclusion_passed = all(
            r["passed"]
            for r in constraint_results
            if not r["constraint"].startswith("must_exclude")
        )
        out.append(
            contribution(
                _inclusion_metric(case), 1 if inclusion_passed else 0, 1
            )
        )
    out.extend(_experience_use(case, result))
    return out, constraint_results, deferred


def _experience_use(case, result):
    turn = result.turns[-1]
    selected = [c for c in turn.candidates if c.selected]
    if not selected:
        return []
    response = _normalize(turn.response or "")
    used = any(
        any(
            len(word) > 4 and word in response
            for word in _normalize(c.text).split()
        )
        for c in selected
    )
    return [
        contribution("experience_use_rate", 1 if used else 0, 1)
    ]
