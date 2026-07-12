"""Phase 11 Prompt 4: fusion configuration and normalization tests."""

import json
import math

import pytest

from experienceos.context.fusion import (
    DEFAULT_FUSION_PROFILE_ID,
    EMBEDDING_ONLY_PROFILE_ID,
    FUSION_COMPONENTS,
    FUSION_NORMALIZATION_ID,
    FUSION_PROFILES,
    REFERENCE_PROFILE_ID,
    FusionConfigError,
    RetrievalFusionProfile,
    fuse_components,
    normalize_component,
    resolve_fusion_profile,
    structured_aggregate,
)


def test_builtin_profiles_registered_and_reproducible():
    assert set(FUSION_PROFILES) == {
        "lexical_reference", "embedding_only", "lexical_semantic",
        "structured_semantic", "full_fusion",
    }
    assert REFERENCE_PROFILE_ID == "lexical_reference"
    assert EMBEDDING_ONLY_PROFILE_ID == "embedding_only"
    assert DEFAULT_FUSION_PROFILE_ID == "full_fusion"
    full = FUSION_PROFILES["full_fusion"]
    assert dict(full.component_weights) == {
        "lexical": 0.35, "structured": 0.25,
        "semantic": 0.30, "temporal": 0.10,
    }
    assert full.version == "1"
    assert full.normalization_id == FUSION_NORMALIZATION_ID


def test_profile_resolution():
    assert resolve_fusion_profile(None).profile_id == "full_fusion"
    assert resolve_fusion_profile("lexical_semantic").profile_id == (
        "lexical_semantic"
    )
    custom = RetrievalFusionProfile(
        profile_id="custom", version="1",
        component_weights={"semantic": 1.0},
    )
    assert resolve_fusion_profile(custom) is custom
    with pytest.raises(FusionConfigError):
        resolve_fusion_profile("does_not_exist")
    with pytest.raises(FusionConfigError):
        resolve_fusion_profile(42)


def test_profile_validation_rules():
    ok = {"lexical": 0.5, "semantic": 0.5}
    with pytest.raises(FusionConfigError):
        RetrievalFusionProfile("p", "1", {"lexical": -0.1})
    with pytest.raises(FusionConfigError):
        RetrievalFusionProfile("p", "1", {"lexical": float("nan")})
    with pytest.raises(FusionConfigError):
        RetrievalFusionProfile("p", "1", {"lexical": float("inf")})
    with pytest.raises(FusionConfigError):
        RetrievalFusionProfile("p", "1", {"unknown_component": 1.0})
    with pytest.raises(FusionConfigError):
        # All-zero relevance weights rejected for non-reference IDs.
        RetrievalFusionProfile("p", "1", {"temporal": 1.0})
    with pytest.raises(FusionConfigError):
        RetrievalFusionProfile("p", "1", ok, normalization_id="v99")
    profile = RetrievalFusionProfile("p", "1", ok)
    assert dict(profile.component_weights) == ok


def test_profile_immutable_and_serializable():
    profile = FUSION_PROFILES["full_fusion"]
    with pytest.raises(Exception):
        profile.profile_id = "hacked"
    with pytest.raises(TypeError):
        profile.component_weights["lexical"] = 99.0
    metadata = profile.to_metadata()
    assert json.loads(json.dumps(metadata)) == metadata


@pytest.mark.parametrize("name,scale", [("lexical", 3.0), ("structured", 2.0)])
def test_bounded_ratio_normalization(name, scale):
    assert normalize_component(name, 0.0) == 0.0
    assert normalize_component(name, scale) == 0.5
    typical = normalize_component(name, 2.0)
    large = normalize_component(name, 500.0)
    assert 0.0 < typical < large < 1.0  # monotonic, bounded
    assert math.isfinite(large)
    with pytest.raises(FusionConfigError):
        normalize_component(name, -1.0)
    with pytest.raises(FusionConfigError):
        normalize_component(name, float("nan"))


def test_semantic_and_temporal_normalization():
    assert normalize_component("semantic", 0.42) == 0.42
    with pytest.raises(FusionConfigError):
        normalize_component("semantic", 1.5)
    assert normalize_component("temporal", 0.85) == 0.85
    assert normalize_component("temporal", 3.0) == 1.0  # clipped
    with pytest.raises(FusionConfigError):
        normalize_component("unknown", 0.5)
    with pytest.raises(FusionConfigError):
        normalize_component("lexical", "high")


def test_unbounded_lexical_cannot_overwhelm_by_scale():
    """A huge raw lexical value asymptotes to weight*1.0 — it can never
    dwarf semantic evidence merely because it is unbounded."""
    profile = FUSION_PROFILES["lexical_semantic"]
    huge_lexical = fuse_components(
        profile, {"lexical": 10_000.0, "semantic": 0.0}
    )
    strong_semantic = fuse_components(
        profile, {"lexical": 0.0, "semantic": 1.0}
    )
    assert huge_lexical.fused_score <= 0.55 + 1e-9
    assert strong_semantic.fused_score == pytest.approx(0.45)


def test_fuse_components_breakdown_reconstructs_score():
    profile = FUSION_PROFILES["full_fusion"]
    breakdown = fuse_components(
        profile,
        {"lexical": 3.0, "structured": 2.0, "semantic": 0.6,
         "temporal": 0.4},
    )
    assert breakdown.normalized == {
        "lexical": 0.5, "structured": 0.5, "semantic": 0.6,
        "temporal": 0.4,
    }
    assert breakdown.fused_score == pytest.approx(
        0.35 * 0.5 + 0.25 * 0.5 + 0.30 * 0.6 + 0.10 * 0.4
    )
    assert breakdown.fused_score == pytest.approx(
        sum(breakdown.contributions.values())
    )
    assert set(breakdown.contributions) == set(FUSION_COMPONENTS)


def test_missing_component_contributes_exactly_zero():
    profile = FUSION_PROFILES["full_fusion"]
    breakdown = fuse_components(profile, {"lexical": 3.0})
    assert breakdown.normalized["semantic"] == 0.0
    assert breakdown.contributions["semantic"] == 0.0
    assert breakdown.contributions["temporal"] == 0.0
    assert breakdown.fused_score == pytest.approx(0.35 * 0.5)


def test_fusion_is_deterministic():
    profile = FUSION_PROFILES["full_fusion"]
    raw = {"lexical": 2.5, "structured": 1.2, "semantic": 0.7,
           "temporal": 0.1}
    assert fuse_components(profile, raw) == fuse_components(profile, raw)


def test_structured_aggregate_uses_strategy_weights():
    from experienceos.context.retrieval import SCORING_WEIGHTS

    scores = {
        "phrase_score": 1.0, "entity_score": 1.0, "attribute_score": 1.0,
        "value_score": 0.5, "scope_score": 0.0, "domain_score": 2.0,
    }
    expected = (1.5 * 1.0 + 2.0 * 1.0 + 1.2 * 1.0 + 1.5 * 0.5
                + 0.8 * 0.0 + 0.6 * 2.0)
    assert structured_aggregate(scores, SCORING_WEIGHTS) == pytest.approx(
        expected
    )
    assert structured_aggregate({}, SCORING_WEIGHTS) == 0.0


def test_strategy_rejects_profile_outside_fused_mode():
    from experienceos.context.retrieval import HybridRetrievalStrategy

    with pytest.raises(ValueError):
        HybridRetrievalStrategy(fusion_profile="full_fusion")


def test_fused_mode_requires_generator_except_reference():
    from experienceos.context.retrieval import HybridRetrievalStrategy

    with pytest.raises(ValueError):
        HybridRetrievalStrategy(semantic_mode="fused")  # needs generator
    reference = HybridRetrievalStrategy(
        semantic_mode="fused", fusion_profile="lexical_reference"
    )
    assert reference.fusion_profile.profile_id == "lexical_reference"
    summary = reference.summary()["semantic_retrieval"]
    assert summary["reference_bypass"] is True
