"""Benchmark case contract: the declarative scenario schema.

A benchmark case describes ordered multi-session setup turns, one
current user message, and the expected lifecycle and response
outcome. Cases are data, not code: the later ~40-scenario dataset is
authored as JSON validated by ``case_from_dict``.

Memory references are logical: a case names memories with a stable
``logical_id`` plus content ``match_terms``, because real memory IDs
are assigned at runtime. Runners resolve logical references against
the system's actual memory state; a reference may also pin an exact
``memory_id`` when a stable ID exists.
"""

from __future__ import annotations

from dataclasses import dataclass

CASE_SCHEMA_VERSION = "1"


class ScenarioCategory:
    CREATION = "creation"
    UPDATE = "update"
    FORGETTING = "forgetting"
    RETRIEVAL = "retrieval"
    SELECTION = "selection"
    ABSTENTION = "abstention"
    MULTI_SESSION = "multi_session"
    DISTRACTOR = "distractor"
    CONTEXT_BUDGET = "context_budget"
    REJECTION = "rejection"
    FALLBACK = "fallback"
    COMPRESSION = "compression"


KNOWN_CATEGORIES = frozenset(
    value
    for name, value in vars(ScenarioCategory).items()
    if not name.startswith("_")
)


class EvaluationMode:
    DETERMINISTIC = "deterministic"
    MODEL_SCORED = "model_scored"


KNOWN_EVALUATION_MODES = frozenset(
    (EvaluationMode.DETERMINISTIC, EvaluationMode.MODEL_SCORED)
)


class ExpectedAction:
    CREATE = "create"
    SUPERSEDE = "supersede"
    FORGET = "forget"
    NONE = "none"


KNOWN_EXPECTED_ACTIONS = frozenset(
    (
        ExpectedAction.CREATE,
        ExpectedAction.SUPERSEDE,
        ExpectedAction.FORGET,
        ExpectedAction.NONE,
    )
)

KNOWN_MEMORY_KINDS = frozenset(("preference", "fact", "instruction"))

KNOWN_TURN_ROLES = frozenset(("user", "assistant"))


class InvalidBenchmarkCase(ValueError):
    """Raised when case data fails contract validation."""


@dataclass(frozen=True)
class MemoryRef:
    """A logical reference to a memory whose real ID exists at runtime.

    Resolvable later: runners match ``match_terms`` (all terms,
    case-insensitive) against memory text, or use ``memory_id``
    directly when pinned.
    """

    logical_id: str
    match_terms: tuple[str, ...] = ()
    memory_id: str | None = None

    def to_payload(self) -> dict:
        return {
            "logical_id": self.logical_id,
            "match_terms": list(self.match_terms),
            "memory_id": self.memory_id,
        }


@dataclass(frozen=True)
class SemanticConstraint:
    """Semantic value matching where exact text is inappropriate."""

    must_include_all: tuple[str, ...] = ()
    must_include_any: tuple[str, ...] = ()
    must_exclude: tuple[str, ...] = ()

    def to_payload(self) -> dict:
        return {
            "must_include_all": list(self.must_include_all),
            "must_include_any": list(self.must_include_any),
            "must_exclude": list(self.must_exclude),
        }


@dataclass(frozen=True)
class ExpectedMemoryAction:
    """One expected lifecycle action for the current message.

    ``action == "none"`` states that no memory action is expected.
    ``logical_id`` names the memory a create produces so later
    expectations and cases can reference it.
    """

    action: str
    kind: str | None = None
    logical_id: str | None = None
    value: SemanticConstraint | None = None
    target: MemoryRef | None = None

    def to_payload(self) -> dict:
        return {
            "action": self.action,
            "kind": self.kind,
            "logical_id": self.logical_id,
            "value": self.value.to_payload() if self.value else None,
            "target": self.target.to_payload() if self.target else None,
        }


@dataclass(frozen=True)
class ScenarioTurn:
    """One ordered setup turn. Order is the list order — no reordering."""

    session_id: str
    role: str
    message: str

    def to_payload(self) -> dict:
        return {
            "session_id": self.session_id,
            "role": self.role,
            "message": self.message,
        }


@dataclass(frozen=True)
class ResponseConstraints:
    """Deterministic response checks; concept lists, never exact prose."""

    must_include_any: tuple[str, ...] = ()
    must_include_all: tuple[str, ...] = ()
    must_exclude: tuple[str, ...] = ()
    expect_abstention: bool = False

    def to_payload(self) -> dict:
        return {
            "must_include_any": list(self.must_include_any),
            "must_include_all": list(self.must_include_all),
            "must_exclude": list(self.must_exclude),
            "expect_abstention": self.expect_abstention,
        }


@dataclass(frozen=True)
class ExpectedOutcome:
    """Lifecycle and response oracle for the current message.

    Empty tuples are UNASSERTED — they impose no expectation. To
    assert that the final-state lists are exhaustive (for example
    "nothing may be active"), set ``final_state_exact`` to true; it
    applies to ``active``, ``superseded``, and ``forgotten``.
    ``compression_expected`` asserts that context compression must
    occur on the current turn.
    """

    memory_actions: tuple[ExpectedMemoryAction, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    fallback_expected: bool = False
    final_state_exact: bool = False
    compression_expected: bool = False
    active: tuple[MemoryRef, ...] = ()
    superseded: tuple[MemoryRef, ...] = ()
    forgotten: tuple[MemoryRef, ...] = ()
    retrieval_candidates: tuple[MemoryRef, ...] = ()
    selected: tuple[MemoryRef, ...] = ()
    skipped: tuple[MemoryRef, ...] = ()
    response: ResponseConstraints | None = None

    def to_payload(self) -> dict:
        return {
            "memory_actions": [a.to_payload() for a in self.memory_actions],
            "rejection_reasons": list(self.rejection_reasons),
            "fallback_expected": self.fallback_expected,
            "final_state_exact": self.final_state_exact,
            "compression_expected": self.compression_expected,
            "active": [r.to_payload() for r in self.active],
            "superseded": [r.to_payload() for r in self.superseded],
            "forgotten": [r.to_payload() for r in self.forgotten],
            "retrieval_candidates": [
                r.to_payload() for r in self.retrieval_candidates
            ],
            "selected": [r.to_payload() for r in self.selected],
            "skipped": [r.to_payload() for r in self.skipped],
            "response": self.response.to_payload() if self.response else None,
        }


@dataclass(frozen=True)
class BenchmarkCase:
    scenario_id: str
    title: str
    category: str
    description: str
    current_message: str
    current_session_id: str
    expected: ExpectedOutcome
    schema_version: str = CASE_SCHEMA_VERSION
    tags: tuple[str, ...] = ()
    seed: int = 0
    context_budget: int = 4
    selection_k: int | None = None
    turns: tuple[ScenarioTurn, ...] = ()
    requires_provider: bool = False
    requires_local_model: bool = False
    evaluation_mode: str = EvaluationMode.DETERMINISTIC
    evaluator_requirements: tuple[str, ...] = ()
    notes: str = ""

    def to_payload(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "tags": list(self.tags),
            "seed": self.seed,
            "context_budget": self.context_budget,
            "selection_k": self.selection_k,
            "turns": [t.to_payload() for t in self.turns],
            "current_message": self.current_message,
            "current_session_id": self.current_session_id,
            "expected": self.expected.to_payload(),
            "requires_provider": self.requires_provider,
            "requires_local_model": self.requires_local_model,
            "evaluation_mode": self.evaluation_mode,
            "evaluator_requirements": list(self.evaluator_requirements),
            "notes": self.notes,
        }


def _require(condition: bool, scenario_id: str, message: str) -> None:
    if not condition:
        label = scenario_id or "<missing scenario_id>"
        raise InvalidBenchmarkCase(f"{label}: {message}")


def _string_tuple(value, scenario_id: str, field_name: str) -> tuple[str, ...]:
    _require(
        isinstance(value, list)
        and all(isinstance(v, str) and v.strip() for v in value),
        scenario_id,
        f"{field_name} must be a list of non-empty strings, got {value!r}",
    )
    return tuple(value)


def _memory_ref(data, scenario_id: str, field_name: str) -> MemoryRef:
    _require(
        isinstance(data, dict),
        scenario_id,
        f"{field_name} must be an object, got {data!r}",
    )
    logical_id = data.get("logical_id")
    memory_id = data.get("memory_id")
    match_terms = data.get("match_terms", [])
    _require(
        isinstance(logical_id, str) and logical_id.strip() != "",
        scenario_id,
        f"{field_name} requires a non-empty logical_id",
    )
    terms = _string_tuple(match_terms, scenario_id, f"{field_name}.match_terms")
    _require(
        memory_id is not None or len(terms) > 0,
        scenario_id,
        f"{field_name} ({logical_id}) must be resolvable: "
        "provide match_terms or a pinned memory_id",
    )
    return MemoryRef(
        logical_id=logical_id, match_terms=terms, memory_id=memory_id
    )


def _memory_refs(value, scenario_id, field_name) -> tuple[MemoryRef, ...]:
    if value is None:
        return ()
    _require(
        isinstance(value, list),
        scenario_id,
        f"{field_name} must be a list",
    )
    return tuple(
        _memory_ref(item, scenario_id, f"{field_name}[{i}]")
        for i, item in enumerate(value)
    )


def _semantic_constraint(data, scenario_id, field_name):
    if data is None:
        return None
    _require(
        isinstance(data, dict), scenario_id, f"{field_name} must be an object"
    )
    return SemanticConstraint(
        must_include_all=_string_tuple(
            data.get("must_include_all", []),
            scenario_id,
            f"{field_name}.must_include_all",
        ),
        must_include_any=_string_tuple(
            data.get("must_include_any", []),
            scenario_id,
            f"{field_name}.must_include_any",
        ),
        must_exclude=_string_tuple(
            data.get("must_exclude", []),
            scenario_id,
            f"{field_name}.must_exclude",
        ),
    )


def _expected_action(data, scenario_id, field_name) -> ExpectedMemoryAction:
    _require(
        isinstance(data, dict), scenario_id, f"{field_name} must be an object"
    )
    action = data.get("action")
    _require(
        action in KNOWN_EXPECTED_ACTIONS,
        scenario_id,
        f"{field_name}.action must be one of "
        f"{sorted(KNOWN_EXPECTED_ACTIONS)}, got {action!r}",
    )
    kind = data.get("kind")
    if kind is not None:
        _require(
            kind in KNOWN_MEMORY_KINDS,
            scenario_id,
            f"{field_name}.kind must be one of "
            f"{sorted(KNOWN_MEMORY_KINDS)}, got {kind!r}",
        )
    target = data.get("target")
    if action in (ExpectedAction.SUPERSEDE, ExpectedAction.FORGET):
        _require(
            target is not None,
            scenario_id,
            f"{field_name}: {action} requires a target reference",
        )
    return ExpectedMemoryAction(
        action=action,
        kind=kind,
        logical_id=data.get("logical_id"),
        value=_semantic_constraint(
            data.get("value"), scenario_id, f"{field_name}.value"
        ),
        target=(
            _memory_ref(target, scenario_id, f"{field_name}.target")
            if target is not None
            else None
        ),
    )


def _response_constraints(data, scenario_id):
    if data is None:
        return None
    _require(
        isinstance(data, dict),
        scenario_id,
        "expected.response must be an object",
    )
    return ResponseConstraints(
        must_include_any=_string_tuple(
            data.get("must_include_any", []),
            scenario_id,
            "expected.response.must_include_any",
        ),
        must_include_all=_string_tuple(
            data.get("must_include_all", []),
            scenario_id,
            "expected.response.must_include_all",
        ),
        must_exclude=_string_tuple(
            data.get("must_exclude", []),
            scenario_id,
            "expected.response.must_exclude",
        ),
        expect_abstention=bool(data.get("expect_abstention", False)),
    )


def case_from_dict(data: dict) -> BenchmarkCase:
    """Validate raw case data and build a BenchmarkCase.

    Raises InvalidBenchmarkCase with the scenario ID and the exact
    failing field, so malformed dataset entries are diagnosable.
    """
    if not isinstance(data, dict):
        raise InvalidBenchmarkCase(
            f"case must be an object, got {type(data).__name__}"
        )
    scenario_id = data.get("scenario_id", "")
    _require(
        isinstance(scenario_id, str) and scenario_id.strip() != "",
        scenario_id,
        "scenario_id must be a non-empty string",
    )
    _require(
        data.get("schema_version") == CASE_SCHEMA_VERSION,
        scenario_id,
        f"schema_version must be {CASE_SCHEMA_VERSION!r}, "
        f"got {data.get('schema_version')!r}",
    )
    category = data.get("category")
    _require(
        category in KNOWN_CATEGORIES,
        scenario_id,
        f"category must be one of {sorted(KNOWN_CATEGORIES)}, "
        f"got {category!r}",
    )
    for text_field in ("title", "description", "current_message",
                       "current_session_id"):
        value = data.get(text_field)
        _require(
            isinstance(value, str) and value.strip() != "",
            scenario_id,
            f"{text_field} must be a non-empty string",
        )
    tags = _string_tuple(data.get("tags", []), scenario_id, "tags")
    seed = data.get("seed", 0)
    _require(
        isinstance(seed, int) and not isinstance(seed, bool),
        scenario_id,
        f"seed must be an integer, got {seed!r}",
    )
    context_budget = data.get("context_budget", 4)
    _require(
        isinstance(context_budget, int)
        and not isinstance(context_budget, bool)
        and context_budget > 0,
        scenario_id,
        f"context_budget must be a positive integer, got {context_budget!r}",
    )
    selection_k = data.get("selection_k")
    if selection_k is not None:
        _require(
            isinstance(selection_k, int)
            and not isinstance(selection_k, bool)
            and selection_k > 0,
            scenario_id,
            f"selection_k must be a positive integer, got {selection_k!r}",
        )
    evaluation_mode = data.get("evaluation_mode", EvaluationMode.DETERMINISTIC)
    _require(
        evaluation_mode in KNOWN_EVALUATION_MODES,
        scenario_id,
        f"evaluation_mode must be one of {sorted(KNOWN_EVALUATION_MODES)}, "
        f"got {evaluation_mode!r}",
    )

    raw_turns = data.get("turns", [])
    _require(isinstance(raw_turns, list), scenario_id, "turns must be a list")
    turns = []
    for i, raw in enumerate(raw_turns):
        _require(
            isinstance(raw, dict), scenario_id, f"turns[{i}] must be an object"
        )
        role = raw.get("role", "user")
        _require(
            role in KNOWN_TURN_ROLES,
            scenario_id,
            f"turns[{i}].role must be one of {sorted(KNOWN_TURN_ROLES)}, "
            f"got {role!r}",
        )
        for turn_field in ("session_id", "message"):
            value = raw.get(turn_field)
            _require(
                isinstance(value, str) and value.strip() != "",
                scenario_id,
                f"turns[{i}].{turn_field} must be a non-empty string",
            )
        turns.append(
            ScenarioTurn(
                session_id=raw["session_id"], role=role, message=raw["message"]
            )
        )

    expected_data = data.get("expected")
    _require(
        isinstance(expected_data, dict),
        scenario_id,
        "expected must be an object",
    )
    raw_actions = expected_data.get("memory_actions", [])
    _require(
        isinstance(raw_actions, list),
        scenario_id,
        "expected.memory_actions must be a list",
    )
    expected = ExpectedOutcome(
        memory_actions=tuple(
            _expected_action(a, scenario_id, f"expected.memory_actions[{i}]")
            for i, a in enumerate(raw_actions)
        ),
        rejection_reasons=_string_tuple(
            expected_data.get("rejection_reasons", []),
            scenario_id,
            "expected.rejection_reasons",
        ),
        fallback_expected=bool(expected_data.get("fallback_expected", False)),
        final_state_exact=bool(expected_data.get("final_state_exact", False)),
        compression_expected=bool(
            expected_data.get("compression_expected", False)
        ),
        active=_memory_refs(
            expected_data.get("active"), scenario_id, "expected.active"
        ),
        superseded=_memory_refs(
            expected_data.get("superseded"), scenario_id, "expected.superseded"
        ),
        forgotten=_memory_refs(
            expected_data.get("forgotten"), scenario_id, "expected.forgotten"
        ),
        retrieval_candidates=_memory_refs(
            expected_data.get("retrieval_candidates"),
            scenario_id,
            "expected.retrieval_candidates",
        ),
        selected=_memory_refs(
            expected_data.get("selected"), scenario_id, "expected.selected"
        ),
        skipped=_memory_refs(
            expected_data.get("skipped"), scenario_id, "expected.skipped"
        ),
        response=_response_constraints(
            expected_data.get("response"), scenario_id
        ),
    )

    return BenchmarkCase(
        scenario_id=scenario_id,
        schema_version=CASE_SCHEMA_VERSION,
        title=data["title"],
        category=category,
        description=data["description"],
        tags=tags,
        seed=seed,
        context_budget=context_budget,
        selection_k=selection_k,
        turns=tuple(turns),
        current_message=data["current_message"],
        current_session_id=data["current_session_id"],
        expected=expected,
        requires_provider=bool(data.get("requires_provider", False)),
        requires_local_model=bool(data.get("requires_local_model", False)),
        evaluation_mode=evaluation_mode,
        evaluator_requirements=_string_tuple(
            data.get("evaluator_requirements", []),
            scenario_id,
            "evaluator_requirements",
        ),
        notes=data.get("notes", "") or "",
    )
