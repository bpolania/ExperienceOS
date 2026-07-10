"""ExperienceOS + LocalModelMemoryPolicy benchmark adapter.

Three execution modes, all through the REAL production policy,
ExperienceManager validation, and typed fallback path:

- ``scripted`` (default, offline): scenarios with a declared scripted
  fixture get a ScriptedLocalRunner replaying deterministic model
  proposals through the real LocalModelMemoryPolicy; every other
  scenario runs with an unavailable runner, so every turn takes the
  real whole-batch fallback to rules (decision_source = fallback —
  never presented as local-model success).
- ``unavailable``: forces the no-runner path everywhere.
- ``real``: uses the production LlamaCppLocalModelRunner from the
  repository's environment configuration. Never part of default
  tests; no downloads, no filesystem searches; provenance records the
  safe model basename only.
"""

from __future__ import annotations

from benchmarks.adapters.common import ExperienceOSAdapterBase
from benchmarks.adapters.scripted_policy import (
    SCRIPTED_MODEL_NAME,
    scripted_runner_for,
)
from benchmarks.contract import SystemId, safe_model_name
from experienceos import LocalModelMemoryPolicy
from experienceos.policy.local_runner import (
    LocalModelAvailability,
    LocalModelUnavailable,
)

MODES = ("scripted", "unavailable", "real")


class _UnavailableRunner:
    """A runner that is never available: exercises the real fallback
    path without any model, download, or filesystem access."""

    def availability(self) -> LocalModelAvailability:
        return LocalModelAvailability(
            available=False,
            reason="model_unavailable",
            detail="benchmark offline mode: no local model configured",
        )

    def generate_structured(self, *, system_prompt, user_prompt, schema):
        raise LocalModelUnavailable(
            "benchmark offline mode: no local model configured"
        )


class _CountingRunner:
    """Transparent wrapper counting local-policy invocations."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def availability(self):
        return self.inner.availability()

    def generate_structured(self, **kwargs):
        result = self.inner.generate_structured(**kwargs)
        self.calls += 1  # counts completed generations only
        return result


class ExperienceOSLocalAdapter(ExperienceOSAdapterBase):
    system_id = SystemId.EXPERIENCEOS_LOCAL
    memory_policy_label = "local_model"

    def __init__(self, provider=None, seed: int = 0, mode: str = "scripted"):
        if mode not in MODES:
            raise ValueError(
                f"unknown local adapter mode {mode!r}; expected one of {MODES}"
            )
        self.mode = mode
        self._runner = None
        super().__init__(provider=provider, seed=seed)

    def _make_policy(self, case):
        if self.mode == "real":
            from experienceos import LlamaCppLocalModelRunner

            runner = LlamaCppLocalModelRunner()
            availability = runner.availability()
            self.diagnostics["local_mode"] = "real"
            self.diagnostics["real_model_used"] = availability.available
            self.diagnostics["local_model_name"] = safe_model_name(
                availability.model_path
            )
        elif self.mode == "scripted":
            runner = scripted_runner_for(case.scenario_id)
            if runner is not None:
                self.diagnostics["local_mode"] = "scripted"
                self.diagnostics["scripted_fixture"] = case.scenario_id
                self.diagnostics["local_model_name"] = SCRIPTED_MODEL_NAME
            else:
                runner = _UnavailableRunner()
                self.diagnostics["local_mode"] = "unavailable_fallback"
            self.diagnostics["real_model_used"] = False
        else:  # unavailable
            runner = _UnavailableRunner()
            self.diagnostics["local_mode"] = "unavailable_fallback"
            self.diagnostics["real_model_used"] = False
        self._runner = _CountingRunner(runner)
        return LocalModelMemoryPolicy(self._runner)

    def process_turn(self, turn_index, session_id, message):
        evidence = super().process_turn(turn_index, session_id, message)
        # Convention: invocation count = COMPLETED structured
        # generations. Scripted generations count (diagnostics mark
        # them scripted); the unavailable runner raises before
        # generating, so its count stays zero.
        self.local_model_invocation_count = (
            self._runner.calls if self._runner else 0
        )
        return evidence
