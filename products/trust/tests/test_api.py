"""Tests for the Trust API query layer."""

from __future__ import annotations

import time

import pytest

from src.api import ServerNotFoundError, TrustAPI
from src.models import ProbeResult, SecurityScan, Server, TransportType, TrustScore, Window
from src.scorer import ScoreEngine
from src.storage import StorageBackend


class TestRegisterServer:
    async def test_register_with_auto_id(self, api):
        server = await api.register_server(
            name="My Server",
            url="https://example.com/mcp",
        )
        assert server.id is not None
        assert len(server.id) == 12
        assert server.name == "My Server"
        assert server.transport_type == TransportType.HTTP

    async def test_register_with_custom_id(self, api):
        server = await api.register_server(
            name="Custom Server",
            url="https://custom.com/mcp",
            server_id="custom-001",
        )
        assert server.id == "custom-001"

    async def test_register_stdio_server(self, api):
        server = await api.register_server(
            name="Stdio Server",
            url="stdio://local",
            transport_type=TransportType.STDIO,
        )
        assert server.transport_type == TransportType.STDIO

    async def test_registered_server_persisted(self, api, storage):
        server = await api.register_server(
            name="Persisted",
            url="https://persisted.com",
            server_id="persist-001",
        )
        fetched = await storage.get_server("persist-001")
        assert fetched is not None
        assert fetched.name == "Persisted"


class TestGetScore:
    async def test_get_score_computes_on_first_call(self, api, storage):
        server = await api.register_server(
            name="Scored",
            url="https://scored.com",
            server_id="scored-001",
        )
        now = time.time()
        await storage.store_probe_result(ProbeResult(
            server_id="scored-001",
            timestamp=now - 60,
            latency_ms=100,
            status_code=200,
            tools_count=5,
            tools_documented=5,
        ))
        await storage.store_security_scan(SecurityScan(
            server_id="scored-001",
            timestamp=now,
            tls_enabled=True,
            auth_required=True,
            input_validation_score=100.0,
            cve_count=0,
        ))

        score = await api.get_score("scored-001")
        assert score.composite_score > 0
        assert score.confidence > 0

    async def test_get_score_returns_cached(self, api, storage):
        server = await api.register_server(
            name="Cached",
            url="https://cached.com",
            server_id="cached-001",
        )
        # Store a pre-computed score
        await storage.store_trust_score(TrustScore(
            server_id="cached-001",
            timestamp=time.time(),
            window=Window.H24,
            composite_score=77.0,
            confidence=0.9,
        ))

        score = await api.get_score("cached-001")
        assert score.composite_score == 77.0

    async def test_get_score_recompute(self, api, storage):
        server = await api.register_server(
            name="Recompute",
            url="https://recompute.com",
            server_id="recomp-001",
        )
        now = time.time()
        await storage.store_probe_result(ProbeResult(
            server_id="recomp-001",
            timestamp=now - 30,
            latency_ms=100,
            status_code=200,
            tools_count=3,
            tools_documented=3,
        ))
        # Store a stale cached score
        await storage.store_trust_score(TrustScore(
            server_id="recomp-001",
            timestamp=now - 86400,
            window=Window.H24,
            composite_score=10.0,
            confidence=0.5,
        ))

        score = await api.get_score("recomp-001", recompute=True)
        # Fresh computation should differ from the stale 10.0
        assert score.composite_score != 10.0

    async def test_get_score_server_not_found(self, api):
        with pytest.raises(ServerNotFoundError):
            await api.get_score("nonexistent")


class TestGetHistory:
    async def test_get_history(self, api, storage):
        server = await api.register_server(
            name="History",
            url="https://history.com",
            server_id="hist-001",
        )
        now = time.time()
        for i in range(5):
            await storage.store_trust_score(TrustScore(
                server_id="hist-001",
                timestamp=now + i,
                window=Window.H24,
                composite_score=60.0 + i,
                confidence=1.0,
            ))

        history = await api.get_history("hist-001")
        assert len(history) == 5
        # Most recent first
        assert history[0].composite_score == 64.0

    async def test_get_history_with_since(self, api, storage):
        server = await api.register_server(
            name="HistSince",
            url="https://histsince.com",
            server_id="histsince-001",
        )
        now = time.time()
        for i in range(5):
            await storage.store_trust_score(TrustScore(
                server_id="histsince-001",
                timestamp=now + i * 3600,
                window=Window.H24,
                composite_score=70.0 + i,
                confidence=1.0,
            ))

        history = await api.get_history("histsince-001", since=now + 7200)
        assert len(history) == 3

    async def test_get_history_server_not_found(self, api):
        with pytest.raises(ServerNotFoundError):
            await api.get_history("nonexistent")


class TestSearchServers:
    async def test_search_by_name(self, api):
        await api.register_server(name="Alpha MCP", url="https://alpha.com", server_id="a")
        await api.register_server(name="Beta MCP", url="https://beta.com", server_id="b")
        await api.register_server(name="Gamma Tool", url="https://gamma.com", server_id="g")

        results = await api.search_servers(name_contains="MCP")
        assert len(results) == 2

    async def test_search_by_min_score(self, api, storage):
        await api.register_server(name="High", url="https://high.com", server_id="high")
        await api.register_server(name="Low", url="https://low.com", server_id="low")

        await storage.store_trust_score(TrustScore(
            server_id="high",
            timestamp=time.time(),
            window=Window.H24,
            composite_score=90.0,
            confidence=1.0,
        ))
        await storage.store_trust_score(TrustScore(
            server_id="low",
            timestamp=time.time(),
            window=Window.H24,
            composite_score=30.0,
            confidence=0.5,
        ))

        results = await api.search_servers(min_score=50.0)
        assert len(results) == 1
        assert results[0].id == "high"

    async def test_list_all_servers(self, api):
        await api.register_server(name="S1", url="https://s1.com", server_id="s1")
        await api.register_server(name="S2", url="https://s2.com", server_id="s2")

        servers = await api.list_servers()
        assert len(servers) == 2


class TestDeleteServer:
    async def test_delete_server_removes_server(self, api, storage):
        server = await api.register_server(
            name="Doomed", url="https://doomed.com", server_id="doom-001",
        )
        await api.delete_server("doom-001")
        fetched = await storage.get_server("doom-001")
        assert fetched is None

    async def test_delete_server_removes_scores(self, api, storage):
        await api.register_server(
            name="Doomed", url="https://doomed.com", server_id="doom-002",
        )
        now = time.time()
        await storage.store_trust_score(TrustScore(
            server_id="doom-002",
            timestamp=now,
            window=Window.H24,
            composite_score=80.0,
            confidence=1.0,
        ))
        await storage.store_probe_result(ProbeResult(
            server_id="doom-002",
            timestamp=now,
            latency_ms=50,
            status_code=200,
            tools_count=3,
            tools_documented=3,
        ))
        await storage.store_security_scan(SecurityScan(
            server_id="doom-002",
            timestamp=now,
            tls_enabled=True,
            auth_required=True,
            input_validation_score=100.0,
            cve_count=0,
        ))

        await api.delete_server("doom-002")

        # All associated data should be gone
        scores = await storage.get_score_history("doom-002")
        assert scores == []
        probes = await storage.get_probe_results("doom-002")
        assert probes == []
        scans = await storage.get_security_scans("doom-002")
        assert scans == []

    async def test_delete_server_not_found(self, api):
        with pytest.raises(ServerNotFoundError):
            await api.delete_server("nonexistent")


class TestUpdateServer:
    async def test_update_server_name(self, api, storage):
        await api.register_server(
            name="Old Name", url="https://old.com", server_id="upd-001",
        )
        updated = await api.update_server("upd-001", name="New Name")
        assert updated.name == "New Name"
        assert updated.url == "https://old.com"

    async def test_update_server_url(self, api, storage):
        await api.register_server(
            name="My Server", url="https://old.com", server_id="upd-002",
        )
        updated = await api.update_server("upd-002", url="https://new.com")
        assert updated.url == "https://new.com"
        assert updated.name == "My Server"

    async def test_update_server_name_and_url(self, api, storage):
        await api.register_server(
            name="Old", url="https://old.com", server_id="upd-003",
        )
        updated = await api.update_server("upd-003", name="New", url="https://new.com")
        assert updated.name == "New"
        assert updated.url == "https://new.com"

    async def test_update_server_not_found(self, api):
        with pytest.raises(ServerNotFoundError):
            await api.update_server("nonexistent", name="X")
