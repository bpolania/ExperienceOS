"""Scripted local-policy runner and declarative containment fixtures.

The scripted runner implements the production ``LocalModelRunner``
protocol, so scripted proposals flow through the REAL
``LocalModelMemoryPolicy`` parsing and the REAL ``ExperienceManager``
validation and fallback path. Nothing here applies actions to
storage; the engine decides everything downstream.

Fixtures are declarative per-turn proposal scripts keyed by scenario
ID. They define ONLY what the "model" proposes — never the expected
final state, never which action the engine should accept, never what
the scenario needs to pass. This is the documented narrow exception
to the oracle firewall: the fixture stands in for external local-model
output, not for expected results.

Target resolution mirrors the real ID channel: ``target_match``
resolves a memory ID from the prompt's ACTIVE MEMORIES block by text
substring (exactly what a real model does when it picks an ID);
``remember_as``/``target_ref`` let a later turn deliberately target a
now-retired ID; ``target_id`` injects a fabricated ID for
nonexistent-target cases.
"""

from __future__ import annotations

import re

from experienceos.policy.local_runner import (
    LocalModelAvailability,
    LocalModelResult,
    LocalModelUnavailable,
)

SCRIPTED_MODEL_NAME = "scripted-local-proposals"

MALFORMED = "malformed"
FALLBACK = "fallback"


def _decision(
    action,
    kind=None,
    text=None,
    target=None,
    replaces=None,
    confidence=0.9,
    explanation="scripted proposal",
):
    return {
        "action": action,
        "kind": kind,
        "text": text,
        "target_memory_id": target,
        "replaces": replaces,
        "confidence": confidence,
        "explanation": explanation,
    }


# Per-scenario, per-turn proposal scripts for the deterministic
# containment cases. Turn order matches scenario turn order (setup
# turns first, current message last).
SCRIPTED_PROPOSALS = {
    # Phase 7 finding: the model re-proposes the active memory on a
    # planning request. Turn 2's duplicate must be engine-rejected.
    "containment_001_duplicate_create_contained": [
        [
            _decision(
                "create",
                kind="preference",
                text="Prefers aisle seats for short work trips.",
                explanation="Durable seating preference.",
                confidence=0.95,
            )
        ],
        [
            _decision(
                "create",
                kind="preference",
                text="Prefers aisle seats for short work trips.",
                explanation="Re-proposing the active seating preference.",
            )
        ],
    ],
    # Supersede targeting the retired tea record. The supersede pair's
    # replacement create duplicates the active coffee memory, so the
    # engine must reject both halves and leave state untouched.
    "containment_002_supersede_inactive_target": [
        [
            _decision(
                "create",
                kind="preference",
                text="Prefers tea in the morning.",
                explanation="Durable drink preference.",
            )
        ],
        [
            _decision(
                "supersede",
                kind="preference",
                text="Prefers coffee in the morning.",
                target={"match": "tea", "remember_as": "tea"},
                explanation="Drink preference changed.",
            )
        ],
        [
            _decision(
                "supersede",
                kind="preference",
                text="Prefers coffee in the morning.",
                target={"ref": "tea"},
                explanation="Targets the retired tea record.",
            )
        ],
    ],
    # Forget aimed at a fabricated ID that never existed.
    "containment_003_forget_nonexistent_target": [
        [
            _decision(
                "create",
                kind="instruction",
                text="Always run the test suite with pytest -q before committing.",
                explanation="Standing development instruction.",
            )
        ],
        [
            _decision(
                "forget",
                kind="instruction",
                target={"id": "nonexistent-memory-0000"},
                explanation="Targets a memory that does not exist.",
            )
        ],
    ],
    # Malformed structured output: the policy must raise and the
    # manager must fall back to rules, which handle the instruction.
    "containment_004_malformed_proposal_fallback": [
        MALFORMED,
    ],
}

_ID_LINE = r"- id: (\S+)\n  kind: \w+\n  text: [^\n]*{term}"


class ScriptedLocalRunner:
    """LocalModelRunner that replays a declarative per-turn script."""

    def __init__(self, turn_scripts):
        self.turn_scripts = list(turn_scripts)
        self.calls = 0
        self.remembered: dict[str, str] = {}

    def availability(self) -> LocalModelAvailability:
        return LocalModelAvailability(
            available=True, model_path=SCRIPTED_MODEL_NAME
        )

    def _resolve_target(self, target, user_prompt: str) -> str:
        if "id" in target:
            return target["id"]
        if "ref" in target:
            return self.remembered[target["ref"]]
        pattern = _ID_LINE.format(term=re.escape(target["match"]))
        match = re.search(pattern, user_prompt)
        resolved = match.group(1) if match else "unresolved-target"
        if "remember_as" in target:
            self.remembered[target["remember_as"]] = resolved
        return resolved

    def generate_structured(self, *, system_prompt, user_prompt, schema):
        index = self.calls
        self.calls += 1
        if index >= len(self.turn_scripts):
            raise LocalModelUnavailable("scripted proposals exhausted")
        script = self.turn_scripts[index]
        if script == FALLBACK:
            raise LocalModelUnavailable("scripted fallback turn")
        if script == MALFORMED:
            return LocalModelResult(
                data={"decisions": "this-is-not-a-list"},
                model_path=SCRIPTED_MODEL_NAME,
                model_name=SCRIPTED_MODEL_NAME,
            )
        decisions = []
        for spec in script:
            decision = dict(spec)
            target = decision.get("target_memory_id")
            if isinstance(target, dict):
                decision["target_memory_id"] = self._resolve_target(
                    target, user_prompt
                )
            decisions.append(decision)
        return LocalModelResult(
            data={"decisions": decisions},
            model_path=SCRIPTED_MODEL_NAME,
            model_name=SCRIPTED_MODEL_NAME,
        )


def scripted_runner_for(scenario_id: str) -> ScriptedLocalRunner | None:
    """The fixture for a scenario, or None. Keyed strictly by scenario
    ID so unrelated scenarios can never consume a fixture."""
    script = SCRIPTED_PROPOSALS.get(scenario_id)
    if script is None:
        return None
    return ScriptedLocalRunner(script)
