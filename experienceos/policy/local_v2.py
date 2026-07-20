"""Local-policy v2: one-action structured proposals, strictly contained.

A narrow single-action proposal schema replaces the
v1 multi-decision array; strict parsing with SYNTAX-ONLY repair and at
most one bounded retry; per-action deterministic fallback that never
broadens the action; and complete raw-to-applied audit evidence.

Models propose. ExperienceOS decides:

- the model may propose remember / update / forget / none;
- it may target only short aliases of the active memories shown in its
  prompt (mapped back to real IDs inside ExperienceOS — invented
  targets are rejected);
- it cannot assign lifecycle state, temporal validity, provenance
  trust, supersession links, or timestamps;
- semantic errors are rejected or fall back deterministically — never
  silently repaired;
- every applied action still flows through ExperienceManager
  validation and ExperienceEngine lifecycle checks, so malformed or
  unsafe output can never mutate state.

No benchmark oracle data is referenced anywhere in this module.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from experienceos.memory.forget import (
    ForgetIntent,
    ForgetOutcome,
    ForgetTargetResolver,
)
from experienceos.memory.planner import (
    CREATE,
    FORGET,
    SUPERSEDE,
    MemoryAction,
    _normalized_text,
)
from experienceos.policy.base import (
    DecisionSource,
    FallbackReason,
    MemoryDecisionProposal,
    PolicyContext,
)
from experienceos.policy.local_runner import LocalModelRunnerError

LOCAL_POLICY_V2_VERSION = "1"
PROPOSAL_SCHEMA_V2_VERSION = "1"
PARSER_V2_VERSION = "1"
MAX_RETRIES = 1

VALID_ACTIONS_V2 = ("remember", "update", "forget", "none")
_VALID_KINDS = ("preference", "fact", "instruction")
_TOP_LEVEL_FIELDS = frozenset(
    {"action", "memory", "target", "evidence", "confidence", "reason"}
)
_MEMORY_FIELDS = frozenset(
    {"kind", "statement", "subject", "attribute", "value", "scope"}
)
_TARGET_FIELDS = frozenset({"memory_id", "description"})
_MAX_STRING = 300

# One action per generation. No lifecycle status, no metadata
# injection, no supersession links, no timestamps, no trust fields.
MEMORY_PROPOSAL_SCHEMA_V2: dict = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(VALID_ACTIONS_V2)},
        "memory": {
            "type": ["object", "null"],
            "properties": {
                "kind": {"type": "string", "enum": list(_VALID_KINDS)},
                "statement": {"type": "string"},
                "subject": {"type": "string"},
                "attribute": {"type": "string"},
                "value": {"type": "string"},
                "scope": {"type": "string"},
            },
            "required": ["kind", "statement"],
            "additionalProperties": False,
        },
        "target": {
            "type": ["object", "null"],
            "properties": {
                "memory_id": {"type": ["string", "null"]},
                "description": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "evidence": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
    "required": ["action", "evidence", "confidence", "reason"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT_V2 = """\
You manage durable memory for an assistant. Return EXACTLY ONE action.

Actions:
- remember: one new durable memory (memory field required)
- update: the current value changed (memory field with the NEW value;
  target with the short id of the OLD active memory when listed)
- forget: the user asked to stop remembering something (target with a
  short id from the ACTIVE MEMORIES list or a description)
- none: nothing durable changed — a valid, expected answer

Rules:
- evidence must QUOTE the supporting span of the user message.
- Only use target ids that appear in the ACTIVE MEMORIES list.
- Never invent ids, dates, sources, or lifecycle states.
- Return none when uncertain.
- Return ONLY one JSON object matching the schema.
"""


class ParseFailure(Exception):
    """Structural parse or schema failure (may trigger one retry)."""


@dataclass
class ProposalAudit:
    """Bounded raw-to-applied evidence for one local decision."""

    source_ref: str = ""
    model_mode: str = "unavailable"
    raw_excerpt: str = ""
    parse_ok: bool = False
    repairs: tuple = ()
    retries: int = 0
    retry_success: bool = False
    action: str | None = None
    structural_valid: bool = False
    semantic_valid: bool = False
    target_valid: bool | None = None
    rejection_reason: str | None = None
    fallback_type: str | None = None
    applied_from_local: bool = False
    elapsed_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_OUTER_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class ProposalParserV2:
    """Exact JSON parsing with bounded SYNTAX-ONLY repair.

    Allowed: extracting one outer object, stripping markdown fences
    and surrounding commentary, removing trailing commas. Forbidden:
    any change to action, targets, evidence, or values — semantic
    repair never happens here.
    """

    version = PARSER_V2_VERSION

    def parse(self, raw) -> tuple[dict, tuple]:
        if isinstance(raw, dict):
            data, repairs = raw, ()
        else:
            text = str(raw)
            repairs = []
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                cleaned = _FENCE.sub("", text).strip()
                if cleaned != text.strip():
                    repairs.append("stripped_markdown_fence")
                match = _OUTER_OBJECT.search(cleaned)
                if match and match.group(0) != cleaned:
                    cleaned = match.group(0)
                    repairs.append("extracted_outer_object")
                without_commas = _TRAILING_COMMA.sub(r"\1", cleaned)
                if without_commas != cleaned:
                    cleaned = without_commas
                    repairs.append("removed_trailing_comma")
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError as exc:
                    raise ParseFailure(f"unparseable JSON: {exc}") from exc
            repairs = tuple(repairs)
        self._validate_structure(data)
        return data, repairs

    @staticmethod
    def _validate_structure(data) -> None:
        if not isinstance(data, dict):
            raise ParseFailure("proposal must be a JSON object")
        unknown = set(data) - _TOP_LEVEL_FIELDS
        if unknown:
            raise ParseFailure(f"unknown fields: {sorted(unknown)}")
        action = data.get("action")
        if action not in VALID_ACTIONS_V2:
            raise ParseFailure(f"invalid action: {action!r}")
        if isinstance(data.get("action"), list):
            raise ParseFailure("multiple actions are not allowed")
        for key in ("evidence", "reason"):
            value = data.get(key)
            if not isinstance(value, str) or len(value) > _MAX_STRING:
                raise ParseFailure(f"{key} must be a bounded string")
        confidence = data.get("confidence")
        if isinstance(confidence, bool) or not isinstance(
            confidence, (int, float)
        ) or not 0.0 <= confidence <= 1.0:
            raise ParseFailure("confidence out of range")
        memory = data.get("memory")
        if memory is not None:
            if not isinstance(memory, dict):
                raise ParseFailure("memory must be an object")
            if set(memory) - _MEMORY_FIELDS:
                raise ParseFailure("memory has unknown fields")
            if memory.get("kind") not in _VALID_KINDS:
                raise ParseFailure(
                    f"invalid memory kind: {memory.get('kind')!r}"
                )
            statement = memory.get("statement")
            if not isinstance(statement, str) or not statement.strip() \
                    or len(statement) > _MAX_STRING:
                raise ParseFailure("memory.statement must be bounded text")
        target = data.get("target")
        if target is not None:
            if not isinstance(target, dict) or set(target) - _TARGET_FIELDS:
                raise ParseFailure("target has unknown fields")
        if action == "remember" and memory is None:
            raise ParseFailure("remember requires a memory object")
        if action in ("update",) and memory is None:
            raise ParseFailure("update requires a memory object")
        if action == "forget" and target is None:
            raise ParseFailure("forget requires a target")


class LocalPolicyV2:
    """One-action local proposals over a deterministic safety baseline.

    The deterministic planner's plan is ALWAYS computed (it is the
    fallback and the duplicate reference). A valid local proposal is
    validated (structure → grounding → semantics → target) and merged;
    an invalid one falls back per action type — a malformed forget can
    only fall back to deterministic FORGET actions, never to creates.
    """

    mode = DecisionSource.LOCAL_MODEL
    version = LOCAL_POLICY_V2_VERSION
    schema_version = PROPOSAL_SCHEMA_V2_VERSION

    def __init__(self, runner, deterministic_planner,
                 forget_resolver: ForgetTargetResolver | None = None,
                 max_retries: int = MAX_RETRIES):
        self.runner = runner
        self.planner = deterministic_planner
        self.forget_resolver = forget_resolver or ForgetTargetResolver()
        self.parser = ProposalParserV2()
        self.max_retries = max_retries
        self._turn = 0
        self.audits: list[ProposalAudit] = []  # bounded (last 200)
        self.counters = {
            "decisions": 0,
            "structural_valid": 0,
            "structural_invalid": 0,
            "repaired": 0,
            "retries": 0,
            "retry_success": 0,
            "semantic_rejections": 0,
            "target_rejections": 0,
            "local_accepted": 0,
            "local_duplicates_of_deterministic": 0,
            "fallback_remember": 0,
            "fallback_update": 0,
            "fallback_forget": 0,
            "fallback_none": 0,
            "fallback_unclassified": 0,
            "none_actions": 0,
        }

    def summary(self) -> dict:
        fallbacks = sum(
            v for k, v in self.counters.items() if k.startswith("fallback_")
        )
        return {
            **self.counters,
            "fallbacks_total": fallbacks,
            "local_policy_version": self.version,
            "proposal_schema_version": self.schema_version,
            "parser_version": self.parser.version,
            "max_retries": self.max_retries,
            "fallback_strategy": "per_action_deterministic",
            "forget_resolver_version": self.forget_resolver.version,
        }

    # -- planning ----------------------------------------------------------------

    def plan(self, context: PolicyContext) -> list[MemoryDecisionProposal]:
        self._turn += 1
        self.counters["decisions"] += 1
        audit = ProposalAudit(
            source_ref=f"{context.session_id}:{self._turn}"
        )
        deterministic = self.planner.plan_memory_actions(
            context.user_id, context.session_id, context.message,
            existing=context.active_memories,
        )
        alias_map = {
            f"m{i}": memory.id
            for i, memory in enumerate(context.active_memories, start=1)
        }

        proposal = self._generate(context, alias_map, audit, deterministic)
        actions: list[MemoryAction]
        if proposal is None:
            actions = self._fallback(None, deterministic, audit)
        else:
            actions = self._apply_proposal(
                proposal, context, alias_map, deterministic, audit
            )
        if len(self.audits) < 200:
            self.audits.append(audit)
        return [self._to_proposal(a, audit) for a in actions]

    # -- generation with one bounded retry ---------------------------------------------

    def _generate(self, context, alias_map, audit, deterministic):
        del deterministic  # real generation never sees the baseline
        prompt = self._prompt(context, alias_map)
        for attempt in range(1 + self.max_retries):
            try:
                result = self.runner.generate_structured(
                    system_prompt=_SYSTEM_PROMPT_V2 + (
                        "" if attempt == 0 else
                        "\nYour previous output was structurally invalid. "
                        "Return ONLY one valid JSON object for the schema."
                    ),
                    user_prompt=prompt,
                    schema=MEMORY_PROPOSAL_SCHEMA_V2,
                )
            except LocalModelRunnerError as exc:
                audit.model_mode = "unavailable"
                audit.rejection_reason = f"{exc.reason}"
                return None
            audit.model_mode = "generated"
            audit.elapsed_ms = result.elapsed_ms
            audit.prompt_tokens = result.prompt_tokens
            audit.completion_tokens = result.completion_tokens
            raw = result.data
            audit.raw_excerpt = str(raw)[:200]
            try:
                data, repairs = self.parser.parse(raw)
            except ParseFailure as exc:
                audit.rejection_reason = str(exc)[:120]
                self.counters["structural_invalid"] += 1
                if attempt < self.max_retries:
                    self.counters["retries"] += 1
                    audit.retries += 1
                    continue
                return None
            if repairs:
                audit.repairs = repairs
                self.counters["repaired"] += 1
            if attempt > 0:
                self.counters["retry_success"] += 1
                audit.retry_success = True
            audit.parse_ok = True
            audit.structural_valid = True
            audit.action = data["action"]
            self.counters["structural_valid"] += 1
            return data
        return None

    @staticmethod
    def _prompt(context, alias_map) -> str:
        lines = ["ACTIVE MEMORIES"]
        if not alias_map:
            lines.append("(none)")
        for alias, memory_id in alias_map.items():
            memory = next(
                m for m in context.active_memories if m.id == memory_id
            )
            lines.append(f"- id: {alias} [{memory.kind}] {memory.text}")
        lines.append("")
        lines.append(f"USER MESSAGE\n{context.message}")
        return "\n".join(lines)

    # -- validation and conversion -------------------------------------------------------

    def _apply_proposal(self, data, context, alias_map, deterministic,
                        audit) -> list[MemoryAction]:
        action = data["action"]
        if action == "none":
            audit.semantic_valid = True
            self.counters["none_actions"] += 1
            # An explicit none is a VALID result. Deterministic
            # baseline still applies (safety floor), not as fallback.
            return deterministic

        evidence = data.get("evidence", "")
        if evidence and " ".join(evidence.lower().split()) not in " ".join(
            context.message.lower().split()
        ):
            audit.rejection_reason = "evidence not grounded in message"
            self.counters["semantic_rejections"] += 1
            return self._fallback(action, deterministic, audit)

        if action == "remember":
            statement = data["memory"]["statement"].strip()
            audit.semantic_valid = True
            local_action = MemoryAction(
                action=CREATE, kind=data["memory"]["kind"], text=statement,
                reason="local-policy v2 proposal",
            )
            return self._merge_create(
                local_action, deterministic, context, audit
            )

        if action == "update":
            target_id = self._resolve_target_id(
                data, context, alias_map, audit
            )
            statement = data["memory"]["statement"].strip()
            if target_id is None:
                if audit.rejection_reason:
                    return self._fallback(action, deterministic, audit)
                # No explicit target: treat as a create; semantic
                # dedupe/conflict layers decide downstream.
                audit.semantic_valid = True
                local_action = MemoryAction(
                    action=CREATE, kind=data["memory"]["kind"],
                    text=statement, reason="local-policy v2 update",
                )
                return self._merge_create(
                    local_action, deterministic, context, audit
                )
            audit.semantic_valid = True
            audit.target_valid = True
            target = next(
                m for m in context.active_memories if m.id == target_id
            )
            self.counters["local_accepted"] += 1
            audit.applied_from_local = True
            return [
                *[
                    a for a in deterministic
                    if a.memory_id != target_id and a.action != CREATE
                ],
                MemoryAction(
                    action=SUPERSEDE, kind=target.kind, memory_id=target_id,
                    text=target.text,
                    reason="local-policy v2 update proposal",
                ),
                MemoryAction(
                    action=CREATE, kind=data["memory"]["kind"],
                    text=statement, replaces=target_id,
                    reason="local-policy v2 update proposal",
                ),
            ]

        if action == "forget":
            target_id = self._resolve_target_id(
                data, context, alias_map, audit
            )
            if target_id is None and not audit.rejection_reason:
                description = (data.get("target") or {}).get(
                    "description"
                ) or ""
                intent = ForgetIntent(
                    True, confidence=1.0, target_text=description
                )
                result = self.forget_resolver.resolve(
                    intent, context.active_memories
                )
                if result.outcome == ForgetOutcome.RESOLVED:
                    target_id = result.targets[0].id
                else:
                    audit.rejection_reason = (
                        f"forget target unresolved: {result.outcome}"
                    )
            if target_id is None:
                self.counters["target_rejections"] += 1
                return self._fallback(action, deterministic, audit)
            audit.semantic_valid = True
            audit.target_valid = True
            target = next(
                m for m in context.active_memories if m.id == target_id
            )
            self.counters["local_accepted"] += 1
            audit.applied_from_local = True
            deterministic_other = [
                a for a in deterministic if a.memory_id != target_id
            ]
            return [
                *deterministic_other,
                MemoryAction(
                    action=FORGET, kind=target.kind, memory_id=target_id,
                    text=target.text,
                    reason="local-policy v2: user asked to forget this "
                           "experience.",
                    request=context.message[:160],
                ),
            ]
        return self._fallback(None, deterministic, audit)

    def _resolve_target_id(self, data, context, alias_map, audit):
        target = data.get("target") or {}
        raw_id = target.get("memory_id")
        if not raw_id:
            return None
        if raw_id in alias_map:
            return alias_map[raw_id]
        if any(m.id == raw_id for m in context.active_memories):
            return raw_id
        # Invented or inactive target ID: rejected, never guessed.
        audit.rejection_reason = f"target id not in active set: {raw_id!r}"
        audit.target_valid = False
        self.counters["target_rejections"] += 1
        return None

    def _merge_create(self, local_action, deterministic, context, audit):
        normalized = _normalized_text(local_action.text)
        duplicate = any(
            a.action == CREATE and _normalized_text(a.text) == normalized
            for a in deterministic
        ) or any(
            _normalized_text(m.text) == normalized
            for m in context.active_memories
        )
        if duplicate:
            self.counters["local_duplicates_of_deterministic"] += 1
            return deterministic
        self.counters["local_accepted"] += 1
        audit.applied_from_local = True
        return [*deterministic, local_action]

    # -- per-action fallback ------------------------------------------------------------

    def _fallback(self, action, deterministic, audit):
        """Deterministic fallback that never broadens the action.
        A malformed forget can only apply deterministic FORGET
        actions; a malformed remember/update only creates/updates;
        an unclassifiable failure applies the full deterministic plan
        (the base containment contract)."""
        if action == "forget":
            audit.fallback_type = "forget"
            self.counters["fallback_forget"] += 1
            return [a for a in deterministic if a.action == FORGET]
        if action in ("remember", "update"):
            audit.fallback_type = action
            self.counters[f"fallback_{action}"] += 1
            return [
                a for a in deterministic
                if a.action in (CREATE, SUPERSEDE)
            ]
        if action == "none":
            audit.fallback_type = "none"
            self.counters["fallback_none"] += 1
            return []
        audit.fallback_type = "unclassified"
        self.counters["fallback_unclassified"] += 1
        return deterministic

    @staticmethod
    def _to_proposal(action: MemoryAction, audit) -> MemoryDecisionProposal:
        metadata: dict = {}
        if action.request:
            metadata["request"] = action.request
        if action.metadata:
            metadata["entry_metadata"] = action.metadata
        # Per-ACTION labeling: only actions the local proposal produced
        # are local_model; deterministic siblings stay rule_based, and
        # fallback batches are labeled with the actual failure reason.
        from_local = "local-policy v2" in (action.reason or "")
        if from_local:
            source, reason = DecisionSource.LOCAL_MODEL, None
        elif audit.fallback_type:
            source = DecisionSource.FALLBACK
            reason = (
                FallbackReason.MODEL_UNAVAILABLE
                if audit.model_mode == "unavailable"
                else FallbackReason.INVALID_OUTPUT
            )
        else:
            source, reason = DecisionSource.RULE_BASED, None
        return MemoryDecisionProposal(
            action=action.action,
            kind=action.kind,
            text=action.text or None,
            target_memory_id=action.memory_id,
            replaces=action.replaces,
            confidence=1.0,
            explanation=action.reason or "",
            decision_source=source,
            fallback_reason=reason,
            metadata=metadata,
        )


class ScriptedLocalPolicyV2(LocalPolicyV2):
    """Canonical offline mode: a SIMULATED well-behaved model.

    The scripted proposer serializes the deterministic plan's primary
    action into one v2 proposal and pushes it through the REAL parser
    and validation pipeline — measuring the containment machinery on
    every turn with reproducible inputs. Results are labeled simulated
    scripted proposals, never real-model accuracy.
    """

    scripted = True

    def __init__(self, deterministic_planner, forget_resolver=None):
        super().__init__(
            runner=None,
            deterministic_planner=deterministic_planner,
            forget_resolver=forget_resolver,
        )

    def _generate(self, context, alias_map, audit, deterministic):
        audit.model_mode = "scripted_simulated"
        data = self._simulate(context, alias_map, deterministic)
        audit.raw_excerpt = json.dumps(data, sort_keys=True)[:200]
        try:
            parsed, repairs = self.parser.parse(data)
        except ParseFailure as exc:  # pragma: no cover — simulation bug
            audit.rejection_reason = str(exc)[:120]
            self.counters["structural_invalid"] += 1
            return None
        del repairs
        audit.parse_ok = True
        audit.structural_valid = True
        audit.action = parsed["action"]
        self.counters["structural_valid"] += 1
        return parsed

    @staticmethod
    def _simulate(context, alias_map, deterministic) -> dict:
        id_to_alias = {v: k for k, v in alias_map.items()}
        forgets = [a for a in deterministic if a.action == FORGET]
        supersedes = [a for a in deterministic if a.action == SUPERSEDE]
        creates = [a for a in deterministic if a.action == CREATE]
        base = {
            "evidence": context.message[:200],
            "confidence": 0.9,
            "reason": "scripted simulated proposal",
        }
        if forgets:
            return {
                "action": "forget",
                "target": {
                    "memory_id": id_to_alias.get(forgets[0].memory_id),
                    "description": forgets[0].text[:120],
                },
                **base,
            }
        if supersedes and creates:
            paired = next(
                (c for c in creates if c.replaces == supersedes[0].memory_id),
                creates[0],
            )
            return {
                "action": "update",
                "memory": {"kind": paired.kind, "statement": paired.text},
                "target": {
                    "memory_id": id_to_alias.get(supersedes[0].memory_id),
                    "description": supersedes[0].text[:120],
                },
                **base,
            }
        if creates:
            return {
                "action": "remember",
                "memory": {
                    "kind": creates[0].kind,
                    "statement": creates[0].text,
                },
                **base,
            }
        return {"action": "none", **base}
