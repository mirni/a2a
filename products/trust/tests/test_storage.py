"""Tests for SQLite storage layer."""

from __future__ import annotations

import time

import pytest
from src.models import ProbeResult, SecurityScan, Server, TransportType, TrustScore, Window
from src.storage import StorageBackend


class TestStorageConnection:
    async def test_connect_and_close(self, tmp_db):
        backend = StorageBackend(dsn=tmp_db)
        await backend.connect()
        assert backend.db is not None
        await backend.close()
        assert backend._db is None

    async def test_db_property_raises_before_connect(self, tmp_db):
        backend = StorageBackend(dsn=tmp_db)
        with pytest.raises(RuntimeError, match="not connected"):
            _ = backend.db


class TestServerCRUD:
    async def test_register_and_get_server(self, storage):
        server = Server(
            id="srv-1",
            name="Test Server",
            url="https://example.com/mcp",
            transport_type=TransportType.HTTP,
            registered_at=time.time(),
        )
        result = await storage.register_server(server)
        assert result.id == "srv-1"

        fetched = await storage.get_server("srv-1")
        assert fetched is not None
        assert fetched.name == "Test Server"
        assert fetched.transport_type == TransportType.HTTP

    async def test_get_nonexistent_server(self, storage):
        result = await storage.get_server("nonexistent")
        assert result is None

    async def test_update_last_probed(self, storage, sample_server):
        now = time.time()
        await storage.update_server_last_probed(sample_server.id, now)
        updated = await storage.get_server(sample_server.id)
        assert updated is not None
        assert updated.last_probed_at == now

    async def test_list_servers(self, storage):
        for i in range(3):
            s = Server(
                id=f"srv-{i}",
                name=f"Server {i}",
                url=f"https://example.com/{i}",
                transport_type=TransportType.HTTP,
                registered_at=time.time(),
            )
            await storage.register_server(s)

        servers = await storage.list_servers()
        assert len(servers) == 3

    async def test_search_servers_by_name(self, storage):
        for name, suf in [("Alpha Server", "a"), ("Beta Server", "b"), ("Gamma Tool", "g")]:
            s = Server(
                id=f"srv-{suf}",
                name=name,
                url=f"https://example.com/{suf}",
                transport_type=TransportType.HTTP,
                registered_at=time.time(),
            )
            await storage.register_server(s)

        results = await storage.search_servers(name_contains="Server")
        assert len(results) == 2
        names = {s.name for s in results}
        assert "Alpha Server" in names
        assert "Beta Server" in names

    async def test_search_servers_by_min_score(self, storage):
        s = Server(
            id="srv-scored",
            name="Scored Server",
            url="https://example.com",
            transport_type=TransportType.HTTP,
            registered_at=time.time(),
        )
        await storage.register_server(s)

        score = TrustScore(
            server_id="srv-scored",
            timestamp=time.time(),
            window=Window.H24,
            composite_score=75.0,
            confidence=1.0,
        )
        await storage.store_trust_score(score)

        results = await storage.search_servers(min_score=70.0)
        assert len(results) == 1
        assert results[0].id == "srv-scored"

        results = await storage.search_servers(min_score=80.0)
        assert len(results) == 0


class TestProbeResultCRUD:
    async def test_store_and_retrieve(self, storage, sample_server):
        probe = ProbeResult(
            server_id=sample_server.id,
            timestamp=time.time(),
            latency_ms=120.0,
            status_code=200,
            tools_count=5,
            tools_documented=4,
        )
        row_id = await storage.store_probe_result(probe)
        assert row_id > 0

        results = await storage.get_probe_results(sample_server.id)
        assert len(results) == 1
        assert results[0].latency_ms == 120.0
        assert results[0].tools_count == 5

    async def test_get_probe_results_with_since(self, storage, sample_server):
        now = time.time()
        old_probe = ProbeResult(
            server_id=sample_server.id,
            timestamp=now - 7200,
            latency_ms=100.0,
            status_code=200,
        )
        new_probe = ProbeResult(
            server_id=sample_server.id,
            timestamp=now,
            latency_ms=150.0,
            status_code=200,
        )
        await storage.store_probe_result(old_probe)
        await storage.store_probe_result(new_probe)

        results = await storage.get_probe_results(sample_server.id, since=now - 3600)
        assert len(results) == 1
        assert results[0].latency_ms == 150.0

    async def test_get_latest_probe(self, storage, sample_server):
        now = time.time()
        for i in range(3):
            p = ProbeResult(
                server_id=sample_server.id,
                timestamp=now + i,
                latency_ms=100.0 + i * 10,
                status_code=200,
            )
            await storage.store_probe_result(p)

        latest = await storage.get_latest_probe(sample_server.id)
        assert latest is not None
        assert latest.latency_ms == 120.0

    async def test_get_latest_probe_none(self, storage, sample_server):
        result = await storage.get_latest_probe(sample_server.id)
        assert result is None


class TestSecurityScanCRUD:
    async def test_store_and_retrieve(self, storage, sample_server):
        scan = SecurityScan(
            server_id=sample_server.id,
            timestamp=time.time(),
            tls_enabled=True,
            auth_required=True,
            input_validation_score=85.0,
            cve_count=1,
        )
        row_id = await storage.store_security_scan(scan)
        assert row_id > 0

        results = await storage.get_security_scans(sample_server.id)
        assert len(results) == 1
        assert results[0].tls_enabled is True
        assert results[0].cve_count == 1

    async def test_get_latest_scan(self, storage, sample_server):
        now = time.time()
        await storage.store_security_scan(
            SecurityScan(
                server_id=sample_server.id,
                timestamp=now - 100,
                tls_enabled=False,
            )
        )
        await storage.store_security_scan(
            SecurityScan(
                server_id=sample_server.id,
                timestamp=now,
                tls_enabled=True,
            )
        )

        latest = await storage.get_latest_security_scan(sample_server.id)
        assert latest is not None
        assert latest.tls_enabled is True

    async def test_get_latest_scan_none(self, storage, sample_server):
        result = await storage.get_latest_security_scan(sample_server.id)
        assert result is None


class TestTrustScoreCRUD:
    async def test_store_and_retrieve(self, storage, sample_server):
        score = TrustScore(
            server_id=sample_server.id,
            timestamp=time.time(),
            window=Window.H24,
            reliability_score=80.0,
            security_score=70.0,
            documentation_score=90.0,
            responsiveness_score=85.0,
            composite_score=80.5,
            confidence=1.0,
        )
        row_id = await storage.store_trust_score(score)
        assert row_id > 0

        latest = await storage.get_latest_trust_score(sample_server.id, Window.H24)
        assert latest is not None
        assert latest.composite_score == 80.5
        assert latest.confidence == 1.0

    async def test_get_score_history(self, storage, sample_server):
        now = time.time()
        for i in range(5):
            score = TrustScore(
                server_id=sample_server.id,
                timestamp=now + i,
                window=Window.H24,
                composite_score=70.0 + i,
                confidence=1.0,
            )
            await storage.store_trust_score(score)

        history = await storage.get_score_history(sample_server.id, Window.H24)
        assert len(history) == 5
        # Most recent first
        assert history[0].composite_score == 74.0

    async def test_get_score_history_with_since(self, storage, sample_server):
        now = time.time()
        for i in range(5):
            score = TrustScore(
                server_id=sample_server.id,
                timestamp=now + i * 3600,
                window=Window.D7,
                composite_score=70.0 + i,
                confidence=1.0,
            )
            await storage.store_trust_score(score)

        history = await storage.get_score_history(sample_server.id, Window.D7, since=now + 7200)
        assert len(history) == 3

    async def test_window_isolation(self, storage, sample_server):
        """Scores from different windows should not overlap."""
        now = time.time()
        for w in [Window.H24, Window.D7, Window.D30]:
            await storage.store_trust_score(
                TrustScore(
                    server_id=sample_server.id,
                    timestamp=now,
                    window=w,
                    composite_score=50.0,
                    confidence=0.8,
                )
            )

        h24 = await storage.get_score_history(sample_server.id, Window.H24)
        d7 = await storage.get_score_history(sample_server.id, Window.D7)
        d30 = await storage.get_score_history(sample_server.id, Window.D30)

        assert len(h24) == 1
        assert len(d7) == 1
        assert len(d30) == 1
