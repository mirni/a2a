"""Atlas Discovery & Brokering — composite scoring for agent services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AtlasScoreBreakdown:
    """Weighted composite score breakdown (0-100)."""

    trust_component: float  # 0-40
    reputation_component: float  # 0-30
    marketplace_component: float  # 0-20
    volume_component: float  # 0-10
    total: float  # 0-100

    class Config:
        json_schema_extra = {
            "example": {
                "trust_component": 32.0,
                "reputation_component": 18.0,
                "marketplace_component": 16.0,
                "volume_component": 8.0,
                "total": 74.0,
            }
        }


_WEIGHT_TRUST = 0.4
_WEIGHT_REPUTATION = 0.3
_WEIGHT_MARKETPLACE = 0.2
_WEIGHT_VOLUME = 0.1


def compute_atlas_score(
    trust_composite: float | None,
    reputation_composite: float | None,
    average_rating: float,
    transaction_volume_score: float | None,
) -> AtlasScoreBreakdown:
    """Compute a weighted Atlas composite score.

    Missing signals contribute 0 (penalizes unregistered providers).
    ``average_rating`` is on a 0-5 scale and is normalized to 0-100.
    """
    trust_val = trust_composite if trust_composite is not None else 0.0
    rep_val = reputation_composite if reputation_composite is not None else 0.0
    marketplace_val = (average_rating / 5.0) * 100.0 if average_rating else 0.0
    volume_val = transaction_volume_score if transaction_volume_score is not None else 0.0

    trust_component = round(trust_val * _WEIGHT_TRUST, 2)
    reputation_component = round(rep_val * _WEIGHT_REPUTATION, 2)
    marketplace_component = round(marketplace_val * _WEIGHT_MARKETPLACE, 2)
    volume_component = round(volume_val * _WEIGHT_VOLUME, 2)
    total = round(trust_component + reputation_component + marketplace_component + volume_component, 2)

    return AtlasScoreBreakdown(
        trust_component=trust_component,
        reputation_component=reputation_component,
        marketplace_component=marketplace_component,
        volume_component=volume_component,
        total=total,
    )
