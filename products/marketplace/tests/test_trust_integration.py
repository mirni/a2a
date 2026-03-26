"""Tests for marketplace + trust provider integration.

TDD: These tests verify that when a real trust_provider callable is wired
into the Marketplace, search and best_match populate trust_score correctly.
"""

from __future__ import annotations

import pytest

from src.marketplace import Marketplace
from src.models import (
    MatchPreference,
    PricingModel,
    PricingModelType,
    SLA,
    ServiceCreate,
    ServiceSearchParams,
    SortBy,
)
from src.storage import MarketplaceStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_service(
    provider_id: str = "agent-1",
    name: str = "Test Service",
    description: str = "A test service",
    category: str = "testing",
    cost: float = 1.0,
    tags: list[str] | None = None,
) -> ServiceCreate:
    return ServiceCreate(
        provider_id=provider_id,
        name=name,
        description=description,
        category=category,
        tools=["tool_a"],
        pricing=PricingModel(model=PricingModelType.PER_CALL, cost=cost),
        sla=SLA(uptime=99.9, max_latency_ms=200),
        tags=tags or ["test"],
        endpoint="https://example.com/mcp",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def storage():
    s = MarketplaceStorage(dsn="sqlite:///:memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def trust_scores():
    """Mutable dict of provider_id -> score, simulating TrustAPI."""
    return {}


@pytest.fixture
async def marketplace_with_trust(storage, trust_scores):
    """Marketplace wired with a callable trust provider backed by trust_scores dict."""

    async def trust_provider(server_id: str) -> float | None:
        return trust_scores.get(server_id)

    return Marketplace(storage=storage, trust_provider=trust_provider)


# ---------------------------------------------------------------------------
# Tests: search returns trust_score
# ---------------------------------------------------------------------------

class TestSearchWithTrustProvider:
    """Search populates trust_score when trust_provider is wired."""

    async def test_search_returns_trust_score(self, marketplace_with_trust, trust_scores):
        """Services returned by search should carry the provider's trust_score."""
        trust_scores["provider-a"] = 92.5

        await marketplace_with_trust.register_service(
            make_service(provider_id="provider-a", name="Trusted Svc")
        )

        results = await marketplace_with_trust.search()
        assert len(results) == 1
        assert results[0].trust_score == 92.5

    async def test_search_multiple_providers_different_scores(
        self, marketplace_with_trust, trust_scores
    ):
        """Each service should get its own provider's trust score."""
        trust_scores["p1"] = 95.0
        trust_scores["p2"] = 60.0

        await marketplace_with_trust.register_service(
            make_service(provider_id="p1", name="High Trust")
        )
        await marketplace_with_trust.register_service(
            make_service(provider_id="p2", name="Low Trust")
        )

        results = await marketplace_with_trust.search()
        scores_by_name = {r.name: r.trust_score for r in results}
        assert scores_by_name["High Trust"] == 95.0
        assert scores_by_name["Low Trust"] == 60.0

    async def test_sort_by_trust_score(self, marketplace_with_trust, trust_scores):
        """sort_by=TRUST_SCORE should order services by their actual trust scores."""
        trust_scores["low"] = 30.0
        trust_scores["mid"] = 60.0
        trust_scores["high"] = 90.0

        await marketplace_with_trust.register_service(
            make_service(provider_id="low", name="Low")
        )
        await marketplace_with_trust.register_service(
            make_service(provider_id="mid", name="Mid")
        )
        await marketplace_with_trust.register_service(
            make_service(provider_id="high", name="High")
        )

        params = ServiceSearchParams(sort_by=SortBy.TRUST_SCORE, sort_desc=True)
        results = await marketplace_with_trust.search(params)
        trust_values = [r.trust_score for r in results]
        assert trust_values == [90.0, 60.0, 30.0]

    async def test_sort_by_trust_score_ascending(self, marketplace_with_trust, trust_scores):
        """sort_by=TRUST_SCORE ascending should put lowest first."""
        trust_scores["low"] = 20.0
        trust_scores["high"] = 80.0

        await marketplace_with_trust.register_service(
            make_service(provider_id="high", name="High")
        )
        await marketplace_with_trust.register_service(
            make_service(provider_id="low", name="Low")
        )

        params = ServiceSearchParams(sort_by=SortBy.TRUST_SCORE, sort_desc=False)
        results = await marketplace_with_trust.search(params)
        assert results[0].trust_score == 20.0
        assert results[1].trust_score == 80.0


# ---------------------------------------------------------------------------
# Tests: best_match with prefer=TRUST
# ---------------------------------------------------------------------------

class TestBestMatchWithTrust:
    """best_match with prefer=TRUST should rank by actual trust scores."""

    async def test_best_match_prefers_trust(self, marketplace_with_trust, trust_scores):
        """Higher trust should rank first even if the service costs more."""
        trust_scores["trusted"] = 95.0
        trust_scores["cheap"] = 20.0

        await marketplace_with_trust.register_service(
            make_service(
                provider_id="trusted", name="Trusted Data",
                description="data service", cost=5.0, tags=["data"],
            )
        )
        await marketplace_with_trust.register_service(
            make_service(
                provider_id="cheap", name="Cheap Data",
                description="data service", cost=0.1, tags=["data"],
            )
        )

        matches = await marketplace_with_trust.best_match(
            query="data", prefer=MatchPreference.TRUST
        )
        assert len(matches) >= 2
        # Trusted provider should rank higher
        assert matches[0].service.provider_id == "trusted"
        assert "high_trust" in matches[0].match_reasons

    async def test_best_match_trust_scores_in_results(
        self, marketplace_with_trust, trust_scores
    ):
        """Service objects in match results should carry trust_score."""
        trust_scores["prov"] = 88.0

        await marketplace_with_trust.register_service(
            make_service(provider_id="prov", name="Scored Service", tags=["test"])
        )

        matches = await marketplace_with_trust.best_match(query="test")
        assert matches[0].service.trust_score == 88.0


# ---------------------------------------------------------------------------
# Tests: fallback when trust_provider returns None
# ---------------------------------------------------------------------------

class TestTrustProviderFallback:
    """When the trust provider returns None (server not found), trust_score = None."""

    async def test_unknown_provider_gets_none(self, marketplace_with_trust, trust_scores):
        """Provider not in trust system should get trust_score=None."""
        # trust_scores dict is empty - provider "unknown" won't be found
        await marketplace_with_trust.register_service(
            make_service(provider_id="unknown", name="Unknown Svc")
        )

        results = await marketplace_with_trust.search()
        assert len(results) == 1
        assert results[0].trust_score is None

    async def test_exception_in_trust_provider_returns_none(self, storage):
        """If trust provider raises an exception, trust_score should be None."""

        async def broken_provider(server_id: str) -> float | None:
            raise RuntimeError("Trust system down")

        mp = Marketplace(storage=storage, trust_provider=broken_provider)

        await mp.register_service(
            make_service(provider_id="any", name="Any Svc")
        )

        results = await mp.search()
        assert len(results) == 1
        assert results[0].trust_score is None

    async def test_min_trust_filter_excludes_none(self, marketplace_with_trust, trust_scores):
        """Services with trust_score=None should be excluded by min_trust_score filter."""
        trust_scores["known"] = 85.0
        # "unknown" provider not in trust_scores -> returns None

        await marketplace_with_trust.register_service(
            make_service(provider_id="known", name="Known")
        )
        await marketplace_with_trust.register_service(
            make_service(provider_id="unknown", name="Unknown")
        )

        params = ServiceSearchParams(min_trust_score=50.0)
        results = await marketplace_with_trust.search(params)
        assert len(results) == 1
        assert results[0].name == "Known"
