"""Four-level leakage evaluators: candidates → selected → rendered
context → response, tracked for stale (superseded) and forgotten
content.

Registry contributions use the fixed Prompt 1 metrics (the four
stale-leakage metrics; forgotten context/response leakage lives in
the forgetting group). Every contribution also carries per-level raw
evidence for BOTH statuses so reports can surface all eight
level/status combinations without redefining metrics.

Inactive records merely existing in storage never count — only
entering the measured stage counts. The primary lifecycle leakage
metric remains the rendered-context level.
"""

from __future__ import annotations

from benchmarks.evaluators.records import contribution


def _hits(refs, text: str) -> list[str]:
    body = text.lower()
    return [
        ref.logical_id
        for ref in refs
        if ref.match_terms
        and all(t.lower() in body for t in ref.match_terms)
    ]


def _levels(refs, turn) -> dict:
    candidates = list(turn.candidates)
    selected = [c for c in candidates if c.selected]
    memory_context = " ".join(turn.context_messages[1:-1])
    return {
        "candidate_hits": sum(
            1 for c in candidates if _hits(refs, c.text)
        ),
        "candidate_total": len(candidates),
        "selected_hits": sum(1 for c in selected if _hits(refs, c.text)),
        "selected_total": len(selected),
        "context_hit_ids": sorted(set(_hits(refs, memory_context))),
        "response_hit_ids": sorted(set(_hits(refs, turn.response or ""))),
    }


def leakage_contributions(case, result):
    out = []
    if not result.turns:
        return out
    turn = result.turns[-1]
    expected = case.expected
    stale = list(expected.superseded)
    forgotten = list(expected.forgotten)
    stale_levels = _levels(stale, turn) if stale else None
    forgotten_levels = _levels(forgotten, turn) if forgotten else None
    evidence = {
        "stale": stale_levels,
        "forgotten": forgotten_levels,
    }

    if stale_levels:
        if stale_levels["candidate_total"]:
            out.append(
                contribution(
                    "stale_candidate_leakage_rate",
                    stale_levels["candidate_hits"],
                    stale_levels["candidate_total"],
                    levels=evidence,
                )
            )
        if stale_levels["selected_total"]:
            out.append(
                contribution(
                    "stale_selected_leakage_rate",
                    stale_levels["selected_hits"],
                    stale_levels["selected_total"],
                )
            )
        out.append(
            contribution(
                "stale_context_leakage_rate",
                1 if stale_levels["context_hit_ids"] else 0,
                1,
                levels=evidence,
            )
        )
        if expected.response is not None and expected.response.must_exclude:
            out.append(
                contribution(
                    "stale_response_contamination_rate",
                    1 if stale_levels["response_hit_ids"] else 0,
                    1,
                )
            )

    if forgotten_levels:
        if expected.response is not None and expected.response.must_exclude:
            out.append(
                contribution(
                    "forgotten_response_contamination_rate",
                    1 if forgotten_levels["response_hit_ids"] else 0,
                    1,
                    levels=evidence,
                )
            )
    return out
