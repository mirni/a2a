"""Tests for the security scanner."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.models import Server, TransportType
from src.scanner import Scanner
from src.storage import StorageBackend


@dataclass
class MockSecurityTransport:
    """Mock transport for security scanning."""

    tls_enabled: bool = True
    auth_required: bool = True
    input_validation_score: float = 90.0
    cve_count: int = 0

    async def check_tls(self, url: str) -> bool:
        return self.tls_enabled

    async def check_auth(self, url: str) -> bool:
        return self.auth_required

    async def check_input_validation(self, url: str) -> float:
        return self.input_validation_score

    async def check_cves(self, url: str) -> int:
        return self.cve_count


class TestScanner:
    async def test_successful_scan(self, storage, sample_server):
        transport = MockSecurityTransport()
        scanner = Scanner(storage=storage, transport=transport)

        result = await scanner.scan(sample_server.id, sample_server.url)

        assert result.server_id == sample_server.id
        assert result.tls_enabled is True
        assert result.auth_required is True
        assert result.input_validation_score == 90.0
        assert result.cve_count == 0

    async def test_scan_stores_result(self, storage, sample_server):
        transport = MockSecurityTransport()
        scanner = Scanner(storage=storage, transport=transport)

        await scanner.scan(sample_server.id, sample_server.url)

        stored = await storage.get_security_scans(sample_server.id)
        assert len(stored) == 1
        assert stored[0].tls_enabled is True

    async def test_scan_no_security(self, storage, sample_server):
        transport = MockSecurityTransport(
            tls_enabled=False,
            auth_required=False,
            input_validation_score=0.0,
            cve_count=5,
        )
        scanner = Scanner(storage=storage, transport=transport)

        result = await scanner.scan(sample_server.id, sample_server.url)

        assert result.tls_enabled is False
        assert result.auth_required is False
        assert result.input_validation_score == 0.0
        assert result.cve_count == 5

    async def test_scan_server_by_id(self, storage, sample_server):
        transport = MockSecurityTransport()
        scanner = Scanner(storage=storage, transport=transport)

        result = await scanner.scan_server(sample_server.id)

        assert result.server_id == sample_server.id

    async def test_scan_server_not_found(self, storage):
        transport = MockSecurityTransport()
        scanner = Scanner(storage=storage, transport=transport)

        with pytest.raises(ValueError, match="Server not found"):
            await scanner.scan_server("nonexistent-id")

    async def test_multiple_scans(self, storage, sample_server):
        transport = MockSecurityTransport()
        scanner = Scanner(storage=storage, transport=transport)

        for _ in range(3):
            await scanner.scan(sample_server.id, sample_server.url)

        stored = await storage.get_security_scans(sample_server.id)
        assert len(stored) == 3
