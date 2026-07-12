"""Grounded-extraction benchmark system definitions.

Each system is an immutable, reproducible configuration with a stable ID
and a deterministic configuration digest. System IDs match the reserved
IDs in the grounded-extraction contract and must never be reused for a
changed behavior. None of these systems changes any default ExperienceOS
behavior: the reference disables grounded extraction entirely, and the
grounded systems are explicit benchmark configurations only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from benchmarks.contract.serialization import canonical_json
from experienceos.memory.grounded_extraction import (
    GROUNDED_EXTRACTION_CONTROLLER_ID,
    GROUNDED_EXTRACTION_VERSION,
)
from experienceos.memory.grounding import (
    GROUNDED_VALIDATOR_ID,
    GROUNDED_VALIDATOR_VERSION,
)
from experienceos.memory.learned_extraction import (
    LEARNED_CONTROLLER_ID,
    LEARNED_CONTROLLER_VERSION,
)

# Reserved system IDs (contract §11). Immutable per behavior.
REFERENCE = "experienceos_hybrid_full_v2_reference"
GROUNDED_RULES = "experienceos_grounded_rules_v1"
LEARNED_SHADOW = "experienceos_grounded_learned_shadow_v1"
LEARNED_CANDIDATE = "experienceos_grounded_learned_candidate_v1"
QWEN_CEILING = "experienceos_grounded_qwen_ceiling_v1"

CONTROLLER_NONE = "none"
CONTROLLER_DETERMINISTIC = "deterministic"
CONTROLLER_LEARNED = "learned"


@dataclass(frozen=True)
class SystemDefinition:
    """Reproducible benchmark system configuration."""

    system_id: str
    controller_type: str
    controller_id: str | None
    controller_version: str | None
    validator_id: str | None
    validator_version: str | None
    runner_id: str | None
    runner_version: str | None
    fallback_mode: str
    requires_runner: bool
    requires_credentials: bool
    description: str
    extra: dict = field(default_factory=dict)

    def config_digest(self) -> str:
        payload = {
            "system_id": self.system_id,
            "controller_type": self.controller_type,
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "validator_id": self.validator_id,
            "validator_version": self.validator_version,
            "runner_id": self.runner_id,
            "runner_version": self.runner_version,
            "fallback_mode": self.fallback_mode,
            "requires_runner": self.requires_runner,
            "requires_credentials": self.requires_credentials,
        }
        return hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()


REGISTRY = {
    REFERENCE: SystemDefinition(
        system_id=REFERENCE,
        controller_type=CONTROLLER_NONE,
        controller_id=None,
        controller_version=None,
        validator_id=None,
        validator_version=None,
        runner_id=None,
        runner_version=None,
        fallback_mode="none",
        requires_runner=False,
        requires_credentials=False,
        description=(
            "Canonical reference: grounded extraction disabled; only the "
            "existing hybrid planner creates memories. The comparison "
            "anchor."),
    ),
    GROUNDED_RULES: SystemDefinition(
        system_id=GROUNDED_RULES,
        controller_type=CONTROLLER_DETERMINISTIC,
        controller_id=GROUNDED_EXTRACTION_CONTROLLER_ID,
        controller_version=GROUNDED_EXTRACTION_VERSION,
        validator_id=GROUNDED_VALIDATOR_ID,
        validator_version=GROUNDED_VALIDATOR_VERSION,
        runner_id=None,
        runner_version=None,
        fallback_mode="none",
        requires_runner=False,
        requires_credentials=False,
        description=(
            "Deterministic grounded extraction, evaluated shadow (proposal), "
            "candidate (lifecycle), and benchmark-only adopted (isolated "
            "durable) — never a default SDK mode, never adopted."),
    ),
    LEARNED_SHADOW: SystemDefinition(
        system_id=LEARNED_SHADOW,
        controller_type=CONTROLLER_LEARNED,
        controller_id=LEARNED_CONTROLLER_ID,
        controller_version=LEARNED_CONTROLLER_VERSION,
        validator_id=GROUNDED_VALIDATOR_ID,
        validator_version=GROUNDED_VALIDATOR_VERSION,
        runner_id=None,
        runner_version=None,
        fallback_mode="none",
        requires_runner=True,
        requires_credentials=False,
        description=(
            "Optional learned extraction, shadow-only; runs only with a "
            "real configured local runner. Fallback disabled so learned "
            "failures are never hidden."),
    ),
    LEARNED_CANDIDATE: SystemDefinition(
        system_id=LEARNED_CANDIDATE,
        controller_type=CONTROLLER_LEARNED,
        controller_id=LEARNED_CONTROLLER_ID,
        controller_version=LEARNED_CONTROLLER_VERSION,
        validator_id=GROUNDED_VALIDATOR_ID,
        validator_version=GROUNDED_VALIDATOR_VERSION,
        runner_id=None,
        runner_version=None,
        fallback_mode="none",
        requires_runner=True,
        requires_credentials=False,
        description=(
            "Optional learned extraction, candidate-mode lifecycle "
            "evaluation in isolated state; conditional on a real runner and "
            "passing learned gates. Non-canonical."),
    ),
    QWEN_CEILING: SystemDefinition(
        system_id=QWEN_CEILING,
        controller_type=CONTROLLER_LEARNED,
        controller_id=LEARNED_CONTROLLER_ID,
        controller_version=LEARNED_CONTROLLER_VERSION,
        validator_id=GROUNDED_VALIDATOR_ID,
        validator_version=GROUNDED_VALIDATOR_VERSION,
        runner_id="qwen_cloud",
        runner_version=None,
        fallback_mode="none",
        requires_runner=True,
        requires_credentials=True,
        description=(
            "Optional live-Qwen extraction quality ceiling; requires "
            "credentials. Never committed as canonical evidence, never "
            "required for default validation."),
    ),
}

# The systems the default offline run evaluates end to end.
OFFLINE_SYSTEMS = (REFERENCE, GROUNDED_RULES)


def get_system(system_id: str) -> SystemDefinition:
    if system_id not in REGISTRY:
        raise KeyError(f"unknown grounded-extraction system: {system_id}")
    return REGISTRY[system_id]
