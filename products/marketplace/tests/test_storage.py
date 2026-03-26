"""Tests for marketplace storage layer."""

import pytest

from src.storage import MarketplaceStorage


class TestConnection:
    async def test_connect_and_close(self):
        s = MarketplaceStorage(dsn="sqlite:///:memory:")
        await s.connect()
        assert s._db is not None
        await s.close()
        assert s._db is None

    async def test_db_raises_before_connect(self):
        s = MarketplaceStorage()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = s.db


class TestInsertAndGet:
    async def test_insert_returns_id(self, storage):
        sid = await storage.insert_service(
            provider_id="agent-1",
            name="Test",
            description="Desc",
            category="data",
            tools=["t1", "t2"],
            pricing={"model": "per_call", "cost": 1.0},
            sla={"uptime": 99.9},
            tags=["crypto"],
        )
        assert sid.startswith("svc-")

    async def test_get_returns_service(self, storage):
        sid = await storage.insert_service(
            provider_id="agent-1",
            name="Test",
            description="Desc",
            category="data",
            tools=["t1"],
            pricing={"model": "free"},
            sla={},
            tags=["tag1"],
        )
        svc = await storage.get_service(sid)
        assert svc is not None
        assert svc["name"] == "Test"
        assert svc["tools"] == ["t1"]
        assert svc["tags"] == ["tag1"]

    async def test_get_nonexistent_returns_none(self, storage):
        assert await storage.get_service("svc-nope") is None

    async def test_get_services_by_provider(self, storage):
        await storage.insert_service(
            provider_id="agent-1", name="S1", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        await storage.insert_service(
            provider_id="agent-1", name="S2", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        await storage.insert_service(
            provider_id="agent-2", name="S3", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        results = await storage.get_services_by_provider("agent-1")
        assert len(results) == 2

    async def test_insert_with_metadata(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="N", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
            metadata={"key": "value"},
        )
        svc = await storage.get_service(sid)
        assert svc is not None
        import json
        meta = json.loads(svc["metadata_json"])
        assert meta["key"] == "value"

    async def test_insert_with_endpoint(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="N", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
            endpoint="https://example.com",
        )
        svc = await storage.get_service(sid)
        assert svc["endpoint"] == "https://example.com"


class TestUpdate:
    async def test_update_name(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="Old", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        assert await storage.update_service(sid, name="New")
        svc = await storage.get_service(sid)
        assert svc["name"] == "New"

    async def test_update_nonexistent(self, storage):
        assert not await storage.update_service("svc-nope", name="X")

    async def test_update_tools(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="N", description="D", category="C",
            tools=["old_tool"], pricing={}, sla={}, tags=[],
        )
        await storage.update_service(sid, tools=["new_tool_1", "new_tool_2"])
        svc = await storage.get_service(sid)
        assert set(svc["tools"]) == {"new_tool_1", "new_tool_2"}

    async def test_update_tags(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="N", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=["old"],
        )
        await storage.update_service(sid, tags=["new1", "new2"])
        svc = await storage.get_service(sid)
        assert set(svc["tags"]) == {"new1", "new2"}

    async def test_update_status(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="N", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        await storage.update_service(sid, status="inactive")
        svc = await storage.get_service(sid)
        assert svc["status"] == "inactive"

    async def test_update_pricing(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="N", description="D", category="C",
            tools=[], pricing={"model": "free"}, sla={}, tags=[],
        )
        await storage.update_service(sid, pricing={"model": "per_call", "cost": 5.0})
        svc = await storage.get_service(sid)
        import json
        p = json.loads(svc["pricing_json"])
        assert p["cost"] == 5.0


class TestSearch:
    async def _seed(self, storage):
        """Seed test data."""
        await storage.insert_service(
            provider_id="a1", name="Market Data", description="Crypto price feeds",
            category="market-data", tools=["get_price"], pricing={"model": "per_call", "cost": 0.5},
            sla={}, tags=["crypto", "real-time"],
        )
        await storage.insert_service(
            provider_id="a2", name="Analytics Engine", description="Data analytics",
            category="analytics", tools=["analyze"], pricing={"model": "per_call", "cost": 2.0},
            sla={}, tags=["analytics", "data"],
        )
        await storage.insert_service(
            provider_id="a3", name="Free Tool", description="A free service",
            category="utilities", tools=["ping"], pricing={"model": "free", "cost": 0},
            sla={}, tags=["free", "utility"],
        )

    async def test_search_all(self, storage):
        await self._seed(storage)
        results = await storage.search_services()
        assert len(results) == 3

    async def test_search_by_query(self, storage):
        await self._seed(storage)
        results = await storage.search_services(query="Crypto")
        assert len(results) == 1
        assert results[0]["name"] == "Market Data"

    async def test_search_by_category(self, storage):
        await self._seed(storage)
        results = await storage.search_services(category="analytics")
        assert len(results) == 1
        assert results[0]["name"] == "Analytics Engine"

    async def test_search_by_tags(self, storage):
        await self._seed(storage)
        results = await storage.search_services(tags=["crypto"])
        assert len(results) == 1

    async def test_search_by_max_cost(self, storage):
        await self._seed(storage)
        results = await storage.search_services(max_cost=1.0)
        assert len(results) == 2  # 0.5 and 0

    async def test_search_by_pricing_model(self, storage):
        await self._seed(storage)
        results = await storage.search_services(pricing_model="free")
        assert len(results) == 1

    async def test_search_inactive_not_returned(self, storage):
        sid = await storage.insert_service(
            provider_id="a", name="Inactive", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        await storage.update_service(sid, status="inactive")
        results = await storage.search_services()
        assert len(results) == 0

    async def test_search_with_limit(self, storage):
        await self._seed(storage)
        results = await storage.search_services(limit=2)
        assert len(results) == 2

    async def test_search_with_offset(self, storage):
        await self._seed(storage)
        all_results = await storage.search_services()
        offset_results = await storage.search_services(offset=1)
        assert len(offset_results) == len(all_results) - 1

    async def test_search_description_match(self, storage):
        await self._seed(storage)
        results = await storage.search_services(query="analytics")
        assert len(results) == 1


class TestCategories:
    async def test_list_categories(self, storage):
        await storage.insert_service(
            provider_id="a", name="S1", description="D", category="data",
            tools=[], pricing={}, sla={}, tags=[],
        )
        await storage.insert_service(
            provider_id="a", name="S2", description="D", category="data",
            tools=[], pricing={}, sla={}, tags=[],
        )
        await storage.insert_service(
            provider_id="a", name="S3", description="D", category="ai",
            tools=[], pricing={}, sla={}, tags=[],
        )
        cats = await storage.list_categories()
        assert len(cats) == 2
        assert cats[0]["category"] == "data"
        assert cats[0]["count"] == 2

    async def test_list_categories_empty(self, storage):
        cats = await storage.list_categories()
        assert cats == []


class TestCount:
    async def test_count_empty(self, storage):
        assert await storage.count_services() == 0

    async def test_count_active(self, storage):
        await storage.insert_service(
            provider_id="a", name="S1", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        sid = await storage.insert_service(
            provider_id="a", name="S2", description="D", category="C",
            tools=[], pricing={}, sla={}, tags=[],
        )
        await storage.update_service(sid, status="inactive")
        assert await storage.count_services() == 1
        assert await storage.count_services("inactive") == 1
