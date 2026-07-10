"""Run provenance contract with sanitization.

Every benchmark run records enough provenance to reproduce it — and
nothing that should not live in a repository. Model paths are reduced
to basenames, home-directory prefixes are rejected, and secrets are
never fields at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath

from benchmarks.contract.serialization import canonical_json

PROVENANCE_SCHEMA_VERSION = "1"

# Substrings that must never appear in a committed provenance payload.
FORBIDDEN_PATH_MARKERS = ("/Users/", "/home/", "\\Users\\")
FORBIDDEN_KEY_MARKERS = ("api_key", "authorization", "secret", "token_value")


class UnsafeProvenance(ValueError):
    """Raised when a provenance payload contains unsafe content."""


def safe_model_name(model_path: str | None) -> str | None:
    """Reduce a local model path to its basename — never the full path."""
    if model_path is None:
        return None
    return PurePath(model_path).name


@dataclass(frozen=True)
class RunProvenance:
    run_id: str
    repository_commit: str
    working_tree_clean: bool
    suite_version: str
    manifest_version: str
    manifest_hash: str
    run_timestamp_utc: str
    provider_name: str
    response_model: str
    memory_policy: str
    storage_mode: str
    retrieval_description: str
    context_budget: int
    selection_k: int | None
    temperature: float | None
    max_output_tokens: int | None
    seed: int
    retry_policy: str
    platform: str
    python_version: str
    local_model_name: str | None = None
    used_real_provider: bool = False
    used_real_local_model: bool = False
    used_mock: bool = True
    used_fallback: bool = False
    evaluator_type: str = "deterministic"
    evaluator_model: str | None = None
    executed_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    skipped_cases: int = 0
    partial_cases: int = 0
    notes: tuple[str, ...] = field(default=())

    def to_payload(self) -> dict:
        return {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "repository_commit": self.repository_commit,
            "working_tree_clean": self.working_tree_clean,
            "suite_version": self.suite_version,
            "manifest_version": self.manifest_version,
            "manifest_hash": self.manifest_hash,
            "run_timestamp_utc": self.run_timestamp_utc,
            "provider_name": self.provider_name,
            "response_model": self.response_model,
            "memory_policy": self.memory_policy,
            "storage_mode": self.storage_mode,
            "retrieval_description": self.retrieval_description,
            "context_budget": self.context_budget,
            "selection_k": self.selection_k,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "seed": self.seed,
            "retry_policy": self.retry_policy,
            "platform": self.platform,
            "python_version": self.python_version,
            "local_model_name": self.local_model_name,
            "used_real_provider": self.used_real_provider,
            "used_real_local_model": self.used_real_local_model,
            "used_mock": self.used_mock,
            "used_fallback": self.used_fallback,
            "evaluator_type": self.evaluator_type,
            "evaluator_model": self.evaluator_model,
            "executed_cases": self.executed_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "skipped_cases": self.skipped_cases,
            "partial_cases": self.partial_cases,
            "notes": list(self.notes),
        }


def assert_provenance_safe(provenance: RunProvenance) -> None:
    """Reject provenance carrying personal paths or secret-like keys.

    Runs over the serialized payload so nested additions cannot slip
    unsafe content past field-by-field checks.
    """
    body = canonical_json(provenance.to_payload())
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker in body:
            raise UnsafeProvenance(
                f"provenance contains a personal path marker {marker!r}; "
                "store basenames only (see safe_model_name)"
            )
    lowered = body.lower()
    for marker in FORBIDDEN_KEY_MARKERS:
        if f'"{marker}"' in lowered:
            raise UnsafeProvenance(
                f"provenance contains a secret-like key {marker!r}"
            )
