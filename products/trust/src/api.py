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

    async def list_servers(self) -> list[Server]:
        """List all registered servers."""
        return await self.storage.list_servers()
