"""Edge case tests for Marketplace: best_match ranking, pagination, cost boundaries."""

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
    ServiceStatus,
)


def make_service(
    provider_id: str = "agent-1",
    name: str = "Test Service",
    description: str = "A test service",
    category: str = "testing",
    tools: list[str] | None = None,
    cost: float = 1.0,
    pricing_model: PricingModelType = PricingModelType.PER_CALL,
    tags: list[str] | None = None,
    endpoint: str = "https://example.com/mcp",
    uptime: float = 99.9,
    max_latency_ms: int = 200,
) -> ServiceCreate:
    return ServiceCreate(
        provider_id=provider_id,
        name=name,
        description=description,
        category=category,
        tools=tools or ["tool_a"],
        pricing=PricingModel(model=pricing_model, cost=cost),
        sla=SLA(uptime=uptime, max_latency_ms=max_latency_ms),
        tags=tags or ["test"],
        endpoint=endpoint,
    )


# ---------------------------------------------------------------------------
# 1. best_match edge cases
# ---------------------------------------------------------------------------


class TestBestMatchTiedScores:
    """Three services with identical descriptions matching the query should
    produce a deterministic ordering (all get the same text-match score)."""

    async def test_tied_scores_deterministic_ordering(self, marketplace):
        for i in range(3):
            await marketplace.register_service(make_service(
                provider_id=f"agent-{i}",
                name=f"translation service {i}",
                description="Translates text between languages",
                category="nlp",
                tags=["translation"],
                cost=1.0,
            ))

        matches_a = await marketplace.best_match(query="translation", limit=3)
        matches_b = await marketplace.best_match(query="translation", limit=3)
        assert len(matches_a) == 3
        assert len(matches_b) == 3

        # Ordering must be stable across calls
        ids_a = [m.service.id for m in matches_a]
        ids_b = [m.service.id for m in matches_b]
        assert ids_a == ids_b

        # All scores should be identical (same text match, same cost, no trust)
        scores = [m.rank_score for m in matches_a]
        assert scores[0] == scores[1] == scores[2]


class TestBestMatchPreferCostAllFree:
    """best_match with prefer=COST when all services are free."""

    async def test_all_free_services_returned(self, marketplace):
        for i in range(5):
            await marketplace.register_service(make_service(
                provider_id=f"free-{i}",
                name=f"Free Tool {i}",
                description="A free tool for testing",
                category="utils",
                cost=0.0,
                pricing_model=PricingModelType.FREE,
            ))

        matches = await marketplace.best_match(
            query="free", prefer=MatchPreference.COST, limit=10
        )
        assert len(matches) == 5
        for m in matches:
            assert m.service.pricing.cost == 0.0
            assert m.rank_score > 0  # Should have positive score from text match + free bonus
            assert "free" in m.match_reasons


class TestBestMatchPreferLatency:
    """prefer=LATENCY should rank lower-latency services higher."""

    async def test_latency_preference_ranks_low_latency_higher(self, marketplace):
        latencies = [50, 200, 500, 1000, 2000]
        for i, lat in enumerate(latencies):
            await marketplace.register_service(make_service(
                provider_id=f"lat-{i}",
                name=f"Latency Service {i}",
                description="Fast response service",
                category="perf",
                max_latency_ms=lat,
                cost=1.0,
            ))

        matches = await marketplace.best_match(
            query="service", prefer=MatchPreference.LATENCY, limit=5
        )
        assert len(matches) == 5
        # Lower latency should produce higher rank_score
        # Check that the service with 50ms latency outscores 2000ms
        latency_map = {m.service.sla.max_latency_ms: m.rank_score for m in matches}
        assert latency_map[50] > latency_map[2000]

    async def test_low_latency_reason_attached(self, marketplace):
        await marketplace.register_service(make_service(
            provider_id="fast",
            name="Fast API",
            description="Ultra fast API",
            category="perf",
            max_latency_ms=100,
            cost=1.0,
        ))

        matches = await marketplace.best_match(
            query="fast", prefer=MatchPreference.LATENCY, limit=1
        )
        assert len(matches) == 1
        assert "low_latency" in matches[0].match_reasons


class TestBestMatchEmptyQuery:
    """best_match with empty or None query should still work."""

    async def test_empty_string_query(self, marketplace):
        await marketplace.register_service(make_service(
            provider_id="a1", name="Some Service", cost=0.0,
            pricing_model=PricingModelType.FREE,
        ))
        matches = await marketplace.best_match(query="", limit=5)
        # Should return service(s) even without text match
        assert len(matches) >= 1


class TestBestMatchBudgetFilter:
    """best_match with budget should only return services within budget."""

    async def test_budget_filters_expensive_services(self, marketplace):
        costs = [0.0, 0.5, 1.0]
        for i, cost in enumerate(costs):
            pm = PricingModelType.FREE if cost == 0.0 else PricingModelType.PER_CALL
            await marketplace.register_service(make_service(
                provider_id=f"b-{i}",
                name=f"Budget Test {i}",
                description="Budget testing service",
                category="budget",
                cost=cost,
                pricing_model=pm,
            ))

        matches = await marketplace.best_match(query="budget", budget=0.5, limit=10)
        for m in matches:
            assert m.service.pricing.cost <= 0.5
        # Should include 0.0 and 0.5 but not 1.0
        returned_costs = sorted([m.service.pricing.cost for m in matches])
        assert 1.0 not in returned_costs
        assert 0.0 in returned_costs
        assert 0.5 in returned_costs


class TestBestMatchMinTrustNoProvider:
    """best_match with min_trust_score when no trust provider is configured."""

    async def test_min_trust_no_provider_returns_empty(self, marketplace):
        await marketplace.register_service(make_service(
            provider_id="a1", name="Service A",
        ))
        # No trust provider => trust_score is None for all services
        # min_trust_score filter requires trust_score >= threshold AND trust_score is not None
        matches = await marketplace.best_match(
            query="service", min_trust_score=80, limit=5
        )
        # Should return empty because trust_score is None
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# 2. Search pagination boundary
# ---------------------------------------------------------------------------


class TestSearchPagination:
    """Register 25 services and verify pagination across page boundaries."""

    async def _seed_25(self, marketplace):
        for i in range(25):
            await marketplace.register_service(make_service(
                provider_id=f"pag-{i}",
                name=f"Pagination Service {i:02d}",
                description="A service for pagination testing",
                category="pagination",
            ))

    async def test_first_page(self, marketplace):
        await self._seed_25(marketplace)
        params = ServiceSearchParams(limit=10, offset=0)
        results = await marketplace.search(params)
        assert len(results) == 10

    async def test_second_page(self, marketplace):
        await self._seed_25(marketplace)
        params = ServiceSearchParams(limit=10, offset=10)
        results = await marketplace.search(params)
        assert len(results) == 10

    async def test_third_page_partial(self, marketplace):
        await self._seed_25(marketplace)
        params = ServiceSearchParams(limit=10, offset=20)
        results = await marketplace.search(params)
        assert len(results) == 5

    async def test_beyond_last_page(self, marketplace):
        await self._seed_25(marketplace)
        params = ServiceSearchParams(limit=10, offset=30)
        results = await marketplace.search(params)
        assert len(results) == 0

    async def test_no_duplicates_across_pages(self, marketplace):
        await self._seed_25(marketplace)
        all_ids: set[str] = set()
        for offset in range(0, 30, 10):
            params = ServiceSearchParams(limit=10, offset=offset)
            results = await marketplace.search(params)
            for svc in results:
                assert svc.id not in all_ids, f"Duplicate service id: {svc.id}"
                all_ids.add(svc.id)
        assert len(all_ids) == 25


# ---------------------------------------------------------------------------
# 3. Search with max_cost at boundary
# ---------------------------------------------------------------------------


class TestSearchMaxCostBoundary:
    """Test max_cost filtering at exact boundary values."""

    async def _seed_costs(self, marketplace):
        costs = [0.0, 0.5, 1.0, 1.5, 2.0]
        for i, cost in enumerate(costs):
            pm = PricingModelType.FREE if cost == 0.0 else PricingModelType.PER_CALL
            await marketplace.register_service(make_service(
                provider_id=f"cost-{i}",
                name=f"Cost Service {i}",
                description="Cost boundary service",
                category="cost-test",
                cost=cost,
                pricing_model=pm,
            ))

    async def test_max_cost_one(self, marketplace):
        await self._seed_costs(marketplace)
        params = ServiceSearchParams(max_cost=1.0)
        results = await marketplace.search(params)
        assert len(results) == 3  # 0.0, 0.5, 1.0
        for svc in results:
            assert svc.pricing.cost <= 1.0

    async def test_max_cost_zero(self, marketplace):
        await self._seed_costs(marketplace)
        params = ServiceSearchParams(max_cost=0.0)
        results = await marketplace.search(params)
        assert len(results) == 1  # only 0.0
        assert results[0].pricing.cost == 0.0

    async def test_max_cost_with_pagination(self, marketplace):
        await self._seed_costs(marketplace)
        # Only 3 services cost <= 1.0; fetch with limit=2
        params = ServiceSearchParams(max_cost=1.0, limit=2, offset=0)
        page1 = await marketplace.search(params)
        assert len(page1) == 2

        params = ServiceSearchParams(max_cost=1.0, limit=2, offset=2)
        page2 = await marketplace.search(params)
        assert len(page2) == 1

        all_costs = [s.pricing.cost for s in page1 + page2]
        assert all(c <= 1.0 for c in all_costs)

        # No duplicates
        ids = [s.id for s in page1 + page2]
        assert len(ids) == len(set(ids))
