"""Tests for the Marketplace API."""

import pytest

from src.marketplace import (
    DuplicateServiceError,
    Marketplace,
    ServiceNotFoundError,
)
from src.models import (
    MatchPreference,
    PricingModel,
    PricingModelType,
    SLA,
    ServiceCreate,
    ServiceSearchParams,
    ServiceStatus,
    SortBy,
)

from src.models import ServiceCreate


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
        tools=tools or ["tool_a", "tool_b"],
        pricing=PricingModel(model=pricing_model, cost=cost),
        sla=SLA(uptime=uptime, max_latency_ms=max_latency_ms),
        tags=tags or ["test"],
        endpoint=endpoint,
    )


class TestRegisterService:
    async def test_register_basic(self, marketplace):
        spec = make_service(name="My Service")
        svc = await marketplace.register_service(spec)
        assert svc.id.startswith("svc-")
        assert svc.name == "My Service"
        assert svc.status == ServiceStatus.ACTIVE

    async def test_register_with_tools(self, marketplace):
        spec = make_service(tools=["get_price", "get_orders"])
        svc = await marketplace.register_service(spec)
        assert set(svc.tools) == {"get_price", "get_orders"}

    async def test_register_with_tags(self, marketplace):
        spec = make_service(tags=["crypto", "real-time"])
        svc = await marketplace.register_service(spec)
        assert set(svc.tags) == {"crypto", "real-time"}

    async def test_register_with_pricing(self, marketplace):
        spec = make_service(cost=5.0, pricing_model=PricingModelType.PER_TOKEN)
        svc = await marketplace.register_service(spec)
        assert svc.pricing.model == PricingModelType.PER_TOKEN
        assert svc.pricing.cost == 5.0

    async def test_register_with_sla(self, marketplace):
        spec = make_service(uptime=99.99, max_latency_ms=50)
        svc = await marketplace.register_service(spec)
        assert svc.sla.uptime == 99.99
        assert svc.sla.max_latency_ms == 50

    async def test_register_duplicate_name_raises(self, marketplace):
        spec = make_service(name="Unique")
        await marketplace.register_service(spec)
        with pytest.raises(DuplicateServiceError):
            await marketplace.register_service(spec)

    async def test_register_same_name_different_provider(self, marketplace):
        spec1 = make_service(provider_id="agent-1", name="Shared Name")
        spec2 = make_service(provider_id="agent-2", name="Shared Name")
        s1 = await marketplace.register_service(spec1)
        s2 = await marketplace.register_service(spec2)
        assert s1.id != s2.id

    async def test_register_empty_name_raises(self, marketplace):
        spec = make_service(name="")
        with pytest.raises(ValueError, match="name"):
            await marketplace.register_service(spec)

    async def test_register_empty_provider_raises(self, marketplace):
        spec = make_service(provider_id="")
        with pytest.raises(ValueError, match="Provider"):
            await marketplace.register_service(spec)

    async def test_register_empty_category_raises(self, marketplace):
        spec = make_service(category="")
        with pytest.raises(ValueError, match="Category"):
            await marketplace.register_service(spec)

    async def test_register_with_endpoint(self, marketplace):
        spec = make_service(endpoint="https://my-server.com/mcp")
        svc = await marketplace.register_service(spec)
        assert svc.endpoint == "https://my-server.com/mcp"


class TestGetService:
    async def test_get_existing(self, marketplace):
        spec = make_service(name="Findable")
        created = await marketplace.register_service(spec)
        found = await marketplace.get_service(created.id)
        assert found.name == "Findable"

    async def test_get_nonexistent_raises(self, marketplace):
        with pytest.raises(ServiceNotFoundError):
            await marketplace.get_service("svc-missing")


class TestUpdateService:
    async def test_update_name(self, marketplace):
        spec = make_service(name="Old")
        svc = await marketplace.register_service(spec)
        updated = await marketplace.update_service(svc.id, name="New")
        assert updated.name == "New"

    async def test_update_description(self, marketplace):
        spec = make_service()
        svc = await marketplace.register_service(spec)
        updated = await marketplace.update_service(svc.id, description="Updated desc")
        assert updated.description == "Updated desc"

    async def test_update_pricing(self, marketplace):
        spec = make_service()
        svc = await marketplace.register_service(spec)
        new_pricing = PricingModel(model=PricingModelType.SUBSCRIPTION, cost=100.0)
        updated = await marketplace.update_service(svc.id, pricing=new_pricing)
        assert updated.pricing.model == PricingModelType.SUBSCRIPTION

    async def test_update_tools(self, marketplace):
        spec = make_service(tools=["old_tool"])
        svc = await marketplace.register_service(spec)
        updated = await marketplace.update_service(svc.id, tools=["new_a", "new_b"])
        assert set(updated.tools) == {"new_a", "new_b"}

    async def test_update_nonexistent_raises(self, marketplace):
        with pytest.raises(ServiceNotFoundError):
            await marketplace.update_service("svc-nope", name="X")


class TestDeactivateService:
    async def test_deactivate(self, marketplace):
        spec = make_service()
        svc = await marketplace.register_service(spec)
        deactivated = await marketplace.deactivate_service(svc.id)
        assert deactivated.status == ServiceStatus.INACTIVE

    async def test_deactivate_nonexistent_raises(self, marketplace):
        with pytest.raises(ServiceNotFoundError):
            await marketplace.deactivate_service("svc-nope")

    async def test_deactivated_not_in_search(self, marketplace):
        spec = make_service()
        svc = await marketplace.register_service(spec)
        await marketplace.deactivate_service(svc.id)
        results = await marketplace.search()
        assert len(results) == 0


class TestSearch:
    async def _seed_marketplace(self, marketplace):
        await marketplace.register_service(make_service(
            provider_id="a1", name="Crypto Prices", description="Real-time crypto data",
            category="market-data", tags=["crypto", "real-time"], cost=0.5,
        ))
        await marketplace.register_service(make_service(
            provider_id="a2", name="SQL Analytics", description="Database analytics engine",
            category="analytics", tags=["analytics", "sql"], cost=2.0,
        ))
        await marketplace.register_service(make_service(
            provider_id="a3", name="Free Ping", description="Free health check tool",
            category="utilities", tags=["free", "health"], cost=0.0,
            pricing_model=PricingModelType.FREE,
        ))

    async def test_search_all(self, marketplace):
        await self._seed_marketplace(marketplace)
        results = await marketplace.search()
        assert len(results) == 3

    async def test_search_by_query(self, marketplace):
        await self._seed_marketplace(marketplace)
        params = ServiceSearchParams(query="crypto")
        results = await marketplace.search(params)
        assert len(results) == 1
        assert results[0].name == "Crypto Prices"

    async def test_search_by_category(self, marketplace):
        await self._seed_marketplace(marketplace)
        params = ServiceSearchParams(category="analytics")
        results = await marketplace.search(params)
        assert len(results) == 1

    async def test_search_by_tags(self, marketplace):
        await self._seed_marketplace(marketplace)
        params = ServiceSearchParams(tags=["crypto"])
        results = await marketplace.search(params)
        assert len(results) == 1

    async def test_search_by_max_cost(self, marketplace):
        await self._seed_marketplace(marketplace)
        params = ServiceSearchParams(max_cost=1.0)
        results = await marketplace.search(params)
        assert len(results) == 2

    async def test_search_with_limit(self, marketplace):
        await self._seed_marketplace(marketplace)
        params = ServiceSearchParams(limit=2)
        results = await marketplace.search(params)
        assert len(results) == 2

    async def test_search_empty(self, marketplace):
        results = await marketplace.search()
        assert results == []

    async def test_search_sort_by_cost(self, marketplace):
        await self._seed_marketplace(marketplace)
        params = ServiceSearchParams(sort_by=SortBy.COST, sort_desc=False)
        results = await marketplace.search(params)
        costs = [r.pricing.cost for r in results]
        assert costs == sorted(costs)

    async def test_search_sort_by_name(self, marketplace):
        await self._seed_marketplace(marketplace)
        params = ServiceSearchParams(sort_by=SortBy.NAME, sort_desc=False)
        results = await marketplace.search(params)
        names = [r.name.lower() for r in results]
        assert names == sorted(names)

    async def test_search_kwargs_shorthand(self, marketplace):
        await self._seed_marketplace(marketplace)
        results = await marketplace.search(category="analytics")
        assert len(results) == 1


class TestSearchWithTrust:
    async def test_min_trust_filters(self, marketplace_with_trust):
        mp = marketplace_with_trust
        mp._trust_scores["a1"] = 90.0
        mp._trust_scores["a2"] = 40.0

        await mp.register_service(make_service(provider_id="a1", name="Trusted"))
        await mp.register_service(make_service(provider_id="a2", name="Untrusted"))

        params = ServiceSearchParams(min_trust_score=50.0)
        results = await mp.search(params)
        assert len(results) == 1
        assert results[0].name == "Trusted"

    async def test_trust_score_attached(self, marketplace_with_trust):
        mp = marketplace_with_trust
        mp._trust_scores["a1"] = 85.0

        await mp.register_service(make_service(provider_id="a1", name="Scored"))
        results = await mp.search()
        assert results[0].trust_score == 85.0

    async def test_no_trust_provider_returns_none(self, marketplace):
        await marketplace.register_service(make_service())
        results = await marketplace.search()
        assert results[0].trust_score is None


class TestBestMatch:
    async def _seed(self, marketplace):
        await marketplace.register_service(make_service(
            provider_id="a1", name="Crypto Feed", description="Real-time crypto prices",
            category="market-data", tags=["crypto"], cost=0.5,
        ))
        await marketplace.register_service(make_service(
            provider_id="a2", name="Crypto Premium", description="Premium crypto data",
            category="market-data", tags=["crypto", "premium"], cost=5.0,
        ))
        await marketplace.register_service(make_service(
            provider_id="a3", name="Stock Data", description="US stock market data",
            category="market-data", tags=["stocks"], cost=1.0,
        ))

    async def test_basic_match(self, marketplace):
        await self._seed(marketplace)
        matches = await marketplace.best_match(query="crypto")
        assert len(matches) >= 1
        # Crypto services should rank higher
        assert "crypto" in matches[0].service.name.lower()

    async def test_match_with_budget(self, marketplace):
        await self._seed(marketplace)
        matches = await marketplace.best_match(query="crypto", budget=2.0)
        for m in matches:
            assert m.service.pricing.cost <= 2.0

    async def test_match_limit(self, marketplace):
        await self._seed(marketplace)
        matches = await marketplace.best_match(query="data", limit=2)
        assert len(matches) <= 2

    async def test_match_has_reasons(self, marketplace):
        await self._seed(marketplace)
        matches = await marketplace.best_match(query="crypto")
        assert len(matches[0].match_reasons) > 0

    async def test_match_prefer_cost(self, marketplace):
        await self._seed(marketplace)
        matches = await marketplace.best_match(
            query="crypto", prefer=MatchPreference.COST
        )
        # Lower cost should rank higher with cost preference
        if len(matches) >= 2:
            assert matches[0].service.pricing.cost <= matches[1].service.pricing.cost

    async def test_match_with_trust(self, marketplace_with_trust):
        mp = marketplace_with_trust
        mp._trust_scores["a1"] = 90.0
        mp._trust_scores["a2"] = 30.0

        await mp.register_service(make_service(
            provider_id="a1", name="Trusted Crypto", tags=["crypto"], cost=1.0,
        ))
        await mp.register_service(make_service(
            provider_id="a2", name="Untrusted Crypto", tags=["crypto"], cost=0.5,
        ))

        matches = await mp.best_match(
            query="crypto", prefer=MatchPreference.TRUST
        )
        # Trusted should rank higher despite higher cost
        assert matches[0].service.provider_id == "a1"


class TestListCategories:
    async def test_list_categories(self, marketplace):
        await marketplace.register_service(make_service(category="data", name="S1"))
        await marketplace.register_service(make_service(
            provider_id="a2", category="data", name="S2",
        ))
        await marketplace.register_service(make_service(
            provider_id="a3", category="ai", name="S3",
        ))
        cats = await marketplace.list_categories()
        assert len(cats) == 2

    async def test_list_categories_empty(self, marketplace):
        cats = await marketplace.list_categories()
        assert cats == []


class TestProviderServices:
    async def test_get_provider_services(self, marketplace):
        await marketplace.register_service(make_service(provider_id="a1", name="S1"))
        await marketplace.register_service(make_service(provider_id="a1", name="S2"))
        await marketplace.register_service(make_service(provider_id="a2", name="S3"))
        services = await marketplace.get_provider_services("a1")
        assert len(services) == 2

    async def test_get_provider_no_services(self, marketplace):
        services = await marketplace.get_provider_services("nobody")
        assert services == []


class TestCountServices:
    async def test_count(self, marketplace):
        assert await marketplace.count_services() == 0
        await marketplace.register_service(make_service(name="S1"))
        assert await marketplace.count_services() == 1

    async def test_count_by_status(self, marketplace):
        svc = await marketplace.register_service(make_service(name="S1"))
        await marketplace.deactivate_service(svc.id)
        assert await marketplace.count_services("active") == 0
        assert await marketplace.count_services("inactive") == 1
