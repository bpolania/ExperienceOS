"""Local model memory policy: bounded prompts in, proposals out.

A proposer only. It builds bounded prompts from PolicyContext, invokes
a LocalModelRunner, structurally validates the returned data, and
converts decisions into MemoryDecisionProposal values stamped
``local_model``. It never touches storage, never emits events, and
never applies fallback — the ExperienceManager owns validation and
fallback, and the ExperienceEngine owns mutations.

Validation boundary: this module checks *structure* (required fields,
JSON types) and raises LocalModelInvalidOutput; the ExperienceManager
checks *semantics* (allowed actions/kinds, confidence bounds, required
text/targets) and its rejections trigger validation_failed fallback.
"""

from __future__ import annotations

from dataclasses import replace

from experienceos.policy.base import (
    DecisionSource,
    MemoryDecisionProposal,
    PolicyAction,
    PolicyContext,
)
from experienceos.policy.local_runner import (
    LocalModelInvalidOutput,
    LocalModelRunner,
)

# Structured-output schema for memory decisions. Kinds and actions
# mirror the policy contract; multiple independent decisions per
# message are expected, and an empty list is a valid "nothing worth
# remembering" outcome.
MEMORY_DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "supersede", "forget", "noop"],
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["preference", "fact", "instruction"],
                    },
                    "text": {"type": ["string", "null"]},
                    "target_memory_id": {"type": ["string", "null"]},
                    "replaces": {"type": ["string", "null"]},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "explanation": {"type": "string"},
                },
                "required": [
                    "action",
                    "kind",
                    "text",
                    "target_memory_id",
                    "replaces",
                    "confidence",
                    "explanation",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}

_DECISION_FIELDS = frozenset(
    {
        "action",
        "kind",
        "text",
        "target_memory_id",
        "replaces",
        "confidence",
        "explanation",
    }
)

_SYSTEM_PROMPT = """\
You manage durable memory for an assistant. Decide which memory actions
the user's message requires.

Actions:
- create: remember new durable experience (preference, fact, or instruction)
- supersede: a listed active memory changed; provide the replacement text
  and set target_memory_id to the memory it replaces (also set replaces)
- forget: the user says a listed active memory no longer matters; set
  target_memory_id
- noop: nothing durable in the message

Rules:
- Only remember durable experience; ignore transient conversational noise.
- Only target ids that appear in the ACTIVE MEMORIES list.
- Preserve unrelated memories; do not invent targets.
- Memory text must be one concise normalized sentence.
- explanation must be one short sentence.
- Return only JSON matching the schema; decisions may be empty.

Example: for "Actually I fly from SJC now" with an active memory
(id: m1, fact: Home airport is SFO.) return one decision:
{"action": "supersede", "kind": "fact", "text": "Home airport is SJC.",
 "target_memory_id": "m1", "replaces": "m1", "confidence": 0.9,
 "explanation": "Home airport changed from SFO to SJC."}
"""


def _format_active_memories(context: PolicyContext) -> str:
    if not context.active_memories:
        return "ACTIVE MEMORIES\n(none)"
    lines = ["ACTIVE MEMORIES"]
    for memory in context.active_memories:
        lines.append(f"- id: {memory.id}")
        lines.append(f"  kind: {memory.kind}")
        lines.append(f"  text: {memory.text}")
    return "\n".join(lines)


class LocalModelMemoryPolicy:
    """Plans memory proposals with a local structured-output model."""

    mode = DecisionSource.LOCAL_MODEL

    def __init__(self, runner: LocalModelRunner):
        self.runner = runner

    def plan(self, context: PolicyContext) -> list[MemoryDecisionProposal]:
        system_prompt, user_prompt = self._build_prompts(context)
        result = self.runner.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=MEMORY_DECISION_SCHEMA,
        )
        return self._to_proposals(result.data)

    @staticmethod
    def _build_prompts(context: PolicyContext) -> tuple[str, str]:
        """Deterministic bounded prompts: message + active candidates only."""
        user_prompt = (
            f"{_format_active_memories(context)}\n\n"
            f"USER MESSAGE\n{context.message}"
        )
        return _SYSTEM_PROMPT, user_prompt

    @staticmethod
    def _to_proposals(data: dict) -> list[MemoryDecisionProposal]:
        decisions = data.get("decisions") if isinstance(data, dict) else None
        if not isinstance(decisions, list):
            raise LocalModelInvalidOutput(
                "Local model output must contain a 'decisions' list."
            )
        proposals: list[MemoryDecisionProposal] = []
        for index, decision in enumerate(decisions):
            proposal = _to_proposal(decision, index)
            proposals.append(proposal)
            if proposal.action == PolicyAction.SUPERSEDE:
                # A local supersede decision carries the *replacement*
                # text; the engine's lifecycle expects the canonical
                # supersede + create pair (as the rule planner emits),
                # so expand it here with lineage preserved.
                proposals.append(
                    replace(
                        proposal,
                        action=PolicyAction.CREATE,
                        target_memory_id=None,
                        replaces=proposal.target_memory_id,
                    )
                )
        return proposals


def _to_proposal(decision: object, index: int) -> MemoryDecisionProposal:
    if not isinstance(decision, dict):
        raise LocalModelInvalidOutput(
            f"Decision {index} must be an object, got {type(decision).__name__}."
        )
    unknown = set(decision) - _DECISION_FIELDS
    if unknown:
        raise LocalModelInvalidOutput(
            f"Decision {index} has unsupported fields: {sorted(unknown)}"
        )
    missing = _DECISION_FIELDS - set(decision)
    if missing:
        raise LocalModelInvalidOutput(
            f"Decision {index} is missing fields: {sorted(missing)}"
        )
    for key in ("action", "kind", "explanation"):
        if not isinstance(decision[key], str):
            raise LocalModelInvalidOutput(
                f"Decision {index} field {key!r} must be a string."
            )
    for key in ("text", "target_memory_id", "replaces"):
        if decision[key] is not None and not isinstance(decision[key], str):
            raise LocalModelInvalidOutput(
                f"Decision {index} field {key!r} must be a string or null."
            )
    confidence = decision["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise LocalModelInvalidOutput(
            f"Decision {index} field 'confidence' must be a number."
        )
    # Semantic checks (allowed values, bounds, required text/targets)
    # belong to ExperienceManager validation.
    return MemoryDecisionProposal(
        action=decision["action"],
        kind=decision["kind"],
        text=decision["text"],
        target_memory_id=decision["target_memory_id"],
        replaces=decision["replaces"],
        confidence=float(confidence),
        explanation=decision["explanation"],
        decision_source=DecisionSource.LOCAL_MODEL,
    )
