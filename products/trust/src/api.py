"""Query API for the Trust & Reputation engine.

Provides high-level operations:
- Register a server for probing
- Get current trust score with dimensional breakdown
- Get score history over time
- Search servers by name or minimum score
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from .models import Server, TransportType, TrustScore, Window
from .scorer import ScoreEngine
from .storage import StorageBackend


class ServerNotFoundError(Exception):
    """Raised when a server ID is not found in storage."""

    pass


@dataclass
class TrustAPI:
    """High-level query API for trust & reputation data.

    Attributes:
        storage: StorageBackend for data access.
        scorer: ScoreEngine for computing scores on demand.
    """

    storage: StorageBackend
    scorer: ScoreEngine

    async def register_server(
        self,
        name: str,
        url: str,
        transport_type: TransportType = TransportType.HTTP,
        server_id: str | None = None,
    ) -> Server:
        """Register a new server for trust tracking.

        Args:
            name: Human-readable server name.
            url: Server endpoint URL.
            transport_type: Transport protocol (stdio or http).
            server_id: Optional custom ID; auto-generated if not provided.

        Returns:
            The registered Server object.
        """
        if server_id is None:
            server_id = uuid.uuid4().hex[:12]

        server = Server(
            id=server_id,
            name=name,
            url=url,
            transport_type=transport_type,
            registered_at=time.time(),
            last_probed_at=None,
        )
        return await self.storage.register_server(server)

    async def get_score(
        self,
        server_id: str,
        window: Window = Window.H24,
        recompute: bool = False,
    ) -> TrustScore:
        """Get the current trust score for a server.

        Args:
            server_id: Server identifier.
            window: Time window for score aggregation.
            recompute: If True, recompute from raw data instead of using cached score.

        Returns:
            The most recent TrustScore.

        Raises:
            ServerNotFoundError: If the server does not exist.
        """
        server = await self.storage.get_server(server_id)
        if server is None:
            raise ServerNotFoundError(f"Server not found: {server_id}")

        if recompute:
            return await self.scorer.compute_and_store(server_id, window)

        # Try cached score first
        score = await self.storage.get_latest_trust_score(server_id, window)
        if score is not None:
            return score

        # No cached score — compute fresh
        return await self.scorer.compute_and_store(server_id, window)

    async def get_history(
        self,
        server_id: str,
        window: Window = Window.H24,
        since: float | None = None,
        limit: int = 100,
    ) -> list[TrustScore]:
        """Get trust score history for a server.

        Args:
            server_id: Server identifier.
            window: Time window filter.
            since: Only scores after this Unix timestamp.
            limit: Maximum number of scores to return.

        Returns:
            List of TrustScore objects, most recent first.

        Raises:
            ServerNotFoundError: If the server does not exist.
        """
        server = await self.storage.get_server(server_id)
        if server is None:
            raise ServerNotFoundError(f"Server not found: {server_id}")

        return await self.storage.get_score_history(server_id, window, since, limit)

    async def search_servers(
        self,
        name_contains: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> list[Server]:
        """Search registered servers.

        Args:
            name_contains: Filter by partial name match.
            min_score: Minimum composite score threshold.
            limit: Maximum results.

        Returns:
            List of matching Server objects.
        """
        return await self.storage.search_servers(name_contains, min_score, limit)

    async def delete_server(self, server_id: str) -> None:
        """Delete a server and all its associated data.

        Args:
            server_id: Server identifier to delete.

        Raises:
            ServerNotFoundError: If the server does not exist.
        """
        deleted = await self.storage.delete_server(server_id)
        if not deleted:
            raise ServerNotFoundError(f"Server not found: {server_id}")

    async def update_server(self, server_id: str, **kwargs) -> Server:
        """Update a server's name and/or url.

        Args:
            server_id: Server identifier to update.
            **kwargs: Fields to update (name, url).

        Returns:
            The updated Server object.

        Raises:
            ServerNotFoundError: If the server does not exist.
        """
        updated = await self.storage.update_server(
            server_id,
            name=kwargs.get("name"),
            url=kwargs.get("url"),
        )
        if updated is None:
            raise ServerNotFoundError(f"Server not found: {server_id}")
        return updated

    async def check_sla_compliance(
        self,
        server_id: str,
        claimed_uptime: float = 99.0,
    ) -> dict:
        """Check if a server meets its claimed SLA based on trust probe data.

        Args:
            server_id: Server identifier.
            claimed_uptime: The uptime percentage the server claims to provide.

        Returns:
            Dict with compliance details.
        """
        score = await self.get_score(server_id=server_id, window=Window.H24)
        actual_uptime = score.reliability_score
        compliant = actual_uptime >= claimed_uptime
        violation_pct = max(0.0, claimed_uptime - actual_uptime) if not compliant else 0.0

        return {
            "server_id": server_id,
            "claimed_uptime": claimed_uptime,
            "actual_uptime": round(actual_uptime, 2),
            "compliant": compliant,
            "violation_pct": round(violation_pct, 2),
            "confidence": score.confidence,
        }

    async def list_servers(self) -> list[Server]:
        """List all registered servers."""
        return await self.storage.list_servers()
