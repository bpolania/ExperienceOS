"""Public SDK entrypoint for ExperienceOS.

Usage:

    agent = ExperienceOS(model=MockProvider())
    agent = ExperienceOS.wrap(QwenCloud(...))

    response = agent.chat(
        user_id="demo-user",
        session_id="session-1",
        message="I prefer aisle seats and morning flights.",
    )
    agent.memories_for_user("demo-user")
"""

from __future__ import annotations

from experienceos.context.builder import ContextBuilder
from experienceos.engine.experience_engine import ExperienceEngine
from experienceos.events.bus import EventBus
from experienceos.events.schema import ExperienceEvent
from experienceos.memory.planner import MemoryPlanner
from experienceos.memory.schema import ExperienceEntry, MemoryStatus
from experienceos.memory.store import MemoryStore
from experienceos.policy.base import MemoryPolicy
from experienceos.policy.manager import ExperienceManager
from experienceos.policy.rule_based import RuleBasedMemoryPolicy
from experienceos.providers.base import ModelProvider


class ExperienceOS:
    """Attaches an experience layer to any model provider.

    All collaborators are injectable; defaults are offline and
    in-memory. ``memory_store`` accepts any store implementing the
    memory store interface (``InMemoryMemoryStore`` — the default — or
    ``SQLiteMemoryStore`` for persistence across restarts).

    Memory planning is configurable through exactly one of:
    ``experience_manager`` (a preconfigured ExperienceManager),
    ``memory_policy`` (wrapped in a default manager), or
    ``memory_planner`` (wrapped in the rule-based policy). The default
    is the deterministic rule-based policy; combining these arguments
    raises ValueError.
    """

    def __init__(
        self,
        model: ModelProvider,
        *,
        event_bus: EventBus | None = None,
        context_builder: ContextBuilder | None = None,
        memory_store: MemoryStore | None = None,
        memory_planner: MemoryPlanner | None = None,
        memory_policy: MemoryPolicy | None = None,
        experience_manager: ExperienceManager | None = None,
    ):
        provided = [
            name
            for name, value in (
                ("experience_manager", experience_manager),
                ("memory_policy", memory_policy),
                ("memory_planner", memory_planner),
            )
            if value is not None
        ]
        if len(provided) > 1:
            raise ValueError(
                "Provide only one of experience_manager, memory_policy, or "
                f"memory_planner (got: {', '.join(provided)})."
            )

        self.model = model
        self.event_bus = event_bus or EventBus()
        self.context_builder = context_builder or ContextBuilder()
        self.memory_store = memory_store or MemoryStore()
        self.memory_planner = memory_planner or MemoryPlanner()
        if experience_manager is not None:
            self.experience_manager = experience_manager
        elif memory_policy is not None:
            self.experience_manager = ExperienceManager(memory_policy)
        else:
            self.experience_manager = ExperienceManager(
                RuleBasedMemoryPolicy(self.memory_planner)
            )
        self.engine = ExperienceEngine(
            model=self.model,
            event_bus=self.event_bus,
            context_builder=self.context_builder,
            memory_store=self.memory_store,
            memory_planner=self.memory_planner,
            experience_manager=self.experience_manager,
        )

    @classmethod
    def wrap(cls, model: ModelProvider, **kwargs) -> "ExperienceOS":
        """Attach an experience layer to an existing model provider."""
        return cls(model=model, **kwargs)

    @classmethod
    def with_sqlite_memory(
        cls,
        model: ModelProvider,
        db_path: str = "experienceos.sqlite3",
        **kwargs,
    ) -> "ExperienceOS":
        """Agent whose accumulated experience persists across restarts."""
        from experienceos.memory.sqlite_store import SQLiteMemoryStore

        return cls(model=model, memory_store=SQLiteMemoryStore(db_path), **kwargs)

    def chat(self, user_id: str, session_id: str, message: str) -> str:
        """Send a message through the experience layer."""
        return self.engine.run_interaction(
            user_id=user_id, session_id=session_id, message=message
        )

    def memories_for_user(
        self, user_id: str, status: str | None = MemoryStatus.ACTIVE
    ) -> list[ExperienceEntry]:
        """Accumulated experience for a user, active by default.

        Pass status="superseded" for replaced memories, or None for all.
        """
        return self.memory_store.list_memories(user_id, status=status)

    @property
    def events(self) -> list[ExperienceEvent]:
        """All events emitted so far (demo convenience)."""
        return self.event_bus.history()
