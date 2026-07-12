"""Deterministic retrieval score fusion (Phase 11, Prompt 4).

Pure configuration and math: this module normalizes already-computed
retrieval component scores and combines them under fixed, versioned
weight profiles. It performs no embedding, no provider access, no
store access, and no lifecycle reasoning — the retrieval strategy
feeds it raw component values for lifecycle-admitted candidates only,
and it returns an inspectable breakdown.

Component classification (audited against the live code):

- **Primary query relevance**: ``lexical`` (unbounded BM25-style IDF
  sum, ``lexical_score``), ``structured`` (the weighted
  phrase/entity/attribute/value/scope/domain aggregate, bounded-ish
  small values), ``semantic`` (Prompt 3 score, already [0, 1]).
- **Compatibility evidence**: ``temporal`` — the temporal policy's
  bounded additive bonus (max ≈ 0.85), which already contains the
  only implemented provenance signal (``trust_score``); no separate
  provenance component exists in the codebase and none is invented.
- **Rank refiners** (never fused, never create relevance): memory-kind
  priority, confidence, recency, stable ID — applied in the shared
  deterministic sort after the fused score.
- **Hard eligibility** (never a weight): user scope, lifecycle state,
  explicit historical admission.

Normalization ``bounded_ratio-1``: monotonic, deterministic,
per-candidate (never per-query min-max, so identical raw evidence
always means the same normalized value):

- ``lexical``: ``x / (x + 3.0)`` — 3.0 is the midpoint of observed
  matched-sum magnitudes on deterministic fixtures (single-token match
  ≈ 1.8 → 0.37, strong multi-token ≈ 5.4 → 0.64).
- ``structured``: ``x / (x + 2.0)`` over the SCORING_WEIGHTS-weighted
  structured aggregate (entity+phrase pair ≈ 3.5 → 0.64).
- ``semantic``: identity (already [0, 1]).
- ``temporal``: ``min(x, 1.0)`` — the bonus is bounded ≈ 0.85 by
  construction, so clipping documents the range without reshaping it.

Weights are architectural starting values chosen from score ranges,
signal precision, and exact-match preservation — never from benchmark
labels. Prompt 7 measures whether any profile deserves adoption.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

FUSION_NORMALIZATION_ID = "bounded_ratio-1"
FUSION_PROFILE_VERSION = "1"

_LEXICAL_SCALE = 3.0
_STRUCTURED_SCALE = 2.0

FUSION_COMPONENTS = ("lexical", "structured", "semantic", "temporal")
RELEVANCE_COMPONENTS = ("lexical", "structured", "semantic")

# Structured aggregate = these raw component_scores keys, weighted by
# the strategy's existing SCORING_WEIGHTS entries of the same name.
STRUCTURED_SIGNALS = (
    "phrase", "entity", "attribute", "value", "scope", "domain",
)


class FusionConfigError(ValueError):
    """An explicitly requested fusion configuration is invalid."""


def _bounded_ratio(value: float, scale: float) -> float:
    if value < 0.0:
        raise FusionConfigError(f"negative component value {value!r}")
    return value / (value + scale)


def normalize_component(name: str, value: float) -> float:
    """Deterministic per-component normalization into [0, 1]."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FusionConfigError(f"non-numeric {name} value {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise FusionConfigError(f"non-finite {name} value")
    if name == "lexical":
        return round(_bounded_ratio(value, _LEXICAL_SCALE), 6)
    if name == "structured":
        return round(_bounded_ratio(value, _STRUCTURED_SCALE), 6)
    if name == "semantic":
        if not 0.0 <= value <= 1.0:
            raise FusionConfigError("semantic score outside [0, 1]")
        return round(value, 6)
    if name == "temporal":
        if value < 0.0:
            raise FusionConfigError("negative temporal bonus")
        return round(min(value, 1.0), 6)
    raise FusionConfigError(f"unknown fusion component {name!r}")


@dataclass(frozen=True)
class RetrievalFusionProfile:
    """Immutable, versioned, serializable fusion configuration."""

    profile_id: str
    version: str
    component_weights: Mapping[str, float]
    semantic_floor_rule: str = "semantic_only_candidates"
    normalization_id: str = FUSION_NORMALIZATION_ID

    def __post_init__(self):
        object.__setattr__(
            self,
            "component_weights",
            MappingProxyType(dict(self.component_weights)),
        )
        if self.normalization_id != FUSION_NORMALIZATION_ID:
            raise FusionConfigError(
                f"unknown normalization {self.normalization_id!r}"
            )
        for name, weight in self.component_weights.items():
            if name not in FUSION_COMPONENTS:
                raise FusionConfigError(f"unknown component {name!r}")
            if (
                not isinstance(weight, (int, float))
                or isinstance(weight, bool)
                or not math.isfinite(float(weight))
            ):
                raise FusionConfigError(f"invalid weight for {name!r}")
            if weight < 0.0:
                raise FusionConfigError(f"negative weight for {name!r}")
        if self.profile_id != REFERENCE_PROFILE_ID and not any(
            self.component_weights.get(name, 0.0) > 0.0
            for name in RELEVANCE_COMPONENTS
        ):
            raise FusionConfigError(
                "a fused profile needs at least one positive relevance "
                "weight"
            )

    def to_metadata(self) -> dict:
        """Digest-stable, serializable profile description."""
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "component_weights": dict(self.component_weights),
            "semantic_floor_rule": self.semantic_floor_rule,
            "normalization_id": self.normalization_id,
        }


@dataclass(frozen=True)
class FusionBreakdown:
    """One candidate's complete, reconstructable fusion evidence."""

    raw: dict = field(default_factory=dict)
    normalized: dict = field(default_factory=dict)
    weights: dict = field(default_factory=dict)
    contributions: dict = field(default_factory=dict)
    fused_score: float = 0.0


def fuse_components(
    profile: RetrievalFusionProfile, raw: Mapping[str, float]
) -> FusionBreakdown:
    """Normalize raw components and combine under the profile.

    A component absent from ``raw`` (or weighted zero) contributes
    exactly 0.0 — missing evidence is never fabricated. The fused
    score is the plain weighted sum, reconstructable from the
    returned contributions.
    """
    normalized: dict = {}
    contributions: dict = {}
    fused = 0.0
    weights = dict(profile.component_weights)
    for name in FUSION_COMPONENTS:
        weight = weights.get(name, 0.0)
        if name in raw:
            normalized[name] = normalize_component(name, raw[name])
        else:
            normalized[name] = 0.0
        contribution = round(weight * normalized[name], 6)
        contributions[name] = contribution
        fused += contribution
    return FusionBreakdown(
        raw={k: round(float(v), 6) for k, v in raw.items()},
        normalized=normalized,
        weights=weights,
        contributions=contributions,
        fused_score=round(fused, 6),
    )


REFERENCE_PROFILE_ID = "lexical_reference"
EMBEDDING_ONLY_PROFILE_ID = "embedding_only"
DEFAULT_FUSION_PROFILE_ID = "full_fusion"

FUSION_PROFILES: dict = {}


def _register(profile: RetrievalFusionProfile) -> RetrievalFusionProfile:
    FUSION_PROFILES[profile.profile_id] = profile
    return profile


# Reference: routes through the unchanged Phase 9 lexical path; the
# weights below are documentation only — fusion math never runs and
# the embedding provider is never inspected.
LEXICAL_REFERENCE = _register(
    RetrievalFusionProfile(
        profile_id=REFERENCE_PROFILE_ID,
        version=FUSION_PROFILE_VERSION,
        component_weights={},
    )
)

# Delegates to the Prompt 3 semantic_only path: semantic evidence and
# non-relevance refiners only, lexical never mixed in.
EMBEDDING_ONLY = _register(
    RetrievalFusionProfile(
        profile_id=EMBEDDING_ONLY_PROFILE_ID,
        version=FUSION_PROFILE_VERSION,
        component_weights={"semantic": 1.0},
    )
)

# Ablation: token-level lexical evidence plus semantic evidence only.
LEXICAL_SEMANTIC = _register(
    RetrievalFusionProfile(
        profile_id="lexical_semantic",
        version=FUSION_PROFILE_VERSION,
        component_weights={"lexical": 0.55, "semantic": 0.45},
    )
)

# Ablation: the structured aggregate (phrase/entity/attribute/value/
# scope/domain — the WHOLE lexical token aggregate is excluded, not
# just exact matches) plus semantic evidence.
STRUCTURED_SEMANTIC = _register(
    RetrievalFusionProfile(
        profile_id="structured_semantic",
        version=FUSION_PROFILE_VERSION,
        component_weights={"structured": 0.55, "semantic": 0.45},
    )
)

# Default full fusion: lexical+structured keep the majority (0.60) so
# exact matches stay competitive; semantic (0.30) can lift lexically
# missed candidates; temporal compatibility (0.10) refines. Starting
# values from the range audit — not benchmark-optimized, and Prompt 7
# may classify this profile as experimental.
FULL_FUSION = _register(
    RetrievalFusionProfile(
        profile_id=DEFAULT_FUSION_PROFILE_ID,
        version=FUSION_PROFILE_VERSION,
        component_weights={
            "lexical": 0.35,
            "structured": 0.25,
            "semantic": 0.30,
            "temporal": 0.10,
        },
    )
)


def resolve_fusion_profile(
    profile: RetrievalFusionProfile | str | None,
) -> RetrievalFusionProfile:
    if profile is None:
        return FUSION_PROFILES[DEFAULT_FUSION_PROFILE_ID]
    if isinstance(profile, RetrievalFusionProfile):
        return profile
    if isinstance(profile, str):
        try:
            return FUSION_PROFILES[profile]
        except KeyError:
            raise FusionConfigError(
                f"unknown fusion profile {profile!r}; known: "
                f"{sorted(FUSION_PROFILES)}"
            ) from None
    raise FusionConfigError(f"invalid fusion profile {profile!r}")


def structured_aggregate(
    component_scores: Mapping[str, float], weights: Mapping[str, float]
) -> float:
    """The raw structured aggregate: existing per-signal raw scores
    weighted by the strategy's own SCORING_WEIGHTS entries."""
    total = 0.0
    for signal in STRUCTURED_SIGNALS:
        raw = component_scores.get(f"{signal}_score", 0.0)
        total += float(weights.get(signal, 0.0)) * float(raw)
    return round(total, 6)
