"""Security scanner for MCP servers.

Performs static security assessments: TLS check, auth check,
input validation testing, CVE pattern check. Designed to accept
injectable async callables for testing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .models import SecurityScan
from .storage import StorageBackend


class SecurityTransport(Protocol):
    """Protocol for security scanning transport.

    In tests, inject a mock implementation.
    """

    async def check_tls(self, url: str) -> bool:
        """Check if the server uses TLS. Returns True if TLS is enabled."""
        ...

    async def check_auth(self, url: str) -> bool:
        """Check if the server requires authentication. Returns True if auth required."""
        ...

    async def check_input_validation(self, url: str) -> float:
        """Send malformed inputs and check rejection quality.

        Returns a score 0-100 where 100 means all malformed inputs were properly rejected.
        """
        ...

    async def check_cves(self, url: str) -> int:
        """Check for known CVE patterns. Returns count of known CVEs."""
        ...


@dataclass
class Scanner:
    """Security scanner for MCP servers.

    Attributes:
        storage: StorageBackend for persisting scan results.
        transport: Async transport for performing security checks.
    """

    storage: StorageBackend
    transport: SecurityTransport

    async def scan(self, server_id: str, url: str) -> SecurityScan:
        """Perform a full security scan of a server and store results."""
        tls_enabled = await self.transport.check_tls(url)
        auth_required = await self.transport.check_auth(url)
        input_validation_score = await self.transport.check_input_validation(url)
        cve_count = await self.transport.check_cves(url)

        now = time.time()
        scan_result = SecurityScan(
            server_id=server_id,
            timestamp=now,
            tls_enabled=tls_enabled,
            auth_required=auth_required,
            input_validation_score=input_validation_score,
            cve_count=cve_count,
        )

        await self.storage.store_security_scan(scan_result)
        return scan_result

    async def scan_server(self, server_id: str) -> SecurityScan:
        """Scan a server by looking up its URL from storage."""
        server = await self.storage.get_server(server_id)
        if server is None:
            raise ValueError(f"Server not found: {server_id}")
        return await self.scan(server_id, server.url)
