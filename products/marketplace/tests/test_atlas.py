"""Tests for Atlas scoring module."""

from src.atlas import AtlasScoreBreakdown, compute_atlas_score


class TestComputeAtlasScore:
    def test_all_perfect(self):
        result = compute_atlas_score(
            trust_composite=100.0,
            reputation_composite=100.0,
            average_rating=5.0,
            transaction_volume_score=100.0,
        )
        assert result.total == 100.0
        assert isinstance(result, AtlasScoreBreakdown)

    def test_all_zero(self):
        result = compute_atlas_score(
            trust_composite=None,
            reputation_composite=None,
            average_rating=0.0,
            transaction_volume_score=None,
        )
        assert result.total == 0.0

    def test_trust_only(self):
        result = compute_atlas_score(
            trust_composite=80.0,
            reputation_composite=None,
            average_rating=0.0,
            transaction_volume_score=None,
        )
        assert result.trust_component == 32.0
        assert result.reputation_component == 0.0
        assert result.marketplace_component == 0.0
        assert result.volume_component == 0.0
        assert result.total == 32.0

    def test_reputation_only(self):
        result = compute_atlas_score(
            trust_composite=None,
            reputation_composite=100.0,
            average_rating=0.0,
            transaction_volume_score=None,
        )
        assert result.reputation_component == 30.0
        assert result.total == 30.0

    def test_marketplace_only(self):
        result = compute_atlas_score(
            trust_composite=None,
            reputation_composite=None,
            average_rating=5.0,
            transaction_volume_score=None,
        )
        assert result.marketplace_component == 20.0
        assert result.total == 20.0

    def test_volume_only(self):
        result = compute_atlas_score(
            trust_composite=None,
            reputation_composite=None,
            average_rating=0.0,
            transaction_volume_score=100.0,
        )
        assert result.volume_component == 10.0
        assert result.total == 10.0

    def test_weights_correct(self):
        result = compute_atlas_score(
            trust_composite=50.0,
            reputation_composite=60.0,
            average_rating=4.0,
            transaction_volume_score=80.0,
        )
        assert result.trust_component == 20.0
        assert result.reputation_component == 18.0
        assert result.marketplace_component == 16.0
        assert result.volume_component == 8.0
        assert result.total == 62.0

    def test_frozen_dataclass(self):
        result = compute_atlas_score(
            trust_composite=50.0,
            reputation_composite=50.0,
            average_rating=2.5,
            transaction_volume_score=50.0,
        )
        try:
            result.total = 0.0  # type: ignore[misc]
            assert False, "Should not be able to mutate frozen dataclass"
        except AttributeError:
            pass

    def test_partial_rating(self):
        result = compute_atlas_score(
            trust_composite=None,
            reputation_composite=None,
            average_rating=2.5,
            transaction_volume_score=None,
        )
        assert result.marketplace_component == 10.0
        assert result.total == 10.0

    def test_schema_extra(self):
        assert hasattr(AtlasScoreBreakdown, "Config")
        assert "example" in AtlasScoreBreakdown.Config.json_schema_extra
